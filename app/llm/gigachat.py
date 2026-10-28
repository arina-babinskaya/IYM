"""Optional, cached GigaChat integration with auditable usage accounting."""
from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
import ssl
import time
import uuid
from pathlib import Path
from typing import Any, Literal

import httpx
from pydantic import BaseModel, Field, ValidationError, model_validator

from app.config import Settings, get_settings
from app.models import Product
from app.schemas import EstimateResponse, Suggestion
from app.taxonomy import MATERIAL_TITLES, PRODUCT_CATEGORY_TITLES, WORKS, Material, ProductCategory, WorkType, works_for_material

ErrorKind = Literal["api_error", "invalid_json", "schema_validation", "taxonomy_conflict", "budget"]
TAXONOMY_VERSION = "taxonomy_v2-38"
CLASSIFICATION_PROMPT_VERSION = "hybrid-classification-v2"
EXPLANATION_PROMPT_VERSION = "estimate-explanation-v1"


class GigaChatError(RuntimeError):
    def __init__(self, message: str, *, kind: ErrorKind = "api_error", diagnostic: dict[str, Any] | None = None):
        super().__init__(message); self.kind = kind; self.diagnostic = diagnostic or {}


class GigaClassification(BaseModel):
    decision: Literal["accept", "reject", "uncertain"]
    product_category: ProductCategory | None = None
    material: Material | None = None
    work_types: list[WorkType] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list, max_length=5)
    reason: str = Field(default="", max_length=500)
    result_level: Literal["abstention", "category_only", "estimate_ready"] = "abstention"
    validation_status: Literal["valid", "taxonomy_conflict"] = "valid"

    @model_validator(mode="after")
    def set_level(self) -> "GigaClassification":
        if self.decision == "accept" and self.product_category is None:
            raise ValueError("accept requires product_category")
        if self.decision != "accept" and (self.product_category or self.material or self.work_types):
            raise ValueError("reject/uncertain must not contain classification bindings")
        if self.decision == "accept":
            self.result_level = "estimate_ready" if self.material is not None and bool(self.work_types) else "category_only"
        else:
            self.result_level = "abstention"
        return self


class GigaExplanation(BaseModel):
    item_id: str
    text: str = Field(min_length=1, max_length=400)


class GigaExplanationBatch(BaseModel):
    explanations: list[GigaExplanation]


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def _usage(data: dict[str, Any]) -> tuple[int | None, int | None, int | None]:
    usage = data.get("usage") or {}
    prompt = usage.get("prompt_tokens", usage.get("input_tokens")); completion = usage.get("completion_tokens", usage.get("output_tokens"))
    total = usage.get("total_tokens")
    if total is None and prompt is not None and completion is not None: total = int(prompt) + int(completion)
    return tuple(int(x) if x is not None else None for x in (prompt, completion, total))  # type: ignore[return-value]


class GigaCache:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True); self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("""create table if not exists responses (cache_key text primary key, kind text not null,
            response text not null, prompt_tokens integer not null default 0, completion_tokens integer not null default 0,
            elapsed_ms integer not null default 0, created_at integer not null)""")
        self.db.execute("""create table if not exists request_log (id integer primary key, cache_key text, kind text not null,
            model text not null, attempt integer not null, from_cache integer not null default 0, prompt_tokens integer,
            completion_tokens integer, total_tokens integer, elapsed_ms integer, status text not null, error_kind text,
            error text, created_at integer not null)""")
        # One-time migration makes pre-ledger responses count toward budgets, including invalid
        # classifications whose HTTP response was nevertheless cached.
        if not self.db.execute("select 1 from request_log limit 1").fetchone():
            self.db.execute("""insert into request_log(cache_key,kind,model,attempt,from_cache,prompt_tokens,
                completion_tokens,total_tokens,elapsed_ms,status,created_at)
                select cache_key,kind,'unknown',1,0,prompt_tokens,completion_tokens,
                prompt_tokens+completion_tokens,elapsed_ms,'legacy_response',created_at from responses""")
        self.db.commit()

    def get(self, key: str) -> dict[str, Any] | None:
        row = self.db.execute("select response from responses where cache_key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, key: str, kind: str, response: dict[str, Any], elapsed_ms: int) -> None:
        prompt, completion, _ = _usage(response)
        self.db.execute("insert or replace into responses values (?,?,?,?,?,?,?)", (key, kind,
            json.dumps(response, ensure_ascii=False), prompt or 0, completion or 0, elapsed_ms, int(time.time()))); self.db.commit()

    def log(self, *, key: str, kind: str, model: str, attempt: int, from_cache: bool, data: dict[str, Any] | None,
            elapsed_ms: int | None, status: str, error_kind: str | None = None, error: str | None = None) -> None:
        prompt, completion, total = _usage(data or {})
        self.db.execute("""insert into request_log(cache_key,kind,model,attempt,from_cache,prompt_tokens,completion_tokens,
            total_tokens,elapsed_ms,status,error_kind,error,created_at) values(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (key, kind, model, attempt, int(from_cache), prompt, completion, total, elapsed_ms, status, error_kind,
             (error or "")[:1000], int(time.time()))); self.db.commit()

    def update_validation(self, key: str, status: str, error_kind: str | None = None, error: str = "") -> None:
        row = self.db.execute("select id from request_log where cache_key=? order by id desc limit 1", (key,)).fetchone()
        if row:
            self.db.execute("update request_log set status=?,error_kind=?,error=? where id=?",
                            (status, error_kind, error[:1000], row[0])); self.db.commit()

    def tokens(self) -> int:
        count, total = self.db.execute("select count(*),coalesce(sum(total_tokens),0) from request_log where from_cache=0").fetchone()
        if count: return int(total)
        return int(self.db.execute("select coalesce(sum(prompt_tokens+completion_tokens),0) from responses").fetchone()[0])

    def request_count(self) -> int:
        return int(self.db.execute("select count(*) from request_log where from_cache=0").fetchone()[0])

    def records(self) -> list[dict[str, Any]]:
        cur = self.db.execute("select * from request_log order by id")
        names = [x[0] for x in cur.description]
        return [dict(zip(names, row, strict=True)) for row in cur.fetchall()]


class GigaChatClient:
    def __init__(self, settings: Settings | None = None, transport: httpx.AsyncBaseTransport | None = None):
        self.s = settings or get_settings(); self.transport = transport; self.cache = GigaCache(self.s.gigachat_cache_path)
        self._token: str | None = None; self._token_expiry = 0.0; self._lock = asyncio.Lock()
        self.stats = {"requests": 0, "attempts": 0, "cache_hits": 0, "tokens": self.cache.tokens(), "elapsed_ms": 0,
                      "api_errors": 0, "validation_failures": 0, "unknown_usage": 0}

    @property
    def configured(self) -> bool: return self.s.gigachat_enabled and bool(self.s.gigachat_credentials)

    def _verify(self) -> bool | ssl.SSLContext:
        if not self.s.gigachat_verify_ssl: return False
        if self.s.gigachat_ca_bundle:
            path = Path(self.s.gigachat_ca_bundle).expanduser()
            if not path.is_file(): raise GigaChatError(f"GigaChat CA bundle does not exist: {path}")
            return ssl.create_default_context(cafile=str(path))
        return True

    def _http(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=self.s.gigachat_timeout_s, verify=self._verify(), transport=self.transport)

    async def _authenticate(self, http: httpx.AsyncClient) -> str:
        if self._token and time.time() < self._token_expiry - 30: return self._token
        if not self.s.gigachat_credentials: raise GigaChatError("GigaChat credentials are not configured")
        started = time.perf_counter(); key = _hash([self.s.gigachat_cache_namespace, "oauth", self.s.gigachat_scope])
        response = await http.post(self.s.gigachat_auth_url, headers={"Authorization": f"Basic {self.s.gigachat_credentials}",
            "RqUID": str(uuid.uuid4())}, data={"scope": self.s.gigachat_scope})
        elapsed = int((time.perf_counter() - started) * 1000)
        if response.status_code >= 400:
            self.cache.log(key=key,kind="oauth",model=self.s.gigachat_model,attempt=1,from_cache=False,data=None,
                           elapsed_ms=elapsed,status="api_error",error_kind="api_error",error=f"HTTP {response.status_code}")
            raise GigaChatError(f"GigaChat OAuth HTTP {response.status_code}")
        try: data = response.json(); self._token = data["access_token"]
        except (ValueError, KeyError, TypeError) as exc: raise GigaChatError("GigaChat OAuth returned an invalid response") from exc
        self.cache.log(key=key,kind="oauth",model=self.s.gigachat_model,attempt=1,from_cache=False,data=None,
                       elapsed_ms=elapsed,status="success")
        self._token_expiry = float(data.get("expires_at", int((time.time() + 1500) * 1000))) / 1000; return self._token

    async def models(self) -> list[str]:
        started = time.perf_counter(); key = _hash([self.s.gigachat_cache_namespace, "model_discovery"])
        async with self._http() as http:
            token = await self._authenticate(http)
            response = await http.get(f"{self.s.gigachat_api_url.rstrip('/')}/models", headers={"Authorization": f"Bearer {token}"})
        elapsed = int((time.perf_counter() - started) * 1000)
        if response.status_code >= 400:
            self.cache.log(key=key,kind="model_discovery",model=self.s.gigachat_model,attempt=1,from_cache=False,
                           data=None,elapsed_ms=elapsed,status="api_error",error_kind="api_error",
                           error=f"HTTP {response.status_code}")
            raise GigaChatError(f"GigaChat models HTTP {response.status_code}")
        self.cache.log(key=key,kind="model_discovery",model=self.s.gigachat_model,attempt=1,from_cache=False,
                       data=None,elapsed_ms=elapsed,status="success")
        return sorted(str(x["id"]) for x in response.json().get("data", []) if x.get("id"))

    def _budget_check(self) -> None:
        if self.s.gigachat_max_requests is not None and self.cache.request_count() >= self.s.gigachat_max_requests:
            raise GigaChatError("GigaChat request limit exhausted", kind="budget")
        if self.s.gigachat_token_budget is not None and self.s.gigachat_token_budget - self.cache.tokens() < self.s.gigachat_token_reservation:
            raise GigaChatError("GigaChat token budget cannot cover the conservative reservation", kind="budget")

    async def _chat(self, kind: str, messages: list[dict[str, str]], max_tokens: int,
                    schema: dict[str, Any] | None = None) -> tuple[dict[str, Any], str]:
        key = _hash([self.s.gigachat_cache_namespace, kind, self.s.gigachat_model, messages, max_tokens, schema])
        if hit := self.cache.get(key):
            self.stats["cache_hits"] += 1; self.cache.log(key=key, kind=kind, model=self.s.gigachat_model, attempt=0,
                from_cache=True, data=hit, elapsed_ms=0, status="cache_hit"); return hit, key
        if not self.configured: raise GigaChatError("GigaChat fallback is disabled or has no credentials")
        async with self._lock:
            delay = 1.0
            for attempt in range(1, self.s.gigachat_retries + 2):
                # Re-check before every network attempt. A retry response can itself consume
                # tokens or the request quota, so checking only once before the retry loop can
                # overshoot a configured safety budget.
                self._budget_check()
                started = time.perf_counter(); data: dict[str, Any] | None = None; self.stats["attempts"] += 1
                try:
                    async with self._http() as http:
                        token = await self._authenticate(http)
                        body: dict[str, Any] = {"model": self.s.gigachat_model, "messages": messages, "temperature": 0,
                                                "max_tokens": max_tokens, "stream": False}
                        if schema is not None and self.s.gigachat_structured_output:
                            body["response_format"] = {"type": "json_schema", "json_schema": {"name": kind, "schema": schema}}
                        response = await http.post(f"{self.s.gigachat_api_url.rstrip('/')}/chat/completions",
                                                   headers={"Authorization": f"Bearer {token}"}, json=body)
                    elapsed = int((time.perf_counter() - started) * 1000)
                    try: data = response.json()
                    except ValueError: data = None
                    if response.status_code == 401: self._token = None
                    if (response.status_code == 429 or response.status_code >= 500) and attempt <= self.s.gigachat_retries:
                        self.cache.log(key=key, kind=kind, model=self.s.gigachat_model, attempt=attempt, from_cache=False,
                            data=data, elapsed_ms=elapsed, status="api_error", error_kind="api_error",
                            error=f"HTTP {response.status_code}")
                        retry = response.headers.get("Retry-After"); await asyncio.sleep(float(retry) if retry and retry.isdigit() else delay)
                        delay = min(delay * 2, 20); continue
                    if response.status_code >= 400: raise GigaChatError(f"GigaChat HTTP {response.status_code}")
                    if not isinstance(data, dict): raise GigaChatError("GigaChat returned a non-JSON HTTP response")
                    self.cache.put(key, kind, data, elapsed); self.cache.log(key=key, kind=kind, model=self.s.gigachat_model,
                        attempt=attempt, from_cache=False, data=data, elapsed_ms=elapsed, status="response_received")
                    if _usage(data)[2] is None: self.stats["unknown_usage"] += 1
                    self.stats["requests"] += 1; self.stats["tokens"] = self.cache.tokens(); self.stats["elapsed_ms"] += elapsed
                    return data, key
                except (httpx.TransportError, httpx.TimeoutException, ssl.SSLError, GigaChatError) as exc:
                    elapsed = int((time.perf_counter() - started) * 1000)
                    if not isinstance(exc, GigaChatError) and attempt <= self.s.gigachat_retries:
                        self.cache.log(key=key, kind=kind, model=self.s.gigachat_model, attempt=attempt, from_cache=False,
                            data=data, elapsed_ms=elapsed, status="api_error", error_kind="api_error", error=type(exc).__name__)
                        await asyncio.sleep(delay); delay = min(delay * 2, 20); continue
                    self.stats["api_errors"] += 1; self.cache.log(key=key, kind=kind, model=self.s.gigachat_model,
                        attempt=attempt, from_cache=False, data=data, elapsed_ms=elapsed, status="api_error",
                        error_kind="api_error", error=str(exc)); raise GigaChatError(f"GigaChat unavailable: {type(exc).__name__}") from exc
        raise AssertionError("unreachable")

    @staticmethod
    def _content(data: dict[str, Any]) -> str:
        try: return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc: raise GigaChatError("GigaChat response has no message content", kind="schema_validation") from exc

    async def _parse_classification(self, data: dict[str, Any], key: str, allow_repair: bool) -> GigaClassification:
        content = self._content(data)
        try: result = GigaClassification.model_validate_json(content)
        except ValidationError as exc:
            kind: ErrorKind = "invalid_json" if any(e["type"] == "json_invalid" for e in exc.errors()) else "schema_validation"
            self.stats["validation_failures"] += 1; self.cache.update_validation(key, kind, kind, str(exc))
            if allow_repair and self.s.gigachat_repair_invalid_response:
                messages = [{"role": "system", "content": "Исправь JSON строго по схеме. Не заменяй неизвестные метки; используй uncertain. Верни только JSON."},
                    {"role": "user", "content": json.dumps({"schema": GigaClassification.model_json_schema(),
                        "invalid_response": content, "validation_errors": exc.errors(include_url=False)}, ensure_ascii=False)}]
                repaired, repair_key = await self._chat("classification_repair", messages, 450, GigaClassification.model_json_schema())
                return await self._parse_classification(repaired, repair_key, False)
            raise GigaChatError(f"Invalid structured classification ({kind})", kind=kind,
                diagnostic={"errors": exc.errors(include_url=False), "response_excerpt": content[:1000]}) from exc
        conflict = self._taxonomy_conflict(result)
        if conflict:
            self.cache.update_validation(key, "taxonomy_conflict", "taxonomy_conflict", conflict)
            return result.model_copy(update={"decision": "uncertain", "product_category": None, "material": None,
                "work_types": [], "result_level": "abstention", "validation_status": "taxonomy_conflict", "reason": conflict})
        self.cache.update_validation(key, "success"); return result

    @staticmethod
    def _taxonomy_conflict(result: GigaClassification) -> str | None:
        if result.material is not None:
            direct = {ProductCategory.primer: {Material.primer}, ProductCategory.paint: {Material.paint},
                ProductCategory.putty: {Material.putty}, ProductCategory.plaster: {Material.plaster},
                ProductCategory.drywall: {Material.drywall, Material.profile}, ProductCategory.tile: {Material.tile},
                ProductCategory.sealant: {Material.sealant}, ProductCategory.lighting: {Material.lighting, Material.lamps},
                ProductCategory.ventilation: {Material.ventilation}, ProductCategory.insulation: {Material.insulation}}
            allowed = direct.get(result.product_category)
            if allowed is not None and result.material not in allowed: return "product category/material taxonomy conflict"
            plausible = set(works_for_material(result.material))
            if result.work_types and (not plausible or not set(result.work_types) <= plausible):
                return "work type/material taxonomy conflict"
        elif result.work_types: return "work types require an estimate material"
        return None

    async def classify(self, product: Product, existing: Suggestion | None = None) -> GigaClassification:
        raw = product.raw or {}; chars = raw.get("characteristics") or product.specs or {}
        if isinstance(chars, list): chars = [{str(k)[:100]: str(v)[:300] for k, v in item.items()} for item in chars[:30] if isinstance(item, dict)]
        elif isinstance(chars, dict): chars = {str(k)[:100]: str(v)[:300] for k, v in list(chars.items())[:30]}
        taxonomy = {"product_categories": {x.value: PRODUCT_CATEGORY_TITLES[x] for x in ProductCategory},
            "materials": {x.value: MATERIAL_TITLES[x] for x in Material if x != Material.other},
            "work_types": {x.value: WORKS[x].title for x in WORKS}}
        payload = {"product_id": product.id, "taxonomy_version": TAXONOMY_VERSION,
            "prompt_version": CLASSIFICATION_PROMPT_VERSION,
            "name": product.name, "catalog_categories": list((product.categories or {}).values()),
            "description": (product.description or "")[:2500], "characteristics": chars,
            "existing_ml_prediction": existing.model_dump(mode="json") if existing else None, "taxonomy": taxonomy}
        messages = [{"role": "system", "content": "Ты проверяешь товар для сметы ремонта. Выбирай только метки из taxonomy. accept требует product_category. material и work_types добавляй только при прямых доказательствах; без них accept является category-only. reject означает точно нерелевантный товар, uncertain — недостаточно данных или конфликт. Не используй null-заменители 'none' и не выдумывай метки."},
            {"role": "user", "content": json.dumps({"schema": GigaClassification.model_json_schema(), "product": payload}, ensure_ascii=False)}]
        data, key = await self._chat("classification", messages, 450, GigaClassification.model_json_schema())
        return await self._parse_classification(data, key, True)

    async def explain_estimate(self, response: EstimateResponse | None, signals: list[dict[str, Any]]) -> dict[str, str]:
        messages = [{"role": "system", "content": "Кратко объясни по-русски уже сделанный выбор. Используй только факты, не меняй выбор и не выдумывай свойства."},
            {"role": "user", "content": json.dumps({"prompt_version": EXPLANATION_PROMPT_VERSION,
                "schema": GigaExplanationBatch.model_json_schema(), "items": signals}, ensure_ascii=False)}]
        data, key = await self._chat("explanation", messages, min(1200, 80 * max(1, len(signals))), GigaExplanationBatch.model_json_schema())
        try: batch = GigaExplanationBatch.model_validate_json(self._content(data))
        except ValidationError as exc:
            self.cache.update_validation(key, "schema_validation", "schema_validation", str(exc)); raise GigaChatError("Invalid explanation response", kind="schema_validation") from exc
        self.cache.update_validation(key, "success"); allowed = {str(item["item_id"]) for item in signals}
        return {item.item_id: item.text for item in batch.explanations if item.item_id in allowed}

import asyncio
import hashlib
import json
import logging
import threading
import time
from collections import OrderedDict
from functools import lru_cache
from typing import Any, Literal, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.config import Settings, get_settings

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)
Message = dict[str, str]


class LLMError(RuntimeError):
    pass


class _LRU:
    def __init__(self, size: int):
        self.size = size
        self._data: OrderedDict[str, Any] = OrderedDict()
        self._lock = threading.Lock()
        self.hits = self.misses = 0

    def get(self, key: str) -> Any | None:
        with self._lock:
            if key in self._data:
                self._data.move_to_end(key)
                self.hits += 1
                return self._data[key]
            self.misses += 1
            return None

    def put(self, key: str, value: Any) -> None:
        if self.size <= 0:
            return
        with self._lock:
            self._data[key] = value
            self._data.move_to_end(key)
            while len(self._data) > self.size:
                self._data.popitem(last=False)


def _key(*parts: Any) -> str:
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


class LLMClient:
    def __init__(self, settings: Settings | None = None, transport: httpx.AsyncBaseTransport | None = None):
        self.s = settings or get_settings()
        self._transport = transport
        self._cache = _LRU(self.s.llm_cache_size)
        self.stats = {"requests": 0, "errors": 0, "total_ms": 0}


    async def _post(self, path: str, payload: dict[str, Any], timeout: float | None = None) -> dict[str, Any]:
        delay = 0.5
        last: Exception | None = None
        for attempt in range(self.s.llm_retries + 1):
            t0 = time.perf_counter()
            try:
                async with httpx.AsyncClient(
                    base_url=self.s.ollama_url, timeout=timeout or self.s.llm_timeout_s, transport=self._transport
                ) as http:
                    resp = await http.post(path, json=payload)
                self.stats["requests"] += 1
                self.stats["total_ms"] += int((time.perf_counter() - t0) * 1000)
                if resp.status_code >= 500:
                    raise httpx.HTTPStatusError(resp.text[:200], request=resp.request, response=resp)
                if resp.status_code >= 400:
                    raise LLMError(f"Ollama {path}: HTTP {resp.status_code}: {resp.text[:300]}")
                return resp.json()
            except (httpx.TransportError, httpx.HTTPStatusError) as e:
                last = e
                self.stats["errors"] += 1
                if attempt < self.s.llm_retries:
                    log.warning("Ollama %s failed (%r), retry in %.1fs", path, e, delay)
                    await asyncio.sleep(delay)
                    delay *= 2
        raise LLMError(f"Ollama {path} недоступна: {last!r}")


    async def chat(
        self,
        messages: list[Message],
        *,
        format: dict[str, Any] | Literal["json"] | None = None,
        temperature: float = 0.0,
        model: str | None = None,
        max_tokens: int | None = None,
        use_cache: bool = True,
    ) -> str:
        model = model or self.s.llm_model
        options: dict[str, Any] = {"temperature": temperature, "num_ctx": self.s.llm_num_ctx}
        if max_tokens:
            options["num_predict"] = max_tokens
        cacheable = use_cache and temperature == 0
        key = _key("chat", model, messages, format, options)
        if cacheable and (hit := self._cache.get(key)) is not None:
            return hit
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": options,
            "keep_alive": self.s.llm_keep_alive,
        }
        if format is not None:
            payload["format"] = format
        data = await self._post("/api/chat", payload)
        content = (data.get("message") or {}).get("content", "")
        if cacheable:
            self._cache.put(key, content)
        return content

    async def chat_json(
        self, messages: list[Message], schema: type[T], *, temperature: float = 0.0, fix_attempts: int = 1
    ) -> T:
        key = _key("chat_json", self.s.llm_model, messages, schema.model_json_schema())
        if temperature == 0 and (hit := self._cache.get(key)) is not None:
            return schema.model_validate_json(hit)
        msgs = list(messages)
        last_err: ValidationError | None = None
        for _ in range(fix_attempts + 1):
            raw = await self.chat(msgs, format=schema.model_json_schema(), temperature=temperature, use_cache=False)
            try:
                obj = schema.model_validate_json(raw)
            except ValidationError as e:
                last_err = e
                errors = "; ".join(f"{'.'.join(map(str, er['loc']))}: {er['msg']}" for er in e.errors()[:5])
                msgs = [
                    *msgs,
                    {"role": "assistant", "content": raw},
                    {"role": "user", "content": f"JSON не прошёл проверку ({errors}). Верни исправленный JSON."},
                ]
                continue
            if temperature == 0:
                self._cache.put(key, obj.model_dump_json())
            return obj
        raise LLMError(f"Модель не вернула валидный {schema.__name__}: {last_err}")


    def _prefix(self, kind: Literal["query", "passage"] | None) -> str:
        if kind and "e5" in self.s.embed_model.lower():
            return f"{kind}: "
        return ""

    async def embed(
        self, texts: list[str], *, kind: Literal["query", "passage"] | None = None, batch_size: int = 64
    ) -> list[list[float]]:
        prefix = self._prefix(kind)
        inputs = [prefix + t for t in texts]
        result: list[list[float] | None] = [None] * len(inputs)
        todo: list[int] = []
        for i, text in enumerate(inputs):
            hit = self._cache.get(_key("emb", self.s.embed_model, text))
            if hit is not None:
                result[i] = hit
            else:
                todo.append(i)
        for start in range(0, len(todo), batch_size):
            idx = todo[start : start + batch_size]
            data = await self._post(
                "/api/embed",
                {"model": self.s.embed_model, "input": [inputs[i] for i in idx], "keep_alive": self.s.llm_keep_alive},
            )
            vectors = data.get("embeddings") or []
            if len(vectors) != len(idx):
                raise LLMError(f"Ollama вернула {len(vectors)} эмбеддингов вместо {len(idx)}")
            for i, vec in zip(idx, vectors, strict=True):
                result[i] = vec
                self._cache.put(_key("emb", self.s.embed_model, inputs[i]), vec)
        return result


    async def health(self) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(base_url=self.s.ollama_url, timeout=5, transport=self._transport) as http:
                resp = await http.get("/api/tags")
                resp.raise_for_status()
            names = {m.get("name") for m in resp.json().get("models", [])}
        except Exception as e:
            return {"ok": False, "error": repr(e), "url": self.s.ollama_url}

        def present(model: str) -> bool:
            return model in names or f"{model}:latest" in names

        return {
            "ok": present(self.s.llm_model) and present(self.s.embed_model),
            "url": self.s.ollama_url,
            "llm_model": {"name": self.s.llm_model, "present": present(self.s.llm_model)},
            "embed_model": {"name": self.s.embed_model, "present": present(self.s.embed_model)},
            "available": sorted(n for n in names if n),
            "cache": {"hits": self._cache.hits, "misses": self._cache.misses},
            "stats": self.stats,
        }


    def chat_sync(self, messages: list[Message], **kw: Any) -> str:
        return asyncio.run(self.chat(messages, **kw))

    def chat_json_sync(self, messages: list[Message], schema: type[T], **kw: Any) -> T:
        return asyncio.run(self.chat_json(messages, schema, **kw))

    def embed_sync(self, texts: list[str], **kw: Any) -> list[list[float]]:
        return asyncio.run(self.embed(texts, **kw))


@lru_cache
def get_llm() -> LLMClient:
    return LLMClient()

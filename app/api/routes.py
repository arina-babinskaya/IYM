import asyncio
import logging
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import text

from app.api.deps import (get_catalog_matching_classifier, get_classifier, get_estimate_engine,
                          get_gigachat, get_repo)
from app.api.picker import add_why, apply_explanations, explanation_signals
from app.catalog.repository import MANUAL_ID_START, AdminStatus, CatalogRepo, to_brief
from app.config import get_settings
from app.engine.interface import CalcError
from app.llm.client import LLMError, get_llm
from app.llm.gigachat import GigaChatError
from app.ml.hybrid import decide_hybrid, eligible_for_gigachat, gigachat_suggestion
from app.ml.tfidf import publishable
from app.schemas import (
    AdminProductRow,
    AdminStats,
    AutobindJob,
    BindingIn,
    BindingOut,
    CatalogMatchAlternative,
    CatalogMatchOut,
    EstimateRequest,
    EstimateResponse,
    ProductBrief,
    ProductCalcRequest,
    ProductCalcResponse,
    ProductCreate,
    ProductOut,
    Suggestion,
    ROOM_DEFAULT_OPENINGS,
    ROOM_TITLES,
    RoomType,
    StageOptions,
    TaxonomyOut,
    WorkOption,
    WorkOptionsOut,
)
from app.db import get_sessionmaker
from app.plans import RENOVATION_STAGES, work_materials, works_for_room
from app.taxonomy import (MATERIAL_TITLES, PRODUCT_CATEGORY_TITLES, RENOVATION_TITLES, STAGE_ORDER,
                          STAGE_TITLES, WORKS, Material, RenovationType)

router = APIRouter(prefix="/api/v1")
logger = logging.getLogger(__name__)

# One bulk writer per application process. The operation is idempotent at the database layer
# (save_ml_bindings only inserts missing rows), while this guard prevents duplicate expensive
# classifier/provider work from repeated clicks.
_autobind_task: asyncio.Task[None] | None = None
_autobind_job: AutobindJob | None = None
_autobind_sync_lock = asyncio.Lock()


@router.post("/estimate", response_model=EstimateResponse, tags=["calculator"])
async def estimate(req: EstimateRequest, repo: CatalogRepo = Depends(get_repo)) -> EstimateResponse:
    t0 = time.perf_counter()
    engine = get_estimate_engine()
    resp = add_why(engine.estimate(req, repo), repo)
    if req.explain:
        try:
            resp = await engine.explain(req, resp)
        except LLMError as e:
            resp.warnings.append(f"пояснение недоступно: {e}")
        settings = get_settings()
        if settings.gigachat_explanations:
            try:
                facts = explanation_signals(resp, repo, settings.gigachat_explanation_max_items)
                if facts:
                    apply_explanations(resp, await get_gigachat().explain_estimate(resp, facts))
            except GigaChatError as e:
                resp.warnings.append(f"GigaChat-пояснение недоступно: {e}")
    resp.elapsed_ms = int((time.perf_counter() - t0) * 1000)
    return resp


@router.get("/taxonomy", response_model=TaxonomyOut, tags=["calculator"])
def taxonomy() -> TaxonomyOut:
    return TaxonomyOut(
        stages=[{"id": k.value, "title": v} for k, v in STAGE_TITLES.items()],
        room_types=[{"id": k.value, "title": v, "windows": ROOM_DEFAULT_OPENINGS.get(k, (1, 1))[0],
                     "doors": ROOM_DEFAULT_OPENINGS.get(k, (1, 1))[1]} for k, v in ROOM_TITLES.items()],
        renovation_types=[{"id": k.value, "title": v} for k, v in RENOVATION_TITLES.items()],
        works=[{"id": k.value, "title": v.title, "stage": v.stage.value, "stages": [s.value for s in v.stages],
                "materials": [m.value for m in v.materials]}
               for k, v in WORKS.items()],
        materials=[{"id": k.value, "title": v} for k, v in MATERIAL_TITLES.items()],
        product_categories=[{"id": k.value, "title": v} for k, v in PRODUCT_CATEGORY_TITLES.items()],
    )


SURFACE_TITLES = {"floor": "пол", "wall": "стены", "ceiling": "потолок"}


@router.get("/works", response_model=WorkOptionsOut, tags=["calculator"])
def work_options(room_type: RoomType, renovation_type: RenovationType) -> WorkOptionsOut:
    options = works_for_room(room_type, renovation_type)
    repeated = {o.work for o, _ in options if sum(1 for x, _ in options if x.work == o.work) > 1}
    allowed = RENOVATION_STAGES[renovation_type]
    stages = []
    for stage in STAGE_ORDER:
        works = []
        for o, default in options:
            info = WORKS[o.work]
            if next((s for s in info.stages if s in allowed), info.stage) != stage:
                continue
            suffix = o.variant or (SURFACE_TITLES[o.surface.value] if o.work in repeated and o.surface else None)
            materials = work_materials(o.work, o.materials)
            works.append(WorkOption(
                work_type=o.work, surface=o.surface, title=info.title + (f" — {suffix}" if suffix else ""),
                materials=list(materials), material_titles=[MATERIAL_TITLES[m] for m in materials],
                default=default,
            ))
        if works:
            stages.append(StageOptions(stage=stage, title=STAGE_TITLES[stage], works=works))
    return WorkOptionsOut(room_type=room_type, room_title=ROOM_TITLES[room_type], renovation_type=renovation_type,
                          renovation_title=RENOVATION_TITLES[renovation_type], stages=stages)


@router.get("/products", response_model=list[ProductBrief], tags=["products"])
def list_products(
    q: str | None = None,
    category_id: int | None = None,
    limit: int = Query(50, le=500),
    offset: int = 0,
    repo: CatalogRepo = Depends(get_repo),
) -> list[ProductBrief]:
    return [to_brief(p) for p in repo.search(q, category_id, limit, offset)]


@router.get("/products/{product_id}", response_model=ProductOut, tags=["products"])
def get_product(product_id: int, repo: CatalogRepo = Depends(get_repo)) -> ProductOut:
    product = repo.get_out(product_id)
    if product is None:
        raise HTTPException(404, "товар не найден")
    return product


@router.post("/product/{product_id}/calc", response_model=ProductCalcResponse, tags=["products"])
def product_calc(product_id: int, req: ProductCalcRequest, repo: CatalogRepo = Depends(get_repo)) -> ProductCalcResponse:
    product = repo.get(product_id)
    if product is None:
        raise HTTPException(404, "товар не найден")
    try:
        return get_estimate_engine().calc_product(product, req, repo)
    except CalcError as e:
        raise HTTPException(422, str(e)) from e


def _admin_rows(products: list, repo: CatalogRepo) -> list[AdminProductRow]:
    suggestions = get_classifier().predict(products) if products else []
    rows = []
    for p, s in zip(products, suggestions, strict=True):
        b = repo.binding(p.id)
        rows.append(
            AdminProductRow(
                product=to_brief(p),
                category=next(iter((p.categories or {}).values()), None),
                manual=p.id >= MANUAL_ID_START,
                binding=BindingOut.model_validate(b) if b else None,
                suggestion=s,
            )
        )
    return rows


@router.get("/admin/products", response_model=list[AdminProductRow], tags=["admin"])
def admin_products(
    status: AdminStatus | None = None,
    only_unbound: bool = True,
    q: str | None = None,
    limit: int = Query(50, le=500),
    offset: int = 0,
    repo: CatalogRepo = Depends(get_repo),
) -> list[AdminProductRow]:
    if status is None:
        status = "unbound" if only_unbound and not q else "all"
    return _admin_rows(repo.admin_list(status, q, limit, offset), repo)


@router.post("/admin/products", response_model=AdminProductRow, status_code=201, tags=["admin"])
def admin_create_product(data: ProductCreate, repo: CatalogRepo = Depends(get_repo)) -> AdminProductRow:
    return _admin_rows([repo.create_manual(data)], repo)[0]


@router.delete("/admin/products/{product_id}", status_code=204, tags=["admin"])
def admin_delete_product(product_id: int, repo: CatalogRepo = Depends(get_repo)) -> None:
    if not repo.delete_manual(product_id):
        raise HTTPException(404, "ручной товар не найден (товары из каталога удалять нельзя)")


@router.get("/admin/products/{product_id}/suggest", response_model=Suggestion, tags=["admin"])
def admin_suggest(product_id: int, repo: CatalogRepo = Depends(get_repo)) -> Suggestion:
    product = repo.get(product_id)
    if product is None:
        raise HTTPException(404, "товар не найден")
    return get_classifier().predict([product])[0]


@router.get("/admin/products/{product_id}/catalog-match", response_model=CatalogMatchOut, tags=["admin"])
def admin_catalog_match(product_id: int, repo: CatalogRepo = Depends(get_repo)) -> CatalogMatchOut:
    """Assign a full-catalog leaf without changing renovation bindings or ranking state."""
    product = repo.get(product_id)
    if product is None:
        raise HTTPException(404, "товар не найден")
    try:
        result = get_catalog_matching_classifier().predict_one(product, top_k=3)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(503, f"catalog matching unavailable: {exc}") from exc
    prediction = result.prediction
    return CatalogMatchOut(
        product_id=result.product_id,
        category_id=prediction.category_id,
        category_name=prediction.category_name,
        score=prediction.confidence,
        top_3=[
            CatalogMatchAlternative(
                category_id=prediction.category_id,
                category_name=prediction.category_name,
                score=prediction.confidence,
            ),
            *[
                CatalogMatchAlternative(
                    category_id=item.category_id, category_name=item.category_name, score=item.confidence
                )
                for item in prediction.alternatives
            ],
        ],
        review_recommended=prediction.needs_review,
        score_type=prediction.score_type,
        model=prediction.model,
        taxonomy_version=result.taxonomy_version,
    )


@router.put("/admin/products/{product_id}/binding", response_model=BindingOut, tags=["admin"])
def admin_bind(product_id: int, data: BindingIn, repo: CatalogRepo = Depends(get_repo)) -> BindingOut:
    if repo.get(product_id) is None:
        raise HTTPException(404, "товар не найден")
    return BindingOut.model_validate(repo.set_binding(product_id, data, "manual", None, confirmed=True))


def _autobind_rejection(suggestion: Suggestion, min_confidence: float) -> str | None:
    """Return the first publication rule that rejects a renovation binding."""
    if not suggestion.flags.get("domain_renovation", False):
        return "outside_renovation_domain"
    if suggestion.flags.get("ml_unknown", False):
        return "unknown_or_uncertain"
    if suggestion.product_category is None:
        return "missing_product_category"
    if suggestion.material == Material.other:
        return "unsupported_material"
    if suggestion.confidence < min_confidence:
        return "below_confidence_threshold"
    if suggestion.flags.get("taxonomy_inconsistent", False):
        return "taxonomy_inconsistent"
    return None


async def _run_autobind(
    repo: CatalogRepo, min_confidence: float, batch: int, use_gigachat: bool,
    progress: AutobindJob | None = None,
) -> AdminStats:
    started = time.perf_counter()
    settings = get_settings()
    clf = get_classifier()
    giga = get_gigachat() if use_gigachat else None
    giga_considered = 0
    after_id = -1
    while products := repo.unbound(batch, after_id):
        batch_started = time.perf_counter()
        after_id = products[-1].id
        predict_started = time.perf_counter()
        # Trained inference is CPU-bound. Keeping it off the event loop preserves API health.
        predictions = await asyncio.to_thread(clf.predict, products)
        if not isinstance(predictions, list):
            raise ValueError(f"classifier returned {type(predictions).__name__}, expected a list")
        if len(predictions) != len(products) or not all(isinstance(item, Suggestion) for item in predictions):
            raise ValueError(
                f"classifier returned {len(predictions)} validatable outputs for {len(products)} products"
            )
        classifier_ms = int((time.perf_counter() - predict_started) * 1000)
        pairs = [(p.id, s) for p, s in zip(products, predictions, strict=True)
                 if publishable(s, min_confidence)]
        dependency_ms = 0
        if progress is not None:
            progress.processed += len(products)
            progress.classifier_ms += classifier_ms
            progress.phase = "external fallback" if giga is not None and giga.configured else "saving"
        if giga is not None and giga.configured:
            for product, ml in zip(products, predictions, strict=True):
                if publishable(ml, min_confidence) or not eligible_for_gigachat(ml, min_confidence):
                    continue
                if giga_considered >= settings.gigachat_autobind_max_products:
                    break
                giga_considered += 1
                if progress is not None:
                    progress.gigachat_considered = giga_considered
                dependency_started = time.perf_counter()
                try:
                    result = await giga.classify(product, ml)
                    decision = decide_hybrid(ml, result, min_confidence)
                    if decision.action == "accept_gigachat":
                        pairs.append((product.id, gigachat_suggestion(result,
                            model=settings.gigachat_model, confidence=settings.gigachat_binding_confidence)))
                except (GigaChatError, ValueError) as exc:
                    logger.warning("autobind GigaChat failed product_id=%s: %s", product.id, exc)
                    if progress is not None:
                        progress.errors += 1
                finally:
                    dependency_ms += int((time.perf_counter() - dependency_started) * 1000)
        candidate_ids = {product_id for product_id, _ in pairs}
        rejection_reasons: dict[str, int] = {}
        for product, suggestion in zip(products, predictions, strict=True):
            if product.id in candidate_ids:
                continue
            reason = _autobind_rejection(suggestion, min_confidence) or "not_publishable"
            rejection_reasons[reason] = rejection_reasons.get(reason, 0) + 1
        inserted = repo.save_ml_bindings(pairs)
        if progress is not None:
            progress.candidates += len(candidate_ids)
            progress.bound += inserted
            progress.rejected += len(products) - len(candidate_ids)
            progress.persistence_conflicts += len(candidate_ids) - inserted
            progress.skipped = progress.rejected + progress.persistence_conflicts
            for reason, count in rejection_reasons.items():
                progress.rejection_reasons[reason] = progress.rejection_reasons.get(reason, 0) + count
            progress.gigachat_considered = giga_considered
            progress.batches += 1
            progress.dependency_ms += dependency_ms
            progress.elapsed_ms = int((time.perf_counter() - started) * 1000)
            progress.phase = "external fallback" if dependency_ms else "classifying"
        logger.info(
            "autobind batch=%s processed=%s candidates=%s inserted=%s rejected=%s reasons=%s "
            "classifier_ms=%s dependency_ms=%s batch_ms=%s",
            progress.batches if progress else "sync", len(products), len(candidate_ids), inserted,
            len(products) - len(candidate_ids), rejection_reasons, classifier_ms, dependency_ms,
            int((time.perf_counter() - batch_started) * 1000),
        )
    result = admin_stats(repo)
    logger.info("autobind complete processed=%s bound=%s elapsed_ms=%s", progress.processed if progress else "unknown",
                progress.bound if progress else "unknown", int((time.perf_counter() - started) * 1000))
    return result


async def _run_autobind_job(job: AutobindJob, min_confidence: float, batch: int, use_gigachat: bool) -> None:
    global _autobind_task
    try:
        with get_sessionmaker()() as session:
            job.stats = await _run_autobind(CatalogRepo(session), min_confidence, batch, use_gigachat, job)
        job.status, job.phase = "completed", "completed"
    except asyncio.CancelledError:
        logger.warning("autobind job %s cancelled", job.id)
        job.status, job.phase, job.error = "cancelled", "cancelled", "autobind was cancelled"
        raise
    except Exception as exc:
        logger.exception("autobind job %s failed", job.id)
        job.status, job.phase, job.error = "failed", "failed", f"{type(exc).__name__}: {exc}"
    finally:
        job.elapsed_ms = int((time.perf_counter() - _job_started[job.id]) * 1000)
        _autobind_task = None


_job_started: dict[str, float] = {}


@router.post("/admin/autobind", response_model=AdminStats | AutobindJob, tags=["admin"])
async def admin_autobind(
    min_confidence: float | None = Query(None, ge=0, le=1),
    batch: int = Query(1000, le=5000),
    use_gigachat: bool | None = None,
    background: bool = False,
    response: Response = None,
    repo: CatalogRepo = Depends(get_repo),
) -> AdminStats | AutobindJob:
    global _autobind_job, _autobind_task
    if min_confidence is None:
        min_confidence = get_settings().autobind_min_confidence
    settings = get_settings()
    if use_gigachat is None:
        use_gigachat = settings.gigachat_enabled
    if _autobind_task is not None and not _autobind_task.done():
        if response is not None:
            response.status_code = status.HTTP_202_ACCEPTED
        return _autobind_job
    if _autobind_sync_lock.locked():
        raise HTTPException(409, "autobind is already running")
    if not background:
        async with _autobind_sync_lock:
            return await _run_autobind(repo, min_confidence, batch, use_gigachat)
    job = AutobindJob(id=str(uuid.uuid4()), status="running", phase="starting")
    _autobind_job = job
    _job_started[job.id] = time.perf_counter()
    _autobind_task = asyncio.create_task(_run_autobind_job(job, min_confidence, batch, use_gigachat))
    if response is not None:
        response.status_code = status.HTTP_202_ACCEPTED
    return job


@router.get("/admin/autobind/status", response_model=AutobindJob, tags=["admin"])
def admin_autobind_status() -> AutobindJob:
    if _autobind_job is None:
        raise HTTPException(404, "autobind has not been started")
    if _autobind_job.status == "running":
        _autobind_job.elapsed_ms = int((time.perf_counter() - _job_started[_autobind_job.id]) * 1000)
    return _autobind_job


@router.get("/admin/stats", response_model=AdminStats, tags=["admin"])
def admin_stats(repo: CatalogRepo = Depends(get_repo)) -> AdminStats:
    total, manual, ml = repo.binding_counts()
    return AdminStats(
        products_total=total, bound_manual=manual, bound_ml=ml, unbound=total - manual - ml,
        auto_bound_share=round(ml / total, 4) if total else 0.0,
    )


health_router = APIRouter(tags=["service"])


@health_router.get("/health")
async def health(repo: CatalogRepo = Depends(get_repo)) -> dict:
    try:
        repo.session.execute(text("select 1"))
        db = {"ok": True}
    except Exception as e:
        db = {"ok": False, "error": repr(e)}
    llm = await get_llm().health()
    return {"ok": db["ok"], "db": db, "llm": llm}

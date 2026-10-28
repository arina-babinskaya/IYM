import time

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text

from app.api.deps import get_classifier, get_estimate_engine, get_gigachat, get_repo
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
    BindingIn,
    BindingOut,
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
from app.plans import RENOVATION_STAGES, work_materials, works_for_room
from app.taxonomy import (MATERIAL_TITLES, PRODUCT_CATEGORY_TITLES, RENOVATION_TITLES, STAGE_ORDER,
                          STAGE_TITLES, WORKS, Material, RenovationType)

router = APIRouter(prefix="/api/v1")


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


@router.put("/admin/products/{product_id}/binding", response_model=BindingOut, tags=["admin"])
def admin_bind(product_id: int, data: BindingIn, repo: CatalogRepo = Depends(get_repo)) -> BindingOut:
    if repo.get(product_id) is None:
        raise HTTPException(404, "товар не найден")
    return BindingOut.model_validate(repo.set_binding(product_id, data, "manual", None, confirmed=True))


@router.post("/admin/autobind", response_model=AdminStats, tags=["admin"])
async def admin_autobind(
    min_confidence: float | None = Query(None, ge=0, le=1),
    batch: int = Query(1000, le=5000),
    use_gigachat: bool | None = None,
    repo: CatalogRepo = Depends(get_repo),
) -> AdminStats:
    if min_confidence is None:
        min_confidence = get_settings().autobind_min_confidence
    settings = get_settings()
    clf = get_classifier()
    if use_gigachat is None:
        use_gigachat = settings.gigachat_enabled
    giga = get_gigachat() if use_gigachat else None
    giga_considered = 0
    after_id = -1
    while products := repo.unbound(batch, after_id):
        after_id = products[-1].id
        predictions = clf.predict(products)
        pairs = [(p.id, s) for p, s in zip(products, predictions, strict=True)
                 if publishable(s, min_confidence)]
        if giga is not None and giga.configured:
            for product, ml in zip(products, predictions, strict=True):
                if publishable(ml, min_confidence) or not eligible_for_gigachat(ml, min_confidence):
                    continue
                if giga_considered >= settings.gigachat_autobind_max_products:
                    break
                giga_considered += 1
                try:
                    result = await giga.classify(product, ml)
                    decision = decide_hybrid(ml, result, min_confidence)
                    if decision.action == "accept_gigachat":
                        pairs.append((product.id, gigachat_suggestion(result,
                            model=settings.gigachat_model, confidence=settings.gigachat_binding_confidence)))
                except (GigaChatError, ValueError):
                    # The product remains unbound for admin review; ML autobinding continues.
                    continue
        repo.save_ml_bindings(pairs)
    return admin_stats(repo)


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

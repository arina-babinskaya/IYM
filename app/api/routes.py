import time

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text

from app.api.deps import get_classifier, get_estimate_engine, get_repo
from app.catalog.repository import CatalogRepo, to_brief
from app.engine.interface import CalcError
from app.llm.client import LLMError, get_llm
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
    ProductOut,
    Suggestion,
    TaxonomyOut,
)
from app.taxonomy import MATERIAL_TITLES, RENOVATION_TITLES, STAGE_TITLES, WORKS, Material

router = APIRouter(prefix="/api/v1")


@router.post("/estimate", response_model=EstimateResponse, tags=["calculator"])
async def estimate(req: EstimateRequest, repo: CatalogRepo = Depends(get_repo)) -> EstimateResponse:
    t0 = time.perf_counter()
    engine = get_estimate_engine()
    resp = engine.estimate(req, repo)
    if req.explain:
        try:
            resp = await engine.explain(req, resp)
        except LLMError as e:
            resp.warnings.append(f"пояснение недоступно: {e}")
    resp.elapsed_ms = int((time.perf_counter() - t0) * 1000)
    return resp


@router.get("/taxonomy", response_model=TaxonomyOut, tags=["calculator"])
def taxonomy() -> TaxonomyOut:
    return TaxonomyOut(
        stages=[{"id": k.value, "title": v} for k, v in STAGE_TITLES.items()],
        renovation_types=[{"id": k.value, "title": v} for k, v in RENOVATION_TITLES.items()],
        works=[{"id": k.value, "title": v.title, "stage": v.stage.value, "materials": [m.value for m in v.materials]}
               for k, v in WORKS.items()],
        materials=[{"id": k.value, "title": v} for k, v in MATERIAL_TITLES.items()],
    )


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


@router.get("/admin/products", response_model=list[AdminProductRow], tags=["admin"])
def admin_products(
    only_unbound: bool = True,
    q: str | None = None,
    limit: int = Query(50, le=500),
    offset: int = 0,
    repo: CatalogRepo = Depends(get_repo),
) -> list[AdminProductRow]:
    products = repo.unbound(limit) if only_unbound and not q else repo.search(q, None, limit, offset)
    suggestions = get_classifier().predict(products) if products else []
    rows = []
    for p, s in zip(products, suggestions, strict=True):
        b = repo.binding(p.id)
        rows.append(
            AdminProductRow(
                product=to_brief(p),
                category=next(iter((p.categories or {}).values()), None),
                binding=BindingOut.model_validate(b) if b else None,
                suggestion=s,
            )
        )
    return rows


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
def admin_autobind(
    min_confidence: float = Query(0.8, ge=0, le=1),
    batch: int = Query(1000, le=5000),
    repo: CatalogRepo = Depends(get_repo),
) -> AdminStats:
    clf = get_classifier()
    after_id = -1
    while products := repo.unbound(batch, after_id):
        after_id = products[-1].id
        pairs = [
            (p.id, s)
            for p, s in zip(products, clf.predict(products), strict=True)
            if s.confidence >= min_confidence and s.material != Material.other
        ]
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

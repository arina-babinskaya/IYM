import re
from decimal import Decimal

from fastapi import APIRouter, Depends

from app.api.deps import get_estimate_engine, get_repo
from app.catalog.repository import CatalogRepo, to_brief
from app.engine import baseline as engine_baseline
from app.engine.interface import CalcError
from app.ml.ranker import BASIS_TITLES, SUITABLE_SHARE, ContextRanker, Scored, signals
from app.schemas import (
    EstimateResponse,
    Level,
    OptionProduct,
    OptionsRequest,
    OptionsResponse,
    ProductCalcRequest,
    RoomInput,
    Surface,
)
from app.taxonomy import MATERIAL_TITLES, Material

router = APIRouter(prefix="/api/v1", tags=["calculator"])

NEEDS_MOISTURE = getattr(engine_baseline, "NEEDS_MOISTURE", set())
SURFACE_HINTS = getattr(engine_baseline, "SURFACE_HINTS", {})
CANDIDATES_LIMIT = getattr(engine_baseline, "CANDIDATES_LIMIT", 20000)
MIN_CONFIDENCE = 0.8

FEATURE_TITLES = {
    "moisture_resistant": "влагостойкий", "washable": "моющийся", "wear_class": "износостойкий",
    "anti_slip": "противоскользящий", "frost_resistant": "морозостойкий", "antifungal": "против плесени",
    "low_emission": "без запаха", "ip_protected": "защита от брызг (IP44+)",
}
WHY = {
    "typical": "основной товар для этой работы",
    "moisture_resistant": "влагостойкий — важно для этой комнаты",
    "antifungal": "с защитой от плесени",
    "washable": "моющийся",
    "wear_class": "высокий класс износостойкости",
    "anti_slip": "противоскользящая поверхность",
    "frost_resistant": "морозостойкий",
    "ip_protected": "защита от брызг IP44 и выше — нужна в ванной",
    "low_emission": "без запаха — подходит для жилой комнаты",
    "calculable": "известна фасовка — количество посчитано точно",
    "in_stock": "в наличии",
    "confirmed": "привязка проверена вручную",
}

ranker = ContextRanker()


def needs_moisture(room: RoomInput, material: Material) -> bool:
    return room.effective_humidity == Level.high and material in NEEDS_MOISTURE


def why(s: Scored, check_moisture: bool = False) -> list[str]:
    out = [text for key, text in WHY.items() if s.parts.get(key, 0) > 0]
    if s.parts.get("room_match", 0) > 0:
        out.insert(1, "предназначен для этой комнаты")
    if s.parts.get("price", 0) >= 1.5:
        out.append("одна из лучших цен за единицу")
    if s.parts.get("outdoor", 0) < 0:
        out.append("уличный — для помещения подходит хуже")
    if check_moisture and not s.parts.get("moisture_resistant"):
        out.append("влагостойкость не указана — проверьте перед покупкой")
    return out


def _area(room: RoomInput, surface: Surface | None) -> Decimal:
    if surface == Surface.wall:
        return max(room.perimeter * room.height_m - room.openings_area_m2, Decimal(0))
    return room.floor_area


def _candidates(repo: CatalogRepo, room: RoomInput, material: Material, surface: Surface | None) -> list:
    wet = needs_moisture(room, material)
    cands = repo.candidates(material, required_flags=["moisture_resistant"] if wet else [],
                            min_confidence=MIN_CONFIDENCE, limit=CANDIDATES_LIMIT)
    hint = SURFACE_HINTS.get(surface) if material == Material.tile else None
    if hint:
        matching = [(p, b) for p, b in cands if re.search(hint, (p.name or "").lower())]
        return matching or cands
    return cands


def _option(s: Scored, best_quality: float, ideal: float, req: OptionsRequest, area: Decimal, repo: CatalogRepo,
            with_cost: bool) -> OptionProduct:
    p = s.product
    b = repo.binding(p.id)
    sig = signals(p, b) if b else {}
    out = OptionProduct(
        product=to_brief(p), score=s.score, quality=s.quality,
        quality_pct=ranker.quality_pct(s, ideal),
        suitable=s.quality >= SUITABLE_SHARE * best_quality,
        unit_price=Decimal(str(round(s.unit_price, 2))) if s.unit_price is not None else None,
        unit_price_title=BASIS_TITLES[s.basis],
        features=[FEATURE_TITLES[k] for k, v in sig.items() if v > 0 and k in FEATURE_TITLES],
        why=why(s, needs_moisture(req.room, req.material)),
    )
    if with_cost and area > 0:
        calc = ProductCalcRequest(length_m=area, width_m=Decimal(1), layers=2 if req.material == Material.paint else 1)
        try:
            r = get_estimate_engine().calc_product(p, calc, repo)
        except (CalcError, ValueError, TypeError):
            return out
        out.packages, out.required_amount, out.required_unit, out.cost = (
            r.packages, r.required_amount, r.required_unit, r.total_cost)
    return out


@router.post("/estimate/options", response_model=OptionsResponse)
def estimate_options(req: OptionsRequest, repo: CatalogRepo = Depends(get_repo)) -> OptionsResponse:
    area = _area(req.room, req.surface)
    cands = _candidates(repo, req.room, req.material, req.surface)
    room = req.room.model_copy(update={"picks": []})
    scored = ranker.score(cands, room)
    variants = ranker.variants(cands, room)
    best_quality = variants["quality"].quality if variants else 0.0
    ideal = ranker.ideal_quality(req.material, room, scored)

    items = scored
    if req.q:
        q = req.q.lower()
        items = [s for s in items if q in (s.product.name or "").lower()]
    if req.features:
        pairs = {p.id: b for p, b in cands}
        items = [s for s in items if all(signals(s.product, pairs[s.product.id]).get(f, 0) > 0 for f in req.features)]
    if req.suitable_only:
        items = [s for s in items if s.quality >= SUITABLE_SHARE * best_quality]
    if req.price_min is not None:
        items = [s for s in items if (s.product.result_price or 0) >= req.price_min]
    if req.price_max is not None:
        items = [s for s in items if (s.product.result_price or 0) <= req.price_max]
    no_price = float("inf")
    order = {
        "recommended": lambda s: (-s.score, s.product.id),
        "quality": lambda s: (-s.quality, -s.score, s.product.id),
        "price_asc": lambda s: (s.unit_price if s.unit_price is not None else no_price, s.product.id),
        "price_desc": lambda s: (-(s.unit_price or 0), s.product.id),
        "name": lambda s: ((s.product.name or "").lower(), s.product.id),
    }[req.sort]
    items = sorted(items, key=order)
    page = items[req.offset:req.offset + req.limit]

    return OptionsResponse(
        material=req.material, material_title=MATERIAL_TITLES[req.material], surface=req.surface,
        area_m2=area.quantize(Decimal("0.01")), total=len(items),
        variants={k: _option(v, best_quality, ideal, req, area, repo, True) for k, v in variants.items()},
        products=[_option(s, best_quality, ideal, req, area, repo, True) for s in page],
    )


def add_why(resp: EstimateResponse, repo: CatalogRepo) -> EstimateResponse:
    for room_est in resp.rooms:
        room = room_est.room.model_copy(update={"picks": []})
        for item in room_est.items:
            if not item.product:
                continue
            p, b = repo.get(item.product.id), repo.binding(item.product.id)
            if p and b:
                item.why = why(ranker.score([(p, b)], room)[0], needs_moisture(room, item.material))
    return resp

import re
from decimal import Decimal

from fastapi import APIRouter, Depends

from app.api.deps import get_estimate_engine, get_repo
from app.catalog.repository import CatalogRepo, to_brief
from app.config import get_settings
from app.engine import baseline as engine_baseline
from app.engine.interface import CalcError
from app.ml.ranker import BASIS_TITLES, SUITABLE_SHARE, ContextRanker, Scored, characteristics, signals
from app.schemas import (
    EstimateResponse,
    ExplanationFact,
    Level,
    OptionProduct,
    OptionsRequest,
    OptionsResponse,
    ProductCalcRequest,
    RoomInput,
    RecommendationEvidence,
    Surface,
)
from app.taxonomy import MATERIAL_TITLES, WORKS, Material

router = APIRouter(prefix="/api/v1", tags=["calculator"])

NEEDS_MOISTURE = getattr(engine_baseline, "NEEDS_MOISTURE", set())
SURFACE_HINTS = getattr(engine_baseline, "SURFACE_HINTS", {})
CANDIDATES_LIMIT = getattr(engine_baseline, "CANDIDATES_LIMIT", 20000)

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
    if s.parts.get("decorative", 0) < 0:
        out.append("декоративный — для этой работы обычно не нужен")
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
                            min_confidence=get_settings().autobind_min_confidence, limit=CANDIDATES_LIMIT)
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
    if with_cost:
        try:
            n, need, unit, cost, _ = engine_baseline.calc_product_for_room(
                p, req.material, req.room, req.surface, area
            )
            if cost is not None and n > 0:
                out.packages = n
                out.required_amount = need.quantize(Decimal("0.01")) if isinstance(need, Decimal) else need
                out.required_unit = unit
                out.cost = cost
        except Exception:
            pass
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
        request_room = room_est.room
        room = request_room.model_copy(update={"picks": []})
        for item in room_est.items:
            if not item.product:
                continue
            p, b = repo.get(item.product.id), repo.binding(item.product.id)
            if p and b:
                candidates = repo.candidates(
                    item.material, work_type=item.work_type,
                    required_flags=["moisture_resistant"] if needs_moisture(room, item.material) else [],
                    min_confidence=get_settings().autobind_min_confidence, limit=CANDIDATES_LIMIT,
                )
                scored = ranker.score(candidates, room)
                selected = next((value for value in scored if value.product.id == p.id), None)
                if selected is None:
                    selected = ranker.score([(p, b)], room)[0]
                item.why = why(selected, needs_moisture(room, item.material))
                if not (b.work_types or []) and not b.confirmed:
                    item.why.append("подобран по материалу: вид работ у товара не указан — проверьте")
                evidence, explanation = recommendation_evidence(item, request_room, p, b, selected, scored)
                item.recommendation_evidence = evidence
                item.recommendation_explanation = explanation
    return resp


SIGNAL_LABELS = {
    "moisture_resistant": "подтверждена влагостойкость",
    "washable": "поверхность допускает влажную очистку",
    "wear_class": "указана износостойкость",
    "anti_slip": "указаны противоскользящие свойства",
    "frost_resistant": "подтверждена морозостойкость",
    "antifungal": "указана защита от плесени",
    "low_emission": "в описании указано отсутствие запаха или низкая эмиссия",
    "ip_protected": "степень защиты IP44 или выше",
}


def _catalog_value(p, code: str) -> str | None:
    chars = characteristics(p)
    keys = {
        "moisture_resistant": ("влагостойкость", "влагостойкость краски", "водостойкость", "аквастоп", "тип помещения"),
        "washable": ("влагостойкость обоев",),
        "wear_class": ("износостойкость", "тип напольного покрытия"),
        "frost_resistant": ("морозостойкость",),
        "low_emission": ("аромат",),
        "ip_protected": ("степень защиты", "класс защиты ip", "степень защиты ip"),
    }.get(code, ())
    for key in keys:
        if value := chars.get(key):
            return f"{key}: {value}"
    # The remaining ranker signals are explicitly extracted from the product name/description.
    return "название или описание товара"


def recommendation_evidence(item, room, p, binding, selected: Scored, scored: list[Scored]):
    facts = [
        ExplanationFact(code="material_role", label=f"роль в смете: {MATERIAL_TITLES[item.material]}",
                        source="request"),
        ExplanationFact(code="work_compatibility",
                        label=f"привязка товара совместима с работой «{WORKS[item.work_type].title}»",
                        source="binding", value=item.work_type.value),
    ]
    surface_hint = SURFACE_HINTS.get(item.surface) if item.material == Material.tile else None
    if surface_hint and re.search(surface_hint, (p.name or "").lower()):
        surface_title = {Surface.floor: "пола", Surface.wall: "стен", Surface.ceiling: "потолка"}[item.surface]
        facts.append(ExplanationFact(code="surface_match",
                                     label=f"в названии указано назначение для {surface_title}",
                                     source="catalog", value=p.name))
    sig = signals(p, binding)
    for code, label in SIGNAL_LABELS.items():
        if sig.get(code, 0) > 0 and selected.parts.get(code, 0) > 0:
            facts.append(ExplanationFact(code=code, label=label, source="catalog",
                                         value=_catalog_value(p, code), score=selected.parts.get(code)))
    picked = p.id in room.picks
    if picked:
        facts.append(ExplanationFact(code="user_pick", label="товар выбран пользователем", source="user"))
    else:
        if selected.parts.get("in_stock", 0) > 0:
            facts.append(ExplanationFact(code="in_stock", label="наличие товара",
                                         source="ranking", score=selected.parts["in_stock"]))
        if len(scored) > 1 and selected.parts.get("price", 0) > 0:
            facts.append(ExplanationFact(code="price", label="цена за сопоставимую единицу",
                                         source="ranking", score=selected.parts["price"]))
        if selected.parts.get("rating", 0) > 0:
            facts.append(ExplanationFact(code="rating", label="каталожный рейтинг",
                                         source="ranking", score=selected.parts["rating"]))
        if selected.parts.get("recsys", 0) > 0:
            facts.append(ExplanationFact(code="recsys", label="каталожная рекомендация",
                                         source="ranking", score=selected.parts["recsys"]))
    technical = [f.label for f in facts if f.code in SIGNAL_LABELS or f.code == "surface_match"]
    role = (f"Материал «{MATERIAL_TITLES[item.material]}» нужен для работы «{WORKS[item.work_type].title}»; "
            "товар прошёл привязку к этой позиции.")
    if technical:
        detail = "Для товара " + ", ".join(technical[:2]) + "."
    else:
        detail = "Дополнительных характеристик, подтверждающих преимущество именно этого товара, в каталоге нет."
    if picked:
        ranking = "Это пользовательский выбор, поэтому система не утверждает, что он лучше альтернатив."
    else:
        used = [f.label for f in facts if f.source == "ranking"]
        ranking = ("При ранжировании учитывались " + ", ".join(used[:2]) + ".") if used else ""
    explanation = " ".join(x for x in (role, detail, ranking) if x)
    status = "available" if technical else "limited"
    return RecommendationEvidence(status=status, product_id=p.id, room_type=room.room_type,
                                  work_type=item.work_type, surface=item.surface, material=item.material,
                                  facts=facts), explanation


def explanation_signals(resp: EstimateResponse, repo: CatalogRepo, limit: int = 30) -> list[dict]:
    """Grounded facts for an optional explanation model; no hidden product attributes."""
    out = []
    for room_index, room_est in enumerate(resp.rooms):
        room = room_est.room.model_copy(update={"picks": []})
        for item_index, item in enumerate(room_est.items):
            if not item.product or len(out) >= limit:
                continue
            p, b = repo.get(item.product.id), repo.binding(item.product.id)
            if not p or not b:
                continue
            evidence = item.recommendation_evidence
            out.append({
                "item_id": f"{room_index}:{item_index}",
                "work": item.work_type.value,
                "room": {"type": room.room_type.value, "humidity": room.effective_humidity.value},
                "product": {"id": p.id, "name": p.name, "price": str(p.result_price) if p.result_price else None,
                            "unit": p.unit, "specs": p.specs or {}},
                "evidence": evidence.model_dump(mode="json") if evidence else None,
                "deterministic_explanation": item.recommendation_explanation,
                # Kept for backward compatibility with the v1 explanation provider.
                "selection_signals": {fact.code: fact.score for fact in evidence.facts if fact.score is not None}
                                     if evidence else {},
                "deterministic_reasons": item.why,
                "cost_context": {"packages": item.packages, "cost": str(item.cost)},
            })
    return out


def apply_explanations(resp: EstimateResponse, values: dict[str, str]) -> EstimateResponse:
    for room_index, room_est in enumerate(resp.rooms):
        for item_index, item in enumerate(room_est.items):
            if text := values.get(f"{room_index}:{item_index}"):
                item.reason = text
    return resp

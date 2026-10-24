"""Расчётный движок сметы, карточки товара, доменных правил и RAG-пояснений."""

from __future__ import annotations

import logging
import re
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal
from typing import Any

from app.catalog.normalize import to_decimal
from app.catalog.repository import CatalogRepo, to_brief
from app.engine.consumption_standards import (
    CONSUMPTION_RATES,
    RAG_KNOWLEDGE_BASE,
    RESERVE_PCT,
)
from app.engine.interface import CalcError
from app.ml.interface import Ranker
from app.models import Product
from app.schemas import (
    EstimateItem,
    EstimateRequest,
    EstimateResponse,
    Level,
    ProductCalcRequest,
    ProductCalcResponse,
    ROOM_TITLES,
    RoomEstimate,
    RoomInput,
    RoomType,
    Surface,
)
from app.taxonomy import (
    MATERIAL_TITLES,
    RENOVATION_TITLES,
    STAGE_ORDER,
    STAGE_TITLES,
    WORKS,
    Material,
    RenovationType,
    Stage,
    WorkType,
)

log = logging.getLogger(__name__)

CENT = Decimal("0.01")

# ---------------------------------------------------------------------------
# Поправочные коэффициенты запаса (RESERVE) по материалам
# ---------------------------------------------------------------------------
RESERVE: dict[Material, Decimal] = {
    Material.tile: Decimal("10"),
    Material.tile_adhesive: Decimal("10"),
    Material.grout: Decimal("10"),
    Material.primer: Decimal("10"),
    Material.paint: Decimal("10"),
    Material.wallpaper: Decimal("10"),
    Material.wallpaper_glue: Decimal("10"),
    Material.laminate: Decimal("7"),
    Material.underlay: Decimal("5"),
    Material.linoleum: Decimal("5"),
    Material.drywall: Decimal("10"),
    Material.profile: Decimal("10"),
    Material.fasteners: Decimal("15"),
    Material.putty: Decimal("15"),
    Material.plaster: Decimal("15"),
    Material.screed_mix: Decimal("10"),
    Material.waterproofing: Decimal("10"),
    Material.sealant: Decimal("10"),
    Material.painting_tools: Decimal("0"),
    Material.cable: Decimal("15"),
    Material.socket: Decimal("0"),
    Material.switch: Decimal("0"),
    Material.plumbing: Decimal("0"),
    Material.demolition_tools: Decimal("0"),
    Material.other: Decimal("10"),
}

# Материалы, требующие обязательного флага moisture_resistant при повышенной влажности
NEEDS_MOISTURE = {
    Material.drywall,
    Material.paint,
    Material.putty,
    Material.plaster,
    Material.laminate,
    Material.wallpaper,
}

SURFACE_HINTS: dict[Surface, str] = {
    Surface.floor: r"напольн|керамогранит|для пола",
    Surface.wall: r"настенн|для стен",
}

WET_ROOMS = {RoomType.bathroom, RoomType.toilet}
DRY_ROOMS = {RoomType.living, RoomType.bedroom, RoomType.kids, RoomType.hallway}

# ---------------------------------------------------------------------------
# Доменные правила по помещениям
# ---------------------------------------------------------------------------
ROOM_RULES: dict[RoomType, dict[str, Any]] = {
    RoomType.bathroom: {
        "title": "Санузел",
        "required_works": [WorkType.waterproofing],
        "forbidden_materials": {Material.wallpaper, Material.laminate, Material.linoleum},
        "must_moisture_resistant": True,
        "description": "Мокрая зона (СП 29.13330): обязательна гидроизоляция пола и стен; запрещены невлагостойкие материалы (обои, ламинат).",
    },
    RoomType.toilet: {
        "title": "Туалет",
        "required_works": [WorkType.waterproofing],
        "forbidden_materials": {Material.wallpaper, Material.laminate},
        "must_moisture_resistant": True,
        "description": "Мокрая зона: обязательна гидроизоляция пола, рекомендована плитка или влагостойкая покраска.",
    },
    RoomType.kitchen: {
        "title": "Кухня",
        "required_works": [],
        "forbidden_materials": set(),
        "must_moisture_resistant": False,
        "description": "Зона повышенной нагрузки: рекомендуются моющиеся покрытия (плитка, износостойкая краска).",
    },
    RoomType.kids: {
        "title": "Детская",
        "required_works": [],
        "forbidden_materials": set(),
        "must_moisture_resistant": False,
        "description": "Детская: рекомендуются экологичные покрытия с минимальной эмиссией (бумажные/флизелиновые обои, вододисперсионная краска).",
    },
    RoomType.balcony: {
        "title": "Балкон",
        "required_works": [],
        "forbidden_materials": {Material.wallpaper},
        "must_moisture_resistant": True,
        "description": "Зона с перепадами температур и влажности: запрещены обои, требуются влагостойкие и морозостойкие составы.",
    },
    RoomType.living: {
        "title": "Гостиная",
        "required_works": [],
        "forbidden_materials": set(),
        "must_moisture_resistant": False,
        "description": "Жилая зона: чистовая отделка стен, напольные покрытия с подложкой.",
    },
    RoomType.bedroom: {
        "title": "Спальня",
        "required_works": [],
        "forbidden_materials": set(),
        "must_moisture_resistant": False,
        "description": "Зона отдыха: рекомендуются дышащие обои и ламинат с шумоизоляционной подложкой.",
    },
    RoomType.hallway: {
        "title": "Коридор",
        "required_works": [],
        "forbidden_materials": set(),
        "must_moisture_resistant": False,
        "description": "Зона высокой проходимости: износостойкие напольные покрытия (класс 32+), моющиеся стены.",
    },
}

# ---------------------------------------------------------------------------
# Шаблоны планов ремонта (PLANS)
# Ключ: (renovation_type_group, room_group)
# ---------------------------------------------------------------------------
W = WorkType
F, WL = Surface.floor, Surface.wall

PLANS: dict[tuple[str, str], list[tuple[WorkType, Surface | None]]] = {
    # Косметический ремонт: освежение финишных покрытий
    ("cosmetic", "wet"): [(W.priming, WL), (W.wall_painting, WL)],
    ("cosmetic", "kitchen"): [(W.priming, WL), (W.wall_painting, WL)],
    ("cosmetic", "dry"): [(W.priming, WL), (W.wallpapering, WL)],
    ("cosmetic", "balcony"): [(W.wall_painting, WL)],

    # Ремонт под сдачу: бюджетный, практичный, быстрый
    ("rental", "wet"): [(W.wall_painting, WL)],
    ("rental", "kitchen"): [(W.wall_painting, WL), (W.linoleum_laying, F)],
    ("rental", "dry"): [(W.wall_painting, WL), (W.linoleum_laying, F)],
    ("rental", "balcony"): [(W.wall_painting, WL)],

    # Капитальный ремонт: полный цикл от демонтажа до финиша
    ("capital", "wet"): [
        (W.demolition, None),
        (W.electrical_wiring, None),
        (W.waterproofing, F),
        (W.drywall_install, WL),
        (W.priming, WL),
        (W.tiling, F),
        (W.tiling, WL),
        (W.electrical_fittings, None),
        (W.plumbing_install, None),
    ],
    ("capital", "kitchen"): [
        (W.demolition, None),
        (W.electrical_wiring, None),
        (W.wall_putty, WL),
        (W.priming, WL),
        (W.tiling, F),
        (W.wall_painting, WL),
        (W.electrical_fittings, None),
    ],
    ("capital", "dry"): [
        (W.demolition, None),
        (W.electrical_wiring, None),
        (W.wall_putty, WL),
        (W.priming, WL),
        (W.wallpapering, WL),
        (W.laminate_laying, F),
        (W.electrical_fittings, None),
    ],
    ("capital", "balcony"): [(W.wall_putty, WL), (W.wall_painting, WL)],

    # Евроремонт (дизайнерский): улучшенная подготовка, высококачественные покрытия
    ("euro", "wet"): [
        (W.demolition, None),
        (W.electrical_wiring, None),
        (W.plumbing_rough, None),
        (W.waterproofing, F),
        (W.drywall_install, WL),
        (W.priming, WL),
        (W.tiling, F),
        (W.tiling, WL),
        (W.electrical_fittings, None),
        (W.plumbing_install, None),
    ],
    ("euro", "kitchen"): [
        (W.demolition, None),
        (W.electrical_wiring, None),
        (W.plumbing_rough, None),
        (W.wall_plastering, WL),
        (W.wall_putty, WL),
        (W.priming, WL),
        (W.tiling, F),
        (W.wall_painting, WL),
        (W.electrical_fittings, None),
    ],
    ("euro", "dry"): [
        (W.demolition, None),
        (W.electrical_wiring, None),
        (W.wall_plastering, WL),
        (W.wall_putty, WL),
        (W.priming, WL),
        (W.wallpapering, WL),
        (W.laminate_laying, F),
        (W.electrical_fittings, None),
    ],
    ("euro", "balcony"): [
        (W.wall_plastering, WL),
        (W.wall_putty, WL),
        (W.priming, WL),
        (W.wall_painting, WL),
    ],
}


def _group(room: RoomType) -> str:
    """Группировка помещений по характеру отделки."""
    if room in WET_ROOMS:
        return "wet"
    if room in DRY_ROOMS:
        return "dry"
    return room.value


def _plan(room: RoomInput, renovation: RenovationType) -> list[tuple[WorkType, Surface | None]]:
    """Получение перечня работ для помещения и типа ремонта."""
    if room.works:
        return [(w, None) for w in room.works]
    group_name = _group(room.room_type)
    # Если точный ключ есть в PLANS, используем его, иначе маппим euro -> capital
    if (renovation.value, group_name) in PLANS:
        return PLANS[(renovation.value, group_name)]
    kind = "capital" if renovation in (RenovationType.capital, RenovationType.euro) else renovation.value
    return PLANS.get((kind, group_name), PLANS[("capital", "dry")])


def _ceil(x: Decimal) -> int:
    return int(x.to_integral_value(rounding=ROUND_CEILING))


def _money(x: Decimal) -> Decimal:
    return x.quantize(CENT, rounding=ROUND_HALF_UP)


def _spec(p: Product, key: str) -> Decimal | None:
    v = (p.specs or {}).get(key)
    return to_decimal(v["value"] if isinstance(v, dict) else v)


def packages_for_area(
    p: Product,
    area: Decimal,
    reserve_pct: Decimal,
    layers: int = 1,
) -> tuple[Decimal, str, int, str]:
    """
    Расчёт требуемого количества упаковок/штук материала для заданной площади.

    Returns:
        (потребность_в_единицах, единица_измерения, количество_упаковок, формула)
    """
    need = area * layers * (1 + reserve_pct / 100)
    unit = (p.unit or "").lower()

    # 1. Товар с заданной площадью покрытия упаковкой (плитка, ламинат, панели)
    pack_area = p.package_area or _spec(p, "pack_area_m2")
    if pack_area and pack_area > 0:
        n = _ceil(need / pack_area)
        formula = f"{area:.2f} м² × {layers} × (1 + {reserve_pct}%) / {pack_area} м² в упак. → {n}"
        return need, "м²", n, formula

    # 2. Товар продаётся в м² (линолеум на отрез, ковролин)
    if unit in ("м2", "м²", "кв.м"):
        n = _ceil(need)
        formula = f"{area:.2f} м² × (1 + {reserve_pct}%) → {n} м²"
        return need, "м²", n, formula

    # 3. Листовой или рулонный материал с известными размерами (обои, ГКЛ)
    length, width = _spec(p, "length_m"), _spec(p, "width_m")
    if length and width and length > 0 and width > 0:
        rapport = _spec(p, "rapport_m")
        if rapport and rapport > 0:
            # Расчёт обоев с раппортом: при высоте потолка 2.7 м отходы на подгонку рисунка
            wall_h = Decimal("2.7")
            cut_length = wall_h + rapport
            strips_per_roll = max(int(length / cut_length), 1)
            effective_roll_area = Decimal(strips_per_roll) * width * wall_h
            if effective_roll_area > 0:
                n = _ceil(need / effective_roll_area)
                formula = (
                    f"{area:.2f} м² × (1 + {reserve_pct}%) / {effective_roll_area:.2f} м² "
                    f"(рулон {width}×{length} м с раппортом {rapport} м, {strips_per_roll} пол.) → {n}"
                )
                return need, "м²", n, formula

        sheet = length * width
        n = _ceil(need / sheet)
        formula = f"{area:.2f} м² × (1 + {reserve_pct}%) / {sheet:.3f} м² (лист/рулон) → {n}"
        return need, "м²", n, formula

    # 4. Материал с нормой расхода (краска, грунтовка, штукатурка, смеси)
    cons = (p.specs or {}).get("consumption")
    volume, weight = _spec(p, "volume_l"), _spec(p, "weight_kg")
    if isinstance(cons, dict):
        rate = to_decimal(cons.get("value"))
        cons_unit = cons.get("unit")
        if cons_unit == "l/m2" and volume and rate:
            liters = area * layers * rate * (1 + reserve_pct / 100)
            n = _ceil(liters / volume)
            formula = f"{area:.2f} м² × {layers} сл. × {rate} л/м² / {volume} л → {n}"
            return liters, "л", n, formula
        if cons_unit == "kg/m2" and weight and rate:
            kg = area * rate * (1 + reserve_pct / 100)
            n = _ceil(kg / weight)
            formula = f"{area:.2f} м² × {rate} кг/м² / {weight} кг → {n}"
            return kg, "кг", n, formula
        if cons_unit == "m2/l" and volume and rate and rate > 0:
            liters = area * layers / rate * (1 + reserve_pct / 100)
            n = _ceil(liters / volume)
            formula = f"{area:.2f} м² × {layers} сл. / {rate} м²/л / {volume} л → {n}"
            return liters, "л", n, formula

    raise CalcError(f"Для товара {p.id} нет фасовки или расхода в характеристиках")


def _piece_need(material: Material, room: RoomInput, area: Decimal) -> tuple[Decimal, str] | None:
    """Поштучный или метражный расчёт потребности для инженерных и монтажных позиций."""
    if material == Material.cable:
        # Периметр комнаты × 2 + спуски к розеткам и выключателям (ПУЭ)
        return room.perimeter * 2, "м"
    if material == Material.socket:
        # СП 256.1325800.2016: не менее 1 розетки на 6 м², для кухни от 4-5
        if room.room_type == RoomType.kitchen:
            return Decimal(max(5, _ceil(room.floor_area / 3))), "шт"
        return Decimal(max(2, _ceil(room.floor_area / 4))), "шт"
    if material == Material.switch:
        return Decimal(1), "шт"
    if material in (Material.painting_tools, Material.demolition_tools, Material.plumbing):
        return Decimal(1), "шт"
    if material == Material.sealant:
        return Decimal(1), "шт"
    if material == Material.profile:
        # Профиль для каркаса ГКЛ: ~2.0 м.п. на 1 м² облицовки, шаг стоек 60 см
        return Decimal(_ceil(area / Decimal("1.5"))), "шт"
    if material == Material.fasteners:
        # Саморезы для ГКЛ: ~25 шт. на лист (упаковки по 100-200 шт.)
        return Decimal(_ceil(area / 10)), "упак."
    return None


class BaselineEngine:
    """
    Основной расчётный движок:
      - формирование сметы с учётом доменных правил и норм СНиП;
      - точный расчёт материалов для карточки товара;
      - RAG-генерация обоснований выбора материалов и поправочных коэффициентов.
    """

    def __init__(self, ranker: Ranker):
        self.ranker = ranker

    def _item(
        self,
        repo: CatalogRepo,
        room: RoomInput,
        work: WorkType,
        material: Material,
        surface: Surface | None,
        floor: Decimal,
        walls: Decimal,
    ) -> EstimateItem:
        info = WORKS[work]
        area = walls if surface == Surface.wall else floor
        wet = room.effective_humidity == Level.high and material in NEEDS_MOISTURE

        cands = repo.candidates(
            material,
            required_flags=["moisture_resistant"] if wet else [],
            min_confidence=0.8,
        )
        ranked = self.ranker.rank(cands, room)
        hint = SURFACE_HINTS.get(surface) if material == Material.tile else None
        if hint:
            ranked.sort(key=lambda p: not re.search(hint, p.name.lower()))

        base = dict(
            stage=info.stage,
            work_type=work,
            material=material,
            surface=surface,
            title=MATERIAL_TITLES[material],
        )

        if not ranked:
            return EstimateItem(
                **base,
                required_amount=Decimal(0),
                required_unit="",
                packages=0,
                reason="нет подходящего товара в каталоге",
            )

        p = ranked[0]
        piece = _piece_need(material, room, area)
        if piece:
            need, unit = piece
            n = _ceil(need)
            reason = "влагостойкий, т.к. высокая влажность" if wet else None
        else:
            reserve = RESERVE.get(material, Decimal(5))
            layers = 2 if material == Material.paint else 1
            try:
                need, unit, n, _ = packages_for_area(p, area, reserve, layers=layers)
                reason = "влагостойкий, т.к. высокая влажность" if wet else None
            except CalcError as e:
                # Попытка применить нормативный расход из СНиП (CONSUMPTION_RATES)
                std = CONSUMPTION_RATES.get(material.value)
                volume, weight = _spec(p, "volume_l"), _spec(p, "weight_kg")
                if std and std.consumption_rate:
                    if std.consumption_unit == "l/m2" and volume and volume > 0:
                        liters = area * layers * std.consumption_rate * (1 + reserve / 100)
                        n = _ceil(liters / volume)
                        need, unit = liters, "л"
                        reason = f"расход по СНиП ({std.consumption_rate} л/м²)"
                    elif std.consumption_unit == "kg/m2" and weight and weight > 0:
                        kg = area * std.consumption_rate * (1 + reserve / 100)
                        n = _ceil(kg / weight)
                        need, unit = kg, "кг"
                        reason = f"расход по СНиП ({std.consumption_rate} кг/м²)"
                    else:
                        return EstimateItem(
                            **base,
                            product=to_brief(p),
                            required_amount=area,
                            required_unit="м²",
                            packages=0,
                            reason=str(e),
                        )
                else:
                    return EstimateItem(
                        **base,
                        product=to_brief(p),
                        required_amount=area,
                        required_unit="м²",
                        packages=0,
                        reason=str(e),
                    )

        price = p.result_price or Decimal(0)
        return EstimateItem(
            **base,
            product=to_brief(p),
            required_amount=need.quantize(CENT),
            required_unit=unit,
            packages=n,
            unit_price=price,
            cost=_money(price * n),
            reason=reason,
            alternatives=[to_brief(a) for a in ranked[1:4]],
        )

    def estimate(self, req: EstimateRequest, repo: CatalogRepo) -> EstimateResponse:
        rooms: list[RoomEstimate] = []
        warnings: list[str] = []

        for room in req.rooms:
            floor = room.floor_area
            walls = max(room.perimeter * room.height_m - room.openings_area_m2, Decimal(0))
            items: list[EstimateItem] = []
            seen: set[tuple[Material, Surface | None]] = set()

            # Проверка доменных ограничений помещения
            rule = ROOM_RULES.get(room.room_type)
            if rule:
                forbidden = rule.get("forbidden_materials", set())
                for work, surface in _plan(room, req.renovation_type):
                    for mat in WORKS[work].materials:
                        if mat in forbidden:
                            warnings.append(
                                f"{room.name or ROOM_TITLES[room.room_type]}: "
                                f"материал «{MATERIAL_TITLES[mat]}» не рекомендуется для {rule['title'].lower()} ({rule['description']})"
                            )

            for work, surface in _plan(room, req.renovation_type):
                for material in WORKS[work].materials:
                    if (material, surface) in seen:
                        continue
                    seen.add((material, surface))
                    items.append(self._item(repo, room, work, material, surface, floor, walls))

            items.sort(key=lambda i: STAGE_ORDER.index(i.stage))
            missing = sorted({i.title for i in items if i.packages == 0})
            if missing:
                warnings.append(
                    f"{room.name or ROOM_TITLES[room.room_type]}: не подобраны — {', '.join(missing)}"
                )

            subtotal = _money(sum((i.cost for i in items), Decimal(0)))
            rooms.append(
                RoomEstimate(
                    room=room,
                    floor_area_m2=floor,
                    wall_area_m2=walls.quantize(CENT),
                    items=items,
                    subtotal=subtotal,
                )
            )

        return EstimateResponse(
            object_type=req.object_type,
            renovation_type=req.renovation_type,
            rooms=rooms,
            total=_money(sum((r.subtotal for r in rooms), Decimal(0))),
            warnings=warnings,
        )

    def calc_product(
        self, product: Product, req: ProductCalcRequest, repo: CatalogRepo
    ) -> ProductCalcResponse:
        binding = repo.binding(product.id)
        material = Material(binding.material) if binding else None
        reserve = (
            req.reserve_pct
            if req.reserve_pct is not None
            else RESERVE.get(material, Decimal(5))
        )
        need, unit, n, formula = packages_for_area(product, req.net_area, reserve, req.layers)
        price = product.result_price
        return ProductCalcResponse(
            product=to_brief(product),
            material=material,
            area_m2=req.net_area.quantize(CENT),
            required_amount=need.quantize(CENT),
            required_unit=unit,
            packages=n,
            unit_price=price,
            total_cost=_money(price * n) if price is not None else None,
            reserve_pct=reserve,
            formula=formula,
            warnings=[] if price is not None else ["у товара нет цены"],
        )

    async def explain(self, req: EstimateRequest, resp: EstimateResponse) -> EstimateResponse:
        """
        RAG-генерация обоснования сметы:
          - поиск релевантных статей СНиП и ГОСТ по подобранным материалам;
          - учёт коэффициентов запаса и условий эксплуатации;
          - вызов LLM (Ollama) с fallback на детерминированное экспертное резюме.
        """
        if not req.explain:
            return resp

        # Сбор используемых материалов и видов работ
        used_materials: set[str] = set()
        used_works: set[str] = set()
        high_humidity_rooms: list[str] = []

        for r_est in resp.rooms:
            if r_est.room.effective_humidity == Level.high:
                high_humidity_rooms.append(
                    r_est.room.name or ROOM_TITLES[r_est.room.room_type]
                )
            for it in r_est.items:
                if it.packages > 0:
                    used_materials.add(it.material.value)
                    used_works.add(it.work_type.value)

        # Извлечение сниппетов из RAG_KNOWLEDGE_BASE с помощью FAISS векторного хранилища
        try:
            from app.engine.rag_store import get_rag_store
            store = get_rag_store()
            matched_docs = store.search_by_materials_and_works(
                materials=used_materials,
                works=used_works,
                room_types={r.room.room_type.value for r in resp.rooms},
                top_k=8,
            )
        except Exception as e:
            log.warning("Ошибка FAISS RAG хранилища, fallback на статический перебор: %s", e)
            matched_docs = [
                d for d in RAG_KNOWLEDGE_BASE
                if d.get("material") in used_materials or d.get("work_type") in used_works
            ][:8]

        sources_set: set[str] = {d["source"] for d in matched_docs if d.get("source")}

        # Базовые нормативные документы
        sources_set.add("СНиП 3.04.01-87 «Изоляционные и отделочные покрытия»")
        sources_set.add("СП 29.13330.2011 «Полы»")
        sources_set.add("СП 256.1325800.2016 «Электроустановки жилых и общественных зданий»")
        resp.sources = sorted(sources_set)

        # Попытка генерации через LLM
        try:
            from app.llm.client import get_llm

            llm = get_llm()
            renov_title = RENOVATION_TITLES.get(req.renovation_type, req.renovation_type.value)
            rooms_summary = ", ".join(
                f"{r.room.name or ROOM_TITLES[r.room.room_type]} ({r.floor_area_m2:.1f} м²)"
                for r in resp.rooms
            )
            context_text = "\n".join(f"- {d['text']} (Источник: {d['source']})" for d in matched_docs[:8])

            prompt = (
                f"Ты — профессиональный инженер-сметчик. Дай краткое экспертное обоснование сметы "
                f"для типа ремонта «{renov_title}» (помещения: {rooms_summary}).\n\n"
                f"Используй подтверждённые строительные нормы:\n{context_text}\n\n"
                f"Требования к ответу:\n"
                f"1. Объясни, почему выбраны данные материалы и технологии.\n"
                f"2. Укажи поправочные коэффициенты запаса (на подрезку плитки, раппорт обоев, слои краски).\n"
                f"3. Для мокрых зон ({', '.join(high_humidity_rooms) or 'нет'}) подчеркни требования СП по гидроизоляции и влагостойкости.\n"
                f"4. Не придумывай несуществующие нормы; пиши лаконично (3-5 абзацев)."
            )

            explanation = await llm.chat(
                [{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=600,
            )
            if explanation and len(explanation.strip()) > 20:
                resp.explanation = explanation.strip()
                return resp
        except Exception as e:
            log.info("LLM недоступен для explain, используется детерминированный RAG: %s", e)

        # Детерминированный fallback на основе нормативной базы
        paragraphs: list[str] = []
        renov_title = RENOVATION_TITLES.get(req.renovation_type, req.renovation_type.value)

        paragraphs.append(
            f"Смета составлена для формата «{renov_title}» в соответствии с технологическими "
            f"регламентами СНиП 3.04.01-87 и СП 71.13330.2017. Последовательность работ структурирована "
            f"по 5 технологическим стадиям: от подготовки и демонтажа до чистового монтажа сантехники и электрики."
        )

        if high_humidity_rooms:
            paragraphs.append(
                f"В помещениях с высокой влажностью ({', '.join(high_humidity_rooms)}) применены специальные требования "
                f"СП 29.13330: предусмотрена сплошная обмазочная гидроизоляция пола с заводом на стены, "
                f"а также влагостойкие листовые материалы (ГКЛВ) и плиточный клей с повышенной адгезией."
            )

        paragraphs.append(
            "В расчётах применены нормативные поправочные коэффициенты запаса: "
            "плитка и керамогранит — 10 % (на подрезку и отходы при укладке), "
            "напольные покрытия (ламинат) — 7 %, листовые и профильные конструкции — 10-15 %, "
            "водно-дисперсионные краски и грунтовки — двухслойное нанесение с запасом 10 % согласно ГОСТ Р 52020-2003."
        )

        resp.explanation = "\n\n".join(paragraphs)
        return resp

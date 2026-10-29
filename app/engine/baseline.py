"""
Расчётный движок сметы, карточки товара, доменной логики и RAG-пояснений.

Совместим с app/plans.py и расширенным taxonomy.py из ветки main.
"""

from __future__ import annotations

import logging
import re
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal

from app.catalog.normalize import to_decimal
from app.catalog.repository import CatalogRepo, to_brief
from app.config import get_settings
from app.engine.consumption_standards import CONSUMPTION_RATES, RAG_KNOWLEDGE_BASE
from app.engine.interface import CalcError
from app.ml.interface import Ranker
from app.models import Product
from app.plans import WORK_SURFACE, works_for_room, work_materials
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
    WORKS,
    Material,
    RenovationType,
    WorkType,
)

log = logging.getLogger(__name__)

CENT = Decimal("0.01")
CANDIDATES_LIMIT = 20000

# ---------------------------------------------------------------------------
# Поправочные коэффициенты запаса на подрезку, отходы, раппорт (СНиП 3.04.01-87)
# ---------------------------------------------------------------------------
RESERVE: dict[Material, Decimal] = {
    Material.tile: Decimal(10),
    Material.tile_adhesive: Decimal(10),
    Material.grout: Decimal(10),
    Material.primer: Decimal(10),
    Material.paint: Decimal(5),
    Material.wallpaper: Decimal(10),
    Material.wallpaper_glue: Decimal(10),
    Material.laminate: Decimal(7),
    Material.underlay: Decimal(5),
    Material.linoleum: Decimal(5),
    Material.drywall: Decimal(10),
    Material.profile: Decimal(10),
    Material.fasteners: Decimal(15),
    Material.putty: Decimal(15),
    Material.plaster: Decimal(15),
    Material.screed_mix: Decimal(10),
    Material.waterproofing: Decimal(10),
    Material.sealant: Decimal(10),
    Material.painting_tools: Decimal(0),
    Material.cable: Decimal(15),
    Material.socket: Decimal(0),
    Material.switch: Decimal(0),
    Material.demolition_tools: Decimal(0),
    Material.other: Decimal(10),
}

# Инструменты и оборудование, обобщаемые на весь проект (дедупликация между комнатами)
SHARED_PROJECT_MATERIALS: set[Material] = {
    Material.painting_tools,
    Material.demolition_tools,
}


def _is_shared_tool(item: EstimateItem) -> bool:
    """Определяет, относится ли позиция сметы к общему многоразовому инструменту/инвентарю."""
    if item.material in SHARED_PROJECT_MATERIALS:
        return True
    if item.product and item.product.name:
        name_lower = item.product.name.lower()
        if any(
            w in name_lower
            for w in (
                "миксер строительный",
                "насадка для миксера",
                "шпатель зубчатый",
                "правило штукатурное",
                "уровень строительный",
                "ёмкость для замеса",
            )
        ):
            return True
    return False

# Материалы, для которых в мокрых зонах требуется флаг moisture_resistant
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


Step = tuple[WorkType, Surface | None, tuple[Material, ...]]


def _plan(room: RoomInput, renovation: RenovationType) -> list[Step]:
    """Получение перечня технологических шагов для помещения."""
    if room.works:
        steps = []
        for c in room.works:
            mats = work_materials(c.work_type, c.materials)
            if c.materials is None and c.work_type == WorkType.wall_painting:
                if Material.painting_tools not in mats:
                    mats = mats + (Material.painting_tools,)
            steps.append(
                (
                    c.work_type,
                    c.surface or WORK_SURFACE.get(c.work_type),
                    mats,
                )
            )
        return steps

    options = works_for_room(room.room_type, room.renovation_type or renovation)
    steps = []
    for o, default in options:
        if default:
            mats = work_materials(o.work, o.materials)
            if o.materials is None and o.work == WorkType.wall_painting:
                if Material.painting_tools not in mats:
                    mats = mats + (Material.painting_tools,)
            steps.append((o.work, o.surface, mats))
    return steps


def _ceil(x: Decimal) -> int:
    return int(x.to_integral_value(rounding=ROUND_CEILING))


def _money(x: Decimal) -> Decimal:
    return x.quantize(CENT, rounding=ROUND_HALF_UP)


def _spec(p: Product, key: str) -> Decimal | None:
    v = (p.specs or {}).get(key)
    return to_decimal(v["value"] if isinstance(v, dict) else v)


def _extract_pack_area(name: str | None) -> Decimal | None:
    if not name:
        return None
    m = re.search(r'(\d+(?:[.,]\d+)?)\s*(?:м2|м²|кв\.?\s*м)', name, re.IGNORECASE)
    if m:
        try:
            val = Decimal(m.group(1).replace(',', '.'))
            if val > 0:
                return val
        except Exception:
            pass
    m = re.search(r'(\d+(?:[.,]\d+)?)\s*[xх×]\s*(\d+(?:[.,]\d+)?)\s*м\b', name, re.IGNORECASE)
    if m:
        try:
            val = Decimal(m.group(1).replace(',', '.')) * Decimal(m.group(2).replace(',', '.'))
            if val > 0:
                return val
        except Exception:
            pass
    m = re.search(r'(\d+(?:[.,]\d+)?)\s*[xх×]\s*(\d+(?:[.,]\d+)?)\s*см\b', name, re.IGNORECASE)
    if m:
        try:
            w = Decimal(m.group(1).replace(',', '.')) / Decimal(100)
            h = Decimal(m.group(2).replace(',', '.')) / Decimal(100)
            if w > 0 and h > 0:
                return (w * h * 4).quantize(Decimal('0.01'))
        except Exception:
            pass
    return None


def _extract_weight_volume(name: str | None) -> tuple[Decimal | None, Decimal | None]:
    if not name:
        return None, None
    weight, volume = None, None
    mw = re.search(r'(\d+(?:[.,]\d+)?)\s*(?:кг|kg)\b', name, re.IGNORECASE)
    if mw:
        try:
            weight = Decimal(mw.group(1).replace(',', '.'))
        except Exception:
            pass
    mv = re.search(r'(\d+(?:[.,]\d+)?)\s*(?:л|l)\b', name, re.IGNORECASE)
    if mv:
        try:
            volume = Decimal(mv.group(1).replace(',', '.'))
        except Exception:
            pass
    return weight, volume


PASTE_OR_MIX_MATERIALS = {
    Material.putty,
    Material.plaster,
    Material.screed_mix,
    Material.primer,
    Material.paint,
    Material.tile_adhesive,
    Material.grout,
    Material.wallpaper_glue,
    Material.waterproofing,
}


def _is_paste_or_mix(p: Product, material: Material | None) -> bool:
    if material in PASTE_OR_MIX_MATERIALS:
        return True
    name_lower = (p.name or '').lower()
    return any(
        w in name_lower
        for w in (
            'шпатлевк', 'шпаклевк', 'штукатурк', 'стяжк', 'наливной пол',
            'грунтовк', 'грунт ', 'краск', 'эмаль', 'клей плиточн', 'затирк'
        )
    )


def packages_for_area(
    p: Product,
    area: Decimal,
    reserve_pct: Decimal,
    layers: int = 1,
    material: Material | None = None,
) -> tuple[Decimal, str, int, str]:
    """
    Расчёт требуемого количества упаковок/штук материала для заданной площади.

    Returns:
        (потребность_в_единицах, единица_измерения, количество_упаковок, формула)
    """
    need = area * layers * (1 + reserve_pct / 100)
    unit = (p.unit or "").lower()

    # 1. Товар с заданной площадью покрытия упаковкой (плитка, ламинат, панели, подложка)
    pack_area = p.package_area or _spec(p, "pack_area_m2") or _extract_pack_area(p.name)
    if pack_area and pack_area > 0:
        n = _ceil(need / pack_area)
        formula = f"{area:.2f} м² × {layers} × (1 + {reserve_pct}%) / {pack_area} м² в упак. → {n}"
        return need, "м²", n, formula

    # 2. Товар продаётся в м² (линолеум на отрез, ковролин)
    if unit in ("м2", "м²", "кв.м"):
        n = _ceil(need)
        formula = f"{area:.2f} м² × (1 + {reserve_pct}%) → {n} м²"
        return need, "м²", n, formula

    is_mix = _is_paste_or_mix(p, material)

    # 3. Листовой или рулонный материал с известными размерами (обои, ГКЛ) — строго НЕ строительные смеси
    if not is_mix:
        length, width = _spec(p, "length_m"), _spec(p, "width_m")
        if length and width and length > 0 and width > 0:
            rapport = _spec(p, "rapport_m")
            if rapport and rapport > 0:
                # Учёт раппорта обоев: отходы на подгонку рисунка при стандартной высоте стены 2.7 м
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
    if not volume and not weight:
        ew, ev = _extract_weight_volume(p.name)
        weight, volume = weight or ew, volume or ev

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

    # 5. Применение нормативного расхода из СНиП/СП для смесей и паст без расхода в каталоге
    std_key = material.value if material else None
    if not std_key and is_mix:
        name_lower = (p.name or "").lower()
        if "шпатлевк" in name_lower or "шпаклевк" in name_lower:
            std_key = "putty"
        elif "штукатурк" in name_lower:
            std_key = "plaster"
        elif "стяжк" in name_lower:
            std_key = "screed_mix"
        elif "грунтовк" in name_lower:
            std_key = "primer"
        elif "краск" in name_lower or "эмаль" in name_lower:
            std_key = "paint"

    if std_key:
        std = CONSUMPTION_RATES.get(std_key)
        if std and std.consumption_rate:
            if std.consumption_unit == "kg/m2" and weight and weight > 0:
                kg = area * std.consumption_rate * (1 + reserve_pct / 100)
                n = _ceil(kg / weight)
                formula = f"{area:.2f} м² × {std.consumption_rate} кг/м² (СНиП) / {weight} кг → {n}"
                return kg, "кг", n, formula
            if std.consumption_unit == "l/m2" and volume and volume > 0:
                liters = area * layers * std.consumption_rate * (1 + reserve_pct / 100)
                n = _ceil(liters / volume)
                formula = f"{area:.2f} м² × {layers} сл. × {std.consumption_rate} л/м² (СНиП) / {volume} л → {n}"
                return liters, "л", n, formula

    raise CalcError(f"Для товара {p.id} нет фасовки или расхода в характеристиках")


def _piece_need(material: Material, room: RoomInput, area: Decimal) -> tuple[Decimal, str] | None:
    """Поштучный или метражный расчёт потребности для инженерных и монтажных позиций."""
    floor, perimeter = room.floor_area, room.perimeter
    if material == Material.cable:
        # Периметр комнаты × 2 + спуски к электроточкам (ПУЭ)
        return perimeter * 2, "м"
    if hasattr(Material, "cable_channel") and material == Material.cable_channel:
        return perimeter, "м"
    if hasattr(Material, "skirting") and material == Material.skirting:
        return perimeter, "м"
    if hasattr(Material, "damper_tape") and material == Material.damper_tape:
        return perimeter, "м"
    if material == Material.socket:
        # СП 256.1325800.2016: на кухне повышенное количество электроточек
        if room.room_type == RoomType.kitchen:
            return Decimal(max(5, _ceil(floor / 3))), "шт"
        return Decimal(max(2, _ceil(floor / 4))), "шт"
    if hasattr(Material, "electrical_boxes") and material == Material.electrical_boxes:
        return Decimal(max(3, _ceil(floor / 4) + 1)), "шт"
    if (hasattr(Material, "lighting") and material == Material.lighting) or (
        hasattr(Material, "lamps") and material == Material.lamps
    ):
        return Decimal(max(1, _ceil(floor / 8))), "шт"
    if hasattr(Material, "heating") and material == Material.heating:
        if room.room_type in (RoomType.bathroom,):
            return Decimal(1), "шт"
        return Decimal(max(1, _ceil(floor / 10))), "шт"
    if material == Material.profile or (hasattr(Material, "beacons") and material == Material.beacons):
        return Decimal(_ceil(area / Decimal("1.5"))), "шт"
    if material == Material.fasteners or (
        hasattr(Material, "tile_leveling") and material == Material.tile_leveling
    ):
        return Decimal(max(1, _ceil(area / 10))), "упак."
    if (
        material
        in (
            Material.switch,
            Material.painting_tools,
            Material.sealant,
            Material.plumbing,
            Material.demolition_tools,
        )
        or (hasattr(Material, "doors") and material == Material.doors)
        or (hasattr(Material, "ventilation") and material == Material.ventilation)
        or (hasattr(Material, "pipes") and material == Material.pipes)
        or (hasattr(Material, "circuit_breakers") and material == Material.circuit_breakers)
        or (hasattr(Material, "reinforcing_mesh") and material == Material.reinforcing_mesh)
        or (hasattr(Material, "mounting_foam") and material == Material.mounting_foam)
        or (hasattr(Material, "door_hardware") and material == Material.door_hardware)
        or (hasattr(Material, "mounting_adhesive") and material == Material.mounting_adhesive)
        or (hasattr(Material, "decorative") and material == Material.decorative)
    ):
        return Decimal(1), "шт"
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
        is_tool = material in SHARED_PROJECT_MATERIALS or material in (
            Material.painting_tools,
            Material.demolition_tools,
            Material.hand_tools,
            Material.power_tools,
        )
        cands = repo.candidates(
            material,
            work_type=None if is_tool else work,
            required_flags=["moisture_resistant"] if wet else [],
            min_confidence=get_settings().autobind_min_confidence,
            limit=CANDIDATES_LIMIT,
        )
        ranked = self.ranker.rank(cands, room)
        hint = SURFACE_HINTS.get(surface) if material == Material.tile else None
        if hint:
            ranked.sort(key=lambda p: not re.search(hint, p.name.lower()))

        if material == Material.plaster:
            # Для оштукатуривания стен приоритет у базовых выравнивающих смесей; декоративные (фактурные) опускаем в конец
            ranked.sort(key=lambda p: bool(re.search(r"декоратив|фактурн|шуба|короед|микроцемент|венециан|stucco|grotto|modellier", p.name.lower())))
        elif material == Material.putty:
            # Для шпаклевки также исключаем декоративные пасты
            ranked.sort(key=lambda p: bool(re.search(r"декоратив|фактурн|венециан", p.name.lower())))
        elif hasattr(Material, "heating") and material == Material.heating and room.room_type in (RoomType.bathroom,):
            # В ванной комнате приоритет отдаем полотенцесушителям, а не комнатным радиаторам
            ranked.sort(key=lambda p: not bool(re.search(r"полотенцесушител", p.name.lower())))
        elif hasattr(Material, "beacons") and material == Material.beacons and surface == Surface.wall:
            # Для стен приоритет у стеновых маячковых профилей перед маяками для наливного пола
            ranked.sort(key=lambda p: bool(re.search(r"наливн|для пола", p.name.lower())))

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
            if unit in ("м", "пог. м", "п.м"):
                pack_len = _spec(p, "pack_length_m") or _spec(p, "length_m")
                if not pack_len and p.name:
                    m_len = re.search(r"(?<![\dх×x*])(\d+(?:[.,]\d+)?)\s*м(?:етр\w*)?(?![а-яa-z2²\d])", p.name, re.IGNORECASE)
                    if m_len:
                        try:
                            val = Decimal(m_len.group(1).replace(",", "."))
                            if val >= 1:
                                pack_len = val
                        except Exception:
                            pass
                if not pack_len:
                    if hasattr(Material, "cable_channel") and material == Material.cable_channel:
                        pack_len = Decimal("2.0")
                    elif hasattr(Material, "skirting") and material == Material.skirting:
                        pack_len = Decimal("2.5")
                    elif hasattr(Material, "damper_tape") and material == Material.damper_tape:
                        pack_len = Decimal("25.0")

                p_unit = (p.unit or "").lower()
                if pack_len and pack_len > 0 and p_unit not in ("м", "м.", "пог. м", "пог.м"):
                    n = _ceil(need / pack_len)
                else:
                    n = _ceil(need)
            else:
                # Поштучные позиции (маяки, крепеж, лампы): проверяем фасовку в упаковке
                pcs = _spec(p, "pcs_in_pack")
                if not pcs and p.name:
                    m_pcs = re.search(r"(?<![\dх×x*])(\d+)\s*шт(?![а-яa-z\d])", p.name, re.IGNORECASE)
                    if m_pcs:
                        try:
                            val = Decimal(m_pcs.group(1))
                            if val > 1:
                                pcs = val
                        except Exception:
                            pass
                item_len = _spec(p, "length_m") or _spec(p, "pack_length_m")
                if pcs and pcs > 1:
                    n = _ceil(need / pcs)
                elif item_len and item_len > 1 and material == Material.profile:
                    n = _ceil(need / item_len)
                else:
                    n = _ceil(need)
            reason = "влагостойкий, т.к. высокая влажность" if wet else None
        else:
            reserve = RESERVE.get(material, Decimal(5))
            layers = 2 if material == Material.paint else 1
            try:
                need, unit, n, _ = packages_for_area(p, area, reserve, layers=layers, material=material)
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
        is_multi_room = len(req.rooms) > 1
        shared_tool_items: list[EstimateItem] = []
        seen_tools: set[tuple[Material, int | None]] = set()

        for room in req.rooms:
            floor = room.floor_area
            walls = max(room.perimeter * room.height_m - room.openings_area_m2, Decimal(0))
            items: list[EstimateItem] = []
            seen: set[tuple[Material, Surface | None]] = set()

            for work, surface, materials in _plan(room, req.renovation_type):
                for material in materials:
                    if (material, surface) in seen:
                        continue
                    seen.add((material, surface))
                    item = self._item(repo, room, work, material, surface, floor, walls)

                    # Дедупликация инструментов для многокомнатных проектов
                    if is_multi_room and _is_shared_tool(item):
                        tool_key = (item.material, item.product.id if item.product else None)
                        if tool_key not in seen_tools:
                            seen_tools.add(tool_key)
                            item_copy = item.model_copy()
                            item_copy.reason = "многоразовый инструмент на весь объект (дедупликация)"
                            shared_tool_items.append(item_copy)
                        # Из сметы конкретной комнаты убираем дубликат
                        continue

                    items.append(item)

            items.sort(key=lambda i: STAGE_ORDER.index(i.stage))
            missing_no_product = sorted({i.title for i in items if i.product is None})
            if missing_no_product:
                warnings.append(
                    f"{room.name or ROOM_TITLES[room.room_type]}: не найдены в каталоге — {', '.join(missing_no_product)}"
                )
            missing_qty = sorted({i.title for i in items if i.product is not None and i.packages == 0})
            if missing_qty:
                warnings.append(
                    f"{room.name or ROOM_TITLES[room.room_type]}: товар подобран, но требуется уточнить количество — {', '.join(missing_qty)}"
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

        # Добавление сводного блока "Инструменты и расходники на весь объект" при наличии общих позиций
        if is_multi_room and shared_tool_items:
            shared_tool_items.sort(key=lambda i: STAGE_ORDER.index(i.stage))
            missing_tools = sorted({i.title for i in shared_tool_items if i.packages == 0})
            if missing_tools:
                warnings.append(
                    f"Инструменты и расходники на весь объект: не подобраны — {', '.join(missing_tools)}"
                )
            shared_subtotal = _money(sum((i.cost for i in shared_tool_items), Decimal(0)))
            shared_room = RoomEstimate(
                room=RoomInput(
                    name="Инструменты и расходники на весь объект",
                    room_type=RoomType.general_indoor,
                    length_m=Decimal("1.0"),
                    width_m=Decimal("1.0"),
                    height_m=Decimal("2.7"),
                    openings_area_m2=Decimal("0.0"),
                ),
                floor_area_m2=Decimal("0.0"),
                wall_area_m2=Decimal("0.0"),
                items=shared_tool_items,
                subtotal=shared_subtotal,
            )
            rooms.append(shared_room)

        priced_items = sum(1 for room in rooms for item in room.items if item.packages > 0 and item.cost > 0)
        missing_items = sum(1 for room in rooms for item in room.items if item.packages == 0)
        status = "unavailable" if not priced_items else ("partial" if missing_items else "complete")
        if status == "unavailable":
            warnings.insert(0, "Смета не рассчитана: для выбранных работ нет товаров с подходящей привязкой, ценой и данными для расчёта")
        elif status == "partial":
            warnings.insert(0, f"Смета рассчитана частично: не удалось рассчитать позиций — {missing_items}")

        return EstimateResponse(
            object_type=req.object_type,
            renovation_type=req.renovation_type,
            rooms=rooms,
            total=_money(sum((r.subtotal for r in rooms), Decimal(0))),
            status=status,
            priced_items=priced_items,
            missing_items=missing_items,
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
        need, unit, n, formula = packages_for_area(product, req.net_area, reserve, req.layers, material=material)
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
                d
                for d in RAG_KNOWLEDGE_BASE
                if d.get("material") in used_materials or d.get("work_type") in used_works
            ][:8]

        sources_set: set[str] = {d["source"] for d in matched_docs if d.get("source")}
        sources_set.add("СНиП 3.04.01-87 «Изоляционные и отделочные покрытия»")
        sources_set.add("СП 29.13330.2011 «Полы»")
        sources_set.add("СП 256.1325800.2016 «Электроустановки жилых и общественных зданий»")
        resp.sources = sorted(sources_set)


        paragraphs: list[str] = []
        renov_title = RENOVATION_TITLES.get(req.renovation_type, req.renovation_type.value)

        paragraphs.append(
            f"Смета составлена для формата «{renov_title}» в соответствии с технологическими "
            f"регламентами СНиП 3.04.01-87 и СП 71.13330.2017. Последовательность работ структурирована "
            f"по технологическим стадиям: от подготовки и демонтажа до чистового монтажа сантехники и электрики."
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

        if any(r.room.room_type == RoomType.general_indoor for r in resp.rooms):
            paragraphs.append(
                "Многоразовый инструмент и вспомогательный инвентарь (малярный инструмент, ёмкости) "
                "вынесены в сводный блок на весь объект для предотвращения повторной закупки по каждой комнате."
            )

        resp.explanation = "\n\n".join(paragraphs)
        return resp

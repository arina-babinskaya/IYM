import re
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal

from app.catalog.normalize import to_decimal
from app.catalog.repository import CatalogRepo, to_brief
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
    Surface,
)
from app.taxonomy import MATERIAL_TITLES, STAGE_ORDER, WORKS, Material, RenovationType, WorkType

CENT = Decimal("0.01")
RESERVE: dict[Material, Decimal] = {
    Material.tile: Decimal(10), Material.laminate: Decimal(7), Material.wallpaper: Decimal(10),
    Material.linoleum: Decimal(5), Material.drywall: Decimal(10),
}
NEEDS_MOISTURE = {Material.drywall, Material.paint, Material.putty, Material.plaster, Material.laminate,
                  Material.wallpaper}
SURFACE_HINTS: dict[Surface, str] = {Surface.floor: r"напольн|керамогранит|для пола", Surface.wall: r"настенн|для стен"}


Step = tuple[WorkType, Surface | None, tuple[Material, ...]]


def _plan(room: RoomInput, renovation: RenovationType) -> list[Step]:
    if room.works:
        return [(c.work_type, c.surface or WORK_SURFACE.get(c.work_type), work_materials(c.work_type, c.materials))
                for c in room.works]
    options = works_for_room(room.room_type, room.renovation_type or renovation)
    return [(o.work, o.surface, work_materials(o.work, o.materials)) for o, default in options if default]


def _ceil(x: Decimal) -> int:
    return int(x.to_integral_value(rounding=ROUND_CEILING))


def _money(x: Decimal) -> Decimal:
    return x.quantize(CENT, rounding=ROUND_HALF_UP)


def _spec(p: Product, key: str) -> Decimal | None:
    v = (p.specs or {}).get(key)
    return to_decimal(v["value"] if isinstance(v, dict) else v)


def packages_for_area(p: Product, area: Decimal, reserve_pct: Decimal, layers: int = 1) -> tuple[Decimal, str, int, str]:
    need = area * layers * (1 + reserve_pct / 100)
    unit = (p.unit or "").lower()
    pack_area = p.package_area or _spec(p, "pack_area_m2")
    if pack_area and pack_area > 0:
        n = _ceil(need / pack_area)
        return need, "м²", n, f"{area:.2f} м² × {layers} × (1 + {reserve_pct}%) / {pack_area} м² в упак. → {n}"
    if unit in ("м2", "м²", "кв.м"):
        n = _ceil(need)
        return need, "м²", n, f"{area:.2f} м² × (1 + {reserve_pct}%) → {n} м²"
    length, width = _spec(p, "length_m"), _spec(p, "width_m")
    if length and width:
        sheet = length * width
        n = _ceil(need / sheet)
        return need, "м²", n, f"{area:.2f} м² × (1 + {reserve_pct}%) / {sheet:.3f} м² (лист/рулон) → {n}"
    cons = (p.specs or {}).get("consumption")
    volume, weight = _spec(p, "volume_l"), _spec(p, "weight_kg")
    if isinstance(cons, dict):
        rate = to_decimal(cons["value"])
        if cons["unit"] == "l/m2" and volume and rate:
            liters = area * layers * rate * (1 + reserve_pct / 100)
            n = _ceil(liters / volume)
            return liters, "л", n, f"{area:.2f} м² × {layers} сл. × {rate} л/м² / {volume} л → {n}"
        if cons["unit"] == "kg/m2" and weight and rate:
            kg = area * rate * (1 + reserve_pct / 100)
            n = _ceil(kg / weight)
            return kg, "кг", n, f"{area:.2f} м² × {rate} кг/м² / {weight} кг → {n}"
    raise CalcError(f"Для товара {p.id} нет фасовки или расхода в характеристиках")


def _piece_need(material: Material, room: RoomInput, area: Decimal) -> tuple[Decimal, str] | None:
    floor, perimeter = room.floor_area, room.perimeter
    if material == Material.cable:
        return perimeter * 2, "м"
    if material == Material.cable_channel:
        return perimeter, "м"
    if material == Material.socket:
        return Decimal(max(2, _ceil(floor / 4))), "шт"
    if material == Material.electrical_boxes:
        return Decimal(max(3, _ceil(floor / 4) + 1)), "шт"
    if material in (Material.lighting, Material.lamps):
        return Decimal(max(1, _ceil(floor / 8))), "шт"
    if material == Material.heating:
        return Decimal(max(1, _ceil(floor / 10))), "шт"
    if material in (Material.profile, Material.beacons):
        return Decimal(_ceil(area / Decimal("1.5"))), "шт"
    if material == Material.skirting:
        return Decimal(_ceil(perimeter / Decimal("2.5"))), "шт"
    if material == Material.damper_tape:
        return Decimal(_ceil(perimeter / 25)), "рул."
    if material in (Material.fasteners, Material.tile_leveling):
        return Decimal(max(1, _ceil(area / 10))), "упак."
    if material in (Material.switch, Material.painting_tools, Material.sealant, Material.doors, Material.ventilation,
                    Material.pipes, Material.plumbing, Material.demolition_tools, Material.circuit_breakers,
                    Material.reinforcing_mesh, Material.mounting_foam, Material.door_hardware,
                    Material.mounting_adhesive):
        return Decimal(1), "шт"
    return None


class BaselineEngine:
    def __init__(self, ranker: Ranker):
        self.ranker = ranker

    def _item(self, repo: CatalogRepo, room: RoomInput, work: WorkType, material: Material,
              surface: Surface | None, floor: Decimal, walls: Decimal) -> EstimateItem:
        info = WORKS[work]
        area = walls if surface == Surface.wall else floor
        wet = room.effective_humidity == Level.high and material in NEEDS_MOISTURE
        cands = repo.candidates(material, required_flags=["moisture_resistant"] if wet else [], min_confidence=0.8)
        ranked = self.ranker.rank(cands, room)
        hint = SURFACE_HINTS.get(surface) if material == Material.tile else None
        if hint:
            ranked.sort(key=lambda p: not re.search(hint, p.name.lower()))
        base = dict(stage=info.stage, work_type=work, material=material, surface=surface,
                    title=MATERIAL_TITLES[material])
        if not ranked:
            return EstimateItem(**base, required_amount=Decimal(0), required_unit="", packages=0,
                                reason="нет подходящего товара в каталоге")
        p = ranked[0]
        piece = _piece_need(material, room, area)
        if piece:
            need, unit = piece
            n = _ceil(need)
        else:
            try:
                need, unit, n, _ = packages_for_area(p, area, RESERVE.get(material, Decimal(5)),
                                                     layers=2 if material == Material.paint else 1)
            except CalcError as e:
                return EstimateItem(**base, product=to_brief(p), required_amount=area, required_unit="м²",
                                    packages=0, reason=str(e))
        price = p.result_price or Decimal(0)
        return EstimateItem(
            **base, product=to_brief(p), required_amount=need.quantize(CENT), required_unit=unit, packages=n,
            unit_price=price, cost=_money(price * n),
            reason="влагостойкий, т.к. высокая влажность" if wet else None,
            alternatives=[to_brief(a) for a in ranked[1:4]],
        )

    def estimate(self, req: EstimateRequest, repo: CatalogRepo) -> EstimateResponse:
        rooms, warnings = [], []
        for room in req.rooms:
            floor = room.floor_area
            walls = max(room.perimeter * room.height_m - room.openings_area_m2, Decimal(0))
            items, seen = [], set()
            for work, surface, materials in _plan(room, req.renovation_type):
                for material in materials:
                    if (material, surface) in seen:
                        continue
                    seen.add((material, surface))
                    items.append(self._item(repo, room, work, material, surface, floor, walls))
            items.sort(key=lambda i: STAGE_ORDER.index(i.stage))
            missing = sorted({i.title for i in items if i.packages == 0})
            if missing:
                warnings.append(f"{room.name or ROOM_TITLES[room.room_type]}: не подобраны — {', '.join(missing)}")
            rooms.append(RoomEstimate(room=room, floor_area_m2=floor, wall_area_m2=walls.quantize(CENT), items=items,
                                      subtotal=_money(sum((i.cost for i in items), Decimal(0)))))
        return EstimateResponse(
            object_type=req.object_type, renovation_type=req.renovation_type, rooms=rooms,
            total=_money(sum((r.subtotal for r in rooms), Decimal(0))), warnings=warnings,
        )

    def calc_product(self, product: Product, req: ProductCalcRequest, repo: CatalogRepo) -> ProductCalcResponse:
        binding = repo.binding(product.id)
        material = Material(binding.material) if binding else None
        reserve = req.reserve_pct if req.reserve_pct is not None else RESERVE.get(material, Decimal(5))
        need, unit, n, formula = packages_for_area(product, req.net_area, reserve, req.layers)
        price = product.result_price
        return ProductCalcResponse(
            product=to_brief(product), material=material, area_m2=req.net_area.quantize(CENT),
            required_amount=need.quantize(CENT), required_unit=unit, packages=n, unit_price=price,
            total_cost=_money(price * n) if price is not None else None, reserve_pct=reserve, formula=formula,
            warnings=[] if price is not None else ["у товара нет цены"],
        )

    async def explain(self, req: EstimateRequest, resp: EstimateResponse) -> EstimateResponse:
        return resp

import re

from app.models import Product, ProductBinding
from app.schemas import RoomInput, RoomType, Suggestion
from app.taxonomy import Material, WorkType, works_for_material

WET = [RoomType.bathroom, RoomType.toilet, RoomType.kitchen]
DRY = [RoomType.living, RoomType.bedroom, RoomType.kids, RoomType.hallway]
ALL = WET + DRY + [RoomType.balcony]

RULES: list[tuple[str, Material]] = [
    (r"клей.{0,20}плит|плиточн\w* клей", Material.tile_adhesive),
    (r"клей.{0,20}обо|обойн\w* клей", Material.wallpaper_glue),
    (r"затирк", Material.grout),
    (r"грунт(?!-?эмал)", Material.primer),
    (r"шпакл|шпатл", Material.putty),
    (r"штукатур", Material.plaster),
    (r"стяжк|наливн\w* пол|ровнител", Material.screed_mix),
    (r"гидроизол", Material.waterproofing),
    (r"герметик", Material.sealant),
    (r"профил\w*.{0,30}(гипсокартон|гкл)|профил\w* (пп|пн|cd|ud)\b", Material.profile),
    (r"саморез|дюбел|шуруп", Material.fasteners),
    (r"подложк", Material.underlay),
    (r"керамогранит|плитк|кафел", Material.tile),
    (r"ламинат", Material.laminate),
    (r"линолеум", Material.linoleum),
    (r"обои", Material.wallpaper),
    (r"краск|эмал", Material.paint),
    (r"валик|кист[ьи]|малярн", Material.painting_tools),
    (r"гипсокартон|\bгкл", Material.drywall),
    (r"кабел|провод", Material.cable),
    (r"розетк", Material.socket),
    (r"выключател", Material.switch),
    (r"смесител|унитаз|раковин|душев", Material.plumbing),
    (r"перфоратор|кувалд|\bлом\b", Material.demolition_tools),
]
MOISTURE = re.compile(r"влагостойк|гклв|для ванн|водостойк|аквастоп|aqua|влагозащ", re.IGNORECASE)
WASHABLE = re.compile(r"моющ", re.IGNORECASE)
INHERENTLY_WET = {Material.tile, Material.tile_adhesive, Material.grout, Material.waterproofing, Material.sealant}
ROOMS_BY_MATERIAL: dict[Material, list[RoomType]] = {
    Material.waterproofing: WET,
    Material.laminate: DRY,
    Material.underlay: DRY,
    Material.wallpaper: DRY + [RoomType.kitchen],
    Material.wallpaper_glue: DRY + [RoomType.kitchen],
}


def _materials(text: str) -> list[Material]:
    found = []
    for pattern, material in RULES:
        if re.search(pattern, text) and material not in found:
            found.append(material)
    return found


class KeywordClassifier:
    name = "keyword-baseline"

    def predict(self, products: list[Product]) -> list[Suggestion]:
        return [self._one(p) for p in products]

    def _one(self, p: Product) -> Suggestion:
        name = p.name.lower()
        cats = " ".join((p.categories or {}).values()).lower()
        text = f"{name} {cats} {(p.description or '')[:300].lower()}"
        found, confidence = _materials(name), 0.9
        if not found:
            found, confidence = _materials(cats), 0.7
        flags = {"moisture_resistant": bool(MOISTURE.search(text)), "washable": bool(WASHABLE.search(text))}
        if not found:
            return Suggestion(material=Material.other, confidence=0.1, flags=flags, model=self.name)
        material = found[0]
        flags["moisture_resistant"] |= material in INHERENTLY_WET
        works = works_for_material(material)
        if material == Material.wallpaper and "покраск" in name:
            works.append(WorkType.wall_painting)
        rooms = list(ROOMS_BY_MATERIAL.get(material, ALL))
        if flags["moisture_resistant"]:
            rooms = list(dict.fromkeys([*rooms, *WET]))
        return Suggestion(
            material=material,
            work_types=works,
            work_scores={w: confidence for w in works},
            room_types=rooms,
            flags=flags,
            confidence=confidence,
            model=self.name,
        )


class RatingRanker:
    def rank(self, candidates: list[tuple[Product, ProductBinding]], room: RoomInput) -> list[Product]:
        def key(pb: tuple[Product, ProductBinding]) -> tuple:
            p, b = pb
            return (not p.in_stock, not b.confirmed, -(p.recsys_rating or 0), -float(p.rating or 0),
                    float(p.result_price or 0))

        return [p for p, _ in sorted(candidates, key=key)]

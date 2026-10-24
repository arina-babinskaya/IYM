import math
import re
from dataclasses import dataclass, field

from app.models import Product, ProductBinding
from app.schemas import Level, RoomInput, RoomType
from app.taxonomy import Material

M, R = Material, RoomType


def _rx(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.IGNORECASE)


MOISTURE = _rx(r"влагост|водост|влагозащ|для ванн|аквастоп|гклв")
WASHABLE = _rx(r"моющ|к мытью|стойк\w* к истиранию")
ANTI_SLIP = _rx(r"противоскольз|антискольз|нескольз|\bR(9|1[0-3])\b")
FROST = _rx(r"морозост")
ANTIFUNGAL = _rx(r"антисепт|антиплесен|противогрибк|фунгицид|от плесени|грибк")
LOW_EMISSION = _rx(r"без запаха|гипоаллерг|экологич|\bE1\b|для детск")
NO = _rx(r"^(нет|no|-|отсутств|0$)")
WEAR_CLASS = _rx(r"\b(3[1-4])\s*класс|класс\w*\s*(?:износостойкости|эксплуатации|нагрузки)?\D{0,3}(3[1-4])\b")
PEI = _rx(r"\bPEI\s*(I{1,3}V?|V|[1-5])\b")
OUTDOOR = _rx(r"уличн|прожектор|садов|ландшафт|солнечн\w* батар|промышленн|наземн|фасадн|грунтов\w* светил")
IP = _rx(r"\bIP\s?(\d{2})\b")
ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5}

ROOM_WORDS: dict[RoomType, re.Pattern[str]] = {r: _rx(p) for r, p in {
    R.kitchen: r"\bкухн",
    R.bathroom: r"\bванн|\bдуш|\bсанузл|\bтуалет",
    R.hallway: r"\bприхож|\bкоридор",
    R.balcony: r"\bбалкон|\bлоджи",
    R.bedroom: r"\bспальн",
    R.living_room: r"\bгостин",
    R.utility_room: r"\bпостироч|\bкладов",
}.items()}

TYPICAL: dict[Material, re.Pattern[str]] = {m: _rx(p) for m, p in {
    M.cable: r"^(кабель|провод)\b(?!-канал)(?!.*(с вилкой|utp|ftp|hdmi|usb|антенн|акустич|телефон|коаксиал|сетев|удлинит|шнур|нагрев|грею|торшер|для светильник|для ламп))",
    M.cable_channel: r"^(кабель-канал|гофротруб|труба гофрир)",
    M.electrical_boxes: r"^(подрозетник|коробка|распределительн\w* коробк|распаечн)",
    M.circuit_breakers: r"^(автомат|выключатель автомат|узо|дифавтомат|щит)",
    M.socket: r"^розетк(?!.*(переносн|удлинит|колодк|таймер))",
    M.switch: r"^выключател(?!\w* автомат)",
    M.lighting: r"^(светильник|люстр|бра\b|спот|торшер)",
    M.lamps: r"^(лампа|лампочк)(?!.*(настольн|напольн|растени|аквариум|автомоб|\b12\s?в\b|h[1-9]\b|ультрафиолет|бактерицид|холодильн|швейн|духов|печ))",
    M.pipes: r"^труб(?!.*(газ|гофр|гоф\b|дренаж|кабел|вентиляц|рейлинг|алюмин|квадрат|профильн|карниз|штанг|мебел))",
    M.plumbing: r"^(смесител|унитаз|раковин|ванна|душев\w* (кабин|поддон|стойк|систем)|инсталляц)",
    M.heating: r"^(радиатор|полотенцесушител|т[её]плый пол|конвектор|кот[её]л)",
    M.ventilation: r"^(вентилятор|воздуховод|решетк\w* вентил|решётк\w* вентил)",
    M.doors: r"^(двер|полотно дверн|блок дверн|окно)",
    M.door_hardware: r"^(ручк\w* дверн|петл|замок|защ[её]лк)",
    M.fasteners: r"^(дюбел|саморез|шуруп|анкер)",
    M.mounting_foam: r"^пена",
    M.mounting_adhesive: r"^(жидкие гвозди|клей монтажн)",
    M.skirting: r"^(плинтус|порож)",
    M.decorative: r"^(панел|молдинг|плинтус потолоч|карниз потолоч|карниз декоратив|розетк\w* потолоч)",
    M.paint: r"^краска",
    M.primer: r"^грунт(овка)?\b(?!.*(для пластик|аэрозол|по металл|по ржавч|для osb|osb|дерев|wood|авто|-эмаль|-краска))",
    M.putty: r"^шпа[кт]л",
    M.plaster: r"^штукатурк",
    M.screed_mix: r"^(смесь для пол|пол наливн|наливной пол|ровнител|пескобетон|цементно-песчан|стяжка для пол)",
    M.waterproofing: r"^(гидроизол|мастика)",
    M.tile: r"^(плитка|керамогранит)",
    M.tile_adhesive: r"^клей (плиточн|для плитк)",
    M.grout: r"^затирк",
    M.tile_leveling: r"^(свп|система для выравнив|зажим|клин)",
    M.laminate: r"^(ламинат|плитка spc|кварцвинил)",
    M.linoleum: r"^линолеум",
    M.underlay: r"^подложк(?!\w* под ков)",
    M.wallpaper: r"^обои",
    M.wallpaper_glue: r"^клей (обойн|для обоев)",
    M.drywall: r"^(гипсокартон|гкл|лист гипс)",
    M.profile: r"^профил\w* (потолочн|направляющ|стоечн|для гкл|для гипсокартон|пп\b|пн\b|пс\b|cd\b|ud\b|cw\b|uw\b)",
    M.beacons: r"^(маяк|профиль маяч)",
    M.reinforcing_mesh: r"^(серпянк|сетка|лента стекловолок)",
    M.damper_tape: r"^лента демпф",
}.items()}

WALLPAPER_WASH = {"супермою": 1.0, "моющ": 2 / 3, "влагост": 1 / 3}
FLOOR_USE = {"полукоммерч": 2 / 3, "коммерч": 1.0, "бытов": 1 / 3}
ROOM_KIND = {"сух": 0.0, "умерен": 0.5, "влажн": 1.0, "всех": 1.0}

FINISH = {M.paint, M.wallpaper, M.wallpaper_glue, M.putty, M.plaster, M.primer, M.drywall, M.laminate, M.linoleum,
          M.tile, M.tile_adhesive, M.grout, M.skirting, M.decorative, M.mounting_adhesive}
WALLS = {M.paint, M.wallpaper}
FLOORS = {M.laminate, M.linoleum, M.tile}
MIXES = {M.putty, M.plaster, M.primer, M.paint, M.grout, M.tile_adhesive, M.screed_mix}
ELECTRIC = {M.lighting, M.socket, M.switch, M.ventilation, M.electrical_boxes}
LIVING = {R.bedroom, R.living_room, R.home_office, R.dining_room}
BUSY = {R.kitchen, R.hallway}
WET = {R.bathroom, R.utility_room, R.kitchen, R.balcony}


@dataclass(frozen=True)
class Rule:
    signal: str
    weight: float
    materials: frozenset[Material] | None = None
    rooms: frozenset[RoomType] | None = None
    humidity: Level | None = None

    def applies(self, material: Material | None, room: RoomInput) -> bool:
        return ((self.materials is None or material in self.materials)
                and (self.rooms is None or room.room_type in self.rooms)
                and (self.humidity is None or room.effective_humidity == self.humidity))


def rule(signal: str, weight: float, materials=None, rooms=None, humidity: Level | None = None) -> Rule:
    return Rule(signal, weight, frozenset(materials) if materials else None, frozenset(rooms) if rooms else None,
                humidity)


RULES: list[Rule] = [
    rule("typical", 6),
    rule("moisture_resistant", 5, FINISH, humidity=Level.high),
    rule("moisture_resistant", 2, FINISH, rooms=WET),
    rule("antifungal", 3, MIXES, humidity=Level.high),
    rule("washable", 3, WALLS, rooms=BUSY | {R.bathroom}),
    rule("washable", 1, WALLS),
    rule("wear_class", 3, FLOORS, rooms=BUSY),
    rule("wear_class", 1, FLOORS),
    rule("anti_slip", 4, {M.tile}, rooms={R.bathroom, R.hallway, R.balcony, R.utility_room}),
    rule("frost_resistant", 4, {M.tile, M.tile_adhesive, M.grout, M.paint, M.plaster, M.putty}, rooms={R.balcony}),
    rule("ip_protected", 5, ELECTRIC, rooms={R.bathroom}),
    rule("ip_protected", 3, ELECTRIC, humidity=Level.high),
    rule("outdoor", -10, ELECTRIC, rooms=set(RoomType) - {R.balcony}),
    rule("low_emission", 2, {M.paint, M.wallpaper, M.laminate, M.linoleum, M.primer, M.wallpaper_glue},
         rooms=LIVING),
]

BASE_WEIGHTS = {"in_stock": 3.0, "calculable": 2.0, "confirmed": 1.0, "recsys": 1.5, "rating": 1.0, "room_match": 3.0}

PIECE_MATERIALS = {M.cable, M.cable_channel, M.socket, M.switch, M.electrical_boxes, M.circuit_breakers, M.lighting,
                   M.lamps, M.heating, M.profile, M.beacons, M.skirting, M.damper_tape, M.fasteners,
                   M.tile_leveling, M.painting_tools, M.sealant, M.doors, M.ventilation, M.pipes, M.plumbing,
                   M.demolition_tools, M.reinforcing_mesh, M.mounting_foam, M.door_hardware, M.mounting_adhesive}


@dataclass
class Scored:
    product: Product
    score: float
    parts: dict[str, float] = field(default_factory=dict)
    filled: int = 0


def _num(v: object) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _material(b: ProductBinding) -> Material | None:
    try:
        return Material(b.material)
    except ValueError:
        return None


def characteristics(p: Product) -> dict[str, str]:
    raw = p.raw or {}
    items = raw.get("characteristics") or raw.get("params") or []
    out: dict[str, str] = {}
    for i in items:
        if isinstance(i, dict) and i.get("name"):
            out.setdefault(str(i["name"]).strip().lower(), str(i.get("value") or "").strip().lower())
    return out


def _yes(value: str) -> float:
    return 0.0 if not value or NO.search(value) else 1.0


def _level(value: str, levels: dict[str, float]) -> float | None:
    return next((v for key, v in levels.items() if key in value), None)


def _first(chars: dict[str, str], names: tuple[str, ...]) -> str | None:
    return next((chars[n] for n in names if n in chars), None)


def _moisture(chars: dict[str, str], text: str) -> float:
    value = _first(chars, ("влагостойкость", "влагостойкость краски", "водостойкость", "аквастоп"))
    if value is not None:
        return _yes(value)
    if "влагостойкость обоев" in chars:
        return 1.0
    kind = _level(chars.get("тип помещения", ""), ROOM_KIND)
    if kind is not None:
        return kind
    return 1.0 if MOISTURE.search(text) else 0.0


def _washable(chars: dict[str, str], text: str) -> float:
    level = _level(chars.get("влагостойкость обоев", ""), WALLPAPER_WASH)
    if level is not None:
        return level
    return 1.0 if WASHABLE.search(text) else 0.0


def _wear(chars: dict[str, str], text: str) -> float:
    n = _num(chars.get("износостойкость", "").replace(",", "."))
    if n is not None:
        return min(max((n - 31) / 3, 0.0), 1.0) if n >= 31 else min(max(n / 5, 0.0), 1.0)
    level = _level(chars.get("тип напольного покрытия", ""), FLOOR_USE)
    if level is not None:
        return level
    m = WEAR_CLASS.search(text)
    if m:
        return (int(m.group(1) or m.group(2)) - 31) / 3
    m = PEI.search(text)
    if m:
        v = m.group(1).upper()
        return (ROMAN.get(v) or int(v)) / 5
    return 0.0


def _ip(chars: dict[str, str], text: str) -> float:
    value = _first(chars, ("степень защиты", "класс защиты ip", "степень защиты ip"))
    m = re.search(r"(\d{2})", value) if value else IP.search(text)
    return 1.0 if m and int(m.group(1)) >= 44 else 0.0


def _low_emission(chars: dict[str, str], text: str) -> float:
    if re.search(r"без (запаха|аромата)", chars.get("аромат", "")):
        return 1.0
    return 1.0 if LOW_EMISSION.search(text) else 0.0


def _frost(chars: dict[str, str], text: str) -> float:
    if "морозостойкость" in chars:
        return _yes(chars["морозостойкость"])
    return 1.0 if FROST.search(text) else 0.0


def _outdoor(chars: dict[str, str], text: str) -> float:
    use = chars.get("применение", "")
    if "наружн" in use and "внутр" not in use:
        return 1.0
    return 1.0 if OUTDOOR.search(text) else 0.0


def _typical(material: Material | None, name: str | None) -> float:
    pattern = TYPICAL.get(material)
    return 1.0 if pattern and pattern.search((name or "").strip()) else 0.0


def room_match(name: str | None, room: RoomType) -> float:
    mentioned = {r for r, pattern in ROOM_WORDS.items() if pattern.search(name or "")}
    if not mentioned:
        return 0.0
    return 1.0 if room in mentioned else -1.0


def signals(p: Product, b: ProductBinding) -> dict[str, float]:
    chars = characteristics(p)
    text = " ".join([p.name or "", (p.description or "")[:500]])
    flags = b.flags or {}
    return {
        "moisture_resistant": max(1.0 if flags.get("moisture_resistant") else 0.0, _moisture(chars, text)),
        "washable": max(1.0 if flags.get("washable") else 0.0, _washable(chars, text)),
        "wear_class": _wear(chars, text),
        "anti_slip": 1.0 if ANTI_SLIP.search(text) else 0.0,
        "frost_resistant": _frost(chars, text),
        "antifungal": 1.0 if ANTIFUNGAL.search(text) else 0.0,
        "low_emission": _low_emission(chars, text),
        "ip_protected": _ip(chars, text),
        "outdoor": _outdoor(chars, text),
        "typical": _typical(_material(b), p.name),
    }


def _spec(p: Product, key: str) -> float | None:
    v = (p.specs or {}).get(key)
    return _num(v.get("value") if isinstance(v, dict) else v)


def calculable(p: Product, b: ProductBinding) -> bool:
    if _material(b) in PIECE_MATERIALS:
        return True
    if (_num(p.package_area) or _spec(p, "pack_area_m2") or 0) > 0:
        return True
    if (p.unit or "").lower() in ("м2", "м²", "кв.м"):
        return True
    if _spec(p, "length_m") and _spec(p, "width_m"):
        return True
    cons = (p.specs or {}).get("consumption")
    if isinstance(cons, dict):
        return bool((cons.get("unit") == "l/m2" and _spec(p, "volume_l"))
                    or (cons.get("unit") == "kg/m2" and _spec(p, "weight_kg")))
    return False


def _percentile(values: list[float | None]) -> list[float]:
    known = sorted({v for v in values if v is not None})
    if len(known) < 2:
        return [0.0 if v is None else 1.0 for v in values]
    pos = {v: i / (len(known) - 1) for i, v in enumerate(known)}
    return [0.0 if v is None else pos[v] for v in values]


class ContextRanker:
    def __init__(self, rules: list[Rule] | None = None, base_weights: dict[str, float] | None = None):
        self.rules = RULES if rules is None else rules
        self.base_weights = {**BASE_WEIGHTS, **(base_weights or {})}

    def rank(self, candidates: list[tuple[Product, ProductBinding]], room: RoomInput) -> list[Product]:
        return [s.product for s in self.score(candidates, room)]

    def score(self, candidates: list[tuple[Product, ProductBinding]], room: RoomInput) -> list[Scored]:
        unique: dict[int, tuple[Product, ProductBinding]] = {}
        for p, b in candidates:
            unique.setdefault(p.id, (p, b))
        items = list(unique.values())
        recsys = _percentile([_num(p.recsys_rating) for p, _ in items])

        scored = []
        for (p, b), rs in zip(items, recsys):
            rating = _num(p.rating)
            w = self.base_weights
            parts = {
                "in_stock": w["in_stock"] * (1.0 if p.in_stock else 0.0),
                "calculable": w["calculable"] * (1.0 if calculable(p, b) else 0.0),
                "confirmed": w["confirmed"] * (1.0 if b.confirmed else 0.0),
                "recsys": w["recsys"] * rs,
                "rating": w["rating"] * (min(max(rating / 5, 0.0), 1.0) if rating else 0.0),
                "room_match": w["room_match"] * room_match(p.name, room.room_type),
            }
            material = _material(b)
            sig = signals(p, b)
            for r in self.rules:
                if sig.get(r.signal) and r.applies(material, room):
                    parts[r.signal] = parts.get(r.signal, 0.0) + r.weight * sig[r.signal]
            parts = {k: round(v, 4) for k, v in parts.items() if v}
            scored.append(Scored(p, round(sum(parts.values()), 4), parts, len(characteristics(p))))

        scored.sort(key=lambda s: (-s.score, -s.filled, s.product.id))
        return scored

import math
import re
from dataclasses import dataclass, field

from sqlalchemy import inspect, select
from sqlalchemy.orm import object_session
from sqlalchemy.orm.attributes import set_committed_value

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
DECORATIVE = _rx(r"декоратив|фактурн|короед|\bшуба\b|венецианск|травертин|микроцемент|под бетон|кракелюр|"
                 r"перламутр|металлик|с эффектом|\bэффект(?!ивн)|песчан\w* вихр|рельефн|структурн")
TILE_DECOR = _rx(r"\bдекор\b|бордюр|панно|вставк|фриз|карандаш|\bугол\w* керам")
OUTDOOR = _rx(r"уличн|прожектор|садов|ландшафт|солнечн\w* батар|промышленн|наземн|фасадн|\bфасад\b|facade|"
              r"для наружн\w* работ|грунтов\w* светил")
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
    M.cable: r"^(кабель|провод)\b(?!-канал)(?=.*(ввг|nym|ппг))(?!.*(с вилкой|utp|ftp|hdmi|usb|антенн|акустич|телефон|коаксиал|сетев|удлинит|шнур|нагрев|грею|торшер|для светильник|для ламп))",
    M.cable_channel: r"^(кабель-канал|гофротруб|труба гофрир)",
    M.electrical_boxes: r"^(подрозетник|коробка|распределительн\w* коробк|распаечн)",
    M.circuit_breakers: r"^(автомат|выключатель автомат|узо|дифавтомат|щит)",
    M.socket: r"^розетк(?!.*(переносн|удлинит|колодк|таймер|без заземлен|б/з|телефон|rj\d|компьютер|интернет|\bтв\b|\btv\b|антенн|телевиз|акустич|din|потолочн))",
    M.switch: r"^выключател(?!\w* автомат)(?!.*(на шнур|шнуров|проходн\w* для|кнопк|для ламп|для светильн))",
    M.lighting: r"^(светильник|люстр|бра\b|спот|торшер)",
    M.lamps: r"^(лампа|лампочк)(?!.*(настольн|напольн|растени|аквариум|автомоб|\b12\s?в\b|h[1-9]\b|ультрафиолет|бактерицид|холодильн|швейн|духов|печ))",
    M.pipes: r"^труб(?!.*(газ|гофр|гоф\b|дренаж|кабел|вентиляц|рейлинг|алюмин|квадрат|профильн|карниз|штанг|мебел))",
    M.plumbing: r"^(смесител|унитаз|раковин|ванна|душев\w* (кабин|поддон|стойк|систем)|инсталляц)",
    M.heating: r"^(радиатор|полотенцесушител|т[её]плый пол|конвектор|кот[её]л)",
    M.ventilation: r"^(вентилятор|воздуховод|решетк\w* вентил|решётк\w* вентил)",
    M.doors: r"^(двер|полотно дверн|блок дверн|окно)",
    M.door_hardware: r"^(ручк\w* дверн|петл|замок|защ[её]лк)",
    M.fasteners: r"^(дюбел|саморез|шуруп|анкер)(?!.*(кровельн|сэндвич|мебельн|конфирмат|профнастил|фасадн|для поликарбонат|рыболов))",
    M.mounting_foam: r"^пена",
    M.mounting_adhesive: r"^(жидкие гвозди|клей монтажн)",
    M.skirting: r"^(плинтус|порог|порож)(?!.*(столешниц|мебел|для ванн|потолочн|кухонн\w* (?!.*напольн)))",
    M.painting_tools: r"^((комплект|набор)\s+)?(мини-|миди-)?(валик|кист(ь|и|ей)|ванночк|кювет|шпател|макловиц)"
                      r"|^(лента|скотч|набор) малярн|^малярн\w* (лента|скотч|набор)",
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
    M.wallpaper_glue: r"^клей (обойн|для\s+(\w+\s+){0,2}обоев)",
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
# Base materials of ordinary works; decorative finishes have their own work and material (M.decorative).
PLAIN_FINISH = {M.plaster, M.putty, M.paint, M.primer, M.grout, M.tile_adhesive, M.screed_mix, M.tile}
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
    rule("outdoor", -6, FINISH, rooms=set(RoomType) - {R.balcony}),
    rule("decorative", -8, PLAIN_FINISH),
    rule("low_emission", 2, {M.paint, M.wallpaper, M.laminate, M.linoleum, M.primer, M.wallpaper_glue},
         rooms=LIVING),
]

BASE_WEIGHTS = {"in_stock": 1.0, "calculable": 2.0, "confirmed": 1.0, "recsys": 1.5, "rating": 1.0, "room_match": 3.0,
                "price": 2.0}
SUITABLE_SHARE = 0.8
BASIS_TITLES = {"m2": "₽/м²", "l": "₽/л", "kg": "₽/кг", "m": "₽/м", "pcs": "₽/шт"}

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
    quality: float = 0.0
    unit_price: float | None = None
    basis: str = "pcs"


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
    cached = getattr(p, "_rc_characteristics", None)
    if cached is not None and cached[0] is p.raw:
        return cached[1]
    out = _characteristics(p)
    p._rc_characteristics = (p.raw, out)
    return out


def _characteristics(p: Product) -> dict[str, str]:
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


def moisture_rejected(p: Product) -> bool:
    chars = characteristics(p)
    value = _first(chars, ("влагостойкость", "влагостойкость краски", "водостойкость", "аквастоп"))
    if value is not None:
        return _yes(value) == 0
    if "влагостойкость обоев" in chars:
        return False
    return _level(chars.get("тип помещения", ""), ROOM_KIND) == 0.0


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


def _room_fit(mentioned: frozenset[RoomType], room: RoomType, material: Material | None = None) -> float:
    """+1 for "для кухни" in the kitchen, −1 for another room. For finishing materials wet rooms are
    interchangeable: "краска для ванных и кухонь" fits a laundry too (a kitchen faucet does not)."""
    if not mentioned:
        return 0.0
    if room in mentioned:
        return 1.0
    return 0.0 if material in FINISH and room in WET and mentioned <= WET else -1.0


def is_typical(material: Material | None, name: str | None) -> bool:
    return _typical(material, name) == 1.0


def _decorative(material: Material | None, name: str | None) -> float:
    text = name or ""
    if DECORATIVE.search(text):
        return 1.0
    return 1.0 if material == M.tile and TILE_DECOR.search(text) else 0.0


def _typical(material: Material | None, name: str | None) -> float:
    pattern = TYPICAL.get(material)
    return 1.0 if pattern and pattern.search((name or "").strip()) else 0.0


def room_match(name: str | None, room: RoomType, material: Material | None = None) -> float:
    return _room_fit(frozenset(r for r, pattern in ROOM_WORDS.items() if pattern.search(name or "")), room, material)


@dataclass(frozen=True)
class _Profile:
    signals: dict[str, float]
    filled: int
    unit_price: tuple[float | None, str]
    calculable: bool
    rooms: frozenset[RoomType]
    moisture_rejected: bool


_PROFILES: dict[tuple, _Profile] = {}
_PROFILES_MAX = 300_000


def clear_cache() -> None:
    _PROFILES.clear()


def _key(p: Product, b: ProductBinding) -> tuple:
    # Products are scored thousands of times (every estimate, hint and filter) but change only on a
    # catalog load (new last_seen_run, also when loaded by another process) or a binding/price edit.
    return (p.id, p.last_seen_run, p.name, p.result_price, p.package_area, p.unit, b.material,
            tuple(sorted((b.flags or {}).items())))


def _preload_cards(items: list[tuple[Product, ProductBinding]]) -> None:
    """Candidate queries skip the heavy card columns; fetch them in bulk for products not profiled yet."""
    missing = {p.id: p for p, b in items
               if p.id is not None and _key(p, b) not in _PROFILES and "raw" in inspect(p).unloaded}
    session = object_session(next(iter(missing.values()))) if missing else None
    if session is None:
        return
    ids = list(missing)
    for start in range(0, len(ids), 900):
        chunk = ids[start:start + 900]
        for pid, raw, description in session.execute(
                select(Product.id, Product.raw, Product.description).where(Product.id.in_(chunk))):
            set_committed_value(missing[pid], "raw", raw)
            set_committed_value(missing[pid], "description", description)


def _profile(p: Product, b: ProductBinding) -> _Profile:
    key = _key(p, b)
    cached = _PROFILES.get(key) if p.id is not None else None
    if cached is None:
        cached = _Profile(_signals(p, b), len(characteristics(p)), unit_price(p), calculable(p, b),
                          frozenset(r for r, pattern in ROOM_WORDS.items() if pattern.search(p.name or "")),
                          moisture_rejected(p))
        if p.id is not None:
            if len(_PROFILES) >= _PROFILES_MAX:
                _PROFILES.clear()
            _PROFILES[key] = cached
    return cached


def signals(p: Product, b: ProductBinding) -> dict[str, float]:
    return dict(_profile(p, b).signals)


def has_flags(p: Product, b: ProductBinding, required) -> bool:
    """Wet-room filter: explicit flags or catalog evidence pass; only explicit "not moisture resistant" fails."""
    profile, flags = _profile(p, b), b.flags or {}
    return all(
        flags.get(f) or profile.signals.get(f, 0) >= 1 or (f == "moisture_resistant" and not profile.moisture_rejected)
        for f in required
    )


def preload(items: list[tuple[Product, ProductBinding]]) -> None:
    _preload_cards(items)


def _signals(p: Product, b: ProductBinding) -> dict[str, float]:
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
        "decorative": _decorative(_material(b), p.name),
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
    # Paints, mixes and glues: the engine falls back to standard consumption rates, so a known pack
    # volume or weight is enough to count packages.
    if _material(b) in MIXES | {M.wallpaper_glue, M.waterproofing} and (_spec(p, "volume_l") or _spec(p, "weight_kg")):
        return True
    cons = (p.specs or {}).get("consumption")
    if isinstance(cons, dict):
        return bool((cons.get("unit") == "l/m2" and _spec(p, "volume_l"))
                    or (cons.get("unit") == "kg/m2" and _spec(p, "weight_kg")))
    return False


def unit_price(p: Product) -> tuple[float | None, str]:
    price = _num(p.result_price)
    if not price or price <= 0:
        return None, "pcs"
    area = _num(p.package_area) or _spec(p, "pack_area_m2")
    if not area and _spec(p, "length_m") and _spec(p, "width_m"):
        area = _spec(p, "length_m") * _spec(p, "width_m")
    if (p.unit or "").lower() in ("м2", "м²", "кв.м"):
        return price, "m2"
    for amount, basis in ((area, "m2"), (_spec(p, "volume_l"), "l"), (_spec(p, "weight_kg"), "kg"),
                          (_spec(p, "pack_length_m"), "m")):
        if amount and amount > 0:
            return price / amount, basis
    return price, "pcs"


def _cheapness(prices: list[tuple[float | None, str]]) -> list[float]:
    out = [0.0] * len(prices)
    for basis in {b for _, b in prices}:
        idx = [i for i, (v, b) in enumerate(prices) if b == basis]
        ranks = _percentile([prices[i][0] for i in idx])
        for i, r in zip(idx, ranks):
            out[i] = 0.0 if prices[i][0] is None else 1.0 - r
    return out


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
        _preload_cards(items)
        recsys = _percentile([_num(p.recsys_rating) for p, _ in items])
        profiles = [_profile(p, b) for p, b in items]
        prices = [pr.unit_price for pr in profiles]
        cheap = _cheapness(prices)
        if len(items) < 2:
            cheap = [0.0] * len(items)
        picked = {pid: i for i, pid in enumerate(room.picks)}

        scored = []
        for (p, b), pr, rs, (up, basis), ch in zip(items, profiles, recsys, prices, cheap):
            rating = _num(p.rating)
            w = self.base_weights
            parts = {
                "in_stock": w["in_stock"] * (1.0 if p.in_stock else 0.0),
                "calculable": w["calculable"] * (1.0 if pr.calculable else 0.0),
                "confirmed": w["confirmed"] * (1.0 if b.confirmed else 0.0),
                "recsys": w["recsys"] * rs,
                "rating": w["rating"] * (min(max(rating / 5, 0.0), 1.0) if rating else 0.0),
                "room_match": w["room_match"] * _room_fit(pr.rooms, room.room_type, _material(b)),
            }
            material = _material(b)
            sig = pr.signals
            for r in self.rules:
                if sig.get(r.signal) and r.applies(material, room):
                    parts[r.signal] = parts.get(r.signal, 0.0) + r.weight * sig[r.signal]
            quality = sum(parts.values())
            parts["price"] = self.base_weights["price"] * ch
            parts = {k: round(v, 4) for k, v in parts.items() if v}
            scored.append(Scored(p, round(sum(parts.values()), 4), parts, pr.filled, round(quality, 4),
                                 up, basis))

        scored.sort(key=lambda s: (picked.get(s.product.id, len(picked)), -s.score, -s.filled, s.product.id))
        return scored

    def ideal_quality(self, material: Material | None, room: RoomInput, scored: list[Scored]) -> float:
        w = self.base_weights
        ideal = w["calculable"] + sum(r.weight for r in self.rules if r.weight > 0 and r.applies(material, room))
        for key in ("in_stock", "confirmed", "recsys", "rating"):
            if any(s.parts.get(key, 0) > 0 for s in scored):
                ideal += w[key]
        return ideal

    def quality_pct(self, s: Scored, ideal: float) -> int:
        return max(0, min(100, round(100 * s.quality / ideal))) if ideal > 0 else 100

    def variants(self, candidates: list[tuple[Product, ProductBinding]], room: RoomInput) -> dict[str, Scored]:
        scored = self.score(candidates, room.model_copy(update={"picks": []}))
        if not scored:
            return {}
        recommended = scored[0]
        quality = min(scored, key=lambda s: (-s.quality, -s.filled, s.product.id))
        suitable = [s for s in scored if s.quality >= SUITABLE_SHARE * quality.quality and s.unit_price is not None
                    and s.basis == recommended.basis]
        cheapest = min(suitable, key=lambda s: (s.unit_price, -s.quality, s.product.id)) if suitable else recommended
        return {"recommended": recommended, "quality": quality, "cheapest": cheapest}

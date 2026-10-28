import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

_NUM = r"(\d+(?:[.,]\d+)?)"
_DIM_SEP = r"\s*[xх×*]\s*"

_UNITS: list[tuple[str, str, Decimal]] = [
    (r"кг\s*/\s*м(?:2|²)", "kg/m2", Decimal(1)),
    (r"л\s*/\s*м(?:2|²)", "l/m2", Decimal(1)),
    (r"мл\s*/\s*м(?:2|²)", "l/m2", Decimal("0.001")),
    (r"м(?:2|²)\s*/\s*л", "m2/l", Decimal(1)),
    (r"г\s*/\s*м(?:2|²)", "kg/m2", Decimal("0.001")),
    (r"мм(?:2|²)|кв\.?\s*мм", "mm2", Decimal(1)),
    (r"м(?:2|²)|кв\.?\s*м(?:етр\w*)?|м\.?\s*кв\.?", "m2", Decimal(1)),
    (r"м(?:3|³)|куб\.?\s*м", "m3", Decimal(1)),
    (r"мм", "m", Decimal("0.001")),
    (r"см", "m", Decimal("0.01")),
    (r"км", "m", Decimal(1000)),
    (r"м(?:етр\w*)?", "m", Decimal(1)),
    (r"мл", "l", Decimal("0.001")),
    (r"л(?:итр\w*)?", "l", Decimal(1)),
    (r"кг", "kg", Decimal(1)),
    (r"г(?:р\.?)?", "kg", Decimal("0.001")),
    (r"т", "kg", Decimal(1000)),
    (r"квт", "W", Decimal(1000)),
    (r"вт", "W", Decimal(1)),
    (r"шт\.?|штук\w*", "pcs", Decimal(1)),
    (r"рул\.?|рулон\w*", "roll", Decimal(1)),
]
_UNIT_ALT = "|".join(f"(?:{p})" for p, _, _ in _UNITS)
_MEASURE_RE = re.compile(rf"{_NUM}\s*(?:-\s*{_NUM}\s*)?({_UNIT_ALT})(?![а-яa-z])", re.IGNORECASE)
_DIMS_RE = re.compile(rf"{_NUM}(?:{_DIM_SEP}{_NUM})(?:{_DIM_SEP}{_NUM})?\s*({_UNIT_ALT})?", re.IGNORECASE)
_NAME_UNIT_RE = re.compile(rf"(?:,|\(|\s)\s*({_UNIT_ALT})\s*\)?\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class Measure:
    value: Decimal
    unit: str


def to_decimal(value: Any) -> Decimal | None:
    if value is None or value == "" or isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value))
    text = str(value).strip().replace(" ", "").replace(" ", "").replace(",", ".")
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def canonical_unit(token: str) -> tuple[str, Decimal] | None:
    token = token.strip().lower()
    for pattern, unit, factor in _UNITS:
        if re.fullmatch(pattern, token, re.IGNORECASE):
            return unit, factor
    return None


def parse_measure(text: str | None, unit_hint: str | None = None) -> Measure | None:
    if not text:
        return None
    m = _MEASURE_RE.search(text)
    if m:
        lo, hi, token = m.group(1), m.group(2), m.group(3)
        conv = canonical_unit(token)
        if conv:
            unit, factor = conv
            return Measure(to_decimal(hi or lo) * factor, unit)
    num = to_decimal(text)
    if num is not None and unit_hint:
        conv = canonical_unit(unit_hint)
        if conv:
            return Measure(num * conv[1], conv[0])
    return None


def parse_dimensions(text: str | None, unit_hint: str | None = None) -> list[Decimal] | None:
    if not text:
        return None
    m = _DIMS_RE.search(text)
    if not m:
        return None
    token = m.group(4) or unit_hint
    conv = canonical_unit(token) if token else None
    if not conv or conv[0] != "m":
        return None
    return [to_decimal(g) * conv[1] for g in m.groups()[:3] if g]


def unit_from_name(name: str | None) -> str | None:
    if not name:
        return None
    m = _NAME_UNIT_RE.search(name)
    return m.group(1) if m else None


def normalize_characteristic(name: str | None, value: Any) -> dict[str, Any]:
    raw = None if value is None else str(value)
    hint = unit_from_name(name)
    out: dict[str, Any] = {"value_raw": raw, "value_num": None, "unit": None, "value_json": None}
    dims = parse_dimensions(raw, hint)
    if dims and len(dims) >= 2:
        out["value_json"] = [str(d) for d in dims]
        out["unit"] = "m"
        return out
    measure = parse_measure(raw, hint)
    if measure:
        out["value_num"], out["unit"] = measure.value, measure.unit
    else:
        out["value_num"] = to_decimal(raw)
    return out


_SPEC_RULES: list[tuple[str, str, str]] = [
    ("раппорт", "rapport_m", "m"),
    ("толщин", "thickness_m", "m"),
    ("длин", "length_m", "m"),
    ("ширин", "width_m", "m"),
    ("высот", "height_m", "m"),
    ("объем", "volume_l", "l"),
    ("литраж", "volume_l", "l"),
    ("объём", "volume_l", "l"),
    ("расход", "consumption", "*"),
    ("площадь", "area_m2", "m2"),
    ("сечени", "cross_section_mm2", "mm2"),
    ("мощност", "power_w", "W"),
    ("вес", "weight_kg", "kg"),
    ("масса", "weight_kg", "kg"),
    ("количество в упаков", "pcs_in_pack", "pcs"),
    ("кол-во в упаков", "pcs_in_pack", "pcs"),
]


# Size characteristics of a part or of the box ("Длина сетевого шнура", "Ширина светильника",
# "Длина упаковки") are not the dimensions of the material itself.
_FOREIGN_SIZE = re.compile(r"шнур|провод|кабел|светильник|плафон|абажур|ручк|цокол|арматур|ножк|упаков|коробк|тар[аы]")
_SIZE_KEYS = {"length_m", "width_m", "height_m", "thickness_m"}

_NAME_VOLUME = re.compile(rf"{_NUM}\s*(м?л)(?![а-яa-z])", re.IGNORECASE)
_NAME_SIZE = re.compile(rf"{_NUM}(?:{_DIM_SEP}{_NUM})?(?:{_DIM_SEP}{_NUM})?\s*(мм|см|м)(?![а-яa-z2²])", re.IGNORECASE)
_SIZE_SCALE = {"мм": Decimal("0.001"), "см": Decimal("0.01"), "м": Decimal(1)}
_NAME_WEIGHT = re.compile(rf"{_NUM}\s*(кг|гр?)(?![а-яa-z])", re.IGNORECASE)
_NAME_PACK_AREA = re.compile(rf"{_NUM}\s*(?:м2|м²|кв\.?\s?м)(?![а-яa-z\d])", re.IGNORECASE)
_NAME_BARE_DIMS = re.compile(rf"(?<![\d.,]){_NUM}\s*[xх×]\s*{_NUM}(?:\s*[xх×]\s*\d+(?:[.,]\d+)?)?(?![\d.,]|\s*[xх×]|\s*(?:мм|м(?![а-яa-z])))(?:\s*см)?", re.IGNORECASE)
_TILE_NAME = re.compile(r"плитк|керамогранит|мозаик|клинкер")
_ROLL_FLOOR_NAME = re.compile(r"линолеум|ковролин|ковровое покрытие|искусственн\w* трав")
_NAME_PACK_LENGTH = re.compile(rf"(?<![\dх×x*]){_NUM}\s*м(?:етр\w*)?(?![а-яa-z2²\d])", re.IGNORECASE)
_NAME_ROLL = re.compile(rf"{_NUM}{_DIM_SEP}{_NUM}\s*м(?![а-яa-z2²])", re.IGNORECASE)


def _guess(specs: dict[str, Any], key: str, value: Decimal) -> None:
    specs[key] = str(value)
    specs.setdefault("guessed", []).append(key)


def _name_sizes(name: str) -> list[Decimal]:
    out = []
    for m in _NAME_SIZE.finditer(name):
        scale = _SIZE_SCALE[m.group(m.lastindex).lower()]
        out += [to_decimal(g) * scale for g in m.groups()[:-1] if g]
    return out


def _trust_name_units(specs: dict[str, Any], unitless: dict[str, Decimal], name: str) -> None:
    """A number without a unit in the card loses to the same quantity written with a unit in the
    product name: "Вес: 250" + "клей 250г" is 0.25 kg, "Длина: 150" + "150х70см" is 1.5 m."""
    for key, rx, base in (("weight_kg", _NAME_WEIGHT, "кг"), ("volume_l", _NAME_VOLUME, "л")):
        if key not in specs or not (m := rx.search(name)):
            continue
        value = to_decimal(m.group(1))
        value = value if m.group(2).lower() == base else value / 1000
        card = to_decimal(specs[key])
        # Unitless card values lose to the name; values with a unit lose only when they are off by
        # exactly the g↔kg / ml↔l factor ("Объем, л: 400" for a 400 ml aerosol).
        off_by_thousand = card and value and any(abs(card / value - f) < f * Decimal("0.02") for f in (1000, Decimal("0.001")))
        if key in unitless or off_by_thousand:
            specs[key] = format(value.normalize(), "f")
    sizes = _name_sizes(name)
    for key in ("length_m", "width_m", "height_m", "thickness_m"):
        raw = unitless.get(key)
        if raw is None and key in specs and not any(abs(to_decimal(specs[key]) - size) <= size * Decimal("0.02") for size in sizes):
            raw = to_decimal(specs[key])
        if raw is None or not sizes:
            continue
        for scale in (Decimal(1), Decimal("0.01"), Decimal("0.001")):
            value = raw * scale
            if any(abs(value - size) <= size * Decimal("0.02") for size in sizes):
                specs[key] = format(value.normalize(), "f")
                if key not in specs.setdefault("guessed", []):
                    specs["guessed"].append(key)
                break


def _from_name(specs: dict[str, Any], name: str) -> None:
    lower = name.lower()
    if "pack_area_m2" not in specs and (m := _NAME_PACK_AREA.search(name)):
        area = to_decimal(m.group(1))
        if area and 0 < area < 100:
            _guess(specs, "pack_area_m2", area)
    if _ROLL_FLOOR_NAME.search(lower) and "width_m" in specs:
        specs.setdefault("length_m", "1")
        specs.pop("pack_length_m", None)
    if _ROLL_FLOOR_NAME.search(lower) and "width_m" not in specs and (m := _NAME_PACK_LENGTH.search(name)):
        # "линолеум … 3,5 м" is the roll width; it is sold by the running metre.
        width = to_decimal(m.group(1))
        if width and 0.5 <= width <= 6:
            _guess(specs, "width_m", width)
            specs.setdefault("length_m", "1")
            specs["pack_length_m"] = None
    if _TILE_NAME.search(lower) and not ("length_m" in specs and "width_m" in specs) and (m := _NAME_BARE_DIMS.search(name)):
        # Tile formats are written in centimetres without a unit: "25х50", "60х120".
        a, b = to_decimal(m.group(1)), to_decimal(m.group(2))
        if a and b and 5 <= min(a, b) and max(a, b) <= 200:
            _guess(specs, "length_m", max(a, b) / 100)
            _guess(specs, "width_m", min(a, b) / 100)
    if "volume_l" not in specs and (m := _NAME_VOLUME.search(name)):
        v = to_decimal(m.group(1))
        _guess(specs, "volume_l", v if m.group(2).lower() == "л" else v / 1000)
    if "weight_kg" not in specs and (m := _NAME_WEIGHT.search(name)):
        w = to_decimal(m.group(1))
        _guess(specs, "weight_kg", w if m.group(2).lower() == "кг" else w / 1000)
    if "pack_length_m" not in specs and not _NAME_ROLL.search(name) and (m := _NAME_PACK_LENGTH.search(name)):
        length = to_decimal(m.group(1))
        if length and length >= 1:
            _guess(specs, "pack_length_m", length)
    if specs.get("pack_length_m", "") is None or (_ROLL_FLOOR_NAME.search(lower) and "width_m" in specs):
        specs.pop("pack_length_m", None)
    if not ("length_m" in specs and "width_m" in specs) and (m := _NAME_ROLL.search(name)):
        a, b = to_decimal(m.group(1)), to_decimal(m.group(2))
        if a and b and max(a, b) < 50:
            specs.pop("length_m", None)
            specs.pop("width_m", None)
            _guess(specs, "length_m", max(a, b))
            _guess(specs, "width_m", min(a, b))


def _consumption(specs: dict[str, Any], raw: Decimal) -> None:
    volume, weight = to_decimal(specs.get("volume_l")), to_decimal(specs.get("weight_kg"))
    if weight and raw > 5 and raw > weight and "pack_area_m2" not in specs:
        # "Расход: 36" on a 200 g pack of glue cannot be kg/m²: the pack covers 36 m².
        _guess(specs, "pack_area_m2", raw)
        return
    if volume and raw < 1:
        specs["consumption"] = {"value": str(raw), "unit": "l/m2"}
    elif weight and raw <= 40:
        specs["consumption"] = {"value": str(raw), "unit": "kg/m2"}
    elif raw >= 50 and (weight or volume):
        specs["consumption"] = {"value": str(raw / 1000), "unit": "kg/m2" if weight else "l/m2"}
    else:
        return
    specs.setdefault("guessed", []).append("consumption")


def extract_specs(
    characteristics: list[dict[str, Any]] | None,
    package_area: Any = None,
    quantity_in_package: Any = None,
    product_name: str | None = None,
) -> dict[str, Any]:
    specs: dict[str, Any] = {}
    raw_consumption: Decimal | None = None
    unitless: dict[str, Decimal] = {}
    for ch in characteristics or []:
        name = (ch.get("name") or "").lower()
        value = ch.get("value")
        if value in (None, ""):
            continue
        norm = normalize_characteristic(ch.get("name"), value)
        if ("размер" in name or "формат" in name) and "dims_m" not in specs:
            if norm["value_json"]:
                specs["dims_m"] = norm["value_json"]
                continue
            dims = parse_dimensions(str(value), "мм")
            if dims and len(dims) >= 2 and max(dims) >= Decimal("0.1"):
                specs["dims_m"] = [str(d) for d in dims]
                specs.setdefault("guessed", []).append("dims_m")
                continue
        if "метраж" in name and "pack_length_m" not in specs:
            if norm["unit"] == "m" and norm["value_num"]:
                specs["pack_length_m"] = str(norm["value_num"])
            elif norm["unit"] is None and norm["value_num"]:
                _guess(specs, "pack_length_m", norm["value_num"])
            continue
        for keyword, key, unit in _SPEC_RULES:
            if keyword not in name or key in specs:
                continue
            if key in _SIZE_KEYS and _FOREIGN_SIZE.search(name):
                break
            if key in _SIZE_KEYS and norm["unit"] in ("roll", "pcs"):
                norm = {**norm, "unit": None}
            if key == "pcs_in_pack":
                num = norm["value_num"] if norm["unit"] in (None, "pcs") else None
                if num is not None:
                    specs[key] = str(num)
            elif key == "area_m2" and norm["unit"] == "m2":
                specs["pack_area_m2" if "упаков" in name else "area_m2"] = str(norm["value_num"])
            elif unit == "*" and norm["unit"]:
                specs[key] = {"value": str(norm["value_num"]), "unit": norm["unit"]}
            elif unit == "*" and norm["value_num"] is not None:
                raw_consumption = norm["value_num"]
            elif norm["unit"] == unit and norm["value_num"] is not None:
                specs[key] = str(norm["value_num"])
            elif norm["unit"] is None and norm["value_num"] is not None and unit in ("m", "l", "kg"):
                unitless.setdefault(key, norm["value_num"])
                if unit == "m" and (key == "thickness_m" or norm["value_num"] >= 100):
                    _guess(specs, key, norm["value_num"] / 1000)
                elif unit == "m" and 0 < norm["value_num"] < 20:
                    _guess(specs, key, norm["value_num"])
                elif unit in ("l", "kg") and norm["value_num"] > 0:
                    # Retail packs never weigh 100+ kg or hold 100+ l: such bare numbers are g / ml.
                    value = norm["value_num"]
                    _guess(specs, key, value / 1000 if value >= 100 else value)
            break

    if product_name:
        _trust_name_units(specs, unitless, product_name)
        _from_name(specs, product_name)
    if "consumption" not in specs and raw_consumption:
        _consumption(specs, raw_consumption)
    pa = to_decimal(package_area)
    if pa and pa > 0:
        specs["pack_area_m2"] = str(pa)
    qp = to_decimal(quantity_in_package)
    if qp and qp > 0:
        specs.setdefault("pcs_in_pack", str(qp))
    return specs


def characteristic_rows(product_id: int, characteristics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for ch in characteristics:
        code = ch.get("code") or ch.get("name")
        if not code:
            continue
        rows[str(code)[:256]] = {
            "product_id": product_id,
            "code": str(code)[:256],
            "name": ch.get("name"),
            **normalize_characteristic(ch.get("name"), ch.get("value")),
        }
    return list(rows.values())

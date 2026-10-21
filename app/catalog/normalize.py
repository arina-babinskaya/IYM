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


def extract_specs(
    characteristics: list[dict[str, Any]] | None,
    package_area: Any = None,
    quantity_in_package: Any = None,
) -> dict[str, Any]:
    specs: dict[str, Any] = {}
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
        for keyword, key, unit in _SPEC_RULES:
            if keyword not in name or key in specs:
                continue
            if key == "pcs_in_pack":
                num = norm["value_num"] if norm["unit"] in (None, "pcs") else None
                if num is not None:
                    specs[key] = str(num)
            elif key == "area_m2" and norm["unit"] == "m2":
                specs["pack_area_m2" if "упаков" in name else "area_m2"] = str(norm["value_num"])
            elif unit == "*" and norm["unit"]:
                specs[key] = {"value": str(norm["value_num"]), "unit": norm["unit"]}
            elif norm["unit"] == unit and norm["value_num"] is not None:
                specs[key] = str(norm["value_num"])
            elif unit == "m" and norm["unit"] is None and norm["value_num"] is not None and (
                key == "thickness_m" or norm["value_num"] >= 100
            ):
                specs[key] = str(norm["value_num"] / 1000)
                specs.setdefault("guessed", []).append(key)
            break

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

from decimal import Decimal as D

import pytest

from app.catalog.normalize import extract_specs, normalize_characteristic, parse_dimensions, parse_measure, to_decimal


@pytest.mark.parametrize(
    ("text", "hint", "value", "unit"),
    [
        ("2,5 л", None, D("2.5"), "l"),
        ("600 мм", None, D("0.6"), "m"),
        ("64 см", None, D("0.64"), "m"),
        ("1,44 м²", None, D("1.44"), "m2"),
        ("6 кв.м", None, D("6"), "m2"),
        ("0,1-0,14 л/м²", None, D("0.14"), "l/m2"),
        ("4,5 кг/м2", None, D("4.5"), "kg/m2"),
        ("2,5 мм²", None, D("2.5"), "mm2"),
        ("25 кг", None, D("25"), "kg"),
        ("12,5", "мм", D("0.0125"), "m"),
        ("2", "кВт", D("2000"), "W"),
    ],
)
def test_parse_measure(text, hint, value, unit):
    m = parse_measure(text, hint)
    assert m is not None and m.value == value and m.unit == unit


def test_parse_measure_garbage():
    assert parse_measure("Белый") is None
    assert parse_measure("33") is None


def test_dimensions():
    assert parse_dimensions("600x600 мм") == [D("0.6"), D("0.6")]
    assert parse_dimensions("2500 х 1200 х 12,5 мм") == [D("2.5"), D("1.2"), D("0.0125")]
    assert parse_dimensions("60*30", unit_hint="см") == [D("0.6"), D("0.3")]
    assert parse_dimensions("3x2,5") is None


def test_normalize_keeps_raw():
    n = normalize_characteristic("Ширина, м", "1,06")
    assert n == {"value_raw": "1,06", "value_num": D("1.06"), "unit": "m", "value_json": None}


def test_extract_specs():
    specs = extract_specs(
        [
            {"name": "Ширина, м", "value": "1,06"},
            {"name": "Длина", "value": "10 м"},
            {"name": "Раппорт", "value": "64 см"},
            {"name": "Расход", "value": "0,1-0,14 л/м²"},
            {"name": "Площадь в упаковке, м2", "value": "2,131"},
            {"name": "Цвет", "value": "Белый"},
        ],
        package_area=None,
        quantity_in_package=8,
    )
    assert specs["width_m"] == "1.06"
    assert specs["length_m"] == "10"
    assert specs["rapport_m"] == "0.64"
    assert specs["consumption"] == {"value": "0.14", "unit": "l/m2"}
    assert specs["pack_area_m2"] == "2.131"
    assert specs["pcs_in_pack"] == "8"


def test_to_decimal():
    assert to_decimal("1 145,83") == D("1145.83")
    assert to_decimal(1.44) == D("1.44")
    assert to_decimal("abc") is None and to_decimal(True) is None


def test_extract_specs_without_units_and_from_name():
    wallpaper = extract_specs([{"name": "Длина", "value": "10.05"}, {"name": "Ширина", "value": "1,06"}])
    assert wallpaper["length_m"] == "10.05" and wallpaper["width_m"] == "1.06"
    assert extract_specs([{"name": "Ширина", "value": "600"}])["width_m"] == "0.6"
    assert "length_m" not in extract_specs([{"name": "Длина", "value": "60"}])

    paint = extract_specs([{"name": "Литраж банки", "value": "2.5"}, {"name": "Расход материала", "value": "0,12"}])
    assert paint["volume_l"] == "2.5" and paint["consumption"] == {"value": "0.12", "unit": "l/m2"}
    mix = extract_specs([{"name": "Вес", "value": "25"}, {"name": "Расход материала", "value": "1,2"}])
    assert mix["consumption"] == {"value": "1.2", "unit": "kg/m2"}
    grams = extract_specs([{"name": "Расход материала", "value": "200"}], product_name="краска 2,5л")
    assert grams["volume_l"] == "2.5" and grams["consumption"] == {"value": "0.2", "unit": "l/m2"}

    assert extract_specs([], product_name="обои виниловые 10,05х1,06м")["width_m"] == "1.06"
    assert extract_specs([], product_name="клей обойный 240г")["weight_kg"] == "0.24"
    assert extract_specs([], product_name="шпатлевка 18кг")["weight_kg"] == "18"

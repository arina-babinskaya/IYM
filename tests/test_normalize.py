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


def test_pack_length():
    assert extract_specs([], product_name="кабель ВВГ-нг(А) 3х4,0 ГОСТ уп.20м")["pack_length_m"] == "20"
    assert extract_specs([], product_name="провод ПВС 3х1,5 бухта 50 метров")["pack_length_m"] == "50"
    assert extract_specs([], product_name="кабель-канал ПВХ 50х12 мм 2 м.")["pack_length_m"] == "2"
    assert "pack_length_m" not in extract_specs([], product_name="обои 10,05х1,06м")
    assert "pack_length_m" not in extract_specs([], product_name="кабель-канал 25х25мм")
    assert extract_specs([{"name": "Метраж упаковки", "value": "100"}])["pack_length_m"] == "100"


def test_part_and_box_sizes_are_not_material_dimensions():
    lamp_junk = [{"name": n, "value": v} for n, v in [
        ("Вес", "3"), ("Высота светильника", "340"), ("Длина сетевого шнура", "1.6"), ("Ширина светильника", "125")]]
    specs = extract_specs(lamp_junk, product_name="Шпатлевка акриловая ЛАКРА 3кг")
    assert specs["weight_kg"] == "3" and not {"length_m", "width_m", "height_m"} & specs.keys()
    bag = extract_specs([{"name": "Длина упаковки", "value": "600"}, {"name": "Ширина упаковки", "value": "400"}])
    assert "length_m" not in bag and "width_m" not in bag


def test_roll_size_characteristics():
    specs = extract_specs([{"name": "Длина рулона", "value": "10,05"}, {"name": "Ширина рулона", "value": "1,06"}])
    assert specs["length_m"] == "10.05" and specs["width_m"] == "1.06"


@pytest.mark.parametrize("name, chars, expected", [
    ("клей обойный KLEO 250г", {"Вес": "250"}, {"weight_kg": "0.25"}),
    ("краска акриловая 0,9л", {"Объем": "900"}, {"volume_l": "0.9"}),
    ("мовиль FILL INN 520мл аэрозоль", {"Объем": "520"}, {"volume_l": "0.52"}),
    ("панель для ванны AM.PM 150х70см", {"Длина": "150"}, {"length_m": "1.5"}),
    ("планка с крючками 33х5,5х3,5см", {"Длина": "3,5", "Ширина": "33"}, {"length_m": "0.035", "width_m": "0.33"}),
    ("плитка настенная 25х40 см", {"Длина": "40", "Ширина": "25"}, {"length_m": "0.4", "width_m": "0.25"}),
    ("гипсокартон KNAUF 2500х1200х12,5мм", {"Длина": "2500", "Ширина": "1200"}, {"length_m": "2.5", "width_m": "1.2"}),
    ("шпатлевка финишная 20кг", {"Вес": "20"}, {"weight_kg": "20"}),
])
def test_units_in_name_beat_unitless_card_values(name, chars, expected):
    specs = extract_specs([{"name": k, "value": v} for k, v in chars.items()], product_name=name)
    assert {k: specs.get(k) for k in expected} == expected


@pytest.mark.parametrize("name, chars, expected", [
    ("клей обойный ЭКОН универсальный 200гр", {"Вес": "200"}, {"weight_kg": "0.2"}),
    ("клей обойный МЕТИЛАН Флизелин 200г", {"Вес": "200", "Расход материала": "36"},
     {"weight_kg": "0.2", "pack_area_m2": "36", "consumption": None}),
    ("эмаль аэрозольная MOTIP Деко 400мл", {"Объем, л": "400"}, {"volume_l": "0.4"}),
    ("ламинат Дуб фактурный 8мм 2,131м2 32 класс", {}, {"pack_area_m2": "2.131"}),
    ("плитка настенная ВКЗ Axima 25х50 бело-серая", {}, {"length_m": "0.5", "width_m": "0.25"}),
    ("линолеум MASTER HAVANNA OAK 1 3,5 м", {}, {"width_m": "3.5", "length_m": "1", "pack_length_m": None}),
    ("кабель ВВГнг-LS 3х2,5 бухта 50м", {}, {"pack_length_m": "50", "width_m": None}),
])
def test_catalog_audit_cases(name, chars, expected):
    specs = extract_specs([{"name": k, "value": v} for k, v in chars.items()], product_name=name)
    assert {k: specs.get(k) for k in expected} == expected


@pytest.mark.parametrize("name, chars, expected", [
    ("клей для обоев QUELYD MULTI PRO готовый 11л", {"Вес": "11000"}, {"weight_kg": "11"}),
    ("клей обойный KLEO EXTRA готовый 5кг", {"Вес": "5", "Расход материала": "25"}, {"pack_area_m2": "25", "consumption": None}),
    ("штукатурка гипсовая 30кг", {"Вес": "30", "Расход материала": "8,5"}, {"pack_area_m2": None}),
    ("керамогранит Kerama Marazzi Александрия 30х30 см", {}, {"length_m": "0.3", "width_m": "0.3"}),
    ("керамогранит 60x120х0,9 Urban Marble", {}, {"length_m": "1.2", "width_m": "0.6"}),
    ("линолеум IVC Modus 3,5 м", {"Ширина рулона": "3,5"}, {"width_m": "3.5", "length_m": "1", "pack_length_m": None}),
    ("щит мебельный СОЮЗ 3050х600х4мм", {"Длина, м": "3050"}, {"length_m": "3.05"}),
])
def test_catalog_audit_second_round(name, chars, expected):
    specs = extract_specs([{"name": k, "value": v} for k, v in chars.items()], product_name=name)
    assert {k: specs.get(k) for k in expected} == expected

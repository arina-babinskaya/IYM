"""Исполняемая версия taxonomy_v1. Backend enums намеренно не импортируются/не меняются."""
from __future__ import annotations

TAXONOMY_VERSION = "taxonomy_v1"

STAGES = [
    {"id": "preparation_demolition", "ru_name": "Подготовительный этап (демонтаж)", "description": "Обследование, защита зоны, отключение и удаление старых покрытий/конструкций."},
    {"id": "rough_work", "ru_name": "Черновые работы", "description": "Скрытые инженерные сети, основания и конструкции до подготовки под декоративное покрытие."},
    {"id": "white_finish", "ru_name": "Белая отделка", "description": "Подготовка ровного, сухого и загрунтованного основания: базовое/финишное шпатлевание, шлифование и грунтование. Это уже не конструктивные черновые работы, но ещё не видимое финишное покрытие."},
    {"id": "finish_work", "ru_name": "Чистовая отделка", "description": "Монтаж видимых покрытий стен, пола и потолка, плитки, дверей и декоративных материалов."},
    {"id": "final_stage", "ru_name": "Финальный этап", "description": "Установка видимых приборов, электроустановочных изделий, освещения, сантехники и завершающего декора."},
]

WORK_TYPES = [
    ("demolition", "Демонтаж", "Удаление старых покрытий и конструкций", ["preparation_demolition"]),
    ("electrical_wiring", "Электромонтаж и прокладка проводки", "Кабели, гофра, коробки, щиты и защита", ["rough_work"]),
    ("plumbing_rough", "Черновая сантехника", "Разводка труб, фитингов и канализации", ["rough_work"]),
    ("waterproofing", "Гидроизоляция", "Обмазочные составы, мембраны и ленты", ["rough_work"]),
    ("floor_screed", "Стяжка и выравнивание пола", "Стяжка, ровнители и наливной пол", ["rough_work"]),
    ("wall_plastering", "Оштукатуривание", "Черновое выравнивание стен и потолков", ["rough_work"]),
    ("drywall_install", "Монтаж гипсокартона", "ГКЛ/ГВЛ, каркас и специализированный крепёж", ["rough_work"]),
    ("wall_putty", "Шпатлевание", "Базовая и финишная подготовка основания", ["white_finish"]),
    ("priming", "Грунтование", "Нанесение грунтовок перед последующим покрытием", ["white_finish"]),
    ("wall_painting", "Окраска стен и потолков", "Интерьерная окраска и малярные принадлежности", ["finish_work"]),
    ("wallpapering", "Оклейка обоями", "Обои, обойный клей и специальный инструмент", ["finish_work"]),
    ("tiling", "Облицовка плиткой", "Плитка, клей, затирка и СВП", ["finish_work"]),
    ("floor_covering_install", "Укладка напольных покрытий", "Ламинат, линолеум, SPC/LVT, подложки и плинтусы", ["finish_work"]),
    ("door_window_install", "Монтаж дверей и окон", "Полотна, коробки, окна, наличники и монтажная фурнитура", ["finish_work"]),
    ("electrical_fittings", "Установка розеток и выключателей", "Финальные электроустановочные изделия", ["final_stage"]),
    ("plumbing_fixture_install", "Установка сантехнических приборов", "Смесители, раковины, унитазы, ванны и душ", ["final_stage"]),
    ("lighting_install", "Установка освещения", "Стационарные потолочные, настенные и трековые светильники", ["final_stage"]),
    ("decorative_finish_install", "Декоративная отделка и монтаж", "Стеновые панели, молдинги и встроенный декоративный монтаж", ["finish_work", "final_stage"]),
]

PRODUCT_CATEGORIES = [
    "primer", "paint", "putty", "plaster", "drywall", "tile", "floor_covering",
    "waterproofing_material", "adhesive", "sealant", "construction_mix",
    "fasteners", "tools", "protective_equipment", "plumbing", "electrical_goods",
    "lighting", "doors_windows", "decorative_panels", "decorative_materials",
    "installation_accessories", "insulation", "lumber_sheet_material", "other_renovation_material",
]

MATERIAL_ROLES = ["primary_material", "preparation_material", "auxiliary_material", "consumable", "fastener", "tool", "protective_equipment", "finishing_material"]

WORK_ROLE_MAP = {work_id: (["tool", "consumable"] if work_id == "demolition" else
    ["primary_material", "auxiliary_material", "tool", "fastener"])
    for work_id, *_ in WORK_TYPES}

OLD_TO_V1 = {
    "laminate_laying": "floor_covering_install", "linoleum_laying": "floor_covering_install",
    "door_install": "door_window_install", "plumbing_install": "plumbing_fixture_install",
    "lighting_install": "lighting_install",
}

WORK_TO_STAGES = {work_id: stages for work_id, _, _, stages in WORK_TYPES}
WORK_IDS = [row[0] for row in WORK_TYPES]


def stages_for_work_types(work_types: list[str]) -> list[str]:
    unknown = sorted(set(work_types) - set(WORK_IDS))
    if unknown:
        raise ValueError(f"Unknown work types: {unknown}")
    order = [item["id"] for item in STAGES]
    selected = {stage for work in work_types for stage in WORK_TO_STAGES[work]}
    return [stage for stage in order if stage in selected]

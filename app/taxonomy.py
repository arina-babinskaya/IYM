from dataclasses import dataclass
from enum import StrEnum


class Stage(StrEnum):
    preparation_demolition = "preparation_demolition"
    rough_work = "rough_work"
    white_finish = "white_finish"
    finish_work = "finish_work"
    final_stage = "final_stage"


STAGE_TITLES: dict[Stage, str] = {
    Stage.preparation_demolition: "Подготовительный этап (демонтаж)",
    Stage.rough_work: "Черновые работы",
    Stage.white_finish: "Белая отделка",
    Stage.finish_work: "Чистовая отделка",
    Stage.final_stage: "Финальный этап",
}

STAGE_ORDER = list(Stage)


class RenovationType(StrEnum):
    cosmetic = "cosmetic"
    capital = "capital"
    euro = "euro"
    rental = "rental"


RENOVATION_TITLES: dict[RenovationType, str] = {
    RenovationType.cosmetic: "Косметический ремонт",
    RenovationType.capital: "Капитальный ремонт",
    RenovationType.euro: "Евроремонт (элитный ремонт «под ключ»)",
    RenovationType.rental: "Под сдачу",
}


class Material(StrEnum):
    tile = "tile"
    tile_adhesive = "tile_adhesive"
    grout = "grout"
    primer = "primer"
    paint = "paint"
    wallpaper = "wallpaper"
    wallpaper_glue = "wallpaper_glue"
    laminate = "laminate"
    underlay = "underlay"
    linoleum = "linoleum"
    drywall = "drywall"
    profile = "profile"
    fasteners = "fasteners"
    putty = "putty"
    plaster = "plaster"
    screed_mix = "screed_mix"
    waterproofing = "waterproofing"
    sealant = "sealant"
    painting_tools = "painting_tools"
    cable = "cable"
    socket = "socket"
    switch = "switch"
    circuit_breakers = "circuit_breakers"
    cable_channel = "cable_channel"
    electrical_boxes = "electrical_boxes"
    beacons = "beacons"
    reinforcing_mesh = "reinforcing_mesh"
    damper_tape = "damper_tape"
    tile_leveling = "tile_leveling"
    skirting = "skirting"
    mounting_foam = "mounting_foam"
    door_hardware = "door_hardware"
    lamps = "lamps"
    mounting_adhesive = "mounting_adhesive"
    pipes = "pipes"
    plumbing = "plumbing"
    ventilation = "ventilation"
    heating = "heating"
    doors = "doors"
    lighting = "lighting"
    decorative = "decorative"
    adhesive = "adhesive"
    construction_mix = "construction_mix"
    insulation = "insulation"
    lumber_sheet_material = "lumber_sheet_material"
    installation_accessories = "installation_accessories"
    hand_tools = "hand_tools"
    power_tools = "power_tools"
    tool_accessories = "tool_accessories"
    consumables = "consumables"
    protective_equipment = "protective_equipment"
    floor_covering = "floor_covering"
    electrical_goods = "electrical_goods"
    windows = "windows"
    demolition_tools = "demolition_tools"
    other = "other"


MATERIAL_TITLES: dict[Material, str] = {
    Material.tile: "Плитка, керамогранит",
    Material.tile_adhesive: "Плиточный клей",
    Material.grout: "Затирка",
    Material.primer: "Грунтовка",
    Material.paint: "Краска",
    Material.wallpaper: "Обои",
    Material.wallpaper_glue: "Клей для обоев",
    Material.laminate: "Ламинат",
    Material.underlay: "Подложка",
    Material.linoleum: "Линолеум",
    Material.drywall: "Гипсокартон",
    Material.profile: "Профиль",
    Material.fasteners: "Крепёж",
    Material.putty: "Шпаклёвка",
    Material.plaster: "Штукатурка",
    Material.screed_mix: "Смесь для стяжки",
    Material.waterproofing: "Гидроизоляция",
    Material.sealant: "Герметик",
    Material.painting_tools: "Малярный инструмент",
    Material.cable: "Кабель",
    Material.socket: "Розетки",
    Material.switch: "Выключатели",
    Material.circuit_breakers: "Автоматы, УЗО, щитки",
    Material.cable_channel: "Кабель-каналы и гофротруба",
    Material.electrical_boxes: "Распаечные коробки и подрозетники",
    Material.beacons: "Маяки",
    Material.reinforcing_mesh: "Серпянка, армирующая сетка",
    Material.damper_tape: "Демпферная лента",
    Material.tile_leveling: "Система выравнивания плитки (СВП)",
    Material.skirting: "Плинтусы и порожки",
    Material.mounting_foam: "Монтажная пена",
    Material.door_hardware: "Дверная фурнитура",
    Material.lamps: "Лампы",
    Material.mounting_adhesive: "Монтажный клей, жидкие гвозди",
    Material.pipes: "Трубы, фитинги, запорная арматура",
    Material.plumbing: "Сантехнические приборы",
    Material.ventilation: "Вентиляция",
    Material.heating: "Отопление",
    Material.doors: "Двери и окна",
    Material.lighting: "Светильники",
    Material.decorative: "Декоративные панели и молдинги",
    Material.adhesive: "Клеи (тип требует уточнения)",
    Material.construction_mix: "Строительные смеси",
    Material.insulation: "Изоляционные материалы",
    Material.lumber_sheet_material: "Пиломатериалы и листовые материалы",
    Material.installation_accessories: "Монтажные комплектующие",
    Material.hand_tools: "Ручной инструмент",
    Material.power_tools: "Электроинструмент",
    Material.tool_accessories: "Оснастка для инструмента",
    Material.consumables: "Расходные материалы",
    Material.protective_equipment: "Средства защиты",
    Material.floor_covering: "Напольное покрытие (тип требует уточнения)",
    Material.electrical_goods: "Электротовары (тип требует уточнения)",
    Material.windows: "Окна и оконные блоки",
    Material.demolition_tools: "Инструмент для демонтажа",
    Material.other: "Другое",
}


class ProductCategory(StrEnum):
    """Authoritative taxonomy_v2 product-category task classes."""
    primer = "primer"
    paint = "paint"
    putty = "putty"
    plaster = "plaster"
    drywall = "drywall"
    tile = "tile"
    floor_covering = "floor_covering"
    waterproofing_material = "waterproofing_material"
    adhesive = "adhesive"
    sealant = "sealant"
    construction_mix = "construction_mix"
    fasteners = "fasteners"
    hand_tools = "hand_tools"
    power_tools = "power_tools"
    tool_accessories = "tool_accessories"
    consumables = "consumables"
    protective_equipment = "protective_equipment"
    plumbing = "plumbing"
    electrical_goods = "electrical_goods"
    ventilation = "ventilation"
    heating_climate = "heating_climate"
    lighting = "lighting"
    doors_windows = "doors_windows"
    decorative_panels = "decorative_panels"
    decorative_materials = "decorative_materials"
    installation_accessories = "installation_accessories"
    insulation = "insulation"
    lumber_sheet_material = "lumber_sheet_material"
    tables = "tables"
    seating = "seating"
    shelving_storage = "shelving_storage"
    cabinets_wardrobes = "cabinets_wardrobes"
    beds = "beds"
    countertops = "countertops"
    mirrors = "mirrors"
    interior_accessories = "interior_accessories"
    decorative_objects = "decorative_objects"
    other_renovation_material = "other_renovation_material"


PRODUCT_CATEGORY_TITLES: dict[ProductCategory, str] = {
    item: item.value.replace("_", " ") for item in ProductCategory
}


class WorkType(StrEnum):
    demolition = "demolition"
    electrical_wiring = "electrical_wiring"
    plumbing_rough = "plumbing_rough"
    ventilation_install = "ventilation_install"
    heating_climate_install = "heating_climate_install"
    waterproofing = "waterproofing"
    floor_screed = "floor_screed"
    wall_plastering = "wall_plastering"
    drywall_install = "drywall_install"
    wall_putty = "wall_putty"
    priming = "priming"
    wall_painting = "wall_painting"
    wallpapering = "wallpapering"
    tiling = "tiling"
    floor_covering_install = "floor_covering_install"
    door_window_install = "door_window_install"
    electrical_fittings = "electrical_fittings"
    plumbing_fixture_install = "plumbing_fixture_install"
    lighting_install = "lighting_install"
    decorative_finish_install = "decorative_finish_install"
    laminate_laying = "floor_covering_install"
    linoleum_laying = "floor_covering_install"
    plumbing_install = "plumbing_fixture_install"


@dataclass(frozen=True)
class WorkInfo:
    title: str
    stages: tuple[Stage, ...]
    materials: tuple[Material, ...]

    @property
    def stage(self) -> Stage:
        return self.stages[0]


S, M = Stage, Material
WORKS: dict[WorkType, WorkInfo] = {
    WorkType.demolition: WorkInfo("Демонтаж", (S.preparation_demolition,), ()),
    WorkType.electrical_wiring: WorkInfo(
        "Электромонтаж и прокладка проводки", (S.rough_work,),
        (M.cable, M.cable_channel, M.electrical_boxes, M.circuit_breakers, M.fasteners),
    ),
    WorkType.plumbing_rough: WorkInfo("Черновая сантехника", (S.rough_work,), (M.pipes, M.fasteners)),
    WorkType.ventilation_install: WorkInfo(
        "Монтаж вентиляции и воздуховодов", (S.rough_work, S.final_stage), (M.ventilation, M.fasteners)
    ),
    WorkType.heating_climate_install: WorkInfo(
        "Монтаж отопления и климатических систем", (S.rough_work, S.final_stage), (M.heating, M.fasteners)
    ),
    WorkType.waterproofing: WorkInfo("Гидроизоляция", (S.rough_work,), (M.waterproofing, M.primer)),
    WorkType.floor_screed: WorkInfo(
        "Стяжка и выравнивание пола", (S.rough_work,), (M.screed_mix, M.primer, M.damper_tape, M.beacons)
    ),
    WorkType.wall_plastering: WorkInfo(
        "Оштукатуривание", (S.rough_work,), (M.plaster, M.primer, M.beacons, M.reinforcing_mesh)
    ),
    WorkType.drywall_install: WorkInfo(
        "Монтаж гипсокартона", (S.rough_work,), (M.drywall, M.profile, M.fasteners, M.reinforcing_mesh, M.putty)
    ),
    WorkType.wall_putty: WorkInfo("Шпатлевание", (S.white_finish,), (M.putty, M.primer, M.reinforcing_mesh)),
    WorkType.priming: WorkInfo("Грунтование", (S.white_finish,), (M.primer,)),
    WorkType.wall_painting: WorkInfo("Окраска стен и потолков", (S.finish_work,), (M.paint, M.primer)),
    WorkType.wallpapering: WorkInfo("Оклейка обоями", (S.finish_work,), (M.wallpaper, M.wallpaper_glue, M.primer)),
    WorkType.tiling: WorkInfo(
        "Облицовка плиткой", (S.finish_work,), (M.tile, M.tile_adhesive, M.grout, M.primer, M.tile_leveling)
    ),
    WorkType.floor_covering_install: WorkInfo(
        "Укладка напольных покрытий", (S.finish_work,), (M.laminate, M.linoleum, M.underlay, M.skirting, M.fasteners)
    ),
    WorkType.door_window_install: WorkInfo(
        "Монтаж дверей и окон", (S.finish_work,), (M.doors, M.mounting_foam, M.door_hardware, M.fasteners)
    ),
    WorkType.electrical_fittings: WorkInfo(
        "Установка розеток и выключателей", (S.final_stage,), (M.socket, M.switch, M.electrical_boxes)
    ),
    WorkType.plumbing_fixture_install: WorkInfo(
        "Установка сантехнических приборов", (S.final_stage,), (M.plumbing, M.pipes, M.fasteners)
    ),
    WorkType.lighting_install: WorkInfo(
        "Установка освещения", (S.final_stage,), (M.lighting, M.lamps, M.electrical_boxes, M.fasteners)
    ),
    WorkType.decorative_finish_install: WorkInfo(
        "Декоративная отделка и монтаж", (S.finish_work, S.final_stage), (M.decorative, M.mounting_adhesive, M.fasteners)
    ),
}

def works_for_material(material: Material) -> list[WorkType]:
    return [w for w, info in WORKS.items() if material in info.materials]

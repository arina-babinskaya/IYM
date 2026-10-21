from dataclasses import dataclass
from enum import StrEnum


class Stage(StrEnum):
    preparation = "preparation"
    rough = "rough"
    white = "white"
    finishing = "finishing"
    final = "final"


STAGE_TITLES: dict[Stage, str] = {
    Stage.preparation: "Подготовительный этап (демонтаж)",
    Stage.rough: "Черновые работы",
    Stage.white: "Белая отделка",
    Stage.finishing: "Чистовая отделка",
    Stage.final: "Финальный этап",
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
    plumbing = "plumbing"
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
    Material.plumbing: "Сантехника",
    Material.demolition_tools: "Инструмент для демонтажа",
    Material.other: "Другое",
}


class WorkType(StrEnum):
    demolition = "demolition"
    electrical_wiring = "electrical_wiring"
    plumbing_rough = "plumbing_rough"
    waterproofing = "waterproofing"
    floor_screed = "floor_screed"
    wall_plastering = "wall_plastering"
    drywall_install = "drywall_install"
    wall_putty = "wall_putty"
    priming = "priming"
    tiling = "tiling"
    wall_painting = "wall_painting"
    wallpapering = "wallpapering"
    laminate_laying = "laminate_laying"
    linoleum_laying = "linoleum_laying"
    electrical_fittings = "electrical_fittings"
    plumbing_install = "plumbing_install"


@dataclass(frozen=True)
class WorkInfo:
    title: str
    stage: Stage
    materials: tuple[Material, ...]


WORKS: dict[WorkType, WorkInfo] = {
    WorkType.demolition: WorkInfo("Демонтаж", Stage.preparation, (Material.demolition_tools,)),
    WorkType.electrical_wiring: WorkInfo("Прокладка электропроводки", Stage.rough, (Material.cable,)),
    WorkType.plumbing_rough: WorkInfo("Разводка труб", Stage.rough, (Material.plumbing,)),
    WorkType.waterproofing: WorkInfo("Гидроизоляция", Stage.rough, (Material.waterproofing, Material.primer)),
    WorkType.floor_screed: WorkInfo("Стяжка пола", Stage.rough, (Material.screed_mix, Material.primer)),
    WorkType.wall_plastering: WorkInfo("Штукатурка стен", Stage.rough, (Material.plaster, Material.primer)),
    WorkType.drywall_install: WorkInfo(
        "Монтаж гипсокартона", Stage.rough, (Material.drywall, Material.profile, Material.fasteners, Material.putty)
    ),
    WorkType.wall_putty: WorkInfo("Шпаклёвка стен", Stage.white, (Material.putty, Material.primer)),
    WorkType.priming: WorkInfo("Грунтование поверхностей", Stage.white, (Material.primer,)),
    WorkType.tiling: WorkInfo(
        "Укладка керамической плитки",
        Stage.finishing,
        (Material.tile, Material.tile_adhesive, Material.grout, Material.primer),
    ),
    WorkType.wall_painting: WorkInfo(
        "Покраска стен", Stage.finishing, (Material.paint, Material.primer, Material.painting_tools)
    ),
    WorkType.wallpapering: WorkInfo(
        "Поклейка обоев", Stage.finishing, (Material.wallpaper, Material.wallpaper_glue, Material.primer)
    ),
    WorkType.laminate_laying: WorkInfo("Укладка ламината", Stage.finishing, (Material.laminate, Material.underlay)),
    WorkType.linoleum_laying: WorkInfo("Укладка линолеума", Stage.finishing, (Material.linoleum,)),
    WorkType.electrical_fittings: WorkInfo(
        "Установка розеток и выключателей", Stage.final, (Material.socket, Material.switch)
    ),
    WorkType.plumbing_install: WorkInfo("Установка сантехники", Stage.final, (Material.plumbing, Material.sealant)),
}


def works_for_material(material: Material) -> list[WorkType]:
    return [w for w, info in WORKS.items() if material in info.materials]

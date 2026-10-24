from dataclasses import dataclass

from app.schemas import RoomType, Surface
from app.taxonomy import WORKS, Material, RenovationType, Stage, WorkType

W, M = WorkType, Material
F, WL, C = Surface.floor, Surface.wall, Surface.ceiling


@dataclass(frozen=True)
class Option:
    work: WorkType
    surface: Surface | None = None
    materials: tuple[Material, ...] | None = None
    variant: str | None = None

    @property
    def key(self) -> str:
        return f"{self.work.value}:{self.surface.value if self.surface else ''}:{self.variant or ''}"


WORK_SURFACE: dict[WorkType, Surface | None] = {
    W.waterproofing: F, W.floor_screed: F, W.wall_plastering: WL, W.drywall_install: WL, W.wall_putty: WL,
    W.priming: WL, W.wall_painting: WL, W.wallpapering: WL, W.tiling: F, W.floor_covering_install: F,
    W.decorative_finish_install: WL,
}

LAMINATE = Option(W.floor_covering_install, F, (M.laminate, M.underlay, M.skirting, M.fasteners), "ламинат")
LINOLEUM = Option(W.floor_covering_install, F, (M.linoleum, M.skirting, M.fasteners), "линолеум")

DEMOLITION = Option(W.demolition)
WIRING = Option(W.electrical_wiring)
PIPES = Option(W.plumbing_rough)
VENT = Option(W.ventilation_install)
HEATING = Option(W.heating_climate_install)
WATERPROOF = Option(W.waterproofing, F)
SCREED = Option(W.floor_screed, F)
PLASTER = Option(W.wall_plastering, WL)
DRYWALL = Option(W.drywall_install, WL)
PUTTY = Option(W.wall_putty, WL)
PRIMER = Option(W.priming, WL)
PAINT_WALLS = Option(W.wall_painting, WL)
PAINT_CEILING = Option(W.wall_painting, C)
WALLPAPER = Option(W.wallpapering, WL)
TILE_FLOOR = Option(W.tiling, F)
TILE_WALLS = Option(W.tiling, WL)
DOORS = Option(W.door_window_install)
DECOR = Option(W.decorative_finish_install, WL)
FITTINGS = Option(W.electrical_fittings)
FIXTURES = Option(W.plumbing_fixture_install)
LIGHTING = Option(W.lighting_install)

ROOM_GROUP: dict[RoomType, str] = {
    RoomType.bathroom: "wet",
    RoomType.kitchen: "kitchen",
    RoomType.utility_room: "utility",
    RoomType.balcony: "balcony",
}

OPTIONS: dict[str, list[Option]] = {
    "wet": [
        DEMOLITION, WIRING, PIPES, VENT, HEATING, WATERPROOF, SCREED, PLASTER, DRYWALL, PUTTY, PRIMER,
        TILE_FLOOR, TILE_WALLS, PAINT_WALLS, PAINT_CEILING, DOORS, DECOR, FITTINGS, LIGHTING, FIXTURES,
    ],
    "kitchen": [
        DEMOLITION, WIRING, PIPES, VENT, HEATING, SCREED, PLASTER, DRYWALL, PUTTY, PRIMER, TILE_FLOOR, TILE_WALLS,
        PAINT_WALLS, PAINT_CEILING, WALLPAPER, LAMINATE, LINOLEUM, DOORS, DECOR, FITTINGS, LIGHTING, FIXTURES,
    ],
    "dry": [
        DEMOLITION, WIRING, HEATING, SCREED, PLASTER, DRYWALL, PUTTY, PRIMER, PAINT_WALLS, PAINT_CEILING,
        WALLPAPER, LAMINATE, LINOLEUM, DOORS, DECOR, FITTINGS, LIGHTING,
    ],
    "utility": [
        DEMOLITION, WIRING, PIPES, VENT, WATERPROOF, SCREED, PLASTER, PUTTY, PRIMER, TILE_FLOOR, PAINT_WALLS,
        LINOLEUM, DOORS, FITTINGS, LIGHTING, FIXTURES,
    ],
    "balcony": [
        DEMOLITION, WIRING, PLASTER, PUTTY, PRIMER, PAINT_WALLS, TILE_FLOOR, LAMINATE, LINOLEUM, DECOR, DOORS,
        FITTINGS, LIGHTING,
    ],
}

RENOVATION_STAGES: dict[RenovationType, set[Stage]] = {
    RenovationType.cosmetic: {Stage.white_finish, Stage.finish_work, Stage.final_stage},
    RenovationType.rental: {Stage.white_finish, Stage.finish_work, Stage.final_stage},
    RenovationType.capital: set(Stage),
    RenovationType.euro: set(Stage),
}

CAPITAL: dict[str, list[Option]] = {
    "wet": [DEMOLITION, WIRING, PIPES, WATERPROOF, DRYWALL, PRIMER, TILE_FLOOR, TILE_WALLS, FITTINGS, LIGHTING,
            FIXTURES],
    "kitchen": [DEMOLITION, WIRING, PUTTY, PRIMER, TILE_FLOOR, PAINT_WALLS, FITTINGS, LIGHTING],
    "dry": [DEMOLITION, WIRING, PUTTY, PRIMER, WALLPAPER, LAMINATE, FITTINGS, LIGHTING],
    "utility": [DEMOLITION, WIRING, PRIMER, TILE_FLOOR, PAINT_WALLS, LIGHTING],
    "balcony": [PUTTY, PRIMER, PAINT_WALLS],
}

DEFAULTS: dict[tuple[RenovationType, str], list[Option]] = {
    **{(RenovationType.capital, g): works for g, works in CAPITAL.items()},
    **{(RenovationType.euro, g): [*works, PAINT_CEILING, DECOR] if g in ("dry", "kitchen") else works
       for g, works in CAPITAL.items()},
    (RenovationType.cosmetic, "wet"): [PRIMER, PAINT_WALLS],
    (RenovationType.cosmetic, "kitchen"): [PRIMER, PAINT_WALLS],
    (RenovationType.cosmetic, "dry"): [PRIMER, WALLPAPER],
    (RenovationType.cosmetic, "utility"): [PAINT_WALLS],
    (RenovationType.cosmetic, "balcony"): [PAINT_WALLS],
    (RenovationType.rental, "wet"): [PAINT_WALLS],
    (RenovationType.rental, "kitchen"): [PAINT_WALLS, LINOLEUM],
    (RenovationType.rental, "dry"): [PAINT_WALLS, LINOLEUM],
    (RenovationType.rental, "utility"): [PAINT_WALLS],
    (RenovationType.rental, "balcony"): [PAINT_WALLS],
}


def room_group(room: RoomType) -> str:
    return ROOM_GROUP.get(room, "dry")


def available_works(room: RoomType, renovation: RenovationType) -> list[Option]:
    stages = RENOVATION_STAGES[renovation]
    return [o for o in OPTIONS[room_group(room)] if stages.intersection(WORKS[o.work].stages)]


def default_works(room: RoomType, renovation: RenovationType) -> list[Option]:
    return list(DEFAULTS[(renovation, room_group(room))])


DEFAULT_MATERIALS: dict[WorkType, tuple[Material, ...]] = {W.floor_covering_install: LAMINATE.materials}


def work_materials(work: WorkType, materials: list[Material] | tuple[Material, ...] | None = None) -> tuple[Material, ...]:
    return tuple(materials or DEFAULT_MATERIALS.get(work) or WORKS[work].materials)



def works_for_room(room: RoomType, renovation: RenovationType) -> list[tuple[Option, bool]]:
    defaults = {o.key for o in default_works(room, renovation)}
    return [(o, o.key in defaults) for o in available_works(room, renovation)]

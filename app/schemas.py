from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, field_validator

from app.taxonomy import Material, RenovationType, Stage, WorkType

Money = Annotated[Decimal, PlainSerializer(lambda v: float(v), return_type=float, when_used="json")]
Amount = Annotated[Decimal, PlainSerializer(lambda v: float(v), return_type=float, when_used="json")]


class ObjectType(StrEnum):
    apartment = "apartment"
    house = "house"
    studio = "studio"


class RoomType(StrEnum):
    kitchen = "kitchen"
    dining_room = "dining_room"
    living_room = "living_room"
    bedroom = "bedroom"
    bathroom = "bathroom"
    hallway = "hallway"
    home_office = "home_office"
    utility_room = "utility_room"
    balcony = "balcony"
    general_indoor = "general_indoor"
    living = "living_room"


class Level(StrEnum):
    low = "low"
    normal = "normal"
    high = "high"


class Surface(StrEnum):
    floor = "floor"
    wall = "wall"
    ceiling = "ceiling"


ROOM_TITLES: dict[RoomType, str] = {
    RoomType.kitchen: "Кухня",
    RoomType.dining_room: "Столовая",
    RoomType.living_room: "Гостиная",
    RoomType.bedroom: "Спальня",
    RoomType.bathroom: "Ванная / санузел",
    RoomType.hallway: "Прихожая / коридор",
    RoomType.home_office: "Кабинет",
    RoomType.utility_room: "Постирочная / кладовая",
    RoomType.balcony: "Балкон / лоджия",
    RoomType.general_indoor: "Другое помещение",
}

ROOM_DEFAULT_HUMIDITY: dict[RoomType, Level] = {
    RoomType.bathroom: Level.high,
    RoomType.kitchen: Level.normal,
    RoomType.utility_room: Level.high,
    RoomType.balcony: Level.high,
}


class ProductBrief(BaseModel):
    id: int
    sku: str | None = None
    name: str
    url_key: str | None = None
    picture_url: str | None = None
    brand: str | None = None
    unit: str | None = None
    result_price: Money | None = None
    currency: str | None = "RUB"
    in_stock: bool | None = None


class Characteristic(BaseModel):
    code: str
    name: str | None = None
    value: str | None = None
    value_num: Amount | None = None
    unit: str | None = None


class ProductOut(ProductBrief):
    cod_good: str | None = None
    description: str | None = None
    price: Money | None = None
    old_price: Money | None = None
    quantity_in_package: Amount | None = None
    package_area: Amount | None = None
    categories: dict[str, str] = Field(default_factory=dict)
    characteristics: list[Characteristic] = Field(default_factory=list)
    specs: dict[str, Any] = Field(default_factory=dict)
    binding: "BindingOut | None" = None


class WorkChoice(BaseModel):
    work_type: WorkType
    surface: Surface | None = None
    materials: list[Material] | None = None


class RoomInput(BaseModel):
    name: str | None = None
    room_type: RoomType
    renovation_type: RenovationType | None = None
    length_m: Amount = Field(gt=0)
    width_m: Amount = Field(gt=0)
    height_m: Amount = Field(Decimal("2.7"), gt=0)
    openings_area_m2: Amount = Field(Decimal("0"), ge=0)
    humidity: Level | None = None
    works: list[WorkChoice] | None = None

    @field_validator("works", mode="before")
    @classmethod
    def _works(cls, v: Any) -> Any:
        return [{"work_type": w} if isinstance(w, str) else w for w in v] if isinstance(v, list) else v

    @property
    def floor_area(self) -> Decimal:
        return self.length_m * self.width_m

    @property
    def perimeter(self) -> Decimal:
        return 2 * (self.length_m + self.width_m)

    @property
    def effective_humidity(self) -> Level:
        return self.humidity or ROOM_DEFAULT_HUMIDITY.get(self.room_type, Level.normal)


class EstimateRequest(BaseModel):
    object_type: ObjectType = ObjectType.apartment
    renovation_type: RenovationType = RenovationType.cosmetic
    rooms: list[RoomInput] = Field(min_length=1)
    explain: bool = True


class EstimateItem(BaseModel):
    stage: Stage
    work_type: WorkType
    material: Material
    surface: Surface | None = None
    title: str
    product: ProductBrief | None = None
    required_amount: Amount
    required_unit: str
    packages: int
    unit_price: Money | None = None
    cost: Money = Decimal("0")
    reason: str | None = None
    alternatives: list[ProductBrief] = Field(default_factory=list)


class RoomEstimate(BaseModel):
    room: RoomInput
    floor_area_m2: Amount
    wall_area_m2: Amount
    items: list[EstimateItem]
    subtotal: Money


class EstimateResponse(BaseModel):
    object_type: ObjectType
    renovation_type: RenovationType
    rooms: list[RoomEstimate]
    total: Money
    currency: str = "RUB"
    explanation: str | None = None
    sources: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    elapsed_ms: int = 0


class ProductCalcRequest(BaseModel):
    length_m: Amount = Field(gt=0)
    width_m: Amount = Field(gt=0)
    openings_area_m2: Amount = Field(Decimal("0"), ge=0)
    layers: int = Field(1, ge=1, le=5)
    reserve_pct: Amount | None = Field(None, ge=0, le=50)

    @property
    def net_area(self) -> Decimal:
        return max(self.length_m * self.width_m - self.openings_area_m2, Decimal("0"))


class ProductCalcResponse(BaseModel):
    product: ProductBrief
    material: Material | None = None
    area_m2: Amount
    required_amount: Amount
    required_unit: str
    packages: int
    unit_price: Money | None
    total_cost: Money | None
    reserve_pct: Amount
    formula: str
    warnings: list[str] = Field(default_factory=list)


class Suggestion(BaseModel):
    material: Material
    work_types: list[WorkType] = Field(default_factory=list)
    work_scores: dict[WorkType, float] = Field(default_factory=dict)
    room_types: list[RoomType] = Field(default_factory=list)
    flags: dict[str, bool] = Field(default_factory=dict)
    confidence: float = Field(ge=0, le=1)
    model: str = "unknown"


class BindingIn(BaseModel):
    material: Material
    work_types: list[WorkType] = Field(default_factory=list)
    room_types: list[RoomType] = Field(default_factory=list)
    flags: dict[str, bool] = Field(default_factory=dict)


class BindingOut(BindingIn):
    model_config = ConfigDict(from_attributes=True)

    source: Literal["manual", "ml"]
    confidence: float | None = None
    confirmed: bool


class AdminProductRow(BaseModel):
    product: ProductBrief
    category: str | None = None
    binding: BindingOut | None = None
    suggestion: Suggestion | None = None


class AdminStats(BaseModel):
    products_total: int
    bound_manual: int
    bound_ml: int
    unbound: int
    auto_bound_share: float


class WorkOption(BaseModel):
    work_type: WorkType
    surface: Surface | None = None
    title: str
    materials: list[Material]
    material_titles: list[str]
    default: bool


class StageOptions(BaseModel):
    stage: Stage
    title: str
    works: list[WorkOption]


class WorkOptionsOut(BaseModel):
    room_type: RoomType
    room_title: str
    renovation_type: RenovationType
    renovation_title: str
    stages: list[StageOptions]


class TaxonomyOut(BaseModel):
    stages: list[dict[str, str]]
    room_types: list[dict[str, str]] = Field(default_factory=list)
    renovation_types: list[dict[str, str]]
    works: list[dict[str, Any]]
    materials: list[dict[str, str]]


ProductOut.model_rebuild()

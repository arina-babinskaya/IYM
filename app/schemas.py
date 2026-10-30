from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, field_validator, model_validator

from app.taxonomy import Material, ProductCategory, RenovationType, Stage, WorkType

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


WINDOW_AREA_M2 = Decimal("2.1")
DOOR_AREA_M2 = Decimal("1.6")

ROOM_DEFAULT_OPENINGS: dict[RoomType, tuple[int, int]] = {
    RoomType.bathroom: (0, 1),
    RoomType.hallway: (0, 2),
    RoomType.utility_room: (0, 1),
    RoomType.general_indoor: (1, 1),
}


class OpeningType(StrEnum):
    window = "window"
    door = "door"


class OpeningInput(BaseModel):
    kind: OpeningType = OpeningType.window
    title: str | None = None
    width_m: Amount = Decimal("1.5")
    height_m: Amount = Decimal("1.4")
    count: int = Field(1, ge=1, le=30)
    preset_id: str | None = None

    @property
    def total_area_m2(self) -> Decimal:
        return (self.width_m * self.height_m * Decimal(str(self.count))).quantize(Decimal("0.01"))


class RoomInput(BaseModel):
    name: str | None = None
    room_type: RoomType
    renovation_type: RenovationType | None = None
    length_m: Amount = Field(gt=0)
    width_m: Amount = Field(gt=0)
    height_m: Amount = Field(Decimal("2.7"), gt=0)
    openings_area_m2: Amount = Field(Decimal("0"), ge=0)
    windows: int | None = Field(None, ge=0, le=30)
    doors: int | None = Field(None, ge=0, le=30)
    humidity: Level | None = None
    works: list[WorkChoice] | None = None
    picks: list[int] = Field(default_factory=list)
    custom_floor_area: Amount | None = None
    custom_perimeter: Amount | None = None
    is_orthogonal: bool | None = None
    polygon: list[dict[str, float]] | None = None
    openings: list[OpeningInput] | None = None

    @model_validator(mode="after")
    def _openings_from_counts(self) -> "RoomInput":
        if self.openings:
            calc_area = Decimal("0")
            calc_wins = 0
            calc_doors = 0
            for op in self.openings:
                calc_area += op.width_m * op.height_m * Decimal(str(op.count))
                if op.kind == OpeningType.window:
                    calc_wins += op.count
                elif op.kind == OpeningType.door:
                    calc_doors += op.count
            if not self.openings_area_m2:
                self.openings_area_m2 = calc_area.quantize(Decimal("0.01"))
            if self.windows is None:
                self.windows = calc_wins
            if self.doors is None:
                self.doors = calc_doors
        elif not self.openings_area_m2 and (self.windows or self.doors):
            self.openings_area_m2 = (self.windows or 0) * WINDOW_AREA_M2 + (self.doors or 0) * DOOR_AREA_M2
        return self

    @field_validator("works", mode="before")
    @classmethod
    def _works(cls, v: Any) -> Any:
        return [{"work_type": w} if isinstance(w, str) else w for w in v] if isinstance(v, list) else v

    @property
    def floor_area(self) -> Decimal:
        if self.custom_floor_area is not None and self.custom_floor_area > 0:
            return self.custom_floor_area
        return self.length_m * self.width_m

    @property
    def perimeter(self) -> Decimal:
        if self.custom_perimeter is not None and self.custom_perimeter > 0:
            return self.custom_perimeter
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
    why: list[str] = Field(default_factory=list)
    recommendation_explanation: str | None = None
    recommendation_evidence: "RecommendationEvidence | None" = None


class ExplanationFact(BaseModel):
    code: str
    label: str
    source: Literal["binding", "catalog", "request", "ranking", "user"]
    value: str | None = None
    score: float | None = None


class RecommendationEvidence(BaseModel):
    status: Literal["available", "limited", "unavailable"]
    product_id: int
    room_type: RoomType
    work_type: WorkType
    surface: Surface | None = None
    material: Material
    facts: list[ExplanationFact] = Field(default_factory=list)


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
    status: Literal["complete", "partial", "unavailable"] = "complete"
    priced_items: int = 0
    missing_items: int = 0
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
    product_category: ProductCategory | None = None
    material: Material
    work_types: list[WorkType] = Field(default_factory=list)
    work_scores: dict[WorkType, float] = Field(default_factory=dict)
    room_types: list[RoomType] = Field(default_factory=list)
    flags: dict[str, bool] = Field(default_factory=dict)
    confidence: float = Field(ge=0, le=1)
    model: str = "unknown"


class BindingIn(BaseModel):
    product_category: ProductCategory | None = None
    material: Material
    work_types: list[WorkType] = Field(default_factory=list)
    room_types: list[RoomType] = Field(default_factory=list)
    flags: dict[str, bool] = Field(default_factory=dict)


class BindingOut(BindingIn):
    model_config = ConfigDict(from_attributes=True)

    source: Literal["manual", "ml"]
    confidence: float | None = None
    confirmed: bool


class CharacteristicIn(BaseModel):
    name: str = Field(min_length=1)
    value: str = Field(min_length=1)


class ProductCreate(BaseModel):
    name: str = Field(min_length=2, max_length=1024)
    price: Money = Field(gt=0)
    unit: str | None = None
    category: str | None = None
    brand: str | None = None
    description: str | None = None
    package_area: Amount | None = Field(None, gt=0)
    quantity_in_package: Amount | None = Field(None, gt=0)
    characteristics: list[CharacteristicIn] = Field(default_factory=list)


class AdminProductRow(BaseModel):
    product: ProductBrief
    category: str | None = None
    manual: bool = False
    binding: BindingOut | None = None
    suggestion: Suggestion | None = None


class AdminStats(BaseModel):
    products_total: int
    bound_manual: int
    bound_ml: int
    unbound: int
    auto_bound_share: float


class AutobindJob(BaseModel):
    id: str
    status: Literal["running", "completed", "failed", "cancelled"]
    phase: str
    processed: int = 0
    candidates: int = 0
    bound: int = 0
    skipped: int = 0
    rejected: int = 0
    persistence_conflicts: int = 0
    rejection_reasons: dict[str, int] = Field(default_factory=dict)
    errors: int = 0
    gigachat_considered: int = 0
    batches: int = 0
    elapsed_ms: int = 0
    classifier_ms: int = 0
    dependency_ms: int = 0
    error: str | None = None
    stats: AdminStats | None = None


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
    room_types: list[dict[str, Any]] = Field(default_factory=list)
    renovation_types: list[dict[str, str]]
    works: list[dict[str, Any]]
    materials: list[dict[str, str]]
    product_categories: list[dict[str, str]] = Field(default_factory=list)


ProductOut.model_rebuild()


OptionSort = Literal["recommended", "price_asc", "price_desc", "quality", "name"]
OptionFeature = Literal["moisture_resistant", "washable", "wear_class", "anti_slip", "frost_resistant", "antifungal",
                        "low_emission", "ip_protected"]


class OptionsRequest(BaseModel):
    room: RoomInput
    material: Material
    surface: Surface | None = None
    sort: OptionSort = "recommended"
    q: str | None = None
    features: list[OptionFeature] = Field(default_factory=list)
    suitable_only: bool = False
    price_min: Money | None = None
    price_max: Money | None = None
    limit: int = Field(30, ge=1, le=200)
    offset: int = Field(0, ge=0)


class OptionProduct(BaseModel):
    product: ProductBrief
    score: float
    quality: float
    quality_pct: int
    suitable: bool
    unit_price: Money | None = None
    unit_price_title: str = ""
    packages: int | None = None
    required_amount: Amount | None = None
    required_unit: str | None = None
    cost: Money | None = None
    features: list[str] = Field(default_factory=list)
    why: list[str] = Field(default_factory=list)


class OptionsResponse(BaseModel):
    material: Material
    material_title: str
    surface: Surface | None = None
    area_m2: Amount
    total: int
    variants: dict[str, OptionProduct] = Field(default_factory=dict)
    products: list[OptionProduct] = Field(default_factory=list)


class CatalogMatchAlternative(BaseModel):
    category_id: str
    category_name: str
    score: float


class CatalogMatchOut(BaseModel):
    product_id: int | str | None
    category_id: str
    category_name: str
    score: float
    top_3: list[CatalogMatchAlternative]
    review_recommended: bool
    score_type: str
    model: str
    taxonomy_version: str


class CatalogTaxonomyCategory(BaseModel):
    id: str
    name: str
    parent_id: str
    parent_name: str
    definition: str


class CatalogTaxonomyOut(BaseModel):
    version: str
    category_count: int
    categories: list[CatalogTaxonomyCategory]


class CatalogAssignmentOut(BaseModel):
    category_id: str
    category_name: str
    score: float | None = None
    top_3: list[CatalogMatchAlternative] = Field(default_factory=list)
    model: str | None = None
    taxonomy_version: str
    status: Literal["predicted", "needs_review", "confirmed", "corrected"]
    source: Literal["ml", "manual"]


class CatalogAdminRow(BaseModel):
    product: ProductBrief
    source_category: str | None = None
    manual: bool = False
    assignment: CatalogAssignmentOut | None = None


class CatalogCategoryIn(BaseModel):
    category_id: str = Field(min_length=1, max_length=128)


class CatalogAdminStats(BaseModel):
    products_total: int
    assigned: int
    model_suggestions: int
    manual_confirmed: int
    needs_review: int
    unassigned: int
    coverage: float


class CatalogCategorizationJob(BaseModel):
    id: str
    status: Literal["running", "completed", "failed", "cancelled"]
    phase: str
    total: int = 0
    processed: int = 0
    categorized: int = 0
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    manual_preserved: int = 0
    needs_review: int = 0
    errors: int = 0
    batches: int = 0
    elapsed_ms: int = 0
    inference_ms: int = 0
    persistence_ms: int = 0
    error: str | None = None
    stats: CatalogAdminStats | None = None

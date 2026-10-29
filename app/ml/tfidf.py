"""Adapter from catalog products to the trusted taxonomy-v2 TF-IDF artifact."""
from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from app.models import Product
from app.schemas import RoomType, Suggestion
from app.taxonomy import Material, ProductCategory, WorkType, works_for_material
from ml_workspace.ml_api import ProductInput, load_model, predict
from ml_workspace.ml_api.types import Prediction


WORK_TYPE_MAP: dict[str, WorkType] = {
    **{item.value: item for item in WorkType if item.value not in {"laminate_laying", "linoleum_laying", "plumbing_install"}},
    "plumbing_fixture_install": WorkType.plumbing_install,
}
ROOM_TYPE_MAP: dict[str, RoomType] = {
    "kitchen": RoomType.kitchen, "living_room": RoomType.living,
    "bedroom": RoomType.bedroom, "bathroom": RoomType.bathroom,
    "hallway": RoomType.hallway, "balcony": RoomType.balcony,
}
CATEGORY_MATERIAL_MAP: dict[str, Material] = {
    "primer": Material.primer, "paint": Material.paint, "putty": Material.putty,
    "plaster": Material.plaster, "drywall": Material.drywall, "tile": Material.tile,
    "waterproofing_material": Material.waterproofing, "sealant": Material.sealant,
    "fasteners": Material.fasteners, "plumbing": Material.plumbing,
    "lighting": Material.lighting, "doors_windows": Material.doors,
    "heating_climate": Material.heating, "ventilation": Material.ventilation,
    "decorative_materials": Material.decorative, "decorative_panels": Material.decorative,
    "adhesive": Material.adhesive, "construction_mix": Material.construction_mix,
    "insulation": Material.insulation, "lumber_sheet_material": Material.lumber_sheet_material,
    "installation_accessories": Material.installation_accessories,
    "hand_tools": Material.hand_tools, "power_tools": Material.power_tools,
    "tool_accessories": Material.tool_accessories, "consumables": Material.consumables,
    "protective_equipment": Material.protective_equipment,
}

# Categories whose members have several materially different roles are resolved from the
# product card.  Falling through to ``other`` is deliberate: it is safer than publishing an
# unrelated estimate material merely to improve coverage.
MATERIAL_HINTS: tuple[tuple[str, Material], ...] = (
    (r"\bобои\b|обойн\w* полотн", Material.wallpaper),
    (r"рамк\w*.{0,24}(розет|выключател)|накладк\w* декоратив", Material.installation_accessories),
    (r"клемм|соединительн\w* гильз|колпачк\w* сиз", Material.installation_accessories),
    (r"\bсвп\b|систем\w* выравниван\w* плит", Material.tile_leveling),
    (r"плиточн\w* клей|клей.{0,24}(плит|керамогранит)", Material.tile_adhesive),
    (r"обойн\w* клей|клей.{0,24}обо", Material.wallpaper_glue),
    (r"жидк\w* гвозд|монтажн\w* клей", Material.mounting_adhesive),
    (r"затирк|фуг", Material.grout),
    (r"монтажн\w* пен", Material.mounting_foam),
    (r"^(?:подрозетник\b|коробка\s+(?:монтажная|установочная|приборная)\b|"
     r"распаечная\s+коробка\b)", Material.electrical_boxes),
    (r"кабель[- ]канал|гофротруб|гофрированн\w* труб", Material.cable_channel),
    # Product names use both "автоматический выключатель" and "выключатель автоматический".
    # Match protection devices before the generic switch hint below.
    (r"автоматическ\w* выключател|выключател\w* автоматическ|\bузо\b|дифавтомат|электрощит|щиток", Material.circuit_breakers),
    (r"\bрозетк\w*\b(?!.*(рамк|накладк))", Material.socket),
    (r"\bвыключател", Material.switch),
    (r"кабел|электропровод|\bпровод\b", Material.cable),
    (r"дверн\w* (петл|ручк|замок|фурнитур)|наличник", Material.door_hardware),
    (r"профил\w*.{0,30}(гипсокартон|гкл)|\b(cd|ud|cw|uw)[ -]?профил", Material.profile),
    (r"гипсокартон|\bгкл[впо]?\b", Material.drywall),
    (r"демпферн\w* лент", Material.damper_tape),
    (r"маяк", Material.beacons),
    (r"герметик", Material.sealant),
    (r"\bламп[аы]\b|светодиодн\w* ламп", Material.lamps),
    (r"оконн\w* (блок|рама)|стеклопакет|\bокно\b", Material.windows),
    (r"водорозетк|\bтруб[аыу]?\b|фитинг|канализац|запорн\w* арматур|тройник", Material.pipes),
)

HINT_CATEGORIES: dict[Material, frozenset[str]] = {
    Material.wallpaper: frozenset({"other_renovation_material", "decorative_materials"}),
    Material.installation_accessories: frozenset({"electrical_goods", "installation_accessories"}),
    Material.tile_leveling: frozenset({"tile", "installation_accessories"}),
    Material.tile_adhesive: frozenset({"tile", "adhesive", "construction_mix"}),
    Material.wallpaper_glue: frozenset({"adhesive"}),
    Material.mounting_adhesive: frozenset({"adhesive", "installation_accessories"}),
    Material.grout: frozenset({"tile", "installation_accessories"}),
    Material.mounting_foam: frozenset({"sealant", "installation_accessories"}),
    Material.electrical_boxes: frozenset({"electrical_goods", "installation_accessories"}),
    Material.cable_channel: frozenset({"electrical_goods", "installation_accessories"}),
    Material.circuit_breakers: frozenset({"electrical_goods"}),
    Material.socket: frozenset({"electrical_goods"}),
    Material.switch: frozenset({"electrical_goods"}),
    Material.cable: frozenset({"electrical_goods"}),
    Material.door_hardware: frozenset({"doors_windows", "installation_accessories"}),
    Material.profile: frozenset({"drywall", "installation_accessories"}),
    Material.drywall: frozenset({"drywall"}),
    Material.damper_tape: frozenset({"construction_mix", "installation_accessories", "heating_climate"}),
    Material.beacons: frozenset({"construction_mix", "installation_accessories"}),
    Material.reinforcing_mesh: frozenset({"construction_mix", "installation_accessories"}),
    Material.underlay: frozenset({"floor_covering", "installation_accessories"}),
    Material.skirting: frozenset({"floor_covering", "installation_accessories"}),
    Material.sealant: frozenset({"sealant", "adhesive"}),
    Material.lamps: frozenset({"lighting"}),
    Material.windows: frozenset({"doors_windows"}),
    Material.pipes: frozenset({"plumbing"}),
}

DIRECT_RULE_CATEGORY: dict[str, ProductCategory] = {
    "spc_flooring_object": ProductCategory.floor_covering,
    "standalone_floor_underlay": ProductCategory.floor_covering,
    "electrical_box_object": ProductCategory.installation_accessories,
    "circuit_breaker_object": ProductCategory.electrical_goods,
    "reinforcing_mesh_object": ProductCategory.installation_accessories,
    "floor_skirting_object": ProductCategory.floor_covering,
    "floor_screed_mix_object": ProductCategory.construction_mix,
    "floor_damper_tape_object": ProductCategory.installation_accessories,
    "screed_plaster_beacon_object": ProductCategory.installation_accessories,
    "tile_leveling_object": ProductCategory.installation_accessories,
}
DIRECT_EVIDENCE_CONFIDENCE = .95

# These product families occur mostly inside broad renovation categories.  They need object-level
# evidence: an incidental phrase (for example, SPC flooring "с подложкой") must never define the
# material.  Rules are deliberately anchored and source-category constrained where ambiguity is
# common.  They specialize the renovation classifier output; the independent catalog classifier is
# not read here.
UNDERLAY_SOURCE = re.compile(r"^подложка (?:пробковая|пластиковая|пробково-битумная)$", re.I)
FLOOR_SKIRTING_SOURCE = re.compile(
    r"^(?:плинтусы на основе (?:пвх|мдф)|плинтусы напольные|"
    r"декоры и бордюры для керамогранита)$", re.I
)
ELECTRICAL_BOX_SOURCE = re.compile(r"^коробки монтажные$", re.I)
BREAKER_SOURCE = re.compile(r"^автоматы защиты$", re.I)
MESH_SOURCE = re.compile(r"^сетки малярные, серпянка$", re.I)
SCREED_SOURCE = re.compile(r"^смеси для выравнивания полов (?:цементные|гипсовые)$", re.I)
DAMPER_SOURCE = re.compile(r"^пенополиэтилен$", re.I)
BEACON_SOURCE = re.compile(r"^профили и аксессуары для гипсокартона$", re.I)
TILE_LEVELING_SOURCE = re.compile(r"^системы выравнивания плитки$", re.I)


def _evidence_text(product: Product) -> tuple[str, list[str]]:
    return (product.name or "").strip().lower(), [
        str(value).strip().lower() for value in (product.categories or {}).values() if value
    ]


def _direct_material(product: Product) -> tuple[Material | None, tuple[WorkType, ...], str | None]:
    """Return a material only for unambiguous product-identity evidence."""
    name, categories = _evidence_text(product)

    # Attached underlay is a feature of the floor board, not the object being sold.
    if re.match(r"^(?:плитка\s+spc|spc\b|кварц[- ]?винил)", name):
        return Material.floor_covering, (), "spc_flooring_object"

    if re.match(r"^подложка\b", name) and not re.match(r"^подложка\s+под\s+ков[её]р", name):
        if any(UNDERLAY_SOURCE.match(category) for category in categories) or re.search(
            r"\b(?:пробков|хвойн|xps|ппэ|ппк|эва|eva|джутов|пенополистирол)", name
        ):
            return Material.underlay, (WorkType.floor_covering_install,), "standalone_floor_underlay"

    box_object = re.match(
        r"^(?:подрозетник\b|коробка\s+(?:монтажная|установочная|приборная)\b)", name
    )
    if box_object and any(ELECTRICAL_BOX_SOURCE.match(category) for category in categories):
        return Material.electrical_boxes, (WorkType.electrical_wiring, WorkType.electrical_fittings), \
            "electrical_box_object"

    if (re.match(r"^(?:автомат(?:ический)?\b|выключатель\s+автоматический\b|узо\b|дифавтомат\b)", name)
            and any(BREAKER_SOURCE.match(category) for category in categories)):
        return Material.circuit_breakers, (WorkType.electrical_wiring,), "circuit_breaker_object"

    if (re.match(r"^(?:серпянка\b|лента\s+стекловолоконная\s*\(серпянка\))", name)
            and any(MESH_SOURCE.match(category) for category in categories)):
        return Material.reinforcing_mesh, (
            WorkType.wall_plastering, WorkType.drywall_install, WorkType.wall_putty,
        ), "reinforcing_mesh_object"

    # The head noun must be the actual floor skirting. Accessories start with угол/заглушка/etc.;
    # ceiling, countertop and decorative mouldings are explicitly outside this material.
    if (re.match(r"^плинтус\b", name)
            and not re.search(r"\b(?:потолочн|для столешниц|столешниц[ыа]|декоративн)\b", name)
            and any(FLOOR_SKIRTING_SOURCE.match(category) for category in categories)):
        return Material.skirting, (WorkType.floor_covering_install,), "floor_skirting_object"

    if (any(SCREED_SOURCE.match(category) for category in categories)
            and re.match(r"^(?:пол наливной\b|ровнитель\b|выравниватель для пола\b|смесь для пола\b)", name)):
        return Material.screed_mix, (WorkType.floor_screed,), "floor_screed_mix_object"

    if (re.match(r"^лента демпферная\b", name)
            and any(DAMPER_SOURCE.match(category) for category in categories)
            and re.search(r"\b(?:нпэ|ппэ|пенополиэтилен)", name)):
        return Material.damper_tape, (WorkType.floor_screed,), "floor_damper_tape_object"

    if (re.match(r"^профиль (?:маячковый|выравнивающий\b.*\bмаячок)\b", name)
            and any(BEACON_SOURCE.match(category) for category in categories)):
        return Material.beacons, (WorkType.floor_screed, WorkType.wall_plastering), \
            "screed_plaster_beacon_object"

    if (any(TILE_LEVELING_SOURCE.match(category) for category in categories)
            and "наливного пола" not in name
            and re.search(r"\b(?:выравниван\w* плитк|зажим|клин|подков|прижимн\w* гайк)", name)):
        return Material.tile_leveling, (WorkType.tiling,), "tile_leveling_object"

    return None, (), None


class ClassifierArtifactError(RuntimeError):
    """The configured classifier artifact is missing, unsafe, or incompatible."""


def product_to_input(product: Product) -> ProductInput:
    categories = product.categories or {}
    category_values = [str(value) for value in categories.values() if value]
    raw = product.raw or {}
    characteristics = raw.get("characteristics") or raw.get("params") or product.specs or {}
    marketing_description = raw.get("marketing_description") or ""
    return ProductInput(
        product_id=product.id,
        name=product.name,
        source_category=category_values[-1] if category_values else "",
        category_names=" | ".join(category_values),
        description=product.description or "",
        marketing_description=marketing_description,
        characteristics=characteristics,
        price=float(product.result_price or product.price) if (product.result_price or product.price) is not None else None,
        sale_unit=product.unit or "",
        brand_name=product.brand_name or "",
    )


def _floor_work(prediction: Prediction, product: Product) -> WorkType | None:
    if "floor_covering_install" not in prediction.work_types:
        return None
    text = f"{product.name} {' '.join((product.categories or {}).values())}".lower()
    if "ламинат" in text:
        return WorkType.laminate_laying
    if "линолеум" in text:
        return WorkType.linoleum_laying
    return None


def _material(prediction: Prediction, product: Product) -> Material:
    direct, _, _ = _direct_material(product)
    if direct is not None:
        return direct
    text = f"{product.name} {' '.join((product.categories or {}).values())}".lower()
    for pattern, material in MATERIAL_HINTS:
        if prediction.product_category in HINT_CATEGORIES.get(material, frozenset()) and re.search(pattern, text):
            return material
    mapped = CATEGORY_MATERIAL_MAP.get(prediction.product_category)
    if mapped is not None:
        return mapped
    if prediction.product_category == "floor_covering":
        if "ламинат" in text:
            return Material.laminate
        if "линолеум" in text:
            return Material.linoleum
    if prediction.product_category == "electrical_goods":
        if "розет" in text:
            return Material.socket
        if "выключател" in text:
            return Material.switch
        if "кабел" in text or "провод" in text:
            return Material.cable
    if prediction.product_category == "floor_covering":
        if "подложк" in text:
            return Material.underlay
        if "плинтус" in text or "порож" in text:
            return Material.skirting
        return Material.floor_covering
    if prediction.product_category == "electrical_goods":
        return Material.electrical_goods
    return Material.other


def prediction_to_suggestion(prediction: Prediction, product: Product) -> Suggestion:
    mapped: list[WorkType] = []
    scores: dict[WorkType, float] = {}
    unsupported: list[str] = []
    for label in prediction.work_types:
        work = WORK_TYPE_MAP.get(label)
        if label == "floor_covering_install":
            work = _floor_work(prediction, product)
        if work is None:
            unsupported.append(label)
            continue
        if work not in mapped:
            mapped.append(work)
        scores[work] = prediction.scores[label]

    rooms: list[RoomType] = []
    unsupported_rooms: list[str] = []
    for label in prediction.room_types:
        room = ROOM_TYPE_MAP.get(label)
        if room is None:
            unsupported_rooms.append(label)
        elif room not in rooms:
            rooms.append(room)

    flags: dict[str, bool] = {
        "ml_unknown": prediction.status in {"unknown", "uncertain"},
        "domain_renovation": prediction.domain_label == "renovation",
        "domain_furnishing": prediction.domain_label == "furnishing",
        "domain_non_renovation": prediction.status == "non_renovation",
        **{f"unsupported_work_type__{label}": True for label in unsupported},
        **{f"unsupported_room_type__{label}": True for label in unsupported_rooms},
    }
    material = _material(prediction, product)
    direct_material, direct_works, direct_rule = _direct_material(product)
    if direct_material is not None:
        material = direct_material
        if direct_works:
            mapped = list(direct_works)
            flags["work_type_inferred"] = True
        flags["direct_material_evidence"] = True
        flags[f"adapter_rule__{direct_rule}"] = True
        # Exact object name + compatible Maxidom source category is stronger evidence for this
        # narrow material decision than the model's deliberately broad category.  Keep the normal
        # publication threshold, but identify the deterministic decision and its supporting
        # renovation category explicitly.
        flags["domain_renovation"] = True
        flags["domain_furnishing"] = False
        flags["domain_non_renovation"] = False
        flags["ml_unknown"] = False
    plausible = works_for_material(material) if material != Material.other else []
    incompatible = bool(mapped) and bool(plausible) and not any(work in plausible for work in mapped)
    if incompatible:
        flags["taxonomy_inconsistent"] = True
    # A single taxonomy consequence is safe to infer.  Materials shared by several works remain
    # material-only unless the work model supplied evidence.
    if not mapped and len(plausible) == 1 and prediction.status == "predicted":
        mapped = list(plausible)
        flags["work_type_inferred"] = True

    category_scores = prediction.dimension_scores.get("product_category", {})
    domain_scores = prediction.dimension_scores.get("domain", {})
    category_confidence = category_scores.get(prediction.product_category, 0.0)
    domain_confidence = domain_scores.get(prediction.domain_label, 0.0)
    material_confidence = min(category_confidence, domain_confidence) if domain_confidence else category_confidence
    work_confidence = max(scores.values(), default=0.0)
    # Backward-compatible ``confidence`` now represents the binding/material decision, not merely
    # the optional work-type decision. Old artifacts without dimension scores retain work score.
    confidence = material_confidence or work_confidence
    if direct_rule is not None:
        confidence = max(confidence, DIRECT_EVIDENCE_CONFIDENCE)
    flags["material_confident"] = confidence >= 0.7
    flags["work_type_missing"] = not mapped
    category = (DIRECT_RULE_CATEGORY[direct_rule] if direct_rule is not None
                else ProductCategory(prediction.product_category) if prediction.product_category else None)
    return Suggestion(product_category=category, material=material, work_types=mapped, work_scores=scores, room_types=rooms,
                      flags=flags, confidence=confidence, model="tfidf-logreg-taxonomy-v2")


def publishable(suggestion: Suggestion, min_confidence: float) -> bool:
    """Conservative automatic-publication policy shared by API and batch jobs."""
    return (
        suggestion.confidence >= min_confidence
        and suggestion.product_category is not None
        and suggestion.material != Material.other
        and suggestion.flags.get("domain_renovation", False)
        and not suggestion.flags.get("ml_unknown", False)
        and not suggestion.flags.get("taxonomy_inconsistent", False)
    )


class TfidfClassifier:
    """Long-lived backend classifier; construction performs the one artifact load."""

    name = "tfidf-logreg-taxonomy-v2"

    def __init__(self, artifact_path: Path | str):
        path = Path(artifact_path)
        try:
            self.model = load_model(path, "taxonomy_v2", trusted=True)
        except Exception as exc:
            raise ClassifierArtifactError(
                f"Cannot load trusted TF-IDF classifier artifact at {path}: {exc}"
            ) from exc

    def predict(self, products: list[Product]) -> list[Suggestion]:
        if not products:
            return []
        predictions = predict(self.model, [product_to_input(product) for product in products])
        return [prediction_to_suggestion(item, product)
                for item, product in zip(predictions, products, strict=True)]

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
    (r"подрозетник|установочн\w* короб|распаечн\w* короб", Material.electrical_boxes),
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
    (r"серпянк|армирующ\w* сетк|стеклосетк", Material.reinforcing_mesh),
    (r"подложк", Material.underlay),
    (r"плинтус|порожек", Material.skirting),
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
    flags["material_confident"] = confidence >= 0.7
    flags["work_type_missing"] = not mapped
    category = ProductCategory(prediction.product_category) if prediction.product_category else None
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

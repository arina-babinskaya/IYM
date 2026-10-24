"""Adapter from catalog products to the trusted taxonomy-v2 TF-IDF artifact."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from app.models import Product
from app.schemas import RoomType, Suggestion
from app.taxonomy import Material, WorkType
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
    mapped = CATEGORY_MATERIAL_MAP.get(prediction.product_category)
    if mapped is not None:
        return mapped
    text = f"{product.name} {' '.join((product.categories or {}).values())}".lower()
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
        **{f"unsupported_work_type__{label}": True for label in unsupported},
        **{f"unsupported_room_type__{label}": True for label in unsupported_rooms},
    }
    material = _material(prediction, product)
    confidence = max(scores.values(), default=0.0)
    return Suggestion(material=material, work_types=mapped, work_scores=scores, room_types=rooms,
                      flags=flags, confidence=confidence, model="tfidf-logreg-taxonomy-v2")


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

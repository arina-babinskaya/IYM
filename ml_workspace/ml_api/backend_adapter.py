from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

from .api import load_model, predict
from .types import Prediction, ProductInput


BACKEND_WORK_TYPES = {"demolition", "electrical_wiring", "plumbing_rough", "waterproofing",
    "floor_screed", "wall_plastering", "drywall_install", "wall_putty", "priming", "tiling",
    "wall_painting", "wallpapering", "laminate_laying", "linoleum_laying", "electrical_fittings",
    "plumbing_install"}

V2_TO_BACKEND = {
    "plumbing_fixture_install": "plumbing_install",
}


class WorkTypeInferenceAdapter:
    """Long-lived prototype adapter; loads artifacts once and supports batch inference."""
    def __init__(self, artifact_dir: Path, taxonomy_version: str, *, trusted_local_artifact: bool,
                 encoder: Any = None):
        self.model = load_model(artifact_dir, taxonomy_version, trusted=trusted_local_artifact, encoder=encoder)

    def predict(self, products: ProductInput | Sequence[ProductInput]) -> Prediction | list[Prediction]:
        return predict(self.model, products)

    @staticmethod
    def to_backend_suggestion(prediction: Prediction, material: str = "other") -> dict[str, Any]:
        # New draft IDs are omitted rather than sent into strict backend enums.
        mapped = [V2_TO_BACKEND.get(label, label) for label in prediction.labels
                  if V2_TO_BACKEND.get(label, label) in BACKEND_WORK_TYPES]
        unsupported = [label for label in prediction.labels
                       if V2_TO_BACKEND.get(label, label) not in BACKEND_WORK_TYPES]
        scores = {V2_TO_BACKEND.get(label, label): prediction.scores[label] for label in prediction.labels
                  if V2_TO_BACKEND.get(label, label) in BACKEND_WORK_TYPES}
        return {"material": material, "work_types": mapped, "work_scores": scores,
                "room_types": prediction.room_types, "flags": {"ml_unknown": prediction.status in {"unknown", "uncertain"},
                "unsupported_taxonomy_v2_work_types": unsupported, "activity_labels": prediction.activities,
                "domain_label": prediction.domain_label},
                "confidence": max(scores.values(), default=0.0), "model": "workspace-unified-adapter"}

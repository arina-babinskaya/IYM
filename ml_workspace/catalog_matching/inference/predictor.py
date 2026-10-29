from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence

import joblib
import numpy as np

from ..taxonomy.catalog_taxonomy import CATEGORY_BY_ID, TAXONOMY_VERSION

REQUIRED_ARTIFACT_FILES = frozenset(
    {"model.joblib", "metadata.json", "taxonomy.json", "checksums.json"}
)


class CatalogArtifactError(RuntimeError):
    """The full-catalog classifier artifact is absent or incompatible."""


@dataclass(frozen=True)
class Alternative:
    category_id: str
    category_name: str
    confidence: float


@dataclass(frozen=True)
class CategoryPrediction:
    category_id: str
    category_name: str
    confidence: float
    alternatives: tuple[Alternative, ...]
    model: str
    needs_review: bool
    score_type: str = "uncalibrated_probability"

    def to_dict(self) -> dict:
        data = asdict(self)
        data["alternatives"] = list(data["alternatives"])
        return data


class CatalogPredictor:
    """Load one trusted artifact and perform single or batched inference."""

    def __init__(self, artifact_dir: str | Path, require_full_taxonomy: bool = False):
        path = Path(artifact_dir)
        missing = sorted(name for name in REQUIRED_ARTIFACT_FILES if not (path / name).is_file())
        if missing:
            raise CatalogArtifactError(
                f"Catalog classifier artifact at {path} is missing required files: {', '.join(missing)}"
            )
        try:
            checks = json.loads((path / "checksums.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CatalogArtifactError(f"Invalid checksums.json in catalog artifact {path}: {exc}") from exc
        payloads = REQUIRED_ARTIFACT_FILES - {"checksums.json"}
        if set(checks) != payloads:
            raise CatalogArtifactError(
                "Catalog artifact checksum manifest must contain exactly: " + ", ".join(sorted(payloads))
            )
        for name, expected in checks.items():
            if hashlib.sha256((path / name).read_bytes()).hexdigest() != expected:
                raise CatalogArtifactError(f"Catalog artifact checksum mismatch: {name}")

        try:
            metadata = json.loads((path / "metadata.json").read_text(encoding="utf-8"))
            taxonomy = json.loads((path / "taxonomy.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CatalogArtifactError(f"Invalid catalog artifact metadata at {path}: {exc}") from exc
        taxonomy_ids = {str(item["id"]) for item in taxonomy.get("categories", [])}
        model_classes = {str(item) for item in metadata.get("classes", [])}
        trainable_ids = set(CATEGORY_BY_ID) - {"review.unresolved"}
        if metadata.get("taxonomy_version") != TAXONOMY_VERSION or taxonomy.get("version") != TAXONOMY_VERSION:
            raise CatalogArtifactError(
                f"Catalog taxonomy mismatch: expected {TAXONOMY_VERSION}, got "
                f"{metadata.get('taxonomy_version')!r}/{taxonomy.get('version')!r}"
            )
        if taxonomy_ids != set(CATEGORY_BY_ID):
            raise CatalogArtifactError("Artifact taxonomy category IDs do not match the local taxonomy v2")
        if not model_classes or not model_classes <= trainable_ids:
            raise CatalogArtifactError("Catalog model contains unknown or no taxonomy-v2 category IDs")
        if require_full_taxonomy and (len(model_classes) != 90 or model_classes != trainable_ids):
            raise CatalogArtifactError(
                f"Catalog model must contain the 90 trainable taxonomy-v2 leaves; got {len(model_classes)}"
            )
        schema = metadata.get("input_schema", {})
        if schema.get("required") != ["product_name"] or schema.get("feature_mode") not in {
            "name", "name_description"
        }:
            raise CatalogArtifactError(f"Unsupported catalog model input schema: {schema!r}")
        try:
            model = joblib.load(path / "model.joblib")
        except Exception as exc:
            raise CatalogArtifactError(f"Cannot load catalog model at {path}: {exc}") from exc
        if {str(item) for item in getattr(model, "classes_", ())} != model_classes:
            raise CatalogArtifactError("Loaded model classes do not match metadata.json")

        self.artifact_path = path
        self.model = model
        self.metadata = metadata
        self.taxonomy = taxonomy
        self.names = {str(item["id"]): str(item["name"]) for item in taxonomy["categories"]}

    def _feature(self, product_name: str, description: str | None = None) -> str:
        if not isinstance(product_name, str) or not product_name.strip():
            raise ValueError("product_name must be non-empty")
        text = product_name.strip()
        if self.metadata["input_schema"]["feature_mode"] == "name_description" and description:
            text += " " + description.strip()
        return text

    def predict_batch(
        self,
        product_names: Sequence[str],
        descriptions: Sequence[str | None] | None = None,
        top_k: int = 3,
    ) -> list[CategoryPrediction]:
        if top_k < 1:
            raise ValueError("top_k must be at least 1")
        if descriptions is not None and len(descriptions) != len(product_names):
            raise ValueError("descriptions must have the same length as product_names")
        if not product_names:
            return []
        descriptions = descriptions if descriptions is not None else [None] * len(product_names)
        texts = [self._feature(name, desc) for name, desc in zip(product_names, descriptions, strict=True)]
        probabilities = self.model.predict_proba(texts)
        classes = np.asarray(self.model.classes_, dtype=str)
        limit = min(top_k, len(classes))
        threshold = self.metadata.get("review_threshold")
        results = []
        for probs in probabilities:
            order = np.argsort(probs)[::-1][:limit]
            best = int(order[0])
            category_id = str(classes[best])
            alternatives = tuple(
                Alternative(str(classes[i]), self.names[str(classes[i])], float(probs[i])) for i in order[1:]
            )
            results.append(CategoryPrediction(
                category_id, self.names[category_id], float(probs[best]), alternatives,
                self.metadata["model_name"], bool(threshold is not None and probs[best] < threshold),
            ))
        return results

    def predict_category(
        self, product_name: str, description: str | None = None, top_k: int = 3
    ) -> CategoryPrediction:
        return self.predict_batch([product_name], [description], top_k=top_k)[0]


def predict_category(
    artifact_dir: str | Path, product_name: str, description: str | None = None
) -> CategoryPrediction:
    return CatalogPredictor(artifact_dir).predict_category(product_name, description)

"""ML-matching-only adapter for the independent full-catalog classifier.

This module deliberately does not produce ``Suggestion`` or ``ProductBinding`` values.
Those renovation contracts belong to candidate selection and ranking.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from app.models import Product
from ml_workspace.catalog_matching.inference.predictor import (
    CatalogArtifactError,
    CatalogPredictor,
    CategoryPrediction,
)


@dataclass(frozen=True)
class CatalogMatchInput:
    product_id: int | str | None
    name: str


@dataclass(frozen=True)
class CatalogMatchResult:
    product_id: int | str | None
    prediction: CategoryPrediction
    taxonomy_version: str
    artifact_path: str


class CatalogMatchingClassifier:
    """Long-lived adapter used only by catalog-category ML matching."""

    def __init__(self, artifact_path: Path | str):
        self.predictor = CatalogPredictor(artifact_path, require_full_taxonomy=True)

    @property
    def artifact_path(self) -> Path:
        return self.predictor.artifact_path

    def _input(self, product: Product | CatalogMatchInput | dict) -> CatalogMatchInput:
        if isinstance(product, Product):
            return CatalogMatchInput(product.id, product.name)
        if isinstance(product, CatalogMatchInput):
            return product
        if isinstance(product, dict):
            return CatalogMatchInput(product.get("id", product.get("product_id")), product.get("name", ""))
        raise TypeError("product must be a Product, CatalogMatchInput, or mapping")

    def predict_batch(
        self, products: Sequence[Product | CatalogMatchInput | dict], top_k: int = 3
    ) -> list[CatalogMatchResult]:
        inputs = [self._input(product) for product in products]
        predictions = self.predictor.predict_batch([item.name for item in inputs], top_k=top_k)
        version = self.predictor.metadata["taxonomy_version"]
        return [
            CatalogMatchResult(item.product_id, prediction, version, str(self.artifact_path))
            for item, prediction in zip(inputs, predictions, strict=True)
        ]

    def predict_one(
        self, product: Product | CatalogMatchInput | dict, top_k: int = 3
    ) -> CatalogMatchResult:
        return self.predict_batch([product], top_k=top_k)[0]


__all__ = [
    "CatalogArtifactError", "CatalogMatchInput", "CatalogMatchResult", "CatalogMatchingClassifier"
]

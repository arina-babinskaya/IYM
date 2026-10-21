from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol, Sequence

import numpy as np
import pandas as pd


ExperimentName = Literal["tfidf_logreg", "embeddings_logreg", "catboost_structured"]
LabelPolicy = Literal["reviewed_only", "weak_only", "reviewed_plus_weak"]


class SentenceEncoder(Protocol):
    def encode(self, texts: list[str], **kwargs: Any) -> np.ndarray: ...


@dataclass(frozen=True)
class ProductInput:
    product_id: int | None
    name: str
    source_category: str = ""
    description: str = ""
    marketing_description: str = ""
    characteristics: dict[str, Any] = field(default_factory=dict)
    price: float | None = None
    sale_unit: str = ""
    brand_name: str = ""


@dataclass
class DatasetBundle:
    """Rows plus ordered work-type vocabulary. `labels` contains list[str]."""
    frame: pd.DataFrame
    class_names: list[str]
    taxonomy_version: str
    label_policy: LabelPolicy
    split_manifest_path: Path


@dataclass
class FeatureBundle:
    """Prepared X by split and a `(n_rows,n_classes)` binary target matrix."""
    experiment: ExperimentName
    dataset: DatasetBundle
    x_by_split: dict[str, Any]
    y_by_split: dict[str, np.ndarray]
    ids_by_split: dict[str, np.ndarray]
    preprocessor: Any
    feature_schema: list[str]
    encoder: SentenceEncoder | None = None


@dataclass
class TrainingConfig:
    experiment: ExperimentName
    random_seed: int = 20261023
    max_features: int = 80_000
    embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    logistic_max_iter: int = 500
    catboost_iterations: int = 100
    catboost_depth: int = 6
    catboost_learning_rate: float = 0.08
    use_gpu: bool = False


@dataclass
class ModelBundle:
    experiment: ExperimentName
    estimator: Any
    preprocessor: Any
    class_names: list[str]
    thresholds: dict[str, float]
    taxonomy_version: str
    feature_schema: list[str]
    training_config: TrainingConfig
    encoder: SentenceEncoder | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ValidationResult:
    thresholds: dict[str, float]
    metrics: dict[str, Any]
    support: dict[str, int]


@dataclass(frozen=True)
class EvaluationResult:
    split: str
    metrics: dict[str, Any]
    product_ids: list[int]
    y_true: np.ndarray
    y_pred: np.ndarray
    y_score: np.ndarray
    label_provenance: str


@dataclass(frozen=True)
class Prediction:
    product_id: int | None
    labels: list[str]
    scores: dict[str, float]
    status: Literal["predicted", "unknown"]


ProductBatch = ProductInput | Sequence[ProductInput]

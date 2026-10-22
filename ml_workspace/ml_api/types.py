from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol, Sequence
import numpy as np
import pandas as pd

ExperimentName = Literal["tfidf_logreg", "embeddings_logreg", "catboost_structured"]
class SentenceEncoder(Protocol):
    def encode(self, texts: list[str], **kwargs: Any) -> np.ndarray: ...
@dataclass(frozen=True)
class ProductInput:
    product_id: int | None; name: str; source_category: str = ""; category_names: str = ""
    description: str = ""; marketing_description: str = ""; characteristics: dict[str, Any] = field(default_factory=dict)
    price: float | None = None; sale_unit: str = ""; brand_name: str = ""
@dataclass
class DatasetBundle:
    frame: pd.DataFrame; class_names: list[str]; taxonomy_version: str; label_policy: str; split_manifest_path: Path
    task_classes: dict[str, list[str]] = field(default_factory=dict)
@dataclass
class FeatureBundle:
    experiment: ExperimentName; dataset: DatasetBundle; x_by_split: dict[str, Any]; y_by_split: dict[str, np.ndarray]
    ids_by_split: dict[str, np.ndarray]; preprocessor: Any; feature_schema: list[str]; encoder: SentenceEncoder | None = None
    y_by_task: dict[str, dict[str, np.ndarray]] = field(default_factory=dict); fit_product_ids: list[int] = field(default_factory=list)
    supervision_mask_by_task: dict[str, dict[str, np.ndarray]] = field(default_factory=dict)
@dataclass
class TrainingConfig:
    experiment: ExperimentName = "tfidf_logreg"; random_seed: int = 20261022; max_features: int = 80_000
    embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    logistic_max_iter: int = 500; catboost_iterations: int = 100; catboost_depth: int = 6
    catboost_learning_rate: float = .08; use_gpu: bool = False
    tasks: tuple[str, ...] = ("domain", "activities", "product_category", "work_types", "room_types")
@dataclass
class ModelBundle:
    experiment: ExperimentName; estimator: Any; preprocessor: Any; class_names: list[str]; thresholds: dict[str, float]
    taxonomy_version: str; feature_schema: list[str]; training_config: TrainingConfig; encoder: SentenceEncoder | None = None
    metadata: dict[str, Any] = field(default_factory=dict); task_classes: dict[str, list[str]] = field(default_factory=dict)
@dataclass(frozen=True)
class ValidationResult:
    thresholds: dict[str, float]; metrics: dict[str, Any]; support: dict[str, int]
@dataclass(frozen=True)
class EvaluationResult:
    split: str; metrics: dict[str, Any]; product_ids: list[int]; y_true: Any; y_pred: Any; y_score: Any; label_provenance: str
@dataclass(frozen=True)
class Prediction:
    product_id: int | None; labels: list[str]; scores: dict[str, float]
    status: Literal["predicted", "uncertain", "non_renovation", "unknown"]
    domain_label: str = "unknown_needs_review"; product_category: str = ""; work_types: list[str] = field(default_factory=list)
    renovation_stages: list[str] = field(default_factory=list); activities: list[str] = field(default_factory=list)
    room_types: list[str] = field(default_factory=list); dimension_scores: dict[str, dict[str, float]] = field(default_factory=dict)
ProductBatch = ProductInput | Sequence[ProductInput]

from __future__ import annotations

import importlib.metadata
import json
import platform
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Sequence

import joblib
import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.multiclass import OneVsRestClassifier

from .data import load_training_data
from .metrics import compute_metrics
from .types import (DatasetBundle, EvaluationResult, FeatureBundle, ModelBundle,
                    Prediction, ProductBatch, ProductInput, SentenceEncoder,
                    TrainingConfig, ValidationResult)


STRUCTURED_SCHEMA = ["price", "characteristic_count", "information_completeness", "name_length",
                     "description_length", "source_category", "sale_unit", "brand_name"]
STRUCTURED_CATEGORICAL = ["source_category", "sale_unit", "brand_name"]


def load_data(clean_path: Path, weak_labels_path: Path, reviewed_paths: Sequence[Path],
              split_manifest_path: Path, taxonomy_path: Path, taxonomy_version: str,
              label_policy: str = "reviewed_only", random_seed: int = 20261023) -> DatasetBundle:
    """Load features and prioritized labels; returns rows with `labels`, provenance and stable split.

    Human `reviewed`/`approved` labels override weak labels. Unknown applicability is excluded.
    Verified empty lists remain valid negative examples and are never silently removed.
    """
    taxonomy = pd.read_csv(taxonomy_path, keep_default_na=False)
    id_column = "work_type_id" if "work_type_id" in taxonomy else "id"
    class_names = taxonomy[id_column].astype(str).tolist()
    return load_training_data(clean_path, weak_labels_path, list(reviewed_paths), split_manifest_path,
                              class_names, taxonomy_version, label_policy, random_seed)  # type: ignore[arg-type]


def _encode_labels(values: Sequence[list[str]], classes: list[str]) -> np.ndarray:
    index = {label: i for i, label in enumerate(classes)}
    matrix = np.zeros((len(values), len(classes)), dtype=np.int8)
    for row, labels in enumerate(values):
        for label in labels:
            matrix[row, index[label]] = 1
    return matrix


def _structured_frame(frame: pd.DataFrame) -> pd.DataFrame:
    result = pd.DataFrame(index=frame.index)
    result["price"] = pd.to_numeric(frame.get("price", 0), errors="coerce").fillna(0.0)
    result["characteristic_count"] = pd.to_numeric(frame.get("characteristic_count", 0), errors="coerce").fillna(0)
    result["information_completeness"] = pd.to_numeric(frame.get("information_completeness", 0), errors="coerce").fillna(0)
    result["name_length"] = frame.get("name", "").astype(str).str.len()
    desc = frame.get("description_clean", frame.get("description", "")).astype(str)
    result["description_length"] = desc.str.len()
    for column in STRUCTURED_CATEGORICAL:
        result[column] = frame.get(column, "").astype(str).replace("", "<missing>")
    return result[STRUCTURED_SCHEMA]


def _load_sentence_encoder(model_name: str, device: str = "cpu") -> SentenceEncoder:
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise RuntimeError("Install sentence-transformers with a compatible PyTorch build") from exc
    return SentenceTransformer(model_name, device=device)


def prepare_features(data: DatasetBundle, config: TrainingConfig, cache_dir: Path | None = None,
                     encoder: SentenceEncoder | None = None) -> FeatureBundle:
    """Fit preprocessing on train only and return X/Y arrays keyed by split."""
    frame = data.frame
    y_all = _encode_labels(frame.labels.tolist(), data.class_names)
    split_masks = {split: frame.split.eq(split).to_numpy() for split in ["train", "validation", "test"]}
    if any(mask.sum() == 0 for mask in split_masks.values()):
        raise ValueError("train, validation and test must all be non-empty")
    x_by_split: dict[str, Any] = {}
    preprocessor: Any
    if config.experiment == "tfidf_logreg":
        preprocessor = TfidfVectorizer(ngram_range=(1, 2), min_df=1, max_df=0.98,
                                       max_features=config.max_features, sublinear_tf=True)
        preprocessor.fit(frame.loc[split_masks["train"], "text"])
        x_by_split = {split: preprocessor.transform(frame.loc[mask, "text"]) for split, mask in split_masks.items()}
    elif config.experiment == "embeddings_logreg":
        encoder = encoder or _load_sentence_encoder(config.embedding_model, "cuda" if config.use_gpu else "cpu")
        ids = frame.product_id.astype(int).tolist()
        cache_path = (cache_dir or Path("ml_workspace/cache")) / f"embeddings_{config.embedding_model.replace('/', '_')}.npy"
        ids_path = cache_path.with_suffix(".ids.json")
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        if cache_path.exists() and ids_path.exists() and json.loads(ids_path.read_text()) == ids:
            matrix = np.load(cache_path)
        else:
            matrix = np.asarray(encoder.encode(frame.text.tolist(), batch_size=64, show_progress_bar=True,
                                               normalize_embeddings=True))
            np.save(cache_path, matrix)
            ids_path.write_text(json.dumps(ids), encoding="utf-8")
        x_by_split = {split: matrix[mask] for split, mask in split_masks.items()}
        preprocessor = {"embedding_model": config.embedding_model, "normalized": True}
    elif config.experiment == "catboost_structured":
        structured = _structured_frame(frame)
        x_by_split = {split: structured.loc[mask].reset_index(drop=True) for split, mask in split_masks.items()}
        preprocessor = {"categorical_features": STRUCTURED_CATEGORICAL, "schema": STRUCTURED_SCHEMA}
    else:
        raise ValueError(f"Unsupported experiment: {config.experiment}")
    return FeatureBundle(config.experiment, data, x_by_split,
        {split: y_all[mask] for split, mask in split_masks.items()},
        {split: frame.loc[mask, "product_id"].astype(int).to_numpy() for split, mask in split_masks.items()},
        preprocessor, STRUCTURED_SCHEMA if config.experiment == "catboost_structured" else ["text"], encoder)


def train(features: FeatureBundle, config: TrainingConfig) -> ModelBundle:
    """Train estimator(s) on `features.x_by_split['train']` only."""
    if features.experiment != config.experiment:
        raise ValueError("Feature/experiment mismatch")
    x, y = features.x_by_split["train"], features.y_by_split["train"]
    if config.experiment in {"tfidf_logreg", "embeddings_logreg"}:
        estimator = OneVsRestClassifier(LogisticRegression(max_iter=config.logistic_max_iter,
            class_weight="balanced", solver="liblinear"), n_jobs=1)
        estimator.fit(x, y)
    else:
        try:
            from catboost import CatBoostClassifier
        except ImportError as exc:
            raise RuntimeError("Install catboost to run catboost_structured") from exc
        estimator = []
        for column in range(y.shape[1]):
            unique = np.unique(y[:, column])
            if len(unique) == 1:
                estimator.append({"constant": float(unique[0])})
                continue
            model = CatBoostClassifier(iterations=config.catboost_iterations, depth=config.catboost_depth,
                learning_rate=config.catboost_learning_rate, loss_function="Logloss", verbose=False,
                random_seed=config.random_seed, task_type="GPU" if config.use_gpu else "CPU",
                auto_class_weights="Balanced", allow_writing_files=False)
            model.fit(x, y[:, column], cat_features=STRUCTURED_CATEGORICAL)
            estimator.append(model)
    return ModelBundle(config.experiment, estimator, features.preprocessor, features.dataset.class_names,
                       {label: 0.5 for label in features.dataset.class_names}, features.dataset.taxonomy_version,
                       features.feature_schema, config, features.encoder,
                       {"trained_at_unix": time.time(), "label_policy": features.dataset.label_policy})


def _scores(model: ModelBundle, x: Any) -> np.ndarray:
    if model.experiment != "catboost_structured":
        return np.asarray(model.estimator.predict_proba(x))
    columns = []
    for estimator in model.estimator:
        if isinstance(estimator, dict):
            columns.append(np.full(len(x), estimator["constant"], dtype=float))
        else:
            columns.append(np.asarray(estimator.predict_proba(x))[:, 1])
    return np.column_stack(columns)


def _thresholds(y_true: np.ndarray, scores: np.ndarray, classes: list[str]) -> dict[str, float]:
    from sklearn.metrics import f1_score
    result = {}
    for i, label in enumerate(classes):
        if y_true[:, i].sum() == 0:
            result[label] = 0.5
            continue
        candidates = np.arange(0.20, 0.81, 0.05)
        values = [f1_score(y_true[:, i], scores[:, i] >= value, zero_division=0) for value in candidates]
        result[label] = float(candidates[int(np.argmax(values))])
    return result


def validate(model: ModelBundle, features: FeatureBundle) -> ValidationResult:
    """Select per-class thresholds on validation only and update model thresholds."""
    scores = _scores(model, features.x_by_split["validation"])
    y_true = features.y_by_split["validation"]
    thresholds = _thresholds(y_true, scores, model.class_names)
    model.thresholds = thresholds
    pred = scores >= np.array([thresholds[x] for x in model.class_names])
    metrics = compute_metrics(y_true, pred, scores, model.class_names)
    return ValidationResult(thresholds, metrics, {label: int(y_true[:, i].sum()) for i, label in enumerate(model.class_names)})


def evaluate(model: ModelBundle, features: FeatureBundle, split: str = "test") -> EvaluationResult:
    """Evaluate without threshold tuning; test data is never used by `validate()`."""
    if split not in features.x_by_split:
        raise ValueError(f"Unknown split: {split}")
    scores = _scores(model, features.x_by_split[split])
    y_true = features.y_by_split[split]
    pred = scores >= np.array([model.thresholds[x] for x in model.class_names])
    ids = features.ids_by_split[split].astype(int).tolist()
    subset = features.dataset.frame[features.dataset.frame.product_id.isin(ids)]
    provenance = "verified_gold" if len(subset) and subset.is_verified.all() else "weak_or_mixed_provisional"
    return EvaluationResult(split, compute_metrics(y_true, pred, scores, model.class_names), ids,
                            y_true, pred.astype(int), scores, provenance)


def _dependency_versions() -> dict[str, str]:
    result = {"python": platform.python_version()}
    for package in ["numpy", "pandas", "scikit-learn", "joblib", "catboost", "sentence-transformers"]:
        try: result[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError: result[package] = "not-installed"
    return result


def save_model(model: ModelBundle, artifact_dir: Path, validation: ValidationResult | None = None,
               evaluation: EvaluationResult | None = None) -> None:
    """Create portable artifact folder. Existing non-empty folders are rejected."""
    artifact_dir.mkdir(parents=True, exist_ok=True)
    if any(artifact_dir.iterdir()):
        raise FileExistsError(f"Artifact directory is not empty: {artifact_dir}")
    metadata = {"format_version": 1, "experiment": model.experiment, "taxonomy_version": model.taxonomy_version,
                "class_names": model.class_names, "feature_schema": model.feature_schema,
                "training_config": asdict(model.training_config), "metadata": model.metadata}
    (artifact_dir / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    (artifact_dir / "training_config.json").write_text(json.dumps(asdict(model.training_config), ensure_ascii=False, indent=2), encoding="utf-8")
    (artifact_dir / "taxonomy.json").write_text(json.dumps({"version": model.taxonomy_version,
        "class_names": model.class_names}, ensure_ascii=False, indent=2), encoding="utf-8")
    (artifact_dir / "thresholds.json").write_text(json.dumps(model.thresholds, indent=2), encoding="utf-8")
    (artifact_dir / "label_mapping.json").write_text(json.dumps({str(i): x for i, x in enumerate(model.class_names)}, indent=2), encoding="utf-8")
    (artifact_dir / "preprocessing.json").write_text(json.dumps(model.preprocessor if isinstance(model.preprocessor, dict)
        else {"type": type(model.preprocessor).__name__}, ensure_ascii=False, indent=2), encoding="utf-8")
    (artifact_dir / "dependency_versions.json").write_text(json.dumps(_dependency_versions(), indent=2), encoding="utf-8")
    if validation:
        (artifact_dir / "validation_metrics.json").write_text(json.dumps(validation.metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    if evaluation:
        (artifact_dir / "test_metrics.json").write_text(json.dumps({**evaluation.metrics, "label_provenance": evaluation.label_provenance}, ensure_ascii=False, indent=2), encoding="utf-8")
    if model.experiment == "catboost_structured":
        models_dir = artifact_dir / "models"; models_dir.mkdir()
        constants = {}
        for i, estimator in enumerate(model.estimator):
            if isinstance(estimator, dict): constants[str(i)] = estimator["constant"]
            else: estimator.save_model(models_dir / f"class_{i}.cbm")
        (artifact_dir / "constants.json").write_text(json.dumps(constants), encoding="utf-8")
    else:
        joblib.dump(model.estimator, artifact_dir / "estimator.joblib")
        if model.experiment == "tfidf_logreg":
            joblib.dump(model.preprocessor, artifact_dir / "vectorizer.joblib")
        elif model.experiment == "embeddings_logreg" and model.encoder is not None and hasattr(model.encoder, "save"):
            model.encoder.save(str(artifact_dir / "sentence_encoder"))


def load_model(artifact_dir: Path, expected_taxonomy_version: str, trusted: bool = False,
               encoder: SentenceEncoder | None = None) -> ModelBundle:
    """Load only explicitly trusted local artifacts and validate taxonomy/schema."""
    if not trusted:
        raise PermissionError("Refusing to load serialized artifacts without trusted=True")
    required = ["metadata.json", "thresholds.json", "label_mapping.json", "preprocessing.json"]
    missing = [name for name in required if not (artifact_dir / name).exists()]
    if missing:
        raise FileNotFoundError(f"Missing model artifacts: {missing}")
    metadata = json.loads((artifact_dir / "metadata.json").read_text())
    if metadata["taxonomy_version"] != expected_taxonomy_version:
        raise ValueError(f"Taxonomy mismatch: {metadata['taxonomy_version']} != {expected_taxonomy_version}")
    expected_schema = STRUCTURED_SCHEMA if metadata["experiment"] == "catboost_structured" else ["text"]
    if metadata["feature_schema"] != expected_schema:
        raise ValueError(f"Feature schema mismatch: {metadata['feature_schema']} != {expected_schema}")
    class_map = json.loads((artifact_dir / "label_mapping.json").read_text())
    classes = [class_map[str(i)] for i in range(len(class_map))]
    if classes != metadata["class_names"]:
        raise ValueError("Class order mismatch in artifact")
    config = TrainingConfig(**metadata["training_config"])
    preprocessing = json.loads((artifact_dir / "preprocessing.json").read_text())
    if metadata["experiment"] == "catboost_structured":
        from catboost import CatBoostClassifier
        constants = json.loads((artifact_dir / "constants.json").read_text())
        estimators = []
        for i in range(len(classes)):
            if str(i) in constants: estimators.append({"constant": constants[str(i)]})
            else:
                path = artifact_dir / "models" / f"class_{i}.cbm"
                if not path.exists(): raise FileNotFoundError(path)
                model = CatBoostClassifier(); model.load_model(path); estimators.append(model)
    else:
        path = artifact_dir / "estimator.joblib"
        if not path.exists(): raise FileNotFoundError(path)
        estimators = joblib.load(path)
        if metadata["experiment"] == "tfidf_logreg":
            vectorizer = artifact_dir / "vectorizer.joblib"
            if not vectorizer.exists(): raise FileNotFoundError(vectorizer)
            preprocessing = joblib.load(vectorizer)
        elif encoder is None:
            local_encoder = artifact_dir / "sentence_encoder"
            encoder = _load_sentence_encoder(str(local_encoder) if local_encoder.exists() else config.embedding_model,
                                             "cuda" if config.use_gpu else "cpu")
    return ModelBundle(metadata["experiment"], estimators, preprocessing, classes,
        json.loads((artifact_dir / "thresholds.json").read_text()), metadata["taxonomy_version"],
        metadata["feature_schema"], config, encoder, metadata.get("metadata", {}))


def _products_frame(products: Sequence[ProductInput]) -> pd.DataFrame:
    rows = []
    for product in products:
        if not product.name.strip(): raise ValueError("Product name is required")
        rows.append({"product_id": product.product_id, "name": product.name,
            "source_category": product.source_category, "description": product.description,
            "description_clean": product.description, "marketing_description_clean": product.marketing_description,
            "important_attributes_json": json.dumps(product.characteristics, ensure_ascii=False),
            "price": product.price or 0.0, "sale_unit": product.sale_unit, "brand_name": product.brand_name,
            "characteristic_count": len(product.characteristics),
            "information_completeness": sum(bool(x) for x in [product.name, product.source_category,
                product.description, product.characteristics, product.sale_unit]) / 5})
    frame = pd.DataFrame(rows)
    from .data import product_text
    frame["text"] = frame.apply(product_text, axis=1)
    return frame


def predict(model: ModelBundle, products: ProductBatch) -> Prediction | list[Prediction]:
    """Predict a single product or batch; thresholds and class order come from artifact."""
    single = isinstance(products, ProductInput)
    batch = [products] if single else list(products)
    if not batch: return []
    frame = _products_frame(batch)
    if model.experiment == "tfidf_logreg": x = model.preprocessor.transform(frame.text)
    elif model.experiment == "embeddings_logreg":
        if model.encoder is None: raise RuntimeError("Embedding encoder is unavailable")
        x = np.asarray(model.encoder.encode(frame.text.tolist(), batch_size=64, show_progress_bar=False,
                                            normalize_embeddings=True))
    else: x = _structured_frame(frame)
    scores = _scores(model, x)
    thresholds = np.array([model.thresholds[x] for x in model.class_names])
    output = []
    for product, row in zip(batch, scores):
        values = {label: float(score) for label, score in zip(model.class_names, row)}
        labels = [label for label, score, threshold in zip(model.class_names, row, thresholds) if score >= threshold]
        output.append(Prediction(product.product_id, labels, values, "predicted" if labels else "unknown"))
    return output[0] if single else output

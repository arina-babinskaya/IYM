#!/usr/bin/env python3
"""Fixed sentence embeddings + logistic regression; no encoder fine-tuning."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Protocol

import joblib
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.multiclass import OneVsRestClassifier
from sklearn.preprocessing import MultiLabelBinarizer

from common import best_thresholds, evaluate, prepare_work_dataset


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


class Encoder(Protocol):
    def encode(self, texts: list[str], **kwargs) -> np.ndarray: ...


def load_encoder(model_name: str) -> Encoder:
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise RuntimeError("sentence-transformers is optional and not installed; install a CPU-compatible build explicitly") from exc
    # This call may download model weights. It occurs only when the user runs the experiment.
    return SentenceTransformer(model_name, device="cpu")


def encode_cached(encoder: Encoder, texts: list[str], ids: list[int], cache: Path) -> np.ndarray:
    cache.parent.mkdir(parents=True, exist_ok=True)
    ids_path = cache.with_suffix(".ids.json")
    if cache.exists() and ids_path.exists() and json.loads(ids_path.read_text()) == ids:
        return np.load(cache)
    values = np.asarray(encoder.encode(texts, batch_size=64, show_progress_bar=True, normalize_embeddings=True))
    np.save(cache, values)
    ids_path.write_text(json.dumps(ids), encoding="utf-8")
    return values


def train(clean: Path, labels: Path, output: Path, allow_weak_labels: bool,
          model_name: str = DEFAULT_MODEL, encoder: Encoder | None = None) -> dict:
    started = time.perf_counter()
    data = prepare_work_dataset(clean, labels, allow_weak_labels)
    classes = sorted({label for values in data.labels for label in values})
    mlb = MultiLabelBinarizer(classes=classes)
    y = mlb.fit_transform(data.labels)
    encoder = encoder or load_encoder(model_name)
    embedding_started = time.perf_counter()
    x = encode_cached(encoder, data.text.tolist(), data.product_id.astype(int).tolist(), output / "embeddings.npy")
    embedding_seconds = time.perf_counter() - embedding_started
    train_mask, val_mask, test_mask = (data.split == "train"), (data.split == "validation"), (data.split == "test")
    model = OneVsRestClassifier(LogisticRegression(max_iter=500, class_weight="balanced", solver="liblinear"), n_jobs=1)
    model.fit(x[train_mask], y[train_mask])
    thresholds = best_thresholds(y[val_mask], model.predict_proba(x[val_mask]), classes)
    metrics = evaluate(y[test_mask], model.predict_proba(x[test_mask]), classes, thresholds)
    metrics.update({"embedding_model": model_name, "embedding_seconds": embedding_seconds,
                    "elapsed_seconds": time.perf_counter() - started,
                    "label_source": "weak_unverified" if allow_weak_labels else "manually_reviewed",
                    "agreement_not_ground_truth": bool(allow_weak_labels), "train_size": int(train_mask.sum()),
                    "validation_size": int(val_mask.sum()), "test_size": int(test_mask.sum())})
    output.mkdir(parents=True, exist_ok=True)
    joblib.dump({"classifier": model, "classes": classes, "thresholds": thresholds,
                 "embedding_model": model_name}, output / "classifier.joblib")
    data[["product_id", "leakage_group", "split"]].to_csv(output / "splits.csv", index=False)
    (output / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    (output / "config.json").write_text(json.dumps({"embedding_model": model_name, "fine_tuned": False,
                                                     "device": "cpu", "seed": 20261022}, indent=2), encoding="utf-8")
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--clean", type=Path, default=ROOT / "ml_workspace/data/products_clean.csv")
    parser.add_argument("--labels", type=Path, default=ROOT / "ml_workspace/data/products_multidim_weak_labeled.csv")
    parser.add_argument("--output", type=Path, default=ROOT / "ml_workspace/artifacts/experiment_2")
    parser.add_argument("--model-name", default=DEFAULT_MODEL)
    parser.add_argument("--allow-weak-labels", action="store_true")
    args = parser.parse_args()
    print(json.dumps(train(args.clean, args.labels, args.output, args.allow_weak_labels, args.model_name), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

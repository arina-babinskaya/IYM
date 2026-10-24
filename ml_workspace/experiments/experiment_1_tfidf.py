#!/usr/bin/env python3
"""TF-IDF + One-vs-Rest Logistic Regression work-type pilot."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import joblib
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.multiclass import OneVsRestClassifier
from sklearn.preprocessing import MultiLabelBinarizer

from common import best_thresholds, evaluate, prepare_work_dataset


ROOT = Path(__file__).resolve().parents[2]


def train(clean: Path, labels: Path, output: Path, allow_weak_labels: bool, max_features: int = 80000) -> dict:
    started = time.perf_counter()
    data = prepare_work_dataset(clean, labels, allow_weak_labels)
    classes = sorted({label for values in data.labels for label in values})
    encoder = MultiLabelBinarizer(classes=classes)
    y = encoder.fit_transform(data.labels)
    train_mask, val_mask, test_mask = (data.split == "train"), (data.split == "validation"), (data.split == "test")
    vectorizer = TfidfVectorizer(ngram_range=(1, 2), min_df=2, max_df=0.98, max_features=max_features,
                                 sublinear_tf=True, strip_accents=None)
    x_train = vectorizer.fit_transform(data.loc[train_mask, "text"])
    model = OneVsRestClassifier(LogisticRegression(max_iter=500, class_weight="balanced", solver="liblinear"), n_jobs=1)
    model.fit(x_train, y[train_mask])
    val_scores = model.predict_proba(vectorizer.transform(data.loc[val_mask, "text"]))
    thresholds = best_thresholds(y[val_mask], val_scores, classes)
    test_scores = model.predict_proba(vectorizer.transform(data.loc[test_mask, "text"]))
    metrics = evaluate(y[test_mask], test_scores, classes, thresholds)
    metrics.update({"label_source": "weak_unverified" if allow_weak_labels else "manually_reviewed",
                    "agreement_not_ground_truth": bool(allow_weak_labels), "train_size": int(train_mask.sum()),
                    "validation_size": int(val_mask.sum()), "test_size": int(test_mask.sum()),
                    "elapsed_seconds": time.perf_counter() - started})
    output.mkdir(parents=True, exist_ok=True)
    joblib.dump({"vectorizer": vectorizer, "model": model, "classes": classes, "thresholds": thresholds}, output / "model.joblib")
    data[["product_id", "leakage_group", "split"]].to_csv(output / "splits.csv", index=False)
    (output / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    (output / "config.json").write_text(json.dumps({"max_features": max_features, "seed": 20261022,
                                                     "allow_weak_labels": allow_weak_labels}, indent=2), encoding="utf-8")
    return metrics


def predict(model_path: Path, texts: list[str]) -> list[dict[str, float]]:
    bundle = joblib.load(model_path)
    scores = bundle["model"].predict_proba(bundle["vectorizer"].transform(texts))
    return [{label: float(score) for label, score in zip(bundle["classes"], row)
             if score >= bundle["thresholds"][label]} for row in scores]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--clean", type=Path, default=ROOT / "ml_workspace/data/products_clean.csv")
    parser.add_argument("--labels", type=Path, default=ROOT / "ml_workspace/data/products_multidim_weak_labeled.csv")
    parser.add_argument("--output", type=Path, default=ROOT / "ml_workspace/artifacts/experiment_1")
    parser.add_argument("--allow-weak-labels", action="store_true")
    parser.add_argument("--max-features", type=int, default=80000)
    args = parser.parse_args()
    print(json.dumps(train(args.clean, args.labels, args.output, args.allow_weak_labels, args.max_features), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

"""Shared leakage-aware data utilities for work-type experiments."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd


def product_text(row: pd.Series) -> str:
    attrs = row.get("important_attributes_json", "")
    return " | ".join(str(x) for x in [row.get("name", ""), row.get("source_category", ""),
                      row.get("description_clean", ""), row.get("marketing_description_clean", ""), attrs] if x)


def leakage_group(row: pd.Series) -> str:
    # Exact and near-exact duplicated cards must remain in one split.
    value = re.sub(r"\d+(?:[.,]\d+)?", "#", product_text(row).lower())
    value = re.sub(r"\s+", " ", value).strip()
    return hashlib.sha256(value.encode()).hexdigest()


def split_name(group: str) -> str:
    bucket = int(group[:8], 16) % 100
    return "train" if bucket < 70 else "validation" if bucket < 85 else "test"


def prepare_work_dataset(clean_path: Path, labels_path: Path, allow_weak_labels: bool) -> pd.DataFrame:
    clean = pd.read_csv(clean_path, keep_default_na=False, dtype={"cod_good": "string"})
    labels = pd.read_csv(labels_path, keep_default_na=False)
    if "review_status" not in labels:
        raise ValueError("Labels require review_status")
    if not allow_weak_labels:
        labels = labels[labels.review_status == "reviewed"]
        if labels.empty:
            raise ValueError("No reviewed annotations. Use --allow-weak-labels only for a technical pilot.")
    data = clean.merge(labels[["product_id", "proposed_work_types", "review_status"]], on="product_id", validate="one_to_one")
    data["labels"] = data.proposed_work_types.map(json.loads)
    data = data[data.labels.map(bool)].copy()
    data["text"] = data.apply(product_text, axis=1)
    data["leakage_group"] = data.apply(leakage_group, axis=1)
    data["split"] = data.leakage_group.map(split_name)
    return data


def best_thresholds(y_true: np.ndarray, scores: np.ndarray, classes: list[str]) -> dict[str, float]:
    from sklearn.metrics import f1_score
    result = {}
    for index, label in enumerate(classes):
        if y_true[:, index].sum() == 0:
            result[label] = 0.5
            continue
        candidates = np.arange(0.20, 0.81, 0.05)
        values = [f1_score(y_true[:, index], scores[:, index] >= threshold, zero_division=0) for threshold in candidates]
        result[label] = float(candidates[int(np.argmax(values))])
    return result


def evaluate(y_true: np.ndarray, scores: np.ndarray, classes: list[str], thresholds: dict[str, float]) -> dict:
    from sklearn.metrics import f1_score, precision_score, recall_score
    cutoffs = np.array([thresholds[x] for x in classes])
    pred = scores >= cutoffs
    per_class = {}
    for i, label in enumerate(classes):
        per_class[label] = {
            "support": int(y_true[:, i].sum()),
            "precision": float(precision_score(y_true[:, i], pred[:, i], zero_division=0)),
            "recall": float(recall_score(y_true[:, i], pred[:, i], zero_division=0)),
            "f1": float(f1_score(y_true[:, i], pred[:, i], zero_division=0)),
            "threshold": thresholds[label],
        }
    return {
        "micro_f1": float(f1_score(y_true, pred, average="micro", zero_division=0)),
        "macro_f1": float(f1_score(y_true, pred, average="macro", zero_division=0)),
        "micro_precision": float(precision_score(y_true, pred, average="micro", zero_division=0)),
        "micro_recall": float(recall_score(y_true, pred, average="micro", zero_division=0)),
        "per_class": per_class,
    }

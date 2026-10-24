from __future__ import annotations

from typing import Any

import numpy as np
from sklearn.metrics import (accuracy_score, average_precision_score, f1_score,
    hamming_loss, precision_recall_fscore_support, precision_score, recall_score, roc_auc_score)


def compute_metrics(y_true: np.ndarray, y_pred: np.ndarray, y_score: np.ndarray | None = None,
                    class_names: list[str] | None = None, top_k: int = 3) -> dict[str, Any]:
    """Compute multi-label metrics for arrays shaped `(n_samples, n_classes)`.

    Undefined per-class PR/ROC AUC is represented as `None`; classes are never dropped.
    Empty-label samples remain in subset accuracy/hamming/samples-F1 (`zero_division=0`).
    """
    y_true, y_pred = np.asarray(y_true, dtype=int), np.asarray(y_pred, dtype=int)
    if y_true.shape != y_pred.shape or y_true.ndim != 2:
        raise ValueError("y_true and y_pred must have identical 2D shapes")
    names = class_names or [str(i) for i in range(y_true.shape[1])]
    if len(names) != y_true.shape[1]:
        raise ValueError("class_names order/length does not match matrices")
    result = {}
    for average in ["micro", "macro"]:
        result[f"{average}_precision"] = float(precision_score(y_true, y_pred, average=average, zero_division=0))
        result[f"{average}_recall"] = float(recall_score(y_true, y_pred, average=average, zero_division=0))
        result[f"{average}_f1"] = float(f1_score(y_true, y_pred, average=average, zero_division=0))
    result.update({"weighted_f1": float(f1_score(y_true, y_pred, average="weighted", zero_division=0)),
                   "samples_f1": float(f1_score(y_true, y_pred, average="samples", zero_division=0)),
                   "subset_accuracy": float(accuracy_score(y_true, y_pred)),
                   "hamming_loss": float(hamming_loss(y_true, y_pred)), "n_samples": int(len(y_true))})
    precision, recall, f1, support = precision_recall_fscore_support(y_true, y_pred, average=None, zero_division=0)
    per_class = {}
    for i, name in enumerate(names):
        item: dict[str, Any] = {"precision": float(precision[i]), "recall": float(recall[i]),
                                "f1": float(f1[i]), "support": int(support[i]),
                                "undefined_reason": None}
        if y_score is not None:
            positives = int(y_true[:, i].sum())
            negatives = len(y_true) - positives
            if positives == 0:
                item.update({"pr_auc": None, "roc_auc": None, "undefined_reason": "no_positive_examples"})
            else:
                item["pr_auc"] = float(average_precision_score(y_true[:, i], y_score[:, i]))
                item["roc_auc"] = float(roc_auc_score(y_true[:, i], y_score[:, i])) if negatives else None
                if not negatives:
                    item["undefined_reason"] = "no_negative_examples_for_roc_auc"
        per_class[name] = item
    result["per_class"] = per_class
    if y_score is not None and len(y_true):
        k = min(top_k, y_true.shape[1])
        top = np.argsort(-y_score, axis=1)[:, :k]
        hits = np.array([y_true[i, indexes].sum() for i, indexes in enumerate(top)], dtype=float)
        result[f"precision_at_{k}"] = float(np.mean(hits / k))
        positives = y_true.sum(axis=1)
        result[f"recall_at_{k}"] = float(np.mean(np.divide(hits, positives, out=np.zeros_like(hits), where=positives > 0)))
        defined_pr_auc = [item.get("pr_auc") for item in per_class.values() if item.get("pr_auc") is not None]
        result["macro_pr_auc"] = float(np.mean(defined_pr_auc)) if defined_pr_auc else None
    return result

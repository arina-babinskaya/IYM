from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .types import EvaluationResult, ModelBundle


def save_evaluation_outputs(result: EvaluationResult, model: ModelBundle, output_dir: Path) -> None:
    """Save multi-label plots/tables; never creates a misleading multiclass confusion matrix."""
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = [{"class": label, **values} for label, values in result.metrics["per_class"].items()]
    table = pd.DataFrame(rows)
    table.to_csv(output_dir / "per_class_metrics.csv", index=False)
    for columns, filename, title in [(["precision", "recall", "f1"], "per_class_scores.png", "Метрики по классам"),
                                      (["support"], "class_support.png", "Поддержка классов")]:
        ax = table.set_index("class")[columns].plot.bar(figsize=(14, 6))
        ax.set_title(title); ax.set_ylabel("Значение"); plt.tight_layout()
        plt.savefig(output_dir / filename, dpi=140); plt.close()
    counts = pd.DataFrame({"actual": result.y_true.sum(axis=1), "predicted": result.y_pred.sum(axis=1)})
    ax = counts.plot.hist(alpha=.6, bins=range(int(max(counts.max())) + 2), figsize=(8, 5))
    ax.set_title("Распределение числа меток"); plt.tight_layout(); plt.savefig(output_dir / "label_count_distribution.png", dpi=140); plt.close()
    errors = []
    for i, product_id in enumerate(result.product_ids):
        for j, label in enumerate(model.class_names):
            if result.y_true[i, j] != result.y_pred[i, j]:
                errors.append({"product_id": product_id, "class": label,
                               "error": "false_positive" if result.y_pred[i, j] else "false_negative",
                               "score": result.y_score[i, j]})
    pd.DataFrame(errors, columns=["product_id", "class", "error", "score"]).to_csv(output_dir / "errors.csv", index=False)

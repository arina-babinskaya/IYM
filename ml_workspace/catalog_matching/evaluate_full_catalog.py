"""Reproducible name-only evaluation of the trained classifier on the full catalog."""
from __future__ import annotations

import argparse
import csv
import json
import math
import resource
import statistics
import time
from collections import Counter
from pathlib import Path

import numpy as np
from sklearn.metrics import classification_report, confusion_matrix, precision_recall_fscore_support

from .inference.predictor import CatalogPredictor
from .preprocessing.catalog_parser import clean_text, iter_products, source_category

FIELDS = [
    "product_id", "name", "source_category", "predicted_category_id", "predicted_category_name",
    "top_1_score", "top_3_category_ids", "top_3_category_names", "top_3_scores",
    "review_recommended", "had_confident_weak_label", "previous_weak_label_category",
    "weak_label_agreement", "original_review_reason", "manual_review_priority", "inference_error",
]


def load_weak_labels(split_dir: Path) -> dict[str, dict[str, str]]:
    rows: dict[str, dict[str, str]] = {}
    for name in ("train.csv", "validation.csv", "test.csv", "review_queue.csv"):
        with (split_dir / name).open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                row["dataset_partition"] = name.removesuffix(".csv")
                rows[row["product_id"]] = row
    return rows


def priority(score: float, margin: float, unresolved: bool, disagreement: bool) -> str:
    if unresolved and (score < .35 or margin < .10):
        return "critical_unresolved"
    if unresolved:
        return "high_unresolved"
    if disagreement and score >= .80:
        return "high_suspicious_confident_disagreement"
    if disagreement or score < .35 or margin < .10:
        return "medium"
    return "routine"


def evaluate(args: argparse.Namespace) -> dict:
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    predictor = CatalogPredictor(args.artifact, require_full_taxonomy=True)
    labels = load_weak_labels(Path(args.splits))
    products = list(iter_products(args.catalog))
    category_ids = sorted(str(item) for item in predictor.model.classes_)
    names = predictor.names
    predicted_frequency: Counter[str] = Counter()
    score_bins: Counter[str] = Counter()
    rows_for_metrics: dict[str, list[tuple[str, str, list[str]]]] = {
        "train": [], "validation": [], "test": [], "full_labeled": []
    }
    unresolved_rows: list[dict] = []
    review_candidates: list[tuple[tuple, dict]] = []
    batch_latencies: list[float] = []
    errors = 0
    empty_names = 0
    successful = 0
    started = time.perf_counter()
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        for offset in range(0, len(products), args.batch_size):
            batch = products[offset:offset + args.batch_size]
            valid = [(index, clean_text(product.get("name"))) for index, product in enumerate(batch)]
            names_batch = [name for _, name in valid if name]
            empty_names += sum(not name for _, name in valid)
            batch_started = time.perf_counter()
            try:
                predictions = iter(predictor.predict_batch(names_batch, top_k=3))
                batch_error = ""
            except Exception as exc:  # preserve one output row per catalog item
                predictions = iter(())
                batch_error = f"{type(exc).__name__}: {exc}"
            batch_latencies.append(time.perf_counter() - batch_started)
            for product, (_, product_name) in zip(batch, valid, strict=True):
                product_id = str(product.get("id", ""))
                weak = labels.get(product_id, {})
                confident = weak.get("supervised_eligible") == "True"
                source_name = source_category(product)[1]
                error = ""
                prediction = None
                if not product_name:
                    error = "empty product name"
                elif batch_error:
                    error = batch_error
                else:
                    prediction = next(predictions)
                if prediction is None:
                    errors += 1
                    writer.writerow({
                        "product_id": product_id, "name": product_name, "source_category": source_name,
                        "had_confident_weak_label": confident,
                        "previous_weak_label_category": weak.get("target_category_id", "") if confident else "",
                        "original_review_reason": weak.get("review_reason", ""), "inference_error": error,
                    })
                    continue
                successful += 1
                top = [(prediction.category_id, prediction.category_name, prediction.confidence), *[
                    (item.category_id, item.category_name, item.confidence) for item in prediction.alternatives
                ]]
                top_ids = [item[0] for item in top]
                score = prediction.confidence
                margin = score - (top[1][2] if len(top) > 1 else 0.0)
                agreement = prediction.category_id == weak.get("target_category_id") if confident else None
                unresolved = not confident
                review_priority = priority(score, margin, unresolved, bool(confident and not agreement))
                predicted_frequency[prediction.category_id] += 1
                bin_low = math.floor(score * 10) / 10
                score_bins[f"{bin_low:.1f}-{min(1.0, bin_low + .1):.1f}"] += 1
                if confident:
                    record = (weak["target_category_id"], prediction.category_id, top_ids)
                    rows_for_metrics[weak["dataset_partition"]].append(record)
                    rows_for_metrics["full_labeled"].append(record)
                row = {
                    "product_id": product_id, "name": product_name, "source_category": source_name,
                    "predicted_category_id": prediction.category_id,
                    "predicted_category_name": prediction.category_name, "top_1_score": f"{score:.12f}",
                    "top_3_category_ids": "|".join(top_ids),
                    "top_3_category_names": "|".join(item[1] for item in top),
                    "top_3_scores": "|".join(f"{item[2]:.12f}" for item in top),
                    "review_recommended": prediction.needs_review,
                    "had_confident_weak_label": confident,
                    "previous_weak_label_category": weak.get("target_category_id", "") if confident else "",
                    "weak_label_agreement": agreement if agreement is not None else "",
                    "original_review_reason": weak.get("review_reason", ""),
                    "manual_review_priority": review_priority, "inference_error": "",
                }
                writer.writerow(row)
                sample_row = dict(row, top_1_top_2_margin=f"{margin:.12f}")
                if unresolved:
                    unresolved_rows.append(sample_row)
                rank = 0 if review_priority == "critical_unresolved" else 1 if unresolved else 2
                review_candidates.append(((rank, margin, score if unresolved else -score), sample_row))

    elapsed = time.perf_counter() - started
    metrics = {}
    for partition, records in rows_for_metrics.items():
        truth = [item[0] for item in records]
        predicted = [item[1] for item in records]
        top3 = [item[2] for item in records]
        macro = precision_recall_fscore_support(truth, predicted, average="macro", zero_division=0)
        weighted = precision_recall_fscore_support(truth, predicted, average="weighted", zero_division=0)
        metrics[partition] = {
            "count": len(records),
            "agreement": float(np.mean(np.asarray(truth) == np.asarray(predicted))),
            "macro_precision": float(macro[0]), "macro_recall": float(macro[1]),
            "macro_f1": float(macro[2]), "weighted_f1": float(weighted[2]),
            "top_3_accuracy": float(np.mean([actual in choices for actual, choices in zip(truth, top3)])),
        }
    full = rows_for_metrics["full_labeled"]
    truth = [item[0] for item in full]
    predicted = [item[1] for item in full]
    report = classification_report(truth, predicted, labels=category_ids, target_names=category_ids,
                                   output_dict=True, zero_division=0)
    with output.with_name("full_catalog_per_category_v2.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["category_id", "category_name", "precision", "recall", "f1", "support"])
        writer.writeheader()
        for category_id in category_ids:
            item = report[category_id]
            writer.writerow({"category_id": category_id, "category_name": names[category_id],
                             "precision": item["precision"], "recall": item["recall"],
                             "f1": item["f1-score"], "support": int(item["support"])})
    matrix = confusion_matrix(truth, predicted, labels=category_ids)
    with output.with_name("full_catalog_confusion_matrix_v2.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle); writer.writerow(["actual\\predicted", *category_ids])
        for category_id, values in zip(category_ids, matrix, strict=True): writer.writerow([category_id, *values])
    unresolved_fields = [*FIELDS, "top_1_top_2_margin"]
    with output.with_name("unresolved_predictions_v2.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=unresolved_fields); writer.writeheader(); writer.writerows(unresolved_rows)
    candidates = [item[1] for item in review_candidates]
    ambiguous_unresolved = sorted(
        (row for row in candidates if row["had_confident_weak_label"] is False),
        key=lambda row: (float(row["top_1_top_2_margin"]), float(row["top_1_score"])),
    )
    low_score_unresolved = sorted(
        (row for row in candidates if row["had_confident_weak_label"] is False),
        key=lambda row: float(row["top_1_score"]),
    )
    suspicious_disagreements = sorted(
        (row for row in candidates if row["weak_label_agreement"] is False),
        key=lambda row: -float(row["top_1_score"]),
    )
    sample = []
    seen: set[str] = set()
    for pool, limit in ((ambiguous_unresolved, 100), (low_score_unresolved, 25),
                        (suspicious_disagreements, 25)):
        added = 0
        for row in pool:
            if row["product_id"] in seen:
                continue
            sample.append(row); seen.add(row["product_id"]); added += 1
            if added == limit:
                break
    for row in ambiguous_unresolved:
        if len(sample) >= max(150, args.review_sample_size):
            break
        if row["product_id"] not in seen:
            sample.append(row); seen.add(row["product_id"])
    with output.with_name("manual_review_sample_v2.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=unresolved_fields); writer.writeheader(); writer.writerows(sample)
    summary = {
        "catalog_products": len(products), "successful_predictions": successful,
        "failed_predictions": errors, "missing_or_empty_names": empty_names,
        "elapsed_seconds": elapsed, "products_per_second": len(products) / elapsed,
        "batch_size": args.batch_size, "batch_count": len(batch_latencies),
        "batch_latency_seconds": {"mean": statistics.mean(batch_latencies),
                                  "p95": float(np.percentile(batch_latencies, 95)),
                                  "max": max(batch_latencies)},
        "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "prediction_frequency": dict(predicted_frequency.most_common()),
        "score_distribution": dict(sorted(score_bins.items())),
        "diagnostic_weak_label_metrics": metrics,
        "unresolved": {"expected": 8919, "found": len(unresolved_rows),
                       "valid_predictions": sum(not row["inference_error"] for row in unresolved_rows)},
        "artifact": str(args.artifact), "feature_mode": predictor.metadata["input_schema"]["feature_mode"],
    }
    output.with_name("full_catalog_evaluation_summary_v2.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", default="requirments/products_final.json")
    parser.add_argument("--artifact", default="ml_workspace/catalog_matching/data/artifact")
    parser.add_argument("--splits", default="ml_workspace/catalog_matching/data/splits_v2")
    parser.add_argument("--output", default="ml_workspace/catalog_matching/reports/full_catalog_predictions_v2.csv")
    parser.add_argument("--batch-size", type=int, default=1024)
    parser.add_argument("--review-sample-size", type=int, default=150)
    args = parser.parse_args()
    print(json.dumps(evaluate(args), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

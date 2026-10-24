"""Build reproducible, group-isolated, multi-label-stratified dataset v3."""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ml_workspace.ml_api.feature_schema import FEATURE_COLUMNS, build_input_text
from ml_workspace.scripts.build_taxonomy_v1_dataset import duplicate_group
from ml_workspace.scripts.weak_labeling_v3 import LABELING_RULE_VERSION, label_product, serialize_labels
from ml_workspace.taxonomy.taxonomy_v2 import ACTIVITIES, PRODUCT_CATEGORIES, ROOM_TYPES, TAXONOMY_VERSION, WORK_IDS

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "ml_workspace/data"
SPLITS = DATA / "splits_v3"
SOURCE = DATA / "products_clean.csv"
CATALOG = ROOT / "requirments/products_final.json"
MASTER = DATA / "products_taxonomy_v3.csv"
DATASET_VERSION = "dataset_v3"
SEED = 20261024
SPLIT_RATIOS = {"train": 0.70, "validation": 0.15, "test": 0.15}
SPLIT_NAMES = tuple(SPLIT_RATIOS)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _seed_hash(value: str, seed: int = SEED) -> str:
    return hashlib.sha256(f"{seed}:{value}".encode()).hexdigest()


def _parsed(value: str) -> list[str]:
    parsed = json.loads(value)
    if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
        raise ValueError(f"Expected JSON list of strings, got {value!r}")
    return parsed


def stratification_features(master: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Aggregate row and independent-group targets used by the deterministic split."""
    work = master.work_types.map(_parsed)
    eligible = master.work_types_valid.astype(bool)
    feature_rows: dict[str, pd.Series] = {
        f"work:{label}": eligible & work.map(lambda values, label=label: label in values)
        for label in WORK_IDS
    }
    feature_rows["work:multi_label"] = eligible & work.map(lambda values: len(values) >= 2)
    combinations = Counter(tuple(sorted(values)) for values in work[eligible] if len(values) >= 2)
    for combination, count in combinations.items():
        if count >= 2:
            name = "combo:" + "+".join(combination)
            feature_rows[name] = eligible & work.map(lambda values, combination=combination: tuple(sorted(values)) == combination)
    rows = pd.DataFrame(feature_rows, index=master.index).astype(np.int32)
    grouped = rows.groupby(master.duplicate_group, sort=False).sum()
    grouped.insert(0, "row_count", master.groupby("duplicate_group", sort=False).size())
    # Group-presence targets make scarcity of independent examples explicit.
    for column in list(feature_rows):
        grouped[f"groups:{column}"] = grouped[column].gt(0).astype(np.int32)
    return grouped, [column for column in grouped if column != "row_count"]


def group_multilabel_split(master: pd.DataFrame, seed: int = SEED) -> pd.Series:
    """Greedy iterative approximation to group-aware multi-label stratification."""
    grouped, features = stratification_features(master)
    totals = grouped[features].sum(axis=0).astype(float)
    targets = {split: totals * ratio for split, ratio in SPLIT_RATIOS.items()}
    row_targets = {split: len(master) * ratio for split, ratio in SPLIT_RATIOS.items()}
    current = {split: pd.Series(0.0, index=features) for split in SPLIT_NAMES}
    current_rows = {split: 0 for split in SPLIT_NAMES}

    group_support_totals = {column: max(float(totals[column]), 1.0) for column in features}

    def order_key(group: str) -> tuple[float, float, str]:
        vector = grouped.loc[group, features]
        present = [group_support_totals[column] for column in features if vector[column] > 0]
        rarity = min(present) if present else float("inf")
        rarity_mass = -sum(float(vector[column]) / group_support_totals[column] for column in features)
        return rarity, rarity_mass, _seed_hash(str(group), seed)

    assignments: dict[str, str] = {}
    for group in sorted(grouped.index.astype(str), key=order_key):
        vector = grouped.loc[group, features].astype(float)
        row_count = int(grouped.loc[group, "row_count"])
        scores: list[tuple[float, str]] = []
        for split in SPLIT_NAMES:
            before = current[split] - targets[split]
            after = current[split] + vector - targets[split]
            # Relative squared error treats rare targets as first-class constraints.
            label_delta = float((((after ** 2 - before ** 2) / targets[split].clip(lower=1.0))).sum())
            row_before = current_rows[split] - row_targets[split]
            row_after = current_rows[split] + row_count - row_targets[split]
            row_delta = 0.20 * (row_after ** 2 - row_before ** 2) / row_targets[split]
            overflow = max(0.0, row_after) / row_targets[split]
            tie = int(_seed_hash(f"{group}:{split}", seed)[:8], 16) / 2**32
            scores.append((label_delta + row_delta + 100.0 * overflow ** 2 + tie * 1e-9, split))
        chosen = min(scores)[1]
        assignments[group] = chosen
        current[chosen] += vector
        current_rows[chosen] += row_count

    result = master.duplicate_group.astype(str).map(assignments)
    if result.isna().any():
        raise RuntimeError("Some duplicate groups were not assigned")
    return result


def _validity(master: pd.DataFrame) -> pd.DataFrame:
    master["domain_valid"] = master.domain_status.eq("known")
    master["activity_valid"] = master.activity_status.eq("known")
    master["product_category_valid"] = master.product_category_status.eq("known")
    master["work_types_valid"] = master.work_types_status.eq("known")
    master["room_types_valid"] = master.room_types_status.eq("known") & master.domain_label.eq("furnishing")
    return master


def build_master() -> tuple[pd.DataFrame, pd.DataFrame]:
    clean = pd.read_csv(SOURCE, keep_default_na=False, low_memory=False)
    if missing := sorted(set(FEATURE_COLUMNS) - set(clean)):
        raise RuntimeError(f"Source schema misses feature allowlist: {missing}")
    generated = pd.DataFrame([serialize_labels(label_product(row)) for _, row in clean.iterrows()])
    master = pd.concat([clean.reset_index(drop=True), generated], axis=1)
    master["input_text"] = [build_input_text(row) for row in clean.to_dict("records")]
    master["structured_input_features"] = clean[FEATURE_COLUMNS].apply(
        lambda row: json.dumps(row.to_dict(), ensure_ascii=False, sort_keys=True), axis=1)
    master["duplicate_group"] = master.apply(duplicate_group, axis=1)
    master = _validity(master)
    first = group_multilabel_split(master, SEED)
    second = group_multilabel_split(master, SEED)
    if not first.equals(second):
        raise RuntimeError("Split generation is not deterministic")
    master["split"] = first

    previous = pd.read_csv(DATA / "products_taxonomy_v2.csv", usecols=["product_id", "work_types"], keep_default_na=False)
    audit = master[["product_id", "name", "source_category", "work_types", "label_evidence"]].merge(
        previous, on="product_id", suffixes=("_v3", "_v2"), validate="one_to_one")
    audit = audit[audit.work_types_v3 != audit.work_types_v2].copy()
    return master, audit


OUTPUT_COLUMNS = [
    "product_id", "cod_good", "name", "source_category", "category_names", "description_clean",
    "marketing_description_clean", "important_attributes_json", "characteristics_json", "brand_name",
    "sale_unit", "price", "characteristic_count", "information_completeness", "input_text",
    "structured_input_features", "domain_label", "activities", "product_category", "work_types",
    "renovation_stages", "room_types", "material_roles", "domain_valid", "activity_valid",
    "product_category_valid", "work_types_valid", "room_types_valid", "label_confidence",
    "label_evidence", "label_conflicts", "label_status", "labeling_method", "taxonomy_version",
    "duplicate_group", "split",
]


def validate(master: pd.DataFrame) -> dict[str, Any]:
    if master.product_id.duplicated().any():
        raise RuntimeError("Duplicate product_id")
    if master.groupby("duplicate_group").split.nunique().max() != 1:
        raise RuntimeError("Duplicate-group leakage")
    if set(master.split) != set(SPLIT_NAMES):
        raise RuntimeError("All three splits are required")
    allowed = set(WORK_IDS)
    invalid = {label for value in master.work_types for label in _parsed(value) if label not in allowed}
    if invalid:
        raise RuntimeError(f"Labels outside taxonomy: {sorted(invalid)}")
    for column in OUTPUT_COLUMNS:
        if column not in master:
            raise RuntimeError(f"Missing required column: {column}")
    serialized = master.work_types.map(_parsed).map(lambda value: json.dumps(value, ensure_ascii=False))
    if not serialized.map(json.loads).equals(master.work_types.map(_parsed)):
        raise RuntimeError("Multi-label serialization round-trip failed")
    return {
        "rows": len(master),
        "split_rows": master.split.value_counts().to_dict(),
        "groups": int(master.duplicate_group.nunique()),
        "cross_split_product_ids": 0,
        "cross_split_groups": 0,
        "invalid_taxonomy_labels": 0,
        "deterministic": True,
        "serialization_round_trip": True,
    }


def write_outputs(master: pd.DataFrame, audit: pd.DataFrame) -> dict[str, Any]:
    checks = validate(master)
    SPLITS.mkdir(parents=True, exist_ok=True)
    master[OUTPUT_COLUMNS].to_csv(MASTER, index=False)
    for split in SPLIT_NAMES:
        master.loc[master.split.eq(split), OUTPUT_COLUMNS].to_csv(SPLITS / f"{split}.csv", index=False)
    manifest = master[["product_id", "cod_good", "duplicate_group", "split", "taxonomy_version"]].copy()
    manifest["dataset_version"] = DATASET_VERSION
    manifest["labeling_rule_version"] = LABELING_RULE_VERSION
    manifest["random_seed"] = SEED
    manifest.to_csv(SPLITS / "split_manifest.csv", index=False)
    audit.to_csv(SPLITS / "label_change_audit.csv", index=False)

    support = []
    for split in SPLIT_NAMES:
        part = master[master.split.eq(split)]
        labels = part.work_types.map(_parsed)
        valid = part.work_types_valid.astype(bool)
        for label in WORK_IDS:
            support.append({"split": split, "target": "work_types", "class": label,
                            "support": int((valid & labels.map(lambda values, label=label: label in values)).sum()),
                            "valid_rows": int(valid.sum())})
    pd.DataFrame(support).to_csv(SPLITS / "class_support.csv", index=False)
    checksums = {path.name: file_sha256(path) for path in sorted(SPLITS.glob("*.csv"))}
    metadata = {
        "dataset_version": DATASET_VERSION,
        "taxonomy_version": TAXONOMY_VERSION,
        "labeling_rule_version": LABELING_RULE_VERSION,
        "split_algorithm": "deterministic_group_aware_greedy_iterative_multilabel_stratification",
        "random_seed": SEED,
        "split_ratios": SPLIT_RATIOS,
        "source_catalog_sha256": file_sha256(CATALOG),
        "prepared_source_sha256": file_sha256(SOURCE),
        "master_sha256": file_sha256(MASTER),
        "file_checksums": checksums,
        **checks,
    }
    (SPLITS / "dataset_manifest.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return metadata


def main() -> None:
    master, audit = build_master()
    print(json.dumps(write_outputs(master, audit), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

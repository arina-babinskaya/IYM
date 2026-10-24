from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Iterable

import pandas as pd

from .types import DatasetBundle, LabelPolicy


def product_text(row: pd.Series) -> str:
    return " | ".join(str(v) for v in [row.get("name", ""), row.get("source_category", ""),
        row.get("description_clean", row.get("description", "")), row.get("marketing_description_clean", ""),
        row.get("important_attributes_json", row.get("characteristics", ""))] if str(v).strip())


def leakage_group(row: pd.Series) -> str:
    text = re.sub(r"\d+(?:[.,]\d+)?", "#", product_text(row).lower())
    text = re.sub(r"[^a-zа-я#]+", " ", text)
    return hashlib.sha256(re.sub(r"\s+", " ", text).strip().encode()).hexdigest()


def deterministic_split(group: str, seed: int) -> str:
    bucket = int(hashlib.sha256(f"{seed}:{group}".encode()).hexdigest()[:8], 16) % 100
    return "train" if bucket < 70 else "validation" if bucket < 85 else "test"


def _read_reviewed(paths: Iterable[Path]) -> pd.DataFrame:
    frames = []
    for path in paths:
        if path.exists():
            frame = pd.read_csv(path, keep_default_na=False, dtype={"cod_good": "string"})
            frame["review_file"] = str(path)
            frames.append(frame)
    if not frames:
        return pd.DataFrame(columns=["product_id", "review_status", "reviewed_work_types"])
    reviewed = pd.concat(frames, ignore_index=True)
    priority = {"approved": 2, "reviewed": 1, "unknown_applicability": 0, "unreviewed": -1}
    reviewed["_priority"] = reviewed.review_status.map(priority).fillna(-1)
    return reviewed.sort_values("_priority").drop_duplicates("product_id", keep="last")


def create_or_load_manifest(frame: pd.DataFrame, path: Path, seed: int, taxonomy_version: str) -> pd.DataFrame:
    proposed = frame[["product_id", "leakage_group"]].drop_duplicates().copy()
    proposed["split"] = proposed.leakage_group.map(lambda value: deterministic_split(value, seed))
    proposed["seed"] = seed
    proposed["taxonomy_version"] = taxonomy_version
    if path.exists():
        existing = pd.read_csv(path, dtype={"leakage_group": "string"})
        overlap = proposed.merge(existing[["product_id", "leakage_group", "split"]], on="product_id", suffixes=("_new", "_old"))
        if (overlap.leakage_group_new != overlap.leakage_group_old).any():
            raise ValueError("Existing split manifest has incompatible leakage groups")
        split_by_group = existing.groupby("leakage_group").split.nunique()
        if split_by_group.max() > 1:
            raise ValueError("Leakage group appears in multiple splits")
        known = existing.set_index("product_id").split
        proposed["split"] = proposed.product_id.map(known).fillna(proposed.split)
    path.parent.mkdir(parents=True, exist_ok=True)
    proposed.to_csv(path, index=False)
    return proposed


def load_training_data(clean_path: Path, weak_labels_path: Path, reviewed_paths: list[Path],
                       split_manifest_path: Path, class_names: list[str], taxonomy_version: str,
                       label_policy: LabelPolicy, random_seed: int) -> DatasetBundle:
    clean = pd.read_csv(clean_path, keep_default_na=False, dtype={"cod_good": "string"})
    weak = pd.read_csv(weak_labels_path, keep_default_na=False)
    data = clean.merge(weak[["product_id", "proposed_work_types", "work_type_status"]], on="product_id", validate="one_to_one")
    data["weak_labels"] = data.proposed_work_types.map(json.loads)
    data["labels"] = data.weak_labels
    data["label_source"] = "weak"
    data["is_verified"] = False
    # Unknown weak work labels are excluded, never converted to negative rows.
    data["eligible_weak"] = data.work_type_status.isin(["proposed", "verified_empty_candidate"])
    reviewed = _read_reviewed(reviewed_paths)
    human = reviewed[reviewed.review_status.isin(["reviewed", "approved"])].copy()
    if not human.empty:
        human["human_labels"] = human.reviewed_work_types.map(json.loads)
        mapping = human.set_index("product_id").human_labels
        mask = data.product_id.isin(mapping.index)
        data.loc[mask, "labels"] = data.loc[mask, "product_id"].map(mapping)
        data.loc[mask, "label_source"] = "human_reviewed"
        data.loc[mask, "is_verified"] = True
    if label_policy == "reviewed_only":
        data = data[data.is_verified]
    elif label_policy == "weak_only":
        data = data[data.eligible_weak & ~data.is_verified]
    elif label_policy == "reviewed_plus_weak":
        data = data[data.is_verified | data.eligible_weak]
    else:
        raise ValueError(f"Unknown label_policy: {label_policy}")
    if data.empty:
        raise ValueError("No eligible labels for selected policy")
    allowed = set(class_names)
    invalid = {label for values in data.labels for label in values if label not in allowed}
    if invalid:
        raise ValueError(f"Labels not in taxonomy {taxonomy_version}: {sorted(invalid)}")
    data["text"] = data.apply(product_text, axis=1)
    data["leakage_group"] = data.apply(leakage_group, axis=1)
    manifest = create_or_load_manifest(data, split_manifest_path, random_seed, taxonomy_version)
    data = data.merge(manifest[["product_id", "split"]], on="product_id", validate="one_to_one")
    return DatasetBundle(data.reset_index(drop=True), class_names, taxonomy_version, label_policy, split_manifest_path)

"""Единая allowlist-схема признаков и защита от target leakage."""
from __future__ import annotations

import json
from typing import Any, Mapping

import pandas as pd

FEATURE_COLUMNS = [
    "name", "source_category", "category_names", "description_clean",
    "marketing_description_clean", "important_attributes_json",
    "characteristics_json", "brand_name", "sale_unit", "price",
    "characteristic_count", "information_completeness",
]
TEXT_FEATURE_COLUMNS = [
    "name", "source_category", "category_names", "description_clean",
    "marketing_description_clean", "important_attributes_json",
    "characteristics_json", "brand_name",
]
STRUCTURED_FEATURE_COLUMNS = [
    "price", "characteristic_count", "information_completeness",
    "source_category", "sale_unit", "brand_name",
]
TARGET_COLUMNS = ["domain_label", "activities", "product_category", "work_types", "renovation_stages", "room_types"]
METADATA_COLUMNS = [
    "product_id", "cod_good", "split", "duplicate_group", "taxonomy_version",
    "label_status", "labeling_method", "label_confidence", "label_evidence",
    "label_conflicts", "material_roles", "source_hash",
    "domain_valid", "activity_valid", "product_category_valid", "work_types_valid", "room_types_valid",
]
FORBIDDEN_COLUMNS = sorted(set(TARGET_COLUMNS + METADATA_COLUMNS + [
    "proposed_work_types", "proposed_material_roles", "proposed_product_categories",
    "proposed_room_types", "proposed_usage_contexts", "label_scores",
    "dimension_scores", "all_label_evidence", "label_outcome", "label_reasons",
    "conflicting_work_types", "review_status", "needs_manual_review",
    "max_heuristic_score", "proposed_label_count", "weak_labels", "labels",
    "is_verified", "label_source", "eligible_weak", "row_index",
    "domain_status", "activity_status", "product_category_status", "work_types_status", "room_types_status",
]))


def validate_feature_schema(columns: list[str]) -> None:
    forbidden = sorted(set(columns) & set(FORBIDDEN_COLUMNS))
    unexpected = sorted(set(columns) - set(FEATURE_COLUMNS) - {"input_text"})
    if forbidden:
        raise ValueError(f"Target/annotation leakage in feature schema: {forbidden}")
    if unexpected:
        raise ValueError(f"Unexpected columns are not permitted as features: {unexpected}")


def _source_value(row: Mapping[str, Any], column: str) -> str:
    value = row.get(column, "")
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value).strip()


def build_input_text(row: Mapping[str, Any]) -> str:
    """Build text only from explicitly approved, inference-time source fields."""
    validate_feature_schema(TEXT_FEATURE_COLUMNS)
    parts = [f"{column}: {_source_value(row, column)}" for column in TEXT_FEATURE_COLUMNS
             if _source_value(row, column)]
    return " \n ".join(parts)


def select_source_features(frame: pd.DataFrame) -> pd.DataFrame:
    missing = [column for column in FEATURE_COLUMNS if column not in frame]
    if missing:
        raise ValueError(f"Missing approved source features: {missing}")
    validate_feature_schema(FEATURE_COLUMNS)
    return frame.loc[:, FEATURE_COLUMNS].copy()

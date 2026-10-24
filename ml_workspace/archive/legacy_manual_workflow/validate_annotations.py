#!/usr/bin/env python3
"""Validate manually corrected multidimensional annotation CSV files."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from taxonomy_config import PRODUCT_TAXA, ROOM_TAXA, USAGE_TAXA
from prepare_datasets import WORK_TYPES, MATERIAL_ROLES

EXPECTED_TAXONOMY_VERSION = "multidim_v2_20261022"


def validate_file(path: Path) -> list[str]:
    data = pd.read_csv(path, keep_default_na=False)
    if not data.product_id.is_unique:
        raise ValueError("product_id must be unique")
    work_ids = {x.work_type_id for x in WORK_TYPES}
    role_ids = {x[0] for x in MATERIAL_ROLES}
    vocab = {
        "reviewed_product_categories": {x.taxon_id for x in PRODUCT_TAXA},
        "reviewed_work_types": work_ids,
        "reviewed_room_types": {x.taxon_id for x in ROOM_TAXA},
        "reviewed_usage_contexts": {x.taxon_id for x in USAGE_TAXA},
    }
    errors = []
    proposed_vocab = {
        "proposed_product_categories": vocab["reviewed_product_categories"],
        "proposed_work_types": vocab["reviewed_work_types"],
        "proposed_room_types": vocab["reviewed_room_types"],
        "proposed_usage_contexts": vocab["reviewed_usage_contexts"],
    }
    for row in data.itertuples():
        if hasattr(row, "taxonomy_version") and row.taxonomy_version != EXPECTED_TAXONOMY_VERSION:
            errors.append(f"{row.product_id}: taxonomy_version mismatch")
        if row.review_status not in {"unreviewed", "reviewed", "approved", "unknown_applicability"}:
            errors.append(f"{row.product_id}: invalid review_status")
        if hasattr(row, "annotation_status") and row.annotation_status != row.review_status:
            errors.append(f"{row.product_id}: annotation_status must equal review_status")
        for column, allowed in proposed_vocab.items():
            if not hasattr(row, column):
                continue
            try:
                proposed = json.loads(getattr(row, column))
                if not isinstance(proposed, list) or not set(proposed) <= allowed:
                    errors.append(f"{row.product_id}: invalid {column}")
            except json.JSONDecodeError:
                errors.append(f"{row.product_id}: malformed JSON in {column}")
        editable_values = [str(getattr(row, column, "")).strip() for column in [*vocab, "reviewed_material_roles"]]
        if row.review_status == "unreviewed" and any(editable_values):
            errors.append(f"{row.product_id}: unreviewed row contains reviewed labels")
        if row.review_status in {"reviewed", "approved"}:
            for column, allowed in vocab.items():
                value = getattr(row, column)
                try:
                    labels = json.loads(value)
                    if not isinstance(labels, list) or not set(labels) <= allowed:
                        errors.append(f"{row.product_id}: invalid {column}")
                except json.JSONDecodeError:
                    errors.append(f"{row.product_id}: malformed JSON in {column}")
            roles_raw = str(getattr(row, "reviewed_material_roles", "")).strip()
            try:
                roles = json.loads(roles_raw)
                if not isinstance(roles, list) or any(
                    not isinstance(item, dict) or item.get("work_type_id") not in work_ids
                    or item.get("material_role") not in role_ids for item in roles
                ):
                    errors.append(f"{row.product_id}: invalid reviewed_material_roles")
            except json.JSONDecodeError:
                errors.append(f"{row.product_id}: malformed JSON in reviewed_material_roles")
        if row.review_status == "approved" and not str(getattr(row, "review_notes", "")).strip():
            errors.append(f"{row.product_id}: approved row requires review_notes")
    if errors:
        raise ValueError("\n".join(errors[:50]))
    return [f"PASS: {len(data)} rows", "PASS: taxonomy IDs", "PASS: reviewed JSON fields"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    print("\n".join(validate_file(args.path)))


if __name__ == "__main__":
    main()

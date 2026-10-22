#!/usr/bin/env python3
"""Build exactly 500 unique review records while preserving human edits."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "ml_workspace" / "data"
OUTPUT = DATA / "manual_review_500.csv"
SEED = 20261023
TAXONOMY_VERSION = "multidim_v2_20261022"


EDITABLE = ["reviewed_product_categories", "reviewed_work_types", "reviewed_room_types",
            "reviewed_usage_contexts", "reviewed_material_roles", "review_notes"]


def has_human_edits(frame: pd.DataFrame) -> bool:
    if "review_status" in frame and frame.review_status.astype(str).ne("unreviewed").any():
        return True
    return any(column in frame and frame[column].fillna("").astype(str).str.strip().ne("").any() for column in EDITABLE)


def load_existing_samples() -> pd.DataFrame:
    frames = []
    for filename, source in [("manual_review_representative.csv", "representative_v2"),
                             ("manual_review_targeted.csv", "targeted_v2")]:
        frame = pd.read_csv(DATA / filename, keep_default_na=False, dtype={"cod_good": "string"})
        frame["sample_source"] = source
        frames.append(frame)
    combined = pd.concat(frames, ignore_index=True)
    if not combined.product_id.is_unique:
        raise ValueError("The existing 400 records are not unique")
    return combined


def main() -> None:
    if OUTPUT.exists():
        current = pd.read_csv(OUTPUT, keep_default_na=False)
        if has_human_edits(current):
            raise RuntimeError(f"Refusing to overwrite human-edited {OUTPUT}")
    base = load_existing_samples()
    clean = pd.read_csv(DATA / "products_clean.csv", keep_default_na=False, dtype={"cod_good": "string"})
    labels = pd.read_csv(DATA / "products_multidim_weak_labeled.csv", keep_default_na=False)
    pool = clean.merge(labels, on="product_id", validate="one_to_one")
    pool = pool[~pool.product_id.isin(base.product_id)].copy()
    pool["work_count"] = pool.proposed_work_types.map(lambda x: len(json.loads(x)))
    pool["room_count"] = pool.proposed_room_types.map(lambda x: len([v for v in json.loads(x) if v not in {"other", "unknown"}]))
    pool["usage_count"] = pool.proposed_usage_contexts.map(lambda x: len([v for v in json.loads(x) if v not in {"other", "unknown"}]))
    rare_works = {"demolition", "floor_screed", "wall_plastering", "wall_putty", "priming", "waterproofing"}
    masks = [
        ("additional_rare_work", pool.proposed_work_types.map(lambda x: bool(set(json.loads(x)) & rare_works)), 20),
        ("additional_work_multilabel", pool.work_count > 1, 12),
        ("additional_unlabeled_renovation", pool.work_type_status == "unknown_needs_review", 15),
        ("additional_hard_negative", (pool.work_type_status == "verified_empty_candidate") & pool.primary_product_family.isin(["other", "kitchen_dining", "home_textiles"]), 10),
        ("additional_furniture_multiroom", (pool.primary_product_family == "furniture") & (pool.room_count > 1), 12),
        ("additional_garden_outdoor", pool.primary_product_family.isin(["garden_outdoor", "barbecue_grilling", "pest_protection"]), 12),
        ("additional_other_unknown", pool.primary_product_family.isin(["other", "unknown"]), 12),
        ("additional_conflict", pool.label_conflicts.ne('{"product_category":[],"room_type":[],"usage_context":[],"work_type":[]}'), 7),
    ]
    chosen, origins = [], {}
    for index, (origin, mask, target) in enumerate(masks):
        candidates = pool.loc[mask & ~pool.index.isin(chosen)]
        take = candidates.sample(n=min(target, len(candidates)), random_state=SEED + index).index.tolist()
        chosen.extend(take)
        origins.update({row_index: origin for row_index in take})
    if len(chosen) < 100:
        rest = pool.loc[~pool.index.isin(chosen)].sample(n=100-len(chosen), random_state=SEED + 999)
        chosen.extend(rest.index.tolist())
        origins.update({row_index: "additional_random_fill" for row_index in rest.index})
    additional = pool.loc[chosen[:100]].copy()
    additional["description_readable"] = additional.apply(lambda x: (x.marketing_description_clean or x.description_clean)[:1000], axis=1)
    additional["characteristics_readable"] = additional.important_attributes_json
    additional["sample_source"] = [origins[i] for i in additional.index]
    additional["review_status"] = "unreviewed"
    for column in EDITABLE:
        additional[column] = ""

    columns = ["product_id", "cod_good", "name", "source_category", "category_names", "description_readable",
               "characteristics_readable", "proposed_work_types", "proposed_product_categories", "proposed_room_types",
               "proposed_usage_contexts", "proposed_material_roles", "all_label_evidence", "dimension_scores",
               "product_category_status", "work_type_status", "room_type_status", "usage_context_status",
               "needs_manual_review", "sample_source", *EDITABLE, "review_status"]
    # Existing files use sample_provenance; normalize without touching originals.
    base = base.rename(columns={"sample_provenance": "original_sample_provenance"})
    for column in columns:
        if column not in base:
            base[column] = ""
    result = pd.concat([base[columns], additional[columns]], ignore_index=True)
    result["taxonomy_version"] = TAXONOMY_VERSION
    result["annotation_status"] = result.review_status
    result["reviewer_notes"] = result.review_notes
    assert len(result) == 500 and result.product_id.is_unique
    result.to_csv(OUTPUT, index=False, encoding="utf-8-sig")
    print(json.dumps({"rows": len(result), "unique_ids": int(result.product_id.nunique()),
                      "sources": result.sample_source.value_counts().to_dict(), "seed": SEED}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

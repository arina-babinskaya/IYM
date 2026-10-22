"""Пересборка weak labels, group-aware splits, taxonomy CSV и отчётов."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pandas as pd

from ml_workspace.ml_api.feature_schema import FEATURE_COLUMNS, build_input_text
from ml_workspace.scripts.weak_labeling_v1 import label_product, serialize_labels
from ml_workspace.taxonomy.taxonomy_v1 import (MATERIAL_ROLES, OLD_TO_V1, PRODUCT_CATEGORIES,
    STAGES, TAXONOMY_VERSION, WORK_ROLE_MAP, WORK_TO_STAGES, WORK_TYPES)

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "ml_workspace/data"
SPLITS = DATA / "splits"
REPORTS = ROOT / "ml_workspace/reports"
TAXONOMY = ROOT / "ml_workspace/taxonomy"
SEED = 20261022


def duplicate_group(row: pd.Series) -> str:
    # Числа/размеры заменяются: варианты одного семейства остаются в одной группе.
    raw = f"{row['source_category']} {row['name']} {row['description_clean']}"
    value = re.sub(r"\d+(?:[.,]\d+)?", "#", raw.lower().replace("ё", "е"))
    value = re.sub(r"[^a-zа-я#]+", " ", value)
    tokens = value.split()
    # Бренд и длинные хвосты не должны дробить почти идентичные карточки.
    signature = " ".join(tokens[:40])
    return hashlib.sha256(signature.encode()).hexdigest()


def assigned_split(group: str) -> str:
    bucket = int(hashlib.sha256(f"{SEED}:{group}".encode()).hexdigest()[:12], 16) % 100
    return "train" if bucket < 70 else "validation" if bucket < 85 else "test"


def write_taxonomy() -> None:
    pd.DataFrame(STAGES).to_csv(TAXONOMY / "renovation_stages_v1.csv", index=False)
    rows = []
    examples = {
        "demolition": ("лом, инструмент для демонтажа", "декоративный молдинг"),
        "electrical_wiring": ("кабель ВВГ", "водорозетка"), "plumbing_rough": ("фитинг, водорозетка", "садовый шланг"),
        "floor_screed": ("смесь для стяжки", "кабельная стяжка"), "wall_painting": ("интерьерная краска", "эмалированный воздуховод"),
        "priming": ("грунтовка стен", "грунт для рассады"), "decorative_finish_install": ("стеновая панель", "семена огурца"),
    }
    for work_id, name, description, stages in WORK_TYPES:
        positive, negative = examples.get(work_id, (f"товар для операции «{name}»", "товар без подтверждённого назначения"))
        rows.append({"taxonomy_version": TAXONOMY_VERSION, "work_type_id": work_id, "ru_name": name,
            "description": description, "renovation_stages": json.dumps(stages, ensure_ascii=False),
            "required_or_optional_roles": json.dumps(WORK_ROLE_MAP[work_id], ensure_ascii=False),
            "positive_examples": positive, "negative_examples": negative,
            "ambiguous_cases": "Универсальные инструменты и крепёж требуют контекста категории/назначения.",
            "inclusion_criteria": "Есть явное назначение операции в категории, названии или технических свойствах.",
            "exclusion_criteria": "Совпадение только внутри омонима либо явно бытовой/садовый контекст."})
    pd.DataFrame(rows).to_csv(TAXONOMY / "work_types_v1.csv", index=False)
    pd.DataFrame({"taxonomy_version": TAXONOMY_VERSION, "product_category_id": PRODUCT_CATEGORIES,
        "is_multilabel": False}).to_csv(TAXONOMY / "product_categories_v1.csv", index=False)
    pd.DataFrame([{"work_type_id": k, "renovation_stages": json.dumps(v)} for k, v in WORK_TO_STAGES.items()]).to_csv(TAXONOMY / "work_type_to_stage_v1.csv", index=False)
    pd.DataFrame([{"work_type_id": k, "material_roles": json.dumps(v)} for k, v in WORK_ROLE_MAP.items()]).to_csv(TAXONOMY / "work_type_to_material_role_v1.csv", index=False)
    pd.DataFrame([{"old_id": k, "taxonomy_v1_id": v, "compatibility": "renamed_or_merged"} for k, v in OLD_TO_V1.items()]).to_csv(TAXONOMY / "draft_to_v1_mapping.csv", index=False)


def main() -> None:
    write_taxonomy()
    clean = pd.read_csv(DATA / "products_clean.csv", keep_default_na=False, low_memory=False)
    missing = sorted(set(FEATURE_COLUMNS) - set(clean.columns))
    if missing:
        raise RuntimeError(f"Source schema misses feature allowlist: {missing}")
    generated = pd.DataFrame([serialize_labels(label_product(row)) for _, row in clean.iterrows()])
    master = pd.concat([clean.reset_index(drop=True), generated], axis=1)
    master["input_text"] = [build_input_text(row) for row in clean.to_dict("records")]
    master["structured_input_features"] = clean[FEATURE_COLUMNS].apply(
        lambda row: json.dumps(row.to_dict(), ensure_ascii=False, sort_keys=True), axis=1)
    master["duplicate_group"] = master.apply(duplicate_group, axis=1)
    master["split"] = master.duplicate_group.map(assigned_split)
    manifest_path = SPLITS / "split_manifest.csv"
    if manifest_path.exists():
        existing = pd.read_csv(manifest_path, dtype={"duplicate_group": "string"})
        check = master[["product_id", "duplicate_group", "split"]].merge(
            existing[["product_id", "duplicate_group", "split"]], on="product_id", suffixes=("_new", "_old"), validate="one_to_one")
        if len(check) != len(master) or (check.duplicate_group_new != check.duplicate_group_old).any():
            raise RuntimeError("Existing split manifest is incompatible with current duplicate groups")
        if (check.split_new != check.split_old).any():
            raise RuntimeError("Refusing to alter existing split assignments")
        master["split"] = master.product_id.map(existing.set_index("product_id").split)
    if master.product_id.duplicated().any():
        raise RuntimeError("Duplicate product_id in source")
    if master.groupby("duplicate_group").split.nunique().max() != 1:
        raise RuntimeError("Duplicate group leakage")
    out_columns = ["product_id", "cod_good", "name", "source_category", "category_names",
        "description_clean", "marketing_description_clean", "important_attributes_json",
        "characteristics_json", "brand_name", "sale_unit", "price", "characteristic_count",
        "information_completeness", "input_text", "structured_input_features", "domain_label",
        "product_category", "work_types", "renovation_stages", "material_roles", "label_confidence",
        "label_evidence", "label_conflicts", "label_status", "labeling_method", "taxonomy_version",
        "duplicate_group", "split"]
    SPLITS.mkdir(parents=True, exist_ok=True)
    master[out_columns].to_csv(DATA / "products_taxonomy_v1.csv", index=False)
    for split in ("train", "validation", "test"):
        master.loc[master.split.eq(split), out_columns].to_csv(SPLITS / f"{split}.csv", index=False)
    manifest = master[["product_id", "cod_good", "duplicate_group", "split", "taxonomy_version"]].copy()
    manifest["random_seed"] = SEED
    manifest.to_csv(manifest_path, index=False)
    distributions = {
        "rows": len(master), "split_sizes": master.split.value_counts().to_dict(),
        "domain": master.domain_label.value_counts().to_dict(),
        "product_category": master.product_category.replace("", "not_applicable_or_unknown").value_counts().to_dict(),
        "work_types": pd.Series([x for value in master.work_types.map(json.loads) for x in value]).value_counts().to_dict(),
        "stages": pd.Series([x for value in master.renovation_stages.map(json.loads) for x in value]).value_counts().to_dict(),
        "multi_label_rows": int(master.work_types.map(lambda x: len(json.loads(x)) > 1).sum()),
        "conflicting_rows": int(master.label_conflicts.ne("[]").sum()),
    }
    (REPORTS / "dataset_statistics_v1.json").write_text(json.dumps(distributions, ensure_ascii=False, indent=2), encoding="utf-8")
    support = []
    for split, part in master.groupby("split"):
        for label in [x[0] for x in WORK_TYPES]:
            support.append({"split": split, "dimension": "work_types", "class": label,
                "support": int(part.work_types.map(lambda x, label=label: label in json.loads(x)).sum())})
        for label, count in part.domain_label.value_counts().items():
            support.append({"split": split, "dimension": "domain", "class": label, "support": int(count)})
        for label, count in part.product_category.replace("", "not_applicable_or_unknown").value_counts().items():
            support.append({"split": split, "dimension": "product_category", "class": label, "support": int(count)})
    pd.DataFrame(support).to_csv(SPLITS / "class_support.csv", index=False)
    previous = pd.read_csv(DATA / "products_multidim_weak_labeled.csv", usecols=["product_id", "work_type_status"])
    comparison = {"previous_rows": len(previous), "previous_work_status": previous.work_type_status.value_counts().to_dict(),
        "taxonomy_v1": distributions, "warning": "Рост покрытия не означает рост точности; обе версии являются эвристической разметкой."}
    (REPORTS / "labeling_version_comparison.json").write_text(json.dumps(comparison, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(distributions, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

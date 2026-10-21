#!/usr/bin/env python3
"""Create v2 multidimensional weak labels without changing clean source data."""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import pandas as pd

from taxonomy_config import (
    PRODUCT_FAMILY_RULES, PRODUCT_TAXA, ROOM_RULES, ROOM_TAXA,
    USAGE_RULES, USAGE_TAXA, Taxon,
)


ROOT = Path(__file__).resolve().parents[2]
WS = ROOT / "ml_workspace"
DATA = WS / "data"
TAX = WS / "taxonomy"
REPORTS = WS / "reports"
SEED = 20261022
REPRESENTATIVE_SIZE = 200
TARGETED_SIZE = 200


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def norm(value: Any) -> str:
    value = "" if value is None else str(value)
    return re.sub(r"\s+", " ", value.lower().replace("ё", "е")).strip()


def matches(patterns: tuple[str, ...], text: str) -> list[str]:
    result = []
    for pattern in patterns:
        hit = re.search(pattern, text, re.IGNORECASE)
        if hit:
            result.append(hit.group(0))
    return result


def classify_family(row: pd.Series) -> dict[str, Any]:
    category = norm(row.source_category)
    name = norm(row["name"])
    description = norm(f"{row.description_clean} {row.marketing_description_clean}")
    candidates = []
    for family, patterns in PRODUCT_FAMILY_RULES:
        cat_hits = matches(patterns, category)
        name_hits = matches(patterns, name)
        desc_hits = matches(patterns, description)
        score = min(1.0, 0.75 * bool(cat_hits) + 0.35 * bool(name_hits) + 0.15 * bool(desc_hits))
        if score >= 0.60:
            candidates.append((family, score, cat_hits, name_hits, desc_hits))
    candidates.sort(key=lambda item: (-item[1], [x[0] for x in PRODUCT_FAMILY_RULES].index(item[0])))
    conflict = len(candidates) > 1 and candidates[0][1] == candidates[1][1]
    if candidates and not conflict:
        family, score, cat_hits, name_hits, desc_hits = candidates[0]
        labels = [family]
        if family == "barbecue_grilling":
            labels = ["garden_outdoor", family]
        evidence = [{"dimension": "product_category", "label_id": family, "rule_id": f"family:{family}",
                     "score": score, "category": cat_hits, "name": name_hits, "description": desc_hits}]
        return {"labels": labels, "primary": family, "status": "proposed", "score": score,
                "evidence": evidence, "conflicts": [x[0] for x in candidates[1:]]}
    incomplete = not row.has_description and not row.has_marketing_description and not row.has_characteristics
    if incomplete or conflict:
        return {"labels": ["unknown"], "primary": "unknown", "status": "unknown_needs_review", "score": 0.0,
                "evidence": [], "conflicts": [x[0] for x in candidates]}
    return {"labels": ["other"], "primary": "other", "status": "other_supported", "score": 0.30,
            "evidence": [{"dimension": "product_category", "label_id": "other", "rule_id": "family:fallback_other",
                          "score": 0.30, "category": [category]}], "conflicts": []}


def classify_multilabel(row: pd.Series, rules: tuple, dimension: str, family: str) -> dict[str, Any]:
    category = norm(row.source_category)
    name = norm(row["name"])
    description = norm(f"{row.description_clean} {row.marketing_description_clean}")
    characteristics = norm(row.important_attributes_json)
    labels, evidence, scores = [], [], {}
    indoor_only = bool(re.search(r"только для внутренних|для внутренних работ", f"{description} {characteristics}"))
    outdoor_only = bool(re.search(r"только для наружных|для наружных работ", f"{description} {characteristics}"))
    for label, patterns in rules:
        cat_hits = matches(patterns, category)
        name_hits = matches(patterns, name)
        desc_hits = matches(patterns, description)
        char_hits = matches(patterns, characteristics)
        score = min(1.0, 0.70 * bool(cat_hits) + 0.35 * bool(name_hits) + 0.55 * bool(desc_hits) + 0.55 * bool(char_hits))
        conflict = (label in {"outdoor", "garden_outdoor", "terrace"} and indoor_only) or (label == "indoor" and outdoor_only)
        if conflict:
            score -= 0.80
        if score >= 0.55:
            labels.append(label)
            scores[label] = round(score, 2)
            evidence.append({"dimension": dimension, "label_id": label, "rule_id": f"{dimension}:{label}",
                             "score": round(score, 2), "category": cat_hits, "name": name_hits,
                             "description": desc_hits, "characteristics": char_hits})
    if labels:
        return {"labels": labels, "status": "proposed", "scores": scores, "evidence": evidence,
                "conflicts": (["indoor_only"] if indoor_only else []) + (["outdoor_only"] if outdoor_only else [])}
    # Absence of a room is usually non-applicability for tools/consumables, but
    # generic furniture or incomplete records remain unknown rather than other.
    if dimension == "room_type" and family in {"furniture", "home_accessories", "storage_organization"}:
        fallback, status = "unknown", "unknown_needs_review"
    elif not row.has_description and not row.has_marketing_description and not row.has_characteristics:
        fallback, status = "unknown", "unknown_needs_review"
    else:
        fallback, status = "other", "other_or_not_applicable"
    return {"labels": [fallback], "status": status, "scores": {fallback: 0.0}, "evidence": [], "conflicts": []}


def safe_review_write(frame: pd.DataFrame, path: Path) -> None:
    if path.exists():
        old = pd.read_csv(path, keep_default_na=False)
        editable = [c for c in old.columns if c.startswith("reviewed_") or c == "review_notes"]
        if "review_status" in old and ((old.review_status != "unreviewed").any() or any(old[c].astype(str).str.strip().ne("").any() for c in editable)):
            raise RuntimeError(f"Refusing to overwrite manually reviewed file: {path}")
    frame.to_csv(path, index=False, encoding="utf-8-sig")


def taxonomy_frame(taxa: tuple[Taxon, ...], labels: pd.DataFrame, products: pd.DataFrame, column: str) -> pd.DataFrame:
    joined = products[["product_id", "name", "source_category"]].merge(labels[["product_id", column]], on="product_id")
    rows = []
    for taxon in taxa:
        mask = joined[column].map(lambda x: taxon.taxon_id in json.loads(x))
        examples = joined.loc[mask, ["product_id", "name"]].head(3).to_dict("records")
        ambiguous = joined.loc[mask & joined[column].map(lambda x: "unknown" in json.loads(x)), ["product_id", "name"]].head(3).to_dict("records")
        rows.append({"id": taxon.taxon_id, "display_name": taxon.display_name, "definition": taxon.definition,
                     "inclusion_criteria": taxon.inclusion or "Требуется явное свидетельство из категории, названия или назначения.",
                     "exclusion_criteria": taxon.exclusion or "Не присваивать по случайной подстроке или отсутствию данных.",
                     "parent_id": taxon.parent_id, "real_examples": dumps(examples), "ambiguous_examples": dumps(ambiguous),
                     "supports_multi_label": taxon.multi_label, "notes": "Черновая автоматически сформированная таксономия."})
    return pd.DataFrame(rows)


def review_view(joined: pd.DataFrame, provenance: str) -> pd.DataFrame:
    out = joined.copy()
    out["description_readable"] = out.apply(lambda x: (x.marketing_description_clean or x.description_clean)[:1000], axis=1)
    out["characteristics_readable"] = out.important_attributes_json
    out["sample_provenance"] = provenance
    for name in ["reviewed_product_categories", "reviewed_work_types", "reviewed_room_types",
                 "reviewed_usage_contexts", "reviewed_material_roles", "review_notes"]:
        out[name] = ""
    out["review_status"] = "unreviewed"
    columns = ["product_id", "cod_good", "name", "source_category", "category_names", "description_readable",
               "characteristics_readable", "proposed_product_categories", "proposed_work_types",
               "proposed_room_types", "proposed_usage_contexts", "proposed_material_roles", "all_label_evidence",
               "dimension_scores", "product_category_status", "work_type_status", "room_type_status",
               "usage_context_status", "needs_manual_review", "sample_provenance", "reviewed_product_categories",
               "reviewed_work_types", "reviewed_room_types", "reviewed_usage_contexts", "reviewed_material_roles",
               "review_notes", "review_status"]
    return out[columns]


def main() -> None:
    products = pd.read_csv(DATA / "products_clean.csv", dtype={"cod_good": "string"}, keep_default_na=False)
    previous = pd.read_csv(DATA / "products_weak_labeled.csv", keep_default_na=False)
    merged = products.merge(previous, on="product_id", validate="one_to_one")
    output = []
    for _, row in merged.iterrows():
        family = classify_family(row)
        rooms = classify_multilabel(row, ROOM_RULES, "room_type", family["primary"])
        usage = classify_multilabel(row, USAGE_RULES, "usage_context", family["primary"])
        works = json.loads(row.proposed_work_types)
        work_status = "proposed" if works else ("unknown_needs_review" if row.label_outcome in {"insufficient_evidence", "insufficient_information", "conflicting_evidence"} else "verified_empty_candidate")
        evidence = family["evidence"] + rooms["evidence"] + usage["evidence"]
        try:
            old_evidence = json.loads(row.label_evidence)
            for label, items in old_evidence.items():
                for item in items:
                    evidence.append({"dimension": "work_type", "label_id": label, "rule_id": f"work_v1:{label}",
                                     "score": json.loads(row.label_scores).get(label, 0.0), **item})
        except json.JSONDecodeError:
            pass
        review = any(x["status"].startswith("unknown") for x in (family, rooms, usage)) or work_status == "unknown_needs_review" or len(rooms["labels"]) > 1 or len(usage["labels"]) > 1
        output.append({
            "product_id": row.product_id,
            "proposed_product_categories": dumps(family["labels"]),
            "primary_product_family": family["primary"],
            "proposed_work_types": row.proposed_work_types,
            "proposed_room_types": dumps(rooms["labels"]),
            "proposed_usage_contexts": dumps(usage["labels"]),
            "proposed_material_roles": row.proposed_material_roles,
            "product_category_status": family["status"], "work_type_status": work_status,
            "room_type_status": rooms["status"], "usage_context_status": usage["status"],
            "dimension_scores": dumps({"product_category": {family["primary"]: family["score"]},
                                        "work_type": json.loads(row.label_scores), "room_type": rooms["scores"],
                                        "usage_context": usage["scores"]}),
            "all_label_evidence": dumps(evidence),
            "label_conflicts": dumps({"product_category": family["conflicts"], "room_type": rooms["conflicts"],
                                       "usage_context": usage["conflicts"], "work_type": json.loads(row.conflicting_work_types)}),
            "labeling_method": "deterministic_multidimensional_rules_v2",
            "review_status": "unreviewed", "needs_manual_review": review,
        })
    labels = pd.DataFrame(output)
    labels.to_csv(DATA / "products_multidim_weak_labeled.csv", index=False, encoding="utf-8")

    full = products.merge(labels, on="product_id", validate="one_to_one")
    representative = full.sample(n=REPRESENTATIVE_SIZE, random_state=SEED)
    remaining = full.drop(index=representative.index)
    difficult_mask = remaining.needs_manual_review | remaining.primary_product_family.isin(["other", "unknown"])
    difficult = remaining[difficult_mask].copy()
    # Balance families before filling randomly from difficult records.
    selected = []
    for family, group in difficult.groupby("primary_product_family", sort=True):
        selected.extend(group.sample(n=min(5, len(group)), random_state=SEED + len(selected)).index.tolist())
    selected = list(dict.fromkeys(selected))[:TARGETED_SIZE]
    if len(selected) < TARGETED_SIZE:
        pool = difficult.drop(index=selected)
        selected += pool.sample(n=min(TARGETED_SIZE - len(selected), len(pool)), random_state=SEED + 1).index.tolist()
    targeted = remaining.loc[selected[:TARGETED_SIZE]]
    safe_review_write(review_view(representative, "representative_random_seed_20261022"), DATA / "manual_review_representative.csv")
    safe_review_write(review_view(targeted, "targeted_difficult_seed_20261022"), DATA / "manual_review_targeted.csv")

    # Audit the exact v1 unlabeled population, preserving reason overlap explicitly.
    old_unlabeled_ids = set(previous.loc[previous.proposed_label_count == 0, "product_id"])
    audit = full[full.product_id.isin(old_unlabeled_ids)].copy()
    audit = audit.merge(previous[["product_id", "label_outcome"]], on="product_id", how="left", validate="one_to_one")
    category_counts = audit.groupby(["source_category", "primary_product_family"], dropna=False).size().reset_index(name="count")
    audit_sample_parts = []
    for family, group in audit.groupby("primary_product_family", sort=True):
        audit_sample_parts.append(group.sample(n=min(8, len(group)), random_state=SEED))
    audit_sample = pd.concat(audit_sample_parts).drop_duplicates("product_id").head(250)
    audit_cols = ["product_id", "name", "source_category", "description_clean", "important_attributes_json",
                  "primary_product_family", "proposed_product_categories", "proposed_room_types",
                  "proposed_usage_contexts", "product_category_status", "room_type_status", "usage_context_status"]
    audit_sample[audit_cols].to_csv(DATA / "unlabeled_audit_sample.csv", index=False, encoding="utf-8-sig")

    product_tax = taxonomy_frame(PRODUCT_TAXA, labels, products, "proposed_product_categories")
    room_tax = taxonomy_frame(ROOM_TAXA, labels, products, "proposed_room_types")
    usage_tax = taxonomy_frame(USAGE_TAXA, labels, products, "proposed_usage_contexts")
    product_tax.to_csv(TAX / "product_categories_draft.csv", index=False, encoding="utf-8")
    room_tax.to_csv(TAX / "room_types_draft.csv", index=False, encoding="utf-8")
    usage_tax.to_csv(TAX / "usage_contexts_draft.csv", index=False, encoding="utf-8")

    category_map = products[["source_category"]].value_counts().reset_index(name="product_count")
    first = full.drop_duplicates("source_category").set_index("source_category")
    category_map["candidate_product_family"] = category_map.source_category.map(first.primary_product_family)
    category_map["candidate_room_types"] = category_map.source_category.map(first.proposed_room_types)
    category_map["candidate_usage_contexts"] = category_map.source_category.map(first.proposed_usage_contexts)
    category_map["mapping_status"] = "draft_context_only"
    category_map.to_csv(TAX / "category_mapping_multidim_draft.csv", index=False, encoding="utf-8")
    category_map.to_csv(TAX / "category_mapping_draft.csv", index=False, encoding="utf-8")

    # Validation
    assert len(labels) == len(products) == 88790 and labels.product_id.is_unique
    valid = {
        "product": {x.taxon_id for x in PRODUCT_TAXA}, "room": {x.taxon_id for x in ROOM_TAXA},
        "usage": {x.taxon_id for x in USAGE_TAXA},
    }
    assert all(set(json.loads(x)) <= valid["product"] for x in labels.proposed_product_categories)
    assert all(set(json.loads(x)) <= valid["room"] for x in labels.proposed_room_types)
    assert all(set(json.loads(x)) <= valid["usage"] for x in labels.proposed_usage_contexts)

    family_dist = labels.primary_product_family.value_counts().to_dict()
    room_dist = Counter(x for value in labels.proposed_room_types for x in json.loads(value))
    usage_dist = Counter(x for value in labels.proposed_usage_contexts for x in json.loads(value))
    previous_outcomes = audit.label_outcome.value_counts().to_dict()
    audit_family = audit.primary_product_family.value_counts().to_dict()
    top_unlabeled = category_counts.sort_values("count", ascending=False).head(30)
    report = f"""# Аудит ранее неразмеченной части каталога

Аудит выполнен ровно для **{len(audit):,}** товаров с пустым `proposed_work_types` в v1. Это множество объединяет прежние исходы: `{dumps(previous_outcomes)}`. Группы не следует складывать повторно: они являются взаимоисключающими значениями `label_outcome` внутри единой выборки.

Главная причина низкого work-type coverage — не обязательно ошибка: v1 отвечал только на вопрос о ремонтной операции. Посуда, мебель, растения, текстиль и товары для отдыха закономерно имели пустой work type. Ошибкой было интерпретировать отсутствие ремонтной работы как глобальную нерелевантность товара.

## Новые семейства среди прежних work-type-unlabeled

`{dumps(audit_family)}`

Fallback `other` означает понятный товар вне поддерживаемых семейств; `unknown` — недостаток или конфликт данных. Ни один из них не создаёт ремонтную работу.

## Крупнейшие исходные категории

""" + "\n".join(f"- {r.source_category}: {r['count']:,} → `{r.primary_product_family}`" for _, r in top_unlabeled.iterrows()) + """

## Выводы

- Furniture, kitchen/dining, storage, home textiles/accessories, garden/outdoor, barbecue and pest protection выделены независимо от work types.
- Multi-label возможности сосредоточены в room/usage: например, столовая мебель может иметь kitchen+dining_room, а садовый гриль — outdoor+garden+barbecue.
- `unlabeled_audit_sample.csv` содержит реальные ID и стратифицированные примеры семейств.
- Возможные false negatives v1 остаются в `insufficient_evidence` и целевой review-выборке; автоматическое расширение product-family coverage не доказывает улучшение accuracy.
"""
    (REPORTS / "unlabeled_audit.md").write_text(report, encoding="utf-8")

    notes = f"""# Многомерная таксономия v2

Измерения разделены: product category отвечает «что это», work type — «в какой ремонтной операции применяется», room type — «для какой комнаты явно подходит», usage context — «в каком сценарии используется». Renovation stage/type остаются метаданными work type и не присваиваются всем товарам.

Рекомендуемый объём: **{len(PRODUCT_TAXA)-2}** содержательных product families + `other/unknown`, 17 work types, **{len(ROOM_TAXA)-2}** room labels + fallbacks и **{len(USAGE_TAXA)-2}** usage labels + fallbacks. Product family primary label взаимоисключающий, кроме сохранения иерархического parent path; work/room/usage — multi-label.

`other`: объект понятен, но словарь измерения его не покрывает. `unknown`: данных недостаточно или есть равносильный конфликт. Для work type пустой список дополнительно имеет status `verified_empty_candidate` либо `unknown_needs_review`; пустой список не заменяется фиктивной работой.

Backend поддерживает список work/room types, но не product families, usage contexts, dimension statuses или context-dependent roles. Production schemas не менялись; интеграция требует отдельного согласования.
"""
    (TAX / "taxonomy_notes.md").write_text(notes, encoding="utf-8")

    summary = {"products": len(labels), "family_distribution": family_dist, "room_distribution": dict(room_dist),
               "usage_distribution": dict(usage_dist), "representative": len(representative), "targeted": len(targeted),
               "old_unlabeled_audited": len(audit)}
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

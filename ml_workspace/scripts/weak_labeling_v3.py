"""Evidence-gated weak-label refinements for dataset v3 (taxonomy stays v2)."""
from __future__ import annotations

import re
from typing import Any

import pandas as pd

from ml_workspace.scripts.weak_labeling_v2 import label_product as label_v2
from ml_workspace.scripts.weak_labeling_v2 import norm, serialize_labels
from ml_workspace.taxonomy.taxonomy_v2 import WORK_ROLE_MAP, stages_for_work_types

LABELING_RULE_VERSION = "weak_rules_v3"


def _add(works: list[str], evidence: list[dict[str, Any]], label: str,
         rule_id: str, source: str, match: str) -> None:
    if label not in works:
        works.append(label)
    evidence.append({"rule_id": rule_id, "dimension": "work_type", "label": label,
                     "source": source, "matches": [match], "score": 1.0})


def _remove(works: list[str], evidence: list[dict[str, Any]], label: str,
            rule_id: str, match: str) -> None:
    if label in works:
        works.remove(label)
        evidence.append({"rule_id": rule_id, "dimension": "work_type", "label": label,
                         "action": "remove_false_positive", "source": "disambiguation",
                         "matches": [match], "score": 1.0})


def _directional_additions(category: str, text: str, works: list[str],
                           evidence: list[dict[str, Any]]) -> None:
    """Add secondary labels only for an explicit documented downstream use."""
    gates = (
        (r"^грунтовка$", "wall_painting", r"(?:под|перед|до) (?:последующ\w+ )?(?:окраск|окрашив|нанесени\w+ краск)"),
        (r"^грунтовка$", "wallpapering", r"(?:под|перед|до) (?:последующ\w+ )?(?:обои|оклеив|наклеив)"),
        (r"^грунтовка$", "wall_plastering", r"(?:под|перед|до) (?:последующ\w+ )?(?:оштукатур|нанесени\w+ штукатур)"),
        (r"^грунтовка$", "wall_putty", r"(?:под|перед|до) (?:последующ\w+ )?(?:шпатл|шпакл)"),
        (r"^шпатлевки (?:готовые|сухие .+)$", "wall_painting", r"под (?:последующ\w+ )?(?:окраск|окрашив)"),
        (r"^шпатлевки (?:готовые|сухие .+)$", "wallpapering", r"под (?:последующ\w+ )?(?:обои|оклеив)"),
        (r"^шпатлевки (?:готовые|сухие .+)$", "drywall_install", r"(?:задел|заполн|обработ)\w* (?:стык|шв)\w*[^.]{0,100}(?:гипсокарт|гкл|гвл)|(?:стык|шв)\w*[^.]{0,100}(?:гипсокарт|гкл|гвл)"),
        (r"^гидроизоляция полимерная$|^смеси для гидроизоляции полов$", "tiling", r"под плиточ\w+ (?:облицов|покрыт)|перед укладк\w+ плит"),
        (r"^смеси для выравнивания полов .+$", "tiling", r"под (?:укладк\w+ )?(?:напольн\w+ |керамическ\w+ )?плит"),
        (r"^смеси для выравнивания полов .+$", "floor_covering_install", r"под (?:укладк\w+ )?(?:ламинат|линолеум|паркет|напольн\w+ покрыт)"),
        (r"^штукатурка (?:гипсовая|цементная)$", "tiling", r"перед облицовк\w+ плит|под (?:укладк\w+ )?плит"),
        (r"^штукатурка (?:гипсовая|цементная)$", "wall_painting", r"под (?:последующ\w+ )?(?:окраск|окрашив)"),
    )
    for category_pattern, label, use_pattern in gates:
        if re.search(category_pattern, category) and (hit := re.search(use_pattern, text)):
            _add(works, evidence, label, f"v3:documented_use:{label}",
                 "description_or_characteristics", hit.group(0))


def label_product(row: pd.Series | dict[str, Any]) -> dict[str, Any]:
    result = label_v2(row)
    category = norm(row.get("source_category", ""))
    name = norm(row.get("name", ""))
    text = norm(" ".join(str(row.get(field, "")) for field in (
        "name", "description_clean", "marketing_description_clean",
        "important_attributes_json", "characteristics_json")))
    works = list(result["work_types"])
    evidence = list(result["label_evidence"])

    # Correct known substring/retailer-category collisions in v2.
    if "трубопровод" in category:
        _remove(works, evidence, "electrical_wiring", "v3:disambiguate:truboprovod", "трубопровод")
    if "газопровод" in category:
        _remove(works, evidence, "electrical_wiring", "v3:disambiguate:gazoprovod", "газопровод")
        _remove(works, evidence, "plumbing_rough", "v3:disambiguate:gazoprovod", "газопровод")
    if category.startswith("теплый пол под "):
        _remove(works, evidence, "floor_covering_install", "v3:disambiguate:heated_floor", category)
    if category == "шпатлевки тонированные":
        _remove(works, evidence, "plumbing_fixture_install", "v3:disambiguate:bathroom_acrylic", category)
    cargo_tie = bool(re.search(r"стяжки, резинки для крепления груза в автомобиле", category))
    if cargo_tie:
        _remove(works, evidence, "floor_screed", "v3:disambiguate:cargo_tie", category)

    # Automotive body filler is outside the renovation taxonomy.
    automotive_putty = category == "шпатлевки автомобильные"
    if automotive_putty or cargo_tie:
        _remove(works, evidence, "wall_putty", "v3:exclude:automotive_putty", category)
        result["domain_label"] = "non_renovation"
        result["activities"] = []
        result["product_category"] = ""

    # Recover explicit categories suppressed in v2 by incidental description words.
    if category in {"кувалды", "ломы, гвоздодеры"}:
        result["domain_label"] = "renovation"
        result["activities"] = ["renovation"]
        result["product_category"] = "hand_tools"
        _add(works, evidence, "demolition", "v3:category:demolition_tools", "source_category", category)
    if category in {"штукатурка гипсовая", "штукатурка цементная"}:
        result["domain_label"] = "renovation"
        result["activities"] = ["renovation"]
        result["product_category"] = "plaster"
        _add(works, evidence, "wall_plastering", "v3:category:plaster", "source_category", category)
    explicit_floor_leveler = category.startswith("смеси для выравнивания полов ") and (
        category.endswith(("цементные", "гипсовые"))
        or bool(re.search(r"ровнител|выравнивател|наливн\w* пол", text))
    )
    if explicit_floor_leveler:
        result["domain_label"] = "renovation"
        result["activities"] = ["renovation"]
        result["product_category"] = "construction_mix"
        _add(works, evidence, "floor_screed", "v3:category:floor_leveling_mix", "source_category", category)

    # A named two-in-one plaster/putty compound genuinely supports both operations.
    if "штукатур" in name and re.search(r"шпатл|шпакл", name):
        _add(works, evidence, "wall_plastering", "v3:explicit_dual:plaster_putty", "name", name)
        _add(works, evidence, "wall_putty", "v3:explicit_dual:plaster_putty", "name", name)

    if result["domain_label"] == "renovation":
        _directional_additions(category, text, works, evidence)
    else:
        works = []

    works = list(dict.fromkeys(works))
    result.update({
        "work_types": works,
        "renovation_stages": stages_for_work_types(works) if works else [],
        "material_roles": [{"work_type_id": work, "roles": WORK_ROLE_MAP[work]} for work in works],
        "label_evidence": evidence,
        "label_conflicts": [] if result["domain_label"] != "unknown_needs_review" else result["label_conflicts"],
        "domain_status": "known" if result["domain_label"] != "unknown_needs_review" else "unknown",
        "activity_status": "known" if result["domain_label"] != "unknown_needs_review" else "unknown",
        "product_category_status": "known" if result["domain_label"] != "unknown_needs_review" and result["product_category"] else "unknown",
        "work_types_status": "known" if result["domain_label"] != "unknown_needs_review" else "unknown",
        "label_status": "auto_labeled" if result["domain_label"] != "unknown_needs_review" else result["label_status"],
        "labeling_method": "deterministic_rules_taxonomy_v2_weak_rules_v3",
    })
    return result


__all__ = ["LABELING_RULE_VERSION", "label_product", "serialize_labels"]

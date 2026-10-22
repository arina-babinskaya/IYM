"""Детерминированная weak-разметка taxonomy_v1 с проверяемыми свидетельствами."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

import pandas as pd

from ml_workspace.taxonomy.taxonomy_v1 import TAXONOMY_VERSION, WORK_ROLE_MAP, stages_for_work_types


def _norm(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").lower().replace("ё", "е")).strip()


def _hit(pattern: str, text: str) -> str | None:
    match = re.search(pattern, text, re.I)
    return match.group(0) if match else None


@dataclass(frozen=True)
class Rule:
    label: str
    category: tuple[str, ...]
    text: tuple[str, ...]
    negative: tuple[str, ...] = ()
    minimum: float = .65


NON_RENOVATION = (
    r"\bсемен(?:а|ной)\b", r"саженц", r"луковичн.*цвет", r"удобрени", r"грунт для раст",
    r"щепа для копч", r"барбекю|мангал|грил", r"шампур|уголь древес|розжиг",
    r"посуд|тарел|кружк|салатник|сковород|кастрюл", r"полотенц|постель|простын|носк",
    r"бытовая хим|средства для стир", r"корм для|товары для животных", r"игрушк|канцтов|тетради",
    r"растения комнатные|растения искусственные|рассада|кашпо|горшки для .*растен",
    r"\bобувь\b|гели для душа|шампуни|аромадиффузор|фоторамк",
    r"стулья для столовой|столы для столовой|ножи кухонные|банки, емкости|контейнеры, корзинки",
    r"\bшторы\b|\bковры\b|ткани на отрез|подушки|одеяла|комплекты (?:евро|[12],?5?-?спальные|дуэт)",
    r"шланги для полива|соединители шланговые",
)
RENOVATION_CONTEXT = (
    r"строител|отделоч|ремонт|монтаж|крепеж|инструмент|электр|сантех|плитк|краск|обои|двер|окон|светиль|гипс|шпатл|шпакл|штукатур|гидроизоляц|линолеум|ламинат|панел|молдинг",
)

CATEGORY_RULES = (
    Rule("primer", (r"грунтовк",), (r"\bгрунтовк|\bпраймер",), (r"грунт-эмал|эмаль-грунт",)),
    Rule("paint", (r"краски|эмали",), (r"\bкраск|\bэмаль",), (r"эмалированн|эмалевое покрытие|воздуховод",)),
    Rule("putty", (r"шпатлев|шпаклев",), (r"шпатл|шпакл",)),
    Rule("plaster", (r"штукатур",), (r"штукатур",)),
    Rule("drywall", (r"гипсокарт|гвл",), (r"\bгкл\b|\bгвл\b|гипсокарт",)),
    Rule("tile", (r"керамогранит|плитка настенн|плитка напольн",), (r"керамогранит|керамическ.*плит",), (r"spc|пвх|тротуар",)),
    Rule("floor_covering", (r"ламинат|линолеум|плитка spc|ковролин",), (r"ламинат|линолеум|\bspc\b|\blvt\b|ковролин",)),
    Rule("waterproofing_material", (r"гидроизоляц",), (r"гидроизоляц|аквастоп",), (r"обув|одежд",)),
    Rule("adhesive", (r"клеи|клей",), (r"\bклей\b|клеев",)),
    Rule("sealant", (r"герметик",), (r"герметик",)),
    Rule("construction_mix", (r"строительные смеси|цемент|наливные полы|стяж",), (r"цемент|наливн.*пол|смесь.*строит",)),
    Rule("fasteners", (r"саморез|шуруп|дюбел|анкер|гвозд|болты|крепеж",), (r"саморез|шуруп|дюбел|анкер|гвозд|крепеж",)),
    Rule("tools", (r"инструмент|сверла|буры|коронки|кисти маляр|валики|шпатели",), (r"дрель|перфоратор|шпател|сверл|бур\b|кист.*маляр|валик.*маляр",)),
    Rule("protective_equipment", (r"средства защиты|перчатки|респиратор|очки защит",), (r"респиратор|каска|очки защит|перчатки.*строит",)),
    Rule("plumbing", (r"смесител|унитаз|раковин|фитинги|трубы|канализац|водорозет",), (r"смесител|унитаз|раковин|фитинг|водорозет|канализац",), (r"садов.*шланг|шланг.*полив",)),
    Rule("electrical_goods", (r"розетки|выключател|кабель электр|автоматы защиты|электромонтаж",), (r"электрическ.*розет|выключател|кабел.*ввг|электропровод",), (r"водорозет",)),
    Rule("lighting", (r"люстр|светильник|бра|споты|лампы светодиодные|светодиодные ленты",), (r"люстр|светильник|\bбра\b|светодиодн.*(?:ламп|лент)",), (r"садов|уличн|настольн",)),
    Rule("doors_windows", (r"двер|окон|наличник|подокон",), (r"дверн|оконн|наличник|подокон",), (r"мебельн.*двер",)),
    Rule("decorative_panels", (r"стеновые панели|панели стеновые",), (r"стенов.*панел|панел.*стен",)),
    Rule("decorative_materials", (r"молдинг|плинтус потолоч|декоративные покры|декоративные элементы.*карниз|^карнизы$",), (r"молдинг|лепнин|декоративн.*покрыт|карниз.*(?:комплект|декоратив|потолоч|настенн)",)),
    Rule("installation_accessories", (r"монтажн|профили|ленты строитель",), (r"монтажн.*пен|профил.*монтаж|лента.*строит",)),
    Rule("insulation", (r"изоляц|утеплител",), (r"теплоизоляц|звукоизоляц|утеплител",)),
    Rule("lumber_sheet_material", (r"пиломатериал|фанер|осб|дсп",), (r"фанер|\bосб\b|\bдсп\b|пиломатериал",)),
)

WORK_RULES = (
    Rule("demolition", (r"демонтаж|ломы|кувалды",), (r"демонтаж|кувалд|гвоздодер|\bлом\b",)),
    Rule("electrical_wiring", (r"кабель электр|провод|гофр.*кабел|автоматы защиты|клемм",), (r"кабел.*(?:ввг|нг)|электропровод|распределительн.*короб",), (r"водорозет",)),
    Rule("plumbing_rough", (r"^трубы$|фитинги|канализац|водорозет|запорная арматура",), (r"фитинг|канализац|водорозет|запорн.*кран",), (r"садов.*шланг|полив|электрическ.*розет",)),
    Rule("waterproofing", (r"гидроизоляц",), (r"гидроизоляц|аквастоп",), (r"обув|одежд",)),
    Rule("floor_screed", (r"наливные полы|стяж|ровнители для пола",), (r"наливн.*пол|стяжк.*пол|ровнител.*пол",), (r"стяжк.*кабел|кабельн.*стяжк",)),
    Rule("wall_plastering", (r"штукатурк",), (r"штукатур",), (r"декоративн.*штукатур",)),
    Rule("drywall_install", (r"гипсокарт|гвл|профили и аксессуары для гипсокартона",), (r"гипсокарт|\bгкл\b|\bгвл\b",)),
    Rule("wall_putty", (r"шпатлев|шпаклев",), (r"шпатл|шпакл",)),
    Rule("priming", (r"грунтовк",), (r"\bгрунтовк|\bпраймер",), (r"грунт-эмал|эмаль-грунт",)),
    Rule("wall_painting", (r"краски для стен|краски интерьер|кисти маляр|валики",), (r"интерьерн.*краск|краск.*(?:стен|потол)|кист.*маляр|валик.*маляр",), (r"воздуховод|эмалированн|фасадн|по металлу",)),
    Rule("wallpapering", (r"^обои$|клей.*обо",), (r"\bобои\b|обойн.*клей|клей.*обо",)),
    Rule("tiling", (r"керамогранит|плитка настенн|плитка напольн|затирки для плит|клей.*плит",), (r"керамогранит|керамическ.*плит|плиточн.*клей|затирк.*плит",), (r"spc|пвх|тротуар",)),
    Rule("floor_covering_install", (r"ламинат|линолеум|плитка spc|подложк|плинтус",), (r"ламинат|линолеум|\bspc\b|\blvt\b|подложк.*пол|плинтус",), (r"плинтус.*потол",)),
    Rule("door_window_install", (r"двери|окна|наличники|дверные короб",), (r"межкомнатн.*двер|входн.*двер|оконн.*блок|дверн.*короб|наличник",), (r"мебельн",)),
    Rule("electrical_fittings", (r"розетки встраиваемые|выключатели встраиваемые|рамки для розеток",), (r"электрическ.*розет|розетк.*(?:встраиваем|накладн)|выключател",), (r"водорозет|смесител|ручки нажимные",)),
    Rule("plumbing_fixture_install", (r"смесител|раковин|унитаз|ванны|душевые системы|мойки из",), (r"смесител|унитаз|раковин|душев.*систем|ванн.*акрил|мойк.*кухон",)),
    Rule("lighting_install", (r"люстр|светильники|бра|споты",), (r"люстр|светильник.*(?:потолоч|настенн|встраиваем|подвесн|треков)|\bбра\b",), (r"садов|уличн|настольн|фонар",)),
    Rule("decorative_finish_install", (r"стеновые панели|молдинги|декоративные покрытия|декоративные элементы.*карниз|^карнизы$",), (r"стенов.*панел|молдинг|лепнин|декоративн.*покрыт|карниз.*(?:комплект|декоратив|потолоч|настенн)",)),
)


def _apply(rule: Rule, category: str, text: str, technical: str) -> tuple[float, list[dict[str, Any]]]:
    combined = f"{category} {text} {technical}"
    negatives = [m for p in rule.negative if (m := _hit(p, combined))]
    if negatives:
        return 0.0, [{"source": "negative", "match": value} for value in negatives]
    evidence = []
    cat_hits = [m for p in rule.category if (m := _hit(p, category))]
    text_hits = [m for p in rule.text if (m := _hit(p, text))]
    tech_hits = [m for p in rule.text if (m := _hit(p, technical))]
    evidence += [{"source": "source_category", "match": x} for x in cat_hits]
    evidence += [{"source": "name_description", "match": x} for x in text_hits]
    evidence += [{"source": "technical_characteristics", "match": x} for x in tech_hits]
    score = min(1.0, .70 * bool(cat_hits) + .35 * bool(text_hits) + .20 * bool(tech_hits))
    return score, evidence


def label_product(row: pd.Series | dict[str, Any]) -> dict[str, Any]:
    category = _norm(row.get("source_category", ""))
    name_desc = _norm(" ".join(str(row.get(x, "")) for x in ("name", "description_clean", "marketing_description_clean")))
    technical = _norm(" ".join(str(row.get(x, "")) for x in ("important_attributes_json", "characteristics_json")))
    all_text = f"{category} {name_desc} {technical}"
    non_hits = [m for p in NON_RENOVATION if (m := _hit(p, f"{category} {name_desc}"))]
    renovation_hits = [m for p in RENOVATION_CONTEXT if (m := _hit(p, all_text))]
    evidence: list[dict[str, Any]] = []
    categories: list[tuple[str, float]] = []
    works: list[str] = []
    scores: dict[str, float] = {}
    conflicts: list[str] = []
    for dimension, rules in (("product_category", CATEGORY_RULES), ("work_type", WORK_RULES)):
        for rule in rules:
            score, found = _apply(rule, category, name_desc, technical)
            if found:
                evidence += [{"dimension": dimension, "label": rule.label, "score": score, **item} for item in found]
            if score >= rule.minimum:
                scores[f"{dimension}:{rule.label}"] = score
                (categories if dimension == "product_category" else works).append((rule.label, score) if dimension == "product_category" else rule.label)
    # Explicit exclusion evidence wins over broad contextual words. A conflict
    # is retained only when a concrete renovation operation was independently assigned.
    if non_hits and works:
        domain, status = "unknown_needs_review", "conflicting_evidence"
        conflicts.append("non_renovation_and_renovation_evidence")
    elif non_hits:
        domain, status = "non_renovation", "auto_labeled"
        works, categories = [], []
    elif works or categories or renovation_hits:
        domain, status = "renovation", "auto_labeled"
    else:
        domain, status = "unknown_needs_review", "insufficient_evidence"
    works = list(dict.fromkeys(works))
    primary = (max(categories, key=lambda item: item[1])[0] if categories
               else "other_renovation_material") if domain == "renovation" else ""
    stages = stages_for_work_types(works) if domain == "renovation" else []
    roles = [{"work_type_id": work, "roles": WORK_ROLE_MAP[work]} for work in works]
    confidence = max(scores.values(), default=(1.0 if domain == "non_renovation" else 0.0))
    evidence += [{"dimension": "domain", "label": "non_renovation", "source": "exclusion_rule", "match": x, "score": 1.0} for x in non_hits]
    return {"domain_label": domain, "product_category": primary, "work_types": works,
            "renovation_stages": stages, "material_roles": roles, "label_confidence": round(confidence, 3),
            "label_evidence": evidence, "label_conflicts": conflicts, "label_status": status,
            "labeling_method": "deterministic_rules_taxonomy_v1", "taxonomy_version": TAXONOMY_VERSION}


def serialize_labels(result: dict[str, Any]) -> dict[str, Any]:
    return {key: json.dumps(value, ensure_ascii=False, sort_keys=True) if isinstance(value, (list, dict)) else value
            for key, value in result.items()}

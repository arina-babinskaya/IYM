#!/usr/bin/env python3
"""Build provisional catalog datasets and deterministic weak labels.

Run from the repository root with:
    .venv-sandbox/bin/python ml_workspace/scripts/prepare_datasets.py

The script never changes the source catalog or application code. Multi-label and
evidence columns are JSON strings. Heuristic scores are priorities, not calibrated
probabilities and not verified ground truth.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "requirments" / "products_final.json"
WORKSPACE = ROOT / "ml_workspace"
DATA_DIR = WORKSPACE / "data"
TAXONOMY_DIR = WORKSPACE / "taxonomy"
REPORTS_DIR = WORKSPACE / "reports"
RANDOM_SEED = 20261021
SAMPLE_SIZE = 400
SOURCE_SHA256 = "590a500be31d7a8d56e625c231ef978fc1a1a7b6d0a2e65eb33b88d68eee175e"

JSON_COLUMNS = [
    "category_ids", "category_names", "categories_json", "important_attributes_json",
    "characteristics_json", "proposed_work_types", "proposed_material_roles",
    "label_scores", "label_evidence", "label_reasons",
]


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = html.unescape(str(value))
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"[ \t\r\f\v]+", " ", text).strip()


def normalized_name(value: Any) -> str:
    """Conservative spelling normalization; no semantic merging."""
    text = unicodedata.normalize("NFKC", clean_text(value)).lower().replace("ё", "е")
    return re.sub(r"\s+", " ", text).strip()


def compact(value: Any, limit: int = 500) -> str:
    text = clean_text(value).replace("\n", " | ")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


EXACT_NUMBER = re.compile(r"^\s*([+-]?\d+(?:[.,]\d+)?)\s*$")
NUMBER_WITH_UNIT = re.compile(
    r"^\s*([+-]?\d+(?:[.,]\d+)?)\s*(мм|см|м|м2|м²|м3|м³|мл|л|г|кг|шт\.?|%|вт|квт)\s*$",
    re.IGNORECASE,
)


def parse_numeric(value: str) -> tuple[float | None, str | None, str]:
    """Parse only unambiguous scalar values; preserve every original value."""
    match = EXACT_NUMBER.fullmatch(value)
    if match:
        return float(match.group(1).replace(",", ".")), None, "exact_number"
    match = NUMBER_WITH_UNIT.fullmatch(value)
    if match:
        return float(match.group(1).replace(",", ".")), match.group(2).lower(), "number_with_unit"
    return None, None, "not_parsed"


@dataclass(frozen=True)
class WorkType:
    work_type_id: str
    work_type_name: str
    description: str
    renovation_stage: str
    possible_renovation_types: tuple[str, ...]
    required_material_roles: tuple[str, ...]
    category_patterns: tuple[str, ...]
    name_patterns: tuple[str, ...]
    technical_patterns: tuple[str, ...] = ()
    negative_category_patterns: tuple[str, ...] = ()
    negative_text_patterns: tuple[str, ...] = ()
    backend_mapping: tuple[str, ...] = ()
    notes: str = ""


ALL_RENOVATIONS = ("cosmetic", "capital", "euro", "rental")
MAJOR_RENOVATIONS = ("capital", "euro")

# Categories provide context, while name/technical evidence is evaluated independently.
# This is intentionally a work taxonomy rather than a retail material taxonomy.
WORK_TYPES: tuple[WorkType, ...] = (
    WorkType("demolition", "Демонтаж конструкций и покрытий", "Удаление старых покрытий и разборка элементов перед ремонтом.", "preparation", MAJOR_RENOVATIONS, ("tool", "consumable"),
             (r"демонтаж", r"ломы", r"кувалды"), (r"перфоратор", r"кувалд", r"гвоздод[её]р", r"(?<![а-я])лом\b"), backend_mapping=("demolition",)),
    WorkType("electrical_wiring", "Прокладка электропроводки", "Черновая прокладка кабеля, гофры, коробок и защитной автоматики.", "rough", MAJOR_RENOVATIONS, ("primary_material", "auxiliary_material", "fastener", "tool"),
             (r"кабел.*электр", r"провод", r"гофр.*кабел", r"распределительн.*короб", r"автоматы защиты", r"клемм"),
             (r"\bкабел", r"электропровод", r"провод .*ввг", r"гофр.*кабел", r"распределительн.*короб"),
             negative_category_patterns=(r"кабели.*телефон", r"usb", r"удлинител"), negative_text_patterns=(r"водорозет",), backend_mapping=("electrical_wiring",)),
    WorkType("plumbing_rough", "Разводка водоснабжения и канализации", "Монтаж труб, фитингов, запорной арматуры и канализационных элементов.", "rough", MAJOR_RENOVATIONS, ("primary_material", "auxiliary_material", "fastener", "tool"),
             (r"^трубы$", r"фитинги", r"запорная арматура", r"канализац", r"водорозет", r"сифоны"),
             (r"фитинг", r"водорозет", r"канализац", r"запорн.*кран"), technical_patterns=(r"тип трубы", r"диаметр подключения"), backend_mapping=("plumbing_rough",),
             notes="Общее слово «труба» без сантехнической категории/характеристики недостаточно."),
    WorkType("waterproofing", "Устройство гидроизоляции", "Нанесение гидроизоляционных составов, лент и мембран во влажных зонах.", "rough", ("capital", "euro", "rental"), ("primary_material", "preparation_material", "auxiliary_material", "tool"),
             (r"гидроизоляц", r"гидроизоляционные ленты"), (r"гидроизоляц", r"аквастоп"), technical_patterns=(r"водонепроница", r"для гидроизоляции"),
             negative_category_patterns=(r"обув", r"одежд", r"палат"), backend_mapping=("waterproofing",)),
    WorkType("floor_screed", "Выравнивание и устройство стяжки пола", "Стяжка, наливной пол и ремонтные ровнители основания.", "rough", MAJOR_RENOVATIONS, ("primary_material", "preparation_material", "auxiliary_material", "tool"),
             (r"наливные полы", r"стяж", r"ровнители для пола"), (r"наливн.*пол", r"стяжк", r"ровнител.*пол"), technical_patterns=(r"толщина слоя", r"расход материала"),
             negative_category_patterns=(r"стяжки кабельные", r"мебельн", r"крепеж"),
             negative_text_patterns=(r"стяжк.*(?:кабель|мебель|дверн|хомут)",), backend_mapping=("floor_screed",)),
    WorkType("wall_plastering", "Штукатурное выравнивание стен и потолков", "Черновое выравнивание минеральными или полимерными штукатурками.", "rough", MAJOR_RENOVATIONS, ("primary_material", "preparation_material", "auxiliary_material", "tool"),
             (r"штукатурк", r"маяки штукатур"), (r"штукатур",), technical_patterns=(r"толщина слоя", r"основание"),
             negative_category_patterns=(r"декоративн.*штукатур",), backend_mapping=("wall_plastering",)),
    WorkType("drywall_install", "Монтаж гипсокартонных конструкций", "Монтаж листов ГКЛ/ГВЛ, каркаса, подвесов и специализированного крепежа.", "rough", MAJOR_RENOVATIONS, ("primary_material", "fastener", "auxiliary_material", "tool"),
             (r"гипсокарт", r"гвл", r"профили и аксессуары для гипсокартона"),
             (r"гипсокарт", r"\bгкл[впо]?\b", r"\bгвл\b", r"профил.*(?:гкл|гипсокарт)", r"подвес.*профил"), backend_mapping=("drywall_install",)),
    WorkType("wall_putty", "Шпатлевание стен и потолков", "Финишное или базовое шпатлевание перед окраской и оклейкой.", "white", ALL_RENOVATIONS, ("primary_material", "preparation_material", "auxiliary_material", "tool"),
             (r"шпатлев", r"шпаклев"), (r"шпатл", r"шпакл"), technical_patterns=(r"толщина слоя", r"под покраску", r"под обои"), backend_mapping=("wall_putty",)),
    WorkType("priming", "Грунтование поверхностей", "Подготовка основания грунтовками под конкретное последующее покрытие.", "white", ALL_RENOVATIONS, ("preparation_material", "tool"),
             (r"грунтовк",), (r"грунтовк", r"грунт-концентрат"), technical_patterns=(r"назначение", r"область применения", r"тип основания"),
             negative_text_patterns=(r"грунт-эмал", r"эмаль-грунт"), backend_mapping=("priming",), notes="Связь с последующей работой не выводится без явного назначения."),
    WorkType("tiling", "Облицовка плиткой и керамогранитом", "Укладка плитки с клеем, затиркой, системой выравнивания и профилями.", "finishing", ALL_RENOVATIONS, ("primary_material", "auxiliary_material", "consumable", "preparation_material", "tool"),
             (r"керамогранит", r"плитка настенная", r"плитка напольная", r"клей.*плит", r"затирки для плит", r"свп", r"уголки и бордюры для плитки"),
             (r"керамогранит", r"керамическ.*плит", r"плиточн.*клей", r"клей.*плит", r"затирк.*плит", r"систем.*выравнив.*плит"),
             negative_category_patterns=(r"плитка spc", r"плитка пвх", r"тротуар"), backend_mapping=("tiling",)),
    WorkType("wall_painting", "Окраска стен и потолков", "Нанесение интерьерных красок и совместимых малярных материалов/инструмента.", "finishing", ALL_RENOVATIONS, ("primary_material", "preparation_material", "consumable", "tool"),
             (r"краски для стен", r"краски интерьер", r"валики", r"кисти маляр", r"ванночки маляр"),
             (r"краск.*(?:стен|потол)", r"интерьерн.*краск", r"валик.*маляр", r"кист[ьи].*маляр"), technical_patterns=(r"влагостойкость краски", r"расход материала"),
             negative_category_patterns=(r"вентиляц", r"воздуховод", r"краски фасад", r"по металлу", r"автомобиль"),
             negative_text_patterns=(r"эмалированн", r"эмалевое покрытие"), backend_mapping=("wall_painting",)),
    WorkType("wallpapering", "Оклейка стен обоями", "Монтаж обоев и применение специализированного обойного клея и инструмента.", "finishing", ALL_RENOVATIONS, ("primary_material", "auxiliary_material", "preparation_material", "tool"),
             (r"^обои$", r"клей.*обо", r"инструмент.*обо"), (r"\bобои\b", r"обойн.*клей", r"клей.*обо"), technical_patterns=(r"вид обоев", r"влагостойкость обоев", r"тип основы"), backend_mapping=("wallpapering",)),
    WorkType("floor_covering_install", "Укладка напольных покрытий", "Монтаж ламината, линолеума, SPC/LVT и подложек; без керамической плитки.", "finishing", ALL_RENOVATIONS, ("primary_material", "auxiliary_material", "finishing_material", "tool"),
             (r"ламинат", r"линолеум", r"плитка spc", r"lvt", r"подложк", r"плинтус"),
             (r"ламинат", r"линолеум", r"\bspc\b", r"\blvt\b", r"подложк.*(?:ламинат|пол)", r"плинтус"),
             negative_category_patterns=(r"плинтусы потолочные",), backend_mapping=("laminate_laying", "linoleum_laying"), notes="Для backend потребуется разбиение по материалу."),
    WorkType("door_install", "Установка дверей", "Монтаж входных/межкомнатных дверей, коробок, наличников и дверной фурнитуры.", "finishing", ("capital", "euro", "rental"), ("primary_material", "auxiliary_material", "fastener", "finishing_material", "tool"),
             (r"двери межкомнат", r"двери вход", r"дверные короб", r"наличники", r"петли для двер", r"комплектующие для межкомнатных двер"),
             (r"дверн.*полотно", r"межкомнатн.*двер", r"входн.*двер", r"дверн.*короб", r"дверн.*петл", r"наличник"), notes="Новый вид относительно backend; мебельные петли исключаются категорией."),
    WorkType("electrical_fittings", "Установка электроустановочных изделий", "Финальный монтаж силовых розеток, выключателей и рамок.", "final", ALL_RENOVATIONS, ("primary_material", "auxiliary_material", "fastener", "tool"),
             (r"розетки (?:встраиваемые|накладные)", r"выключатели (?:встраиваемые|накладные)", r"рамки для розеток", r"переключатели встраиваемые"),
             (r"электрическ.*розет", r"розетк.*(?:встраиваем|накладн|заземлен)", r"выключател.*(?:встраиваем|накладн|клавиш)"),
             negative_category_patterns=(r"смесител", r"фитинг", r"водорозет", r"ручки нажимные"), negative_text_patterns=(r"водорозет",), backend_mapping=("electrical_fittings",)),
    WorkType("plumbing_install", "Установка сантехнических приборов", "Финальный монтаж смесителей, раковин, унитазов, ванн и душевого оборудования.", "final", ALL_RENOVATIONS, ("primary_material", "auxiliary_material", "fastener", "finishing_material", "tool"),
             (r"смесители", r"раковин", r"унитаз", r"ванны", r"душевые системы", r"мойки из", r"инсталляц"),
             (r"смесител", r"унитаз", r"раковин", r"душев.*систем", r"ванна .*акрил", r"мойка .*кухон"), backend_mapping=("plumbing_install",)),
    WorkType("lighting_install", "Установка стационарного освещения", "Монтаж потолочных, настенных, точечных и трековых светильников.", "final", ALL_RENOVATIONS, ("primary_material", "auxiliary_material", "fastener", "tool"),
             (r"люстры", r"светильники (?:точечные|настенно|подвесные|потолочные|трековых)", r"бра(?: |$)", r"споты"),
             (r"люстра", r"светильник.*(?:потолоч|настенн|встраиваем|подвесн|треков)", r"\bбра\b"),
             negative_category_patterns=(r"фонари", r"лампы настольные", r"уличн"), notes="Новый вид относительно backend; лампы как сменные товары сами по себе не означают монтаж."),
)


MATERIAL_ROLES = (
    ("primary_material", "Основной материал", "Формирует основное покрытие, конструкцию или установленное изделие."),
    ("auxiliary_material", "Вспомогательный материал", "Обеспечивает монтаж или совместную работу основного материала."),
    ("consumable", "Расходный материал", "Расходуется при выполнении работы и обычно не является основным покрытием."),
    ("tool", "Инструмент", "Используется для выполнения операции и обычно не остается частью результата."),
    ("fastener", "Крепёж", "Механически соединяет элементы в рамках конкретной работы."),
    ("preparation_material", "Подготовительный материал", "Подготавливает основание под конкретную последующую операцию."),
    ("finishing_material", "Финишный/доборный материал", "Закрывает стыки, кромки или завершает внешний вид."),
)


ROLE_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("tool", (r"валик", r"кист[ьи]", r"шпател", r"перфоратор", r"кувалд", r"инструмент", r"дрель")),
    ("fastener", (r"саморез", r"дюбел", r"анкер", r"гвозд", r"шуруп", r"креп[её]ж")),
    ("preparation_material", (r"грунтов", r"праймер", r"обезжирив")),
    ("consumable", (r"лента маляр", r"абразив", r"наждач", r"салфет")),
    ("auxiliary_material", (r"клей", r"затирк", r"герметик", r"подложк", r"профил", r"гофр", r"короб")),
    ("finishing_material", (r"плинтус", r"наличник", r"уголок", r"бордюр", r"порог")),
)


def regex_any(patterns: tuple[str, ...], text: str) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(0)
    return None


def role_for(work: WorkType, name: str, category_text: str) -> str:
    text = f"{name} {category_text}"
    for role, patterns in ROLE_PATTERNS:
        if regex_any(patterns, text) and role in work.required_material_roles:
            return role
    return "primary_material" if "primary_material" in work.required_material_roles else work.required_material_roles[0]


def classify_product(row: dict[str, Any]) -> dict[str, Any]:
    name = normalized_name(row["name"])
    categories = " | ".join(normalized_name(x) for x in row["category_names_list"])
    description = normalized_name(row["description_clean"])
    marketing = normalized_name(row["marketing_description_clean"])
    characteristic_text = " | ".join(
        f"{normalized_name(ch.get('name'))}: {normalized_name(ch.get('value'))}"
        for ch in row["characteristics_list"]
    )
    full_description = f"{description} {marketing}"
    assigned: list[str] = []
    roles: list[dict[str, str]] = []
    scores: dict[str, float] = {}
    evidence: dict[str, list[dict[str, Any]]] = {}
    reasons: list[str] = []
    conflicts: list[str] = []

    for work in WORK_TYPES:
        items: list[dict[str, Any]] = []
        score = 0.0
        category_hit = regex_any(work.category_patterns, categories)
        name_hit = regex_any(work.name_patterns, name)
        technical_hit = regex_any(work.technical_patterns, characteristic_text)
        description_hit = regex_any(work.name_patterns, full_description)
        negative_category = regex_any(work.negative_category_patterns, categories)
        negative_text = regex_any(work.negative_text_patterns, f"{name} {full_description} {characteristic_text}")

        if category_hit:
            score += 0.45
            items.append({"source": "category", "match": category_hit})
        if name_hit:
            score += 0.40
            items.append({"source": "name", "match": name_hit})
        if technical_hit:
            score += 0.30
            items.append({"source": "characteristics", "match": technical_hit})
        if description_hit:
            score += 0.15
            items.append({"source": "description", "match": description_hit})
        if negative_category:
            score -= 0.60
            items.append({"source": "negative_category", "match": negative_category})
        if negative_text:
            score -= 0.70
            items.append({"source": "negative_text", "match": negative_text})

        # A generic technical field name alone is not enough without category/name context.
        positive_sources = {item["source"] for item in items if not item["source"].startswith("negative")}
        threshold = 0.55
        valid_context = bool({"category", "name"} & positive_sources)
        if score >= threshold and valid_context:
            assigned.append(work.work_type_id)
            scores[work.work_type_id] = round(min(score, 1.0), 2)
            evidence[work.work_type_id] = items
            roles.append({"work_type_id": work.work_type_id, "material_role": role_for(work, name, categories)})
        elif score > 0 and (negative_category or negative_text):
            conflicts.append(work.work_type_id)

    max_score = max(scores.values(), default=0.0)
    renovation_hint = regex_any(
        (r"ремонт", r"монтаж", r"стен", r"пол(?:а|ов|у)?\b", r"потол", r"строит", r"электр", r"сантех", r"двер", r"плит", r"краск", r"обо"),
        f"{name} {categories}",
    )
    incomplete = not description and not marketing and not row["characteristics_list"]
    if assigned:
        outcome = "proposed_labels"
        if len(assigned) > 3:
            reasons.append("many_candidate_labels")
        if max_score < 0.70:
            reasons.append("low_confidence")
    elif conflicts:
        outcome = "conflicting_evidence"
        reasons.extend([f"suppressed_by_negative_evidence:{x}" for x in conflicts])
    elif incomplete:
        outcome = "insufficient_information"
        reasons.append("missing_description_marketing_and_characteristics")
    elif renovation_hint:
        outcome = "insufficient_evidence"
        reasons.append("renovation_context_without_supported_work_type")
    else:
        outcome = "outside_current_taxonomy"
        reasons.append("no_supported_renovation_work_evidence")

    needs_review = outcome != "outside_current_taxonomy" and (
        not assigned or max_score < 0.70 or len(assigned) > 1 or bool(conflicts) or incomplete
    )
    return {
        "product_id": row["product_id"],
        "proposed_work_types": json_text(assigned),
        "proposed_material_roles": json_text(roles),
        "label_scores": json_text(scores),
        "label_evidence": json_text(evidence),
        "labeling_method": "deterministic_rules_v1",
        "label_outcome": outcome,
        "label_reasons": json_text(reasons),
        "conflicting_work_types": json_text(conflicts),
        "review_status": "unreviewed",
        "needs_manual_review": bool(needs_review),
        "max_heuristic_score": max_score,
        "proposed_label_count": len(assigned),
    }


def load_and_clean() -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    with SOURCE.open(encoding="utf-8") as stream:
        payload = json.load(stream)
    products = payload["products"]
    product_rows: list[dict[str, Any]] = []
    characteristic_rows: list[dict[str, Any]] = []

    important_exact = {
        "назначение", "применение", "область применения", "сфера применения", "влагостойкость",
        "влагостойкость обоев", "влагостойкость краски", "износостойкость", "площадь покрытия",
        "площадь покрытия упаковкой", "расход", "расход материала", "класс нагрузки", "степень защиты",
        "степень защиты ip", "степень защиты от пыли и воды, ip",
    }

    for item in products:
        pid = int(item["id"])
        categories = {str(k): clean_text(v) for k, v in (item.get("categories") or {}).items()}
        characteristics = item.get("characteristics") or []
        recoverable: list[dict[str, Any]] = []
        important: defaultdict[str, list[str]] = defaultdict(list)
        occurrence: Counter[str] = Counter()
        for position, characteristic in enumerate(characteristics):
            original_name = "" if characteristic.get("name") is None else str(characteristic.get("name"))
            original_value = "" if characteristic.get("value") is None else str(characteristic.get("value"))
            clean_name = clean_text(original_name)
            clean_value = clean_text(original_value)
            norm_name = normalized_name(original_name)
            occurrence[norm_name] += 1
            number, parsed_unit, parse_status = parse_numeric(clean_value)
            recoverable.append({"name": original_name, "value": original_value})
            characteristic_rows.append({
                "product_id": pid,
                "characteristic_position": position,
                "characteristic_name": norm_name,
                "characteristic_value": clean_value,
                "original_name": original_name,
                "original_value": original_value,
                "occurrence_index": occurrence[norm_name],
                "numeric_value": number,
                "parsed_unit": parsed_unit,
                "numeric_parse_status": parse_status,
            })
            if norm_name in important_exact:
                important[norm_name].append(clean_value)

        description_clean = clean_text(item.get("description"))
        marketing_clean = clean_text(item.get("marketing_description"))
        brand = item.get("brand") or {}
        collection = item.get("collection") or {}
        country = item.get("country") or {}
        product_rows.append({
            "product_id": pid,
            "cod_good": "" if item.get("cod_good") is None else str(item.get("cod_good")),
            "name": clean_text(item.get("name")),
            "category_ids": json_text(list(categories.keys())),
            "category_names": json_text(list(categories.values())),
            "source_category": " | ".join(categories.values()),
            "categories_json": json_text(categories),
            "description_clean": description_clean,
            "marketing_description_clean": marketing_clean,
            "brand_name": clean_text(brand.get("name")),
            "brand_id": "" if brand.get("id") is None else str(brand.get("id")),
            "collection_name": clean_text(collection.get("name")),
            "collection_id": "" if collection.get("id") is None else str(collection.get("id")),
            "country_name": clean_text(country.get("name")),
            "country_id": "" if country.get("id") is None else str(country.get("id")),
            "price": item.get("price"),
            "currency": clean_text(item.get("currency")),
            "sale_unit": clean_text(item.get("unit")),
            "source_weight": item.get("weight"),
            "url_key": clean_text(item.get("url_key")),
            "important_attributes_json": json_text(dict(important)),
            "characteristics_json": json_text(recoverable),
            "characteristic_count": len(characteristics),
            "has_description": bool(description_clean),
            "has_marketing_description": bool(marketing_clean),
            "has_characteristics": bool(characteristics),
            "information_completeness": round(sum([bool(description_clean), bool(marketing_clean), bool(characteristics), bool(categories), bool(item.get("unit"))]) / 5, 2),
            # Internal objects removed before writing CSV.
            "category_names_list": list(categories.values()),
            "characteristics_list": characteristics,
        })

    products_df = pd.DataFrame(product_rows)
    characteristics_df = pd.DataFrame(characteristic_rows)
    source_stats = {
        "product_count": len(products_df),
        "unique_product_ids": int(products_df["product_id"].nunique()),
        "unique_cod_good": int(products_df["cod_good"].nunique()),
        "duplicate_cod_good_rows": int(products_df.duplicated("cod_good", keep=False).sum()),
        "characteristic_rows": len(characteristics_df),
        "products_without_characteristics": int((~products_df["has_characteristics"]).sum()),
        "products_without_sale_unit": int((products_df["sale_unit"] == "").sum()),
        "products_without_description": int((~products_df["has_description"]).sum()),
        "products_without_marketing": int((~products_df["has_marketing_description"]).sum()),
        "duplicate_normalized_names_rows": int(products_df["name"].str.lower().duplicated(keep=False).sum()),
        "duplicate_nonempty_descriptions_rows": int(products_df.loc[products_df["description_clean"] != "", "description_clean"].duplicated(keep=False).sum()),
    }
    return products_df, characteristics_df, source_stats


def taxonomy_tables(products_df: pd.DataFrame, labels_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    by_id = products_df.set_index("product_id")
    label_lookup = labels_df.set_index("product_id")
    rows: list[dict[str, Any]] = []
    outside_ids = labels_df.loc[labels_df["label_outcome"] == "outside_current_taxonomy", "product_id"].tolist()
    for work_index, work in enumerate(WORK_TYPES):
        positives = labels_df[labels_df["proposed_work_types"].map(lambda x: work.work_type_id in json.loads(x))]
        positive_examples = []
        for pid in positives.sort_values(["max_heuristic_score", "product_id"], ascending=[False, True])["product_id"].head(3):
            product = by_id.loc[pid]
            positive_examples.append({"product_id": int(pid), "name": product["name"]})
        negatives = labels_df[
            (labels_df["label_outcome"] == "conflicting_evidence")
            & labels_df["conflicting_work_types"].map(lambda x: work.work_type_id in json.loads(x))
        ]
        negative_examples = [
            {"product_id": int(pid), "name": by_id.loc[pid, "name"]}
            for pid in negatives["product_id"].head(3)
        ]
        # Ensure every taxonomy row documents real catalog negatives. When no
        # rule-specific conflict exists, use deterministic clearly out-of-scope
        # catalog products rather than inventing a technical incompatibility.
        if not negative_examples:
            start = work_index * 3
            fallback_ids = outside_ids[start : start + 3]
            negative_examples = [
                {"product_id": int(pid), "name": by_id.loc[pid, "name"]}
                for pid in fallback_ids
            ]
        ambiguous = labels_df[
            labels_df["proposed_work_types"].map(lambda x: work.work_type_id in json.loads(x))
            & labels_df["needs_manual_review"]
        ]
        ambiguous_examples = [
            {"product_id": int(pid), "name": by_id.loc[pid, "name"]}
            for pid in ambiguous.sort_values(["max_heuristic_score", "product_id"])["product_id"].head(3)
        ]
        rows.append({
            "work_type_id": work.work_type_id,
            "work_type_name": work.work_type_name,
            "description": work.description,
            "renovation_stage": work.renovation_stage,
            "possible_renovation_types": json_text(work.possible_renovation_types),
            "required_material_roles": json_text(work.required_material_roles),
            "related_catalog_categories": json_text(work.category_patterns),
            "positive_examples": json_text(positive_examples),
            "negative_examples": json_text(negative_examples),
            "ambiguous_examples": json_text(ambiguous_examples),
            "backend_mapping": json_text(work.backend_mapping),
            "notes": work.notes,
        })
    work_df = pd.DataFrame(rows)
    roles_df = pd.DataFrame(MATERIAL_ROLES, columns=["material_role_id", "material_role_name", "description"])
    roles_df["scope"] = "Role is assigned per product-work_type relation, not globally per product."

    category_rows: list[dict[str, Any]] = []
    category_counts: Counter[tuple[str, str]] = Counter()
    for _, row in products_df.iterrows():
        cats = json.loads(row["categories_json"])
        category_counts.update(cats.items())
    for (category_id, category_name), count in sorted(category_counts.items(), key=lambda x: (-x[1], x[0][1])):
        normalized_category = normalized_name(category_name)
        matched = [w.work_type_id for w in WORK_TYPES if regex_any(w.category_patterns, normalized_category) and not regex_any(w.negative_category_patterns, normalized_category)]
        category_rows.append({
            "category_id": category_id,
            "category_name": category_name,
            "product_count": count,
            "candidate_work_types": json_text(matched),
            "mapping_status": "draft_candidate" if matched else "unmapped_or_outside_taxonomy",
            "mapping_basis": "category_pattern_context_only",
            "requires_product_level_evidence": True,
        })
    return work_df, roles_df, pd.DataFrame(category_rows)


def select_manual_sample(products_df: pd.DataFrame, labels_df: pd.DataFrame) -> pd.DataFrame:
    merged = products_df.merge(labels_df, left_on="product_id", right_on="product_id", validate="one_to_one")
    selected: list[int] = []
    strata: list[tuple[str, pd.Series, int]] = []
    for work in [w.work_type_id for w in WORK_TYPES]:
        mask = merged["proposed_work_types"].map(lambda value, w=work: w in json.loads(value))
        strata.append((f"work_type:{work}", mask, 8))
    strata.extend([
        ("multi_label", merged["proposed_label_count"] > 1, 45),
        ("low_confidence", (merged["proposed_label_count"] > 0) & (merged["max_heuristic_score"] < 0.70), 45),
        ("conflicting", merged["label_outcome"] == "conflicting_evidence", 40),
        ("unlabeled_renovation", merged["label_outcome"] == "insufficient_evidence", 40),
        ("incomplete", merged["label_outcome"] == "insufficient_information", 30),
        ("hard_negative", merged["label_outcome"] == "outside_current_taxonomy", 45),
    ])
    membership: defaultdict[int, list[str]] = defaultdict(list)
    for index, (stratum, mask, target) in enumerate(strata):
        candidates = merged.loc[mask & ~merged.index.isin(selected)]
        n = min(target, len(candidates))
        if n:
            picked = candidates.sample(n=n, random_state=RANDOM_SEED + index).index.tolist()
            selected.extend(picked)
            for idx in picked:
                membership[idx].append(stratum)

    remaining = SAMPLE_SIZE - len(set(selected))
    if remaining > 0:
        candidates = merged.loc[~merged.index.isin(selected)]
        picked = candidates.sample(n=min(remaining, len(candidates)), random_state=RANDOM_SEED + 999).index.tolist()
        selected.extend(picked)
        for idx in picked:
            membership[idx].append("random_catalog")
    selected = list(dict.fromkeys(selected))[:SAMPLE_SIZE]
    sample = merged.loc[selected].copy()
    sample["sampling_strata"] = [json_text(membership[idx]) for idx in sample.index]
    sample["relevant_description"] = sample.apply(
        lambda row: compact(row["marketing_description_clean"] or row["description_clean"], 700), axis=1
    )
    sample["technical_characteristics"] = sample["important_attributes_json"]
    sample["reviewed_work_types"] = ""
    sample["reviewed_material_roles"] = ""
    sample["review_notes"] = ""
    sample["review_status"] = "unreviewed"
    columns = [
        "product_id", "cod_good", "name", "source_category", "relevant_description",
        "technical_characteristics", "proposed_work_types", "proposed_material_roles",
        "label_evidence", "label_scores", "label_outcome", "label_reasons",
        "needs_manual_review", "sampling_strata", "reviewed_work_types",
        "reviewed_material_roles", "review_notes", "review_status",
    ]
    return sample[columns].sort_values("product_id")


def validate(
    products_df: pd.DataFrame,
    characteristics_df: pd.DataFrame,
    labels_df: pd.DataFrame,
    work_df: pd.DataFrame,
    sample_df: pd.DataFrame,
) -> list[str]:
    checks: list[tuple[bool, str]] = [
        (len(products_df) == 88790, "Количество товаров равно числу записей источника"),
        (products_df["product_id"].is_unique, "product_id уникален"),
        (products_df["cod_good"].map(type).eq(str).all(), "cod_good сохранён как строка"),
        (labels_df["product_id"].is_unique and len(labels_df) == len(products_df), "Слабая разметка содержит ровно одну строку на товар"),
        (set(labels_df["product_id"]) == set(products_df["product_id"]), "Ни один сложный или неразмеченный товар не потерян"),
        (len(sample_df) == SAMPLE_SIZE, f"Ручная выборка содержит {SAMPLE_SIZE} строк"),
        ((sample_df["review_status"] == "unreviewed").all(), "Автоматические метки не отмечены как проверенные"),
        (characteristics_df["characteristic_position"].notna().all(), "Каждое вхождение характеристики имеет позицию"),
    ]
    valid_work_ids = set(work_df["work_type_id"])
    for column in ["proposed_work_types", "proposed_material_roles", "label_scores", "label_evidence", "label_reasons"]:
        try:
            labels_df[column].map(json.loads)
            checks.append((True, f"{column}: валидный JSON"))
        except (json.JSONDecodeError, TypeError):
            checks.append((False, f"{column}: валидный JSON"))
    emitted = {item for value in labels_df["proposed_work_types"] for item in json.loads(value)}
    checks.append((emitted <= valid_work_ids, "Все выданные work_type_id существуют в черновой таксономии"))
    failed = [message for ok, message in checks if not ok]
    if failed:
        raise AssertionError("Validation failed: " + "; ".join(failed))
    return ["PASS — " + message for _, message in checks]


def write_reports(
    products_df: pd.DataFrame,
    characteristics_df: pd.DataFrame,
    labels_df: pd.DataFrame,
    work_df: pd.DataFrame,
    category_df: pd.DataFrame,
    sample_df: pd.DataFrame,
    stats: dict[str, Any],
    checks: list[str],
) -> None:
    category_counts = Counter()
    for text in products_df["category_names"]:
        category_counts.update(json.loads(text))
    characteristic_counts = characteristics_df["characteristic_name"].value_counts()
    duplicate_characteristics = (
        characteristics_df.groupby(["product_id", "characteristic_name"], dropna=False).size().gt(1).groupby(level=0).any().sum()
    )
    conflicting_characteristics = characteristics_df.groupby(["product_id", "characteristic_name"], dropna=False)["original_value"].nunique().gt(1).sum()
    numeric_parse_counts = characteristics_df["numeric_parse_status"].value_counts().to_dict()

    data_report = f"""# Анализ и подготовка каталога

Все результаты построены из read-only источника `requirments/products_final.json` (SHA-256 `{SOURCE_SHA256}`). Использован pandas {pd.__version__}. Дата/seed воспроизводимости: `{RANDOM_SEED}`.

## Основные результаты

- Товаров: **{stats['product_count']:,}**; уникальных `id`: **{stats['unique_product_ids']:,}**.
- Уникальных `cod_good`: **{stats['unique_cod_good']:,}**; строк, входящих в группы повторяющихся `cod_good`: **{stats['duplicate_cod_good_rows']:,}**. `id` и `cod_good` сохранены раздельно, артикул — строкой.
- Строк характеристик: **{stats['characteristic_rows']:,}**; нормализованных написаний имён: **{characteristics_df['characteristic_name'].nunique():,}**.
- Без массива характеристик: **{stats['products_without_characteristics']:,}**; без единицы продажи: **{stats['products_without_sale_unit']:,}**; без описания: **{stats['products_without_description']:,}**; без marketing description: **{stats['products_without_marketing']:,}**.
- Товаров с повторным именем характеристики: **{int(duplicate_characteristics):,}**; пар товар–характеристика с различающимися повторными значениями: **{int(conflicting_characteristics):,}**.
- Строки характеристик с однозначным числом: **{numeric_parse_counts.get('exact_number', 0):,}**, с числом и явной единицей: **{numeric_parse_counts.get('number_with_unit', 0):,}**, намеренно не разобраны: **{numeric_parse_counts.get('not_parsed', 0):,}**.

## Решения по обработке

`products_clean.csv` содержит одну строку на исходный товар и не содержит work-type меток. HTML-разрывы строк очищены, исходные description и marketing description сохранены раздельно. Категории и весь список характеристик сериализованы в JSON; это позволяет восстановить порядок и повторы. Отдельная long-table `product_characteristics.csv` хранит позицию, оригинальные имя/значение, консервативно нормализованное имя и только безопасно распознанное скалярное число.

Нормализация имени характеристики ограничена Unicode NFKC, регистром, `ё→е` и пробелами. Технически разные поля (например, `Влагостойкость`, `Влагостойкость обоев`, `Влагостойкость краски`) не объединяются. Неоднозначные размеры, диапазоны и составные значения не превращаются в выдуманные числа.

Единица продажи не подменяется технической единицей измерения. Пустая единица остаётся пустой. Поле `weight` в источнике полностью пустое, поэтому не выводится из названия или характеристик.

## Категории и нерелевантный ассортимент

Каталог содержит **{len(category_counts):,}** разных названий категорий. В нём одновременно присутствуют стройматериалы и товары вне текущего scope: семена, посуда, текстиль, обувь, растения и т. п. Такие товары сохраняются, но правила могут оставить их без work-type.

Наиболее крупные категории:

""" + "\n".join(f"- {name}: {count:,}" for name, count in category_counts.most_common(20)) + """

## Частые характеристики

""" + "\n".join(f"- `{name}`: {count:,}" for name, count in characteristic_counts.head(20).items()) + """

## Проверки

""" + "\n".join(f"- {check}" for check in checks) + """

Исходный файл после генерации повторно проверяется по SHA-256. CSV следует читать с UTF-8; JSON-поля — через `json.loads`. Пропуски не интерпретируются как отрицательные признаки.
"""

    proposed = "\n".join(f"- `{r.work_type_id}` — {r.work_type_name} ({r.renovation_stage})" for r in WORK_TYPES)
    taxonomy_report = f"""# Анализ черновой таксономии

Таксономия содержит **{len(WORK_TYPES)}** видов работ. Это немного выше исходного ориентира 10–15: реальные категории требуют отдельно учитывать двери и стационарное освещение, а сантехнический/электрический черновой монтаж нельзя смешивать с финальной установкой приборов.

## Виды работ

{proposed}

`renovation_stage` — этап процесса; `renovation_type` — пакет/масштаб ремонта; `work_type` — конкретная операция; `material_role` — функция товара в отношении конкретной операции. Стадия и тип ремонта не присваиваются товару напрямую. Возможные renovation types в CSV описывают, в каких пакетах обычно встречается работа, а не автоматически выведенную принадлежность товара.

## Multi-label и роли

Связь хранится как `product → work_type → material_role`. Один SKU может иметь несколько работ, а роль может различаться между ними. Multi-label означает несколько независимо подтверждённых контекстов применения, а не несколько слов в названии. Универсальная грунтовка получает `priming`; связь с окраской, обоями или плиткой не добавляется без явных технических сведений.

## Отличия от `app/taxonomy.py`

Большинство ID сохранено или имеет прямое соответствие. `floor_covering_install` объединяет backend-ID `laminate_laying` и `linoleum_laying`, поскольку каталог также содержит SPC/LVT; при интеграции его нужно снова специализировать по материалу либо одобрить новый общий ID. Добавлены `door_install` и `lighting_install`, которых backend сейчас не знает. Все остальные соответствия записаны в `backend_mapping`.

Backend `Suggestion` и `BindingIn` уже допускают `work_types: list[WorkType]`, то есть multi-label поддержан, но `material` там один глобальный. Контекстные material roles текущая схема не представляет: потребуется отдельная relation/list structure после согласования. `RoomInput.works` может ограничить работы комнаты. Для будущего room-aware ranking сохранены характеристики, цена, единица, brand, расход/площадь, влагостойкость, износостойкость, класс нагрузки и IP, но понадобятся подтверждённые room constraints, наличие/остатки, совместимость и независимые признаки качества. Цена сама по себе не является качеством.

`category_mapping_draft.csv` — только контекстный черновик. Категория не является work type и не гарантирует метку отдельному товару.

## Неопределённости для согласования

1. Одобрить ли новые `door_install` и `lighting_install`.
2. Оставить общий `floor_covering_install` или сохранить отдельные backend-классы для ламината и линолеума плюс добавить SPC/LVT.
3. Нужна ли отдельная работа для фасадной окраски/наружных работ: текущий scope ориентирован на помещения, поэтому фасадные краски исключены из `wall_painting`.
4. Как формально трактовать «Белую отделку»: здесь это подготовленная под финиш поверхность (шпатлевание/грунтование), но термин неоднозначен и требует продуктового подтверждения.
"""

    dist: Counter[str] = Counter()
    for value in labels_df["proposed_work_types"]:
        dist.update(json.loads(value))
    outcomes = labels_df["label_outcome"].value_counts().to_dict()
    evidence_sources: Counter[str] = Counter()
    for value in labels_df["label_evidence"]:
        for items in json.loads(value).values():
            evidence_sources.update(item["source"] for item in items)
    examples = labels_df[labels_df["needs_manual_review"]].head(12)[["product_id", "label_outcome", "label_reasons"]]
    weak_report = f"""# Отчёт о предварительной слабой разметке

Все метки **предварительные**, `review_status=unreviewed`; это не ground truth и не оценка модели. F1 не рассчитывался, потому что независимого ручного test set нет.

## Итоги

- Товаров хотя бы с одной предложенной меткой: **{int((labels_df['proposed_label_count'] > 0).sum()):,}**.
- Без предложенных меток: **{int((labels_df['proposed_label_count'] == 0).sum()):,}**.
- Multi-label товаров: **{int((labels_df['proposed_label_count'] > 1).sum()):,}**.
- Помечены для приоритетной ручной проверки: **{int(labels_df['needs_manual_review'].sum()):,}**.
- Низкий score (<0.70 при наличии метки): **{int(((labels_df['proposed_label_count'] > 0) & (labels_df['max_heuristic_score'] < 0.70)).sum()):,}**.
- Подавленные конфликтом положительного и отрицательного свидетельства: **{outcomes.get('conflicting_evidence', 0):,}**.

Исходы: {json_text(outcomes)}.

## Распределение видов работ

""" + "\n".join(f"- `{name}`: {count:,}" for name, count in dist.most_common()) + f"""

## Скоринг и трассировка

Баллы суммируются детерминированно: категория +0.45, название +0.40, техническая характеристика +0.30, описание +0.15, отрицательная категория −0.60, явное отрицательное текстовое свидетельство −0.70. Для выдачи нужно не менее 0.55 и контекст из категории или названия. Score ограничивается единицей и является приоритетом проверки, **не калиброванной вероятностью**. Порог backend 0.8 не используется как доказательство корректности.

Частота источников у выданных меток: {json_text(evidence_sources)}. `label_evidence` хранит источник и совпавший фрагмент для каждой метки. Пропуск никогда не считается отрицательным доказательством.

## Сложные случаи

- `водорозетка` явно подавляет `electrical_fittings` и поддерживает `plumbing_rough`.
- `эмалированное/эмалевое покрытие` и вентиляционная категория подавляют ложную окраску воздуховодов.
- Грунтовка не размножается на все возможные последующие операции; предлагается только `priming`, если нет отдельного явного контекста.
- Керамическая плитка отделена от SPC/PVC отрицательными category patterns.
- Фасадная и антикоррозионная краска не считается интерьерной окраской стен.

Примеры приоритетной проверки:

""" + "\n".join(f"- ID {r.product_id}: {r.label_outcome}; `{r.label_reasons}`" for r in examples.itertuples()) + """

Ограничения: правила остаются лексико-структурными эвристиками и не доказывают фактическую совместимость; категории дают контекст, но короткие/ошибочные карточки и необычные названия потребуют ручного решения. Описание иногда содержит маркетинговые упоминания, не являющиеся назначением.
"""

    sample_strata: Counter[str] = Counter()
    for value in sample_df["sampling_strata"]:
        sample_strata.update(json.loads(value))
    guide = f"""# Руководство по ручной аннотации

Файл `manual_review_sample.csv` содержит **{len(sample_df)}** товаров; seed `{RANDOM_SEED}`. Выборка сочетает покрытие каждого work type, multi-label, низкий score, конфликты, неполные карточки, hard negatives и случайный остаток. Распределение sampling strata: `{json_text(sample_strata)}`.

Эта выборка намеренно обогащена трудными случаями и **не репрезентативна** для частот полного каталога. По ней нельзя честно оценивать catalog-wide micro-F1. Позже нужен отдельный независимо отобранный и вручную проверенный evaluation set.

## Как заполнять

1. Сначала прочитайте название, категорию, релевантное описание и технические характеристики; proposed labels и evidence используйте как подсказку, а не истину.
2. В `reviewed_work_types` внесите JSON-массив ID из `work_types_draft.csv`, например `["tiling","waterproofing"]`. Оставляйте несколько работ только при независимом подтверждении каждой.
3. В `reviewed_material_roles` внесите JSON-массив объектов `{{"work_type_id":"tiling","material_role":"auxiliary_material"}}`. Роль определяется отдельно для каждой работы.
4. Если применимость неизвестна из карточки, не приравнивайте это к нерелевантности: оставьте reviewed fields пустыми, укажите `unknown_applicability` в notes/status и причину.
5. Если товар точно вне таксономии, используйте пустой JSON-массив `[]` и отметьте в notes `confirmed_irrelevant`.
6. После фактической проверки поменяйте `review_status` на `reviewed`; до этого сохраняйте `unreviewed`.
7. Не выводите свойства из цены, бренда или отсутствующего поля. Противоречия между категорией, названием и характеристиками опишите в `review_notes`.

## Контроль согласованности

Используйте только допустимые work type и material role ID. Не присваивайте renovation stage/type непосредственно товару. Для универсальных материалов указывайте несколько работ лишь когда область применения явно подтверждена. Не исправляйте `products_clean.csv`: ручные решения должны жить в отдельном аннотационном файле.
"""

    (REPORTS_DIR / "data_analysis.md").write_text(data_report, encoding="utf-8")
    (REPORTS_DIR / "taxonomy_analysis.md").write_text(taxonomy_report, encoding="utf-8")
    (REPORTS_DIR / "weak_labeling_report.md").write_text(weak_report, encoding="utf-8")
    (REPORTS_DIR / "manual_annotation_guide.md").write_text(guide, encoding="utf-8")


def main() -> None:
    for directory in (DATA_DIR, TAXONOMY_DIR, REPORTS_DIR):
        directory.mkdir(parents=True, exist_ok=True)
    before_hash = sha256(SOURCE)
    if before_hash != SOURCE_SHA256:
        raise RuntimeError(f"Unexpected source hash: {before_hash}")
    for work in WORK_TYPES:
        pattern_groups = (
            work.category_patterns, work.name_patterns, work.technical_patterns,
            work.negative_category_patterns, work.negative_text_patterns,
        )
        if any(isinstance(group, str) for group in pattern_groups):
            raise TypeError(f"Regex group must be a tuple for {work.work_type_id}")

    products_df, characteristics_df, stats = load_and_clean()
    labels_df = pd.DataFrame(classify_product(row) for row in products_df.to_dict("records"))
    work_df, roles_df, category_df = taxonomy_tables(products_df, labels_df)
    sample_df = select_manual_sample(products_df, labels_df)
    checks = validate(products_df, characteristics_df, labels_df, work_df, sample_df)

    clean_output = products_df.drop(columns=["category_names_list", "characteristics_list"])
    clean_output.to_csv(DATA_DIR / "products_clean.csv", index=False, encoding="utf-8")
    characteristics_df.to_csv(DATA_DIR / "product_characteristics.csv", index=False, encoding="utf-8")
    category_df.to_csv(DATA_DIR / "categories_summary.csv", index=False, encoding="utf-8")
    labels_df.to_csv(DATA_DIR / "products_weak_labeled.csv", index=False, encoding="utf-8")
    sample_df.to_csv(DATA_DIR / "manual_review_sample.csv", index=False, encoding="utf-8-sig")
    work_df.to_csv(TAXONOMY_DIR / "work_types_draft.csv", index=False, encoding="utf-8")
    roles_df.to_csv(TAXONOMY_DIR / "material_roles_draft.csv", index=False, encoding="utf-8")
    category_df.to_csv(TAXONOMY_DIR / "category_mapping_draft.csv", index=False, encoding="utf-8")

    write_reports(products_df, characteristics_df, labels_df, work_df, category_df, sample_df, stats, checks)
    after_hash = sha256(SOURCE)
    if before_hash != after_hash:
        raise RuntimeError("Source catalog changed during processing")
    print(json.dumps({
        "source_sha256": after_hash,
        "products": len(products_df),
        "characteristics": len(characteristics_df),
        "labeled": int((labels_df["proposed_label_count"] > 0).sum()),
        "multi_label": int((labels_df["proposed_label_count"] > 1).sum()),
        "manual_review_sample": len(sample_df),
        "work_types": len(work_df),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

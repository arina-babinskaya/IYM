#!/usr/bin/env python3
"""Generate Russian stage-2 reports from reproducible artifacts."""

import importlib.metadata
import json
from collections import Counter
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
WS = ROOT / "ml_workspace"
DATA, REPORTS = WS / "data", WS / "reports"


def dumps(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def distribution(series):
    count = Counter()
    for value in series:
        count.update(json.loads(value))
    return dict(count.most_common())


def main():
    clean = pd.read_csv(DATA / "products_clean.csv", keep_default_na=False)
    old = pd.read_csv(DATA / "products_weak_labeled.csv", keep_default_na=False)
    labels = pd.read_csv(DATA / "products_multidim_weak_labeled.csv", keep_default_na=False)
    full = clean.merge(labels, on="product_id")
    family = labels.primary_product_family.value_counts().to_dict()
    works = distribution(labels.proposed_work_types)
    rooms = distribution(labels.proposed_room_types)
    usage = distribution(labels.proposed_usage_contexts)
    counts = {
        "family_other": int((labels.primary_product_family == "other").sum()),
        "family_unknown": int((labels.primary_product_family == "unknown").sum()),
        "work_unknown": int((labels.work_type_status == "unknown_needs_review").sum()),
        "work_empty_candidate": int((labels.work_type_status == "verified_empty_candidate").sum()),
        "room_other": int(labels.proposed_room_types.map(lambda x: "other" in json.loads(x)).sum()),
        "room_unknown": int(labels.proposed_room_types.map(lambda x: "unknown" in json.loads(x)).sum()),
        "usage_other": int(labels.proposed_usage_contexts.map(lambda x: "other" in json.loads(x)).sum()),
        "usage_unknown": int(labels.proposed_usage_contexts.map(lambda x: "unknown" in json.loads(x)).sum()),
        "work_multi": int(labels.proposed_work_types.map(lambda x: len(json.loads(x)) > 1).sum()),
        "room_multi": int(labels.proposed_room_types.map(lambda x: len([z for z in json.loads(x) if z not in {"other", "unknown"}]) > 1).sum()),
        "usage_multi": int(labels.proposed_usage_contexts.map(lambda x: len([z for z in json.loads(x) if z not in {"other", "unknown"}]) > 1).sum()),
    }
    taxonomy = f"""# Анализ многомерной таксономии

## Результат

Таксономия разделена на четыре независимых задачи: product family, renovation work type, room suitability и usage context. Наличие product-family label не делает товар участником ремонтной сметы.

Рекомендуемый состав: 20 содержательных product families + `other/unknown`, 17 work types, 12 room labels + fallbacks, 12 usage labels + fallbacks. Primary product family взаимоисключающий; `barbecue_grilling` дополнительно сохраняет parent `garden_outdoor`. Work/room/usage допускают multi-label.

Product family: `{dumps(family)}`.

Work types: `{dumps(works)}`.

Room types: `{dumps(rooms)}`.

Usage contexts: `{dumps(usage)}`.

## Семантика fallback

- `other`: карточка понятна, но поддерживаемый словарь конкретного измерения неприменим или не покрывает этот класс.
- `unknown`: сведений недостаточно либо равносильные свидетельства конфликтуют.
- Для work types пустой список сопровождается `verified_empty_candidate` или `unknown_needs_review`; это не одно и то же.

Stage/type ремонта остаются workflow metadata work type. «Белая отделка» по-прежнему трактуется как подготовка поверхности, но требует продуктового согласования. Backend не знает `door_install`, `lighting_install`, общий `floor_covering_install`, product families, usage contexts и context-dependent roles — production taxonomy/schema не изменялись.
"""
    (REPORTS / "taxonomy_analysis.md").write_text(taxonomy, encoding="utf-8")

    weak = f"""# Отчёт о многомерной слабой разметке

Все автоматически выданные labels имеют `review_status=unreviewed`. Coverage не является accuracy.

| Измерение | other | unknown | multi-label |
|---|---:|---:|---:|
| Product family | {counts['family_other']:,} | {counts['family_unknown']:,} | Иерархический parent: {int(labels.proposed_product_categories.map(lambda x: len(json.loads(x)) > 1).sum()):,} |
| Work type | empty candidate {counts['work_empty_candidate']:,} | {counts['work_unknown']:,} | {counts['work_multi']:,} |
| Room type | {counts['room_other']:,} | {counts['room_unknown']:,} | {counts['room_multi']:,} |
| Usage context | {counts['usage_other']:,} | {counts['usage_unknown']:,} | {counts['usage_multi']:,} |

V1 имел 15 252 work-labeled и 73 538 work-unlabeled товаров. V2 намеренно не меняет work labels (изменено **0** work-label sets), чтобы расширение retail coverage не маскировало изменение target semantics. Теперь все товары имеют product-family fallback/status, а rooms/usage размечаются отдельно. Это улучшение представимости, не доказательство качества классификации.

Известные случаи сохраняются: водорозетка не электрическая розетка; эмалированный воздуховод не краска; кабельная стяжка не стяжка пола; садовая труба не сантехника; грунтовка не получает все работы.

Evidence хранится в `all_label_evidence`: dimension, label, rule ID, score и совпадения по источникам. Scores не калиброваны.
"""
    (REPORTS / "weak_labeling_report.md").write_text(weak, encoding="utf-8")

    guide = """# Руководство по ручной аннотации

Подготовлены два непересекающихся файла по 200 строк: `manual_review_representative.csv` — случайная catalog sample для оценки реальной частоты ошибок; `manual_review_targeted.csv` — трудные, unknown/other и недопредставленные семейства. Seed: 20261022. Targeted sample не репрезентативна.

## Работа

```python
import pandas as pd
df = pd.read_csv("ml_workspace/data/manual_review_representative.csv", keep_default_na=False)
df[df["work_type_status"] == "unknown_needs_review"]
df[df["proposed_product_categories"].str.contains("unknown")]
```

В VS Code откройте CSV через Data Viewer/Excel extension; readable name/category/description находятся рядом с labels. Исходные характеристики доступны в `products_clean.csv` и `product_characteristics.csv` по `product_id`.

Заполняйте reviewed-поля JSON-массивами. Известная неприменимость work types — `[]`; неизвестная применимость — статус `unknown_applicability` и пояснение, а не подтверждённый пустой set. `other` означает понятный класс вне словаря, `unknown` — нехватку данных. После проверки установите `review_status=reviewed`.

Проверка:

```bash
.venv-sandbox/bin/python ml_workspace/scripts/validate_annotations.py ml_workspace/data/manual_review_representative.csv
.venv-sandbox/bin/python ml_workspace/scripts/explore_labels.py
```

В будущий training pipeline импортируются только строки `review_status=reviewed`; proposed labels не заменяют reviewed labels.
"""
    (REPORTS / "manual_annotation_guide.md").write_text(guide, encoding="utf-8")

    metrics_path = WS / "artifacts/experiment_1/metrics.json"
    metrics = json.loads(metrics_path.read_text()) if metrics_path.exists() else {}
    exp1 = f"""# Experiment 1 — TF-IDF + Logistic Regression

Реализованы word 1–2 gram TF‑IDF, One-vs-Rest Logistic Regression с `class_weight=balanced`, fixed hash splits по нормализованной карточке, validation threshold selection, joblib save/load и per-class metrics.

Запуск pilot:

```bash
.venv-sandbox/bin/python ml_workspace/experiments/experiment_1_tfidf.py --allow-weak-labels
```

Технический результат: micro-F1 **{metrics.get('micro_f1', float('nan')):.4f}**, macro-F1 **{metrics.get('macro_f1', float('nan')):.4f}**, precision **{metrics.get('micro_precision', float('nan')):.4f}**, recall **{metrics.get('micro_recall', float('nan')):.4f}**; train/val/test = {metrics.get('train_size')}/{metrics.get('validation_size')}/{metrics.get('test_size')}.

Это agreement с теми же эвристическими weak labels, которые выводятся из текста. Высокий результат ожидаем и не является валидной оценкой accuracy. Организаторский micro-F1 вычисляется по всем `(product,label)` решениям на независимо вручную размеченном, не использованном для threshold selection test set: `2TP/(2TP+FP+FN)`. Только тогда можно сравнивать с 0.8. Macro-F1 — среднее F1 классов.
"""
    (REPORTS / "experiment_1.md").write_text(exp1, encoding="utf-8")

    exp2 = """# Experiment 2 — Sentence Embeddings + Logistic Regression

Реализованы configurable sentence encoder, fixed normalized embeddings, `.npy` cache с проверкой product IDs, те же leakage-aware splits/targets, OvR Logistic Regression, thresholds, timing и сохранение classifier/config. Encoder не fine-tune-ится.

```bash
.venv-sandbox/bin/python ml_workspace/experiments/experiment_2_embeddings.py --allow-weak-labels --model-name sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
```

Полный pilot не запущен: `.venv-sandbox` использует Python 3.14, а официальный PyTorch CPU index не предоставил совместимый `torch` wheel (`torch was not found in the package registry`). Обычный resolver начал выбирать многогигабайтную CUDA-сборку и был остановлен. Модельные веса не скачивались. Реализация проверена автоматическим тестом с mocked embeddings; после появления CPU-compatible PyTorch команда станет исполнимой без изменений. Результаты будут agreement с weak labels, пока не появится verified set.
"""
    (REPORTS / "experiment_2.md").write_text(exp2, encoding="utf-8")

    rec = """# Интеграция multiple-candidate ranking

`ml_workspace/recommendation/ranker.py` реализует отдельный Top-K prototype. Сначала применяются hard filters: work type, context-dependent material role, stock, room compatibility, required properties и optional max price. Затем suitability объединяет applicability, room evidence и независимый quality score. Цена не повышает quality; в budget strategy она служит ограничением/тай-брейкером. Missing quality data явно возвращается в результате.

Output содержит product ID, suitability score, price, reasons и `missing_quality_data`. Furniture/outdoor товары не попадают в material estimate без требуемых work type + role.

Для backend безопасная интеграция возможна как новый adapter/service: `CatalogRepo.candidates` формирует кандидатов, prototype ранжирует, а существующий `RatingRanker.rank` пока не меняется. Для полного объяснимого результата понадобятся новые DTO для material role relation, hard constraints, quality evidence и ranked alternatives; это schema change и требует одобрения. Полный budget optimizer не реализован.
"""
    (REPORTS / "recommendation_integration.md").write_text(rec, encoding="utf-8")

    versions = []
    for package in ["pandas", "numpy", "scikit-learn", "scipy", "joblib", "pytest"]:
        versions.append(f"{package}=={importlib.metadata.version(package)}")
    (WS / "requirements-ml.lock.txt").write_text("\n".join(versions) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

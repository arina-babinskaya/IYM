# Обучение, оценка и развёртывание RepairCalc ML

## 1. Ручная разметка 500 товаров

Файл: `ml_workspace/data/manual_review_500.csv`. В нём ровно 500 уникальных ID: 200 representative, 200 targeted и 100 дополнительных сложных случаев. Эта смесь **не является репрезентативной** для полного каталога.

CSV записан как UTF-8 with BOM для Excel. Не меняйте `product_id`, `sample_source` и weak-label поля.

Заполняемые поля:

- `reviewed_work_types`, `reviewed_product_categories`, `reviewed_room_types`, `reviewed_usage_contexts` — JSON-массивы, например `["tiling","waterproofing"]`;
- `reviewed_material_roles` — JSON-массив объектов, например `[{"work_type_id":"tiling","material_role":"primary_material"}]`;
- `review_notes` и `reviewer_notes` — пояснение решения;
- `review_status` и `annotation_status`: `unreviewed`, `reviewed`, `approved` или `unknown_applicability`.

Для подтверждённого отсутствия work types используйте `[]`. Если применимость неизвестна, не превращайте её в negative: оставьте labels пустыми и установите `unknown_applicability`.

В Excel импортируйте файл как UTF-8 и сохраните CSV UTF-8. В Google Sheets: File → Import → Upload; отключите автоматическое преобразование JSON/артикулов, а `cod_good` оставьте текстом. После экспорта не открывайте и не пересохраняйте файл приложением, меняющим кавычки JSON.

Проверка:

```bash
.venv-sandbox/bin/python ml_workspace/scripts/validate_annotations.py \
  ml_workspace/data/manual_review_500.csv
```

Validator проверяет уникальность ID, taxonomy version, статусы, JSON, work/room/usage/family IDs и contextual material roles. `approved` требует заполненную заметку; `unreviewed` с reviewed labels считается ошибкой.

## 2. Google Drive и Colab

1. Загрузите проверенный `manual_review_500.csv` в `MyDrive/RepairCalc/`.
2. Откройте [train_and_evaluate_colab.ipynb](../notebooks/train_and_evaluate_colab.ipynb) через Google Colab.
3. Для private GitHub используйте Colab Secret `GITHUB_TOKEN`; не вставляйте token в URL, который сохраняется в notebook output или Git.
4. Выполняйте ячейки последовательно.
5. Выберите `EXPERIMENT = "tfidf_logreg"`, `"catboost_structured"` или `"embeddings_logreg"`.
6. Для verified оценки оставьте `LABEL_POLICY="reviewed_only"`. `weak_only` разрешён только как provisional pilot.
7. GPU не нужен TF-IDF. Для CatBoost/embeddings выберите Runtime → Change runtime type → GPU; notebook проверит CUDA.

Notebook монтирует Drive, повторно использует Python-модули проекта, сохраняет split manifest, thresholds, metrics, figures и portable artifacts. Для embeddings установка `sentence-transformers` вынесена в явную закомментированную команду, поэтому веса не скачиваются случайно.

## 3. Локальный запуск

TF-IDF на verified annotations:

```bash
.venv-sandbox/bin/python ml_workspace/scripts/run_unified_experiment.py \
  --experiment tfidf_logreg \
  --label-policy reviewed_only \
  --reviewed ml_workspace/data/manual_review_500.csv \
  --output ml_workspace/artifacts/tfidf_verified_v1
```

CatBoost:

```bash
.venv-sandbox/bin/python ml_workspace/scripts/run_unified_experiment.py \
  --experiment catboost_structured \
  --label-policy reviewed_only \
  --reviewed ml_workspace/data/manual_review_500.csv \
  --output ml_workspace/artifacts/catboost_verified_v1
```

Embeddings после установки совместимых CPU/GPU PyTorch и sentence-transformers:

```bash
.venv-sandbox/bin/python ml_workspace/scripts/run_unified_experiment.py \
  --experiment embeddings_logreg \
  --label-policy reviewed_only \
  --reviewed ml_workspace/data/manual_review_500.csv \
  --output ml_workspace/artifacts/embeddings_verified_v1
```

Output directory должен отсутствовать или быть пустым: существующий model export намеренно не перезаписывается.

## 4. Labels, splits и gold test

Политики:

- `reviewed_only`: только `reviewed/approved`; это обязательный режим для валидной оценки;
- `weak_only`: только допустимые weak labels; `unknown_needs_review` исключается, verified-empty candidate сохраняется;
- `reviewed_plus_weak`: human labels имеют приоритет, остальные допустимые строки получают weak labels.

Unknown applicability никогда не становится отрицательным примером. Подтверждённый `[]` сохраняется как all-zero row.

Split определяется hash от нормализованной карточки с удалёнными числами: near-duplicate варианты остаются вместе. Manifest сохраняется и повторно используется всеми экспериментами. Human-reviewed records, попавшие в `test`, образуют locked gold candidate; thresholds и hyperparameters на них не настраиваются. До появления достаточного числа independently reviewed test records результат остаётся provisional.

## 5. Метрики

Сохраняются micro/macro precision, recall и F1, weighted/samples F1, exact-match accuracy, Hamming loss, per-class support, PR-AUC, ROC-AUC и Precision/Recall@K. Для класса без positives AUC равен `null`, а причина указана в `undefined_reason`; класс не удаляется.

Micro-F1 агрегирует TP/FP/FN всех `(product,label)`. Macro-F1 одинаково взвешивает work types. `subset_accuracy` требует полного совпадения всего набора labels и поэтому наиболее строгая. Сравнивать модели можно только на одинаковом manifest, taxonomy version и class order.

Figures: per-class F1/precision/recall, support, actual/predicted label counts и отдельная таблица false positives/false negatives. Обычная multiclass confusion matrix не применяется.

## 6. Model artifacts и перенос на macOS

Artifact folder содержит metadata, class mapping, thresholds, preprocessing config, dependency versions, validation/test metrics и estimator. TF-IDF сохраняет vectorizer/joblib; CatBoost — отдельные `.cbm`; embeddings — classifier, encoder model name и, если encoder поддерживает `save()`, локальную папку `sentence_encoder/` с весами/tokenizer.

Скопируйте всю папку из Drive на Mac. Версии Python/scikit-learn/joblib должны быть совместимы. Загружайте только собственные artifacts:

```python
from pathlib import Path
from ml_api import load_model, predict, ProductInput

model = load_model(Path("artifacts/tfidf_verified_v1"),
                   expected_taxonomy_version="work_types_draft_v2",
                   trusted=True)
result = predict(model, ProductInput(None, "краска для стен", "Краски для стен"))
```

При missing file, taxonomy mismatch или class-order conflict загрузка завершится явной ошибкой.

## 7. Backend adapter

Production code не изменён. Prototype:

```python
from pathlib import Path
from ml_api.backend_adapter import WorkTypeInferenceAdapter
from ml_api import ProductInput

adapter = WorkTypeInferenceAdapter(Path("artifacts/tfidf_verified_v1"),
    "work_types_draft_v2", trusted_local_artifact=True)
pred = adapter.predict([ProductInput(1, "обои виниловые", "Обои")])[0]
payload = adapter.to_backend_suggestion(pred, material="wallpaper")
```

Adapter загружает model один раз, поддерживает batch, возвращает scores/thresholded labels и фильтрует draft work IDs, отсутствующие в строгом backend enum. Material пока передаётся отдельно: work-type model не решает material classification. Для production нужны согласованные mappings `floor_covering_install`, `door_install`, `lighting_install` и schema для unknown.

## 8. Воспроизводимость и диагностика

```bash
.venv-sandbox/bin/python -m pytest -q ml_workspace/tests tests
```

Если нет verified строк, `reviewed_only` сообщит `No eligible labels`. Если split слишком мал и один из train/validation/test пуст, нужно больше проверенных данных — нельзя переносить test rows вручную ради метрики. Для Python 3.14 локальный sentence-transformers заблокирован отсутствием CPU PyTorch wheel; используйте Colab либо Python 3.11–3.13 environment. Не загружайте неизвестные `.joblib` с `trusted=True`.

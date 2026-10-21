# ML workspace

Временная, независимая от backend область подготовки каталога и предварительной слабой разметки.

Запуск из корня репозитория:

```bash
.venv-sandbox/bin/python ml_workspace/scripts/prepare_datasets.py
.venv-sandbox/bin/python ml_workspace/scripts/prepare_extended_labels.py
.venv-sandbox/bin/python ml_workspace/scripts/explore_labels.py
.venv-sandbox/bin/python ml_workspace/scripts/validate_annotations.py ml_workspace/data/manual_review_500.csv
.venv-sandbox/bin/python ml_workspace/scripts/run_unified_experiment.py --experiment tfidf_logreg --label-policy reviewed_only --output ml_workspace/artifacts/tfidf_verified_v1
.venv-sandbox/bin/python -m pytest -q ml_workspace/tests
```

Скрипт проверяет SHA-256 read-only источника, строит CSV через pandas, выполняет валидации и повторно проверяет hash. Все work-type метки являются предварительными (`unreviewed`), не ground truth.

Структура:

- `data/products_clean.csv` — очищенный каталог без новых меток;
- `data/product_characteristics.csv` — все вхождения характеристик в long format;
- `data/categories_summary.csv` — категории и черновые контекстные соответствия;
- `data/products_weak_labeled.csv` — отдельные слабые multi-label аннотации;
- `data/manual_review_sample.csv` — стратифицированная выборка для проверки;
- `taxonomy/*.csv` — черновая таксономия;
- `reports/*.md` — русскоязычные отчёты и руководство.

V2 сохраняет clean data и v1 weak labels, а многомерные labels пишет в
`products_multidim_weak_labeled.csv`. Два review-файла защищены от перезаписи,
если в них появились ручные изменения. Эксперименты и prototype ranking находятся
в `experiments/` и `recommendation/`; generated artifacts не являются production-моделями.

- `data/manual_review_500.csv` — единый набор из 500 уникальных товаров;
- `notebooks/train_and_evaluate_colab.ipynb` — последовательный Colab workflow;
- `ml_api/` — единые load/prepare/train/validate/evaluate/save/load/predict функции;
- `reports/training_and_deployment_guide.md` — полное руководство.

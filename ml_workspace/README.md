# RepairCalc ML workspace (`taxonomy_v2`)

Активный workflow полностью автоматический и не зависит от ручной разметки.

```bash
.venv-sandbox/bin/python -m ml_workspace.scripts.build_taxonomy_v2_dataset
.venv-sandbox/bin/pytest -q ml_workspace/tests/test_taxonomy_v1.py ml_workspace/tests/test_leakage_v1.py ml_workspace/tests/test_pipeline_v1.py
```

Результаты: master table `data/products_taxonomy_v2.csv`, готовые Colab-файлы `data/splits_v2/{train,validation,test}.csv`, повторно используемый manifest и class support. Таксономия находится в `taxonomy/README_taxonomy_v2.md`; аудит утечек — в `reports/data_leakage_audit_v2.md`.

Обучение выполняется через публичные функции `load_data`, `prepare_features`, `train`, `validate`, `evaluate`, `save_model`, `load_model`, `predict`. Targets: domain, activities, primary product category, multi-label work types и room types. Стадии выводятся из work types.

Generated-only manual review CSV проверены на отсутствие правок и перенесены в `archive/manual_review_generated/`. Старые эксперименты сохранены для сравнения, но не являются входом нового workflow.

Все labels эвристические. Test split измеряет согласие с правилами и не доказывает реальную точность.

# Обучение и последующая интеграция

Сначала пересоберите taxonomy_v2 командой из `ml_workspace/README.md` и дождитесь успешных leakage tests. Notebook `notebooks/train_and_evaluate_colab.ipynb` читает четыре файла из `data/splits_v2`: `train.csv`, `validation.csv`, `test.csv`, `split_manifest_reused.csv`. Он устанавливает зависимости, проверяет GPU, подключает Drive, обучает experiment, выбирает thresholds только по validation, оценивает test, экспортирует, повторно загружает artifact и выполняет inference. Default — TF-IDF; большие weights не скачиваются.

Архитектура: независимые heads/models на общей матрице — multiclass domain, multiclass primary product category, multi-label activities/work types/room types. Task-specific masks исключают неизвестный target, не отбрасывая другие известные labels строки. Stages детерминированно выводятся из work types; furnishing не является стадией ремонта.

`save_model` сохраняет estimators, fitted preprocessing, feature schema, ordered classes, thresholds, taxonomy version, config, package versions, metrics и IDs train-fit. `load_model(..., trusted=True)` используется лишь для доверенных joblib artifacts. `predict` принимает один `ProductInput` или batch, сохраняет ID и возвращает status/domain/category/works/derived stages/scores.

`WorkTypeInferenceAdapter` загружает artifact один раз. Для backend потребуется отдельный mapping taxonomy_v1 → production enums; `app/taxonomy.py`, `app/schemas.py` и backend interfaces не менялись. Adapter не пишет БД и не меняет ручные назначения.

Для переноса нужны совместимые major versions Python/scikit-learn/joblib. Sentence embeddings требуют доступный encoder; TF-IDF artifact самодостаточен. CatBoost требует `catboost`.

Метрики отражают только согласие с weak labels, а не независимую real-world accuracy и не подтверждают micro-F1 ≥ 0.8 организатора.

# Итоговый отчёт taxonomy_v2

## Изменения

Сохранены пять стадий ремонта и 18 work types v1; добавлены `ventilation_install` и `heating_climate_install`. Product categories разделяют ручной инструмент, электроинструмент, оснастку, расходники и СИЗ. Добавлены функциональные furnishing categories. `room_furnishing` реализован отдельной activity, а не шестой стадией. Room types назначаются только по evidence.

Domain distribution: renovation 45 421, furnishing 7 022, non-renovation 17 124, unknown 19 223. Из v1 unknown в поддерживаемые domain перешли 5 420 строк: 4 437 furnishing, 918 renovation, 65 non-renovation; ещё 238 изменили другие labels, сохранив unknown. Всего изменено 12 336 строк. Примеры исправлений: бита KENDO → tool_accessories; радиатор → heating/climate installation; стальной эмалированный воздуховод → ventilation, не paint; декоративная консоль → decorative installation; кровать/стол/кухонный фасад → furnishing.

Work support включает: ventilation 535, heating/climate 633, electrical wiring 1 305, plumbing rough 1 590. Furnishing: cabinets/wardrobes 3 608, interior accessories 1 011, shelving/storage 597, seating 434, countertops 370, mirrors 293, tables 227, beds 77. Подробности — `dataset_statistics_v2.json`, `taxonomy_v1_to_v2_changed_products.csv`, `splits_v2/class_support.csv`.

Splits не изменены: train 62 081, validation 13 392, test 13 317. Domain по splits:

| split | renovation | furnishing | non-renovation | unknown |
|---|---:|---:|---:|---:|
| train | 31 852 | 4 885 | 11 946 | 13 398 |
| validation | 6 823 | 1 066 | 2 542 | 2 961 |
| test | 6 746 | 1 071 | 2 636 | 2 864 |

Manifest SHA-256 остался `9e78da4122b48ab25fe839f3a8a67bac1cff36f3786223bb9f32fee43c440f77`. Product ID и duplicate groups не пересекают splits.

## Validity masks и leakage

В полном dataset сохранены unknown и все metadata. В supervised loss/metrics допускаются только строки с `*_valid=True` для конкретного target: domain/activity/work 69 567, product category 52 443, room types 6 236. Неизвестность rooms не удаляет известный furnishing/domain target. Targets, masks, evidence, scores, ID и split запрещены feature allowlist. Thresholds выбираются только на validation.

## Проверка и обучение

Полномасштабное обучение не выполнялось. Выполнен TF-IDF smoke pipeline на 627 строках с export/reload и batch adapter. Core tests не скачивают модели. Полный pytest: 70 passed, 7 warnings (одна внешняя deprecation и constant-label warnings малой smoke-выборки). В validation отсутствует support для `demolition` и `utility_room`, в test — для `waterproofing`/`waterproofing_material`; эти per-class metrics должны показываться как zero/undefined и не интерпретироваться как качество. Метрики отражают только согласие с weak labels.

Открывать: `ml_workspace/notebooks/train_and_evaluate_colab.ipynb`. Загрузить рядом в `ml_workspace/data/splits_v2/` четыре файла: `train.csv`, `validation.csv`, `test.csv`, `split_manifest_reused.csv`; project Python code также должен быть доступен через clone repository. В cell `EXPERIMENT` выбрать `tfidf_logreg`, `catboost_structured` или `embeddings_logreg`. Для embeddings пользователь отдельно устанавливает/downloads encoder; большие Transformer weights автоматически не загружаются.

Artifact `repaircalc_taxonomy_v2_artifact` копируется notebook в Google Drive. Для локальной загрузки скопируйте всю директорию без удаления JSON/joblib/encoder-файлов и вызовите `load_model(path, "taxonomy_v2", trusted=True)`. Затем используйте тот же `predict` для одного `ProductInput` или списка.

Backend approval требуется для двух новых engineering work IDs, furnishing domain/activity, furnishing categories и room types. Adapter сообщает unsupported IDs явно; production enums не менялись.

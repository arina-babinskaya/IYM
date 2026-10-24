# Аудит утечек данных — taxonomy_v1

Источник: `products_clean.csv`, 88 790 уникальных product ID. Исходный `requirments/products_final.json` не изменён.

Разрешённые признаки централизованы в `ml_api/feature_schema.py`: `name`, `source_category`, `category_names`, `description_clean`, `marketing_description_clean`, `important_attributes_json`, `characteristics_json`, `brand_name`, `sale_unit`, `price`, `characteristic_count`, `information_completeness`. Retailer category существует до предсказания и допустима. Text строится заново только из текстовой части allowlist; сохранённый `input_text` сверяется с builder.

Targets: `domain_label`, `product_category`, `work_types`; `renovation_stages` детерминированно вычисляется из work types. Metadata включает ID, split, duplicate group, статус, evidence, confidence, taxonomy version. Запрещены все targets, ID, split, review/annotation поля, proposed labels, scores, rule evidence, conflicts и target-derived flags. Неожиданный новый столбец не может молча войти в feature matrix.

Нормализованные имя, категория и описание (числовые варианты заменены маркером) образуют SHA-256 duplicate group. Все товары одной группы назначаются в один split стабильным hash с seed 20261022. Manifest хранит product ID, cod_good, group, split, seed и taxonomy version. TF-IDF fit выполняется только на train; thresholds — только на validation; `evaluate` не разрешает train и test не используется для настройки.

Проверки: уникальность ID, отсутствие group overlap, идентичность сохранённого текста allowlist-builder, схема artifact/inference, train-only fit IDs и запрет test в threshold selection покрыты pytest. Все обязательные leakage checks прошли; полный прогон: 54 passed. Manifest содержит 88 790 уникальных ID, ни одна duplicate-group не пересекает splits.

Главное ограничение не устраняется split-ом: labels созданы правилами из тех же исходных полей. Метрики измеряют воспроизведение weak-label rules, а не независимо проверенную реальную точность и не подтверждают целевой micro-F1 организатора.

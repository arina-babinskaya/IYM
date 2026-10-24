# Повторный аудит утечек taxonomy_v2

Feature allowlist не расширялся: используются только исходные name, retailer category hierarchy, descriptions, marketing description, raw characteristics, brand, unit, price и исходные completeness counters. Activities, room types, furnishing/domain labels, stages, work/category targets, validity masks, evidence, scores, conflicts, IDs и split запрещены как признаки.

`input_text` строится заново через `build_input_text`; serialized target dictionaries не читаются. TF-IDF fit выполняется только на train. Validation выбирает thresholds отдельно для activities/work types/room types; test используется только в `evaluate`.

Каждый target имеет собственную validity mask. Unknown domain rows исключены из domain/activity/work supervised loss и metrics. Product category использует только строки с известной category. Room metrics используют только furnishing rows с подтверждённой room evidence. Неизвестность одного target не удаляет валидный другой target.

Исходные 88 790 ID и duplicate groups не изменились. Повторно использован прежний manifest с SHA-256 `9e78da4122b48ab25fe839f3a8a67bac1cff36f3786223bb9f32fee43c440f77`; build аварийно завершается при несовпадении ID/group. Splits: 62 081 / 13 392 / 13 317, group overlap отсутствует.

Ограничение остаётся: метрики test отражают согласие модели с deterministic weak labels, а не независимую real-world accuracy.

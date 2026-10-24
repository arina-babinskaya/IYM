# Совместимость taxonomy_v2 с backend

Backend-файлы не изменены. Новые `ventilation_install` и `heating_climate_install` отсутствуют в production `WorkType`. Furnishing domain/activity, furnishing categories и room types также не имеют production contract.

Adapter сохраняет новые значения в `flags.unsupported_taxonomy_v2_work_types`, `flags.activity_labels`, `flags.domain_label` и `room_types`. Поддерживаемые work types передаются как раньше; `plumbing_fixture_install` отображается в `plumbing_install`. До изменения production schemas нельзя отправлять новые IDs в строгие enum-поля.

Требует одобрения: расширение backend domain/activity schema, добавление двух инженерных work enums, контракт room types и решение о хранении furnishing category. Запись в БД не реализована.

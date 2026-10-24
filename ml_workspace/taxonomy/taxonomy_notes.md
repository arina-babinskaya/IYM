# Многомерная таксономия v2

Измерения разделены: product category отвечает «что это», work type — «в какой ремонтной операции применяется», room type — «для какой комнаты явно подходит», usage context — «в каком сценарии используется». Renovation stage/type остаются метаданными work type и не присваиваются всем товарам.

Рекомендуемый объём: **20** содержательных product families + `other/unknown`, 17 work types, **12** room labels + fallbacks и **12** usage labels + fallbacks. Product family primary label взаимоисключающий, кроме сохранения иерархического parent path; work/room/usage — multi-label.

`other`: объект понятен, но словарь измерения его не покрывает. `unknown`: данных недостаточно или есть равносильный конфликт. Для work type пустой список дополнительно имеет status `verified_empty_candidate` либо `unknown_needs_review`; пустой список не заменяется фиктивной работой.

Backend поддерживает список work/room types, но не product families, usage contexts, dimension statuses или context-dependent roles. Production schemas не менялись; интеграция требует отдельного согласования.

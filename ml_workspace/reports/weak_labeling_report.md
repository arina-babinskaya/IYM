# Отчёт о многомерной слабой разметке

Все автоматически выданные labels имеют `review_status=unreviewed`. Coverage не является accuracy.

| Измерение | other | unknown | multi-label |
|---|---:|---:|---:|
| Product family | 27,132 | 2,241 | Иерархический parent: 240 |
| Work type | empty candidate 61,148 | 12,390 | 55 |
| Room type | 42,414 | 3,429 | 12,342 |
| Usage context | 52,920 | 13 | 12,041 |

V1 имел 15 252 work-labeled и 73 538 work-unlabeled товаров. V2 намеренно не меняет work labels (изменено **0** work-label sets), чтобы расширение retail coverage не маскировало изменение target semantics. Теперь все товары имеют product-family fallback/status, а rooms/usage размечаются отдельно. Это улучшение представимости, не доказательство качества классификации.

Известные случаи сохраняются: водорозетка не электрическая розетка; эмалированный воздуховод не краска; кабельная стяжка не стяжка пола; садовая труба не сантехника; грунтовка не получает все работы.

Evidence хранится в `all_label_evidence`: dimension, label, rule ID, score и совпадения по источникам. Scores не калиброваны.

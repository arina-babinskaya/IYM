# Аудит ранее неразмеченной части каталога

Аудит выполнен ровно для **73,538** товаров с пустым `proposed_work_types` в v1. Это множество объединяет прежние исходы: `{"conflicting_evidence":203,"insufficient_evidence":12174,"insufficient_information":13,"outside_current_taxonomy":61148}`. Группы не следует складывать повторно: они являются взаимоисключающими значениями `label_outcome` внутри единой выборки.

Главная причина низкого work-type coverage — не обязательно ошибка: v1 отвечал только на вопрос о ремонтной операции. Посуда, мебель, растения, текстиль и товары для отдыха закономерно имели пустой work type. Ошибкой было интерпретировать отсутствие ремонтной работы как глобальную нерелевантность товара.

## Новые семейства среди прежних work-type-unlabeled

`{"appliances":549,"barbecue_grilling":240,"building_materials":1009,"doors_windows":1409,"electrical_goods":1836,"finishing_materials":2858,"furniture":5888,"garden_outdoor":6498,"hardware_fasteners":2475,"heating_climate_ventilation":1048,"home_accessories":2701,"home_textiles":3344,"household_maintenance":992,"kitchen_dining":3812,"lighting":3350,"other":26448,"pest_protection":221,"plumbing":2503,"seasonal_leisure":799,"storage_organization":1029,"tools":2557,"unknown":1972}`

Fallback `other` означает понятный товар вне поддерживаемых семейств; `unknown` — недостаток или конфликт данных. Ни один из них не создаёт ремонтную работу.

## Крупнейшие исходные категории

- Фасады - МДФ: 2,084 → `furniture`
- Семена овощей: 1,177 → `garden_outdoor`
- Семена цветов: 863 → `garden_outdoor`
- Саморезы, шурупы: 824 → `hardware_fasteners`
- Кашпо, горшки для комнатных растений: 807 → `garden_outdoor`
- Луковичные цветы: 710 → `garden_outdoor`
- Шторы рулонные: 640 → `home_textiles`
- Тарелки: 603 → `kitchen_dining`
- Саженцы: 573 → `garden_outdoor`
- Мебельные ручки: 548 → `furniture`
- Лампы светодиодные: 536 → `lighting`
- Болты, гайки, винты, шайбы: 517 → `hardware_fasteners`
- Декоративные элементы и комплектующие для карнизов: 503 → `home_accessories`
- Плитка настенная для ванной: 460 → `finishing_materials`
- Растения комнатные: 433 → `garden_outdoor`
- Полотенца: 433 → `home_textiles`
- Салатники, миски: 423 → `kitchen_dining`
- Обувь: 402 → `other`
- Свёрла: 387 → `tools`
- Кружки: 385 → `kitchen_dining`
- Рамки для розеток, выключателей, накладки декоративные: 374 → `unknown`
- Удобрения: 347 → `garden_outdoor`
- Шторы: 338 → `home_textiles`
- Ковры: 303 → `home_textiles`
- Антисептики защитно-декоративные: 298 → `home_accessories`
- Лампы настольные: 285 → `lighting`
- Фонари садовые: 276 → `unknown`
- Комплектующие для межкомнатных дверей: 260 → `doors_windows`
- Сковороды: 259 → `kitchen_dining`
- Фоторамки: 257 → `home_accessories`

## Выводы

- Furniture, kitchen/dining, storage, home textiles/accessories, garden/outdoor, barbecue and pest protection выделены независимо от work types.
- Multi-label возможности сосредоточены в room/usage: например, столовая мебель может иметь kitchen+dining_room, а садовый гриль — outdoor+garden+barbecue.
- `unlabeled_audit_sample.csv` содержит реальные ID и стратифицированные примеры семейств.
- Возможные false negatives v1 остаются в `insufficient_evidence` и целевой review-выборке; автоматическое расширение product-family coverage не доказывает улучшение accuracy.

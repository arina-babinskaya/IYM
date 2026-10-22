# Taxonomy v2: ремонт и меблировка

`taxonomy_v2` сохраняет пять официальных стадий ремонта без добавления шестой стадии. `room_furnishing` — отдельная activity для меблировки готовой комнаты. Основные независимые targets: `domain_label`, `activities`, primary `product_category`, multi-label `work_types`, evidence-based `room_types`. `renovation_stages` всегда детерминированно выводятся из work types.

Domain имеет четыре состояния: `renovation`, `furnishing`, `non_renovation`, `unknown_needs_review`. Монтируемая стеновая панель относится к renovation/decorative installation; свободно размещаемая репродукция или мебель — к furnishing; посуда, семена и товары личной гигиены — non-renovation. Внешняя привлекательность сама по себе не является evidence.

Добавлены `ventilation_install` и `heating_climate_install`. Электрические кабели, сантехнические трубы и инженерные соединители различаются по retailer category и техническому контексту; садовый шланг и generic metal tube не получают plumbing label автоматически.

Tools разделены на `hand_tools`, `power_tools`, `tool_accessories`, `consumables`, `protective_equipment`, без отдельного work type для каждой оснастки. Work type назначается инструменту только при подтверждённом назначении.

Furnishing-категории компактны: `tables`, `seating`, `shelving_storage`, `cabinets_wardrobes`, `beds`, `countertops`, `mirrors`, `interior_accessories`, `decorative_objects`, `other_furnishing`. Room labels выводятся только по словам категории/описания (`спальня`, `кухня`, `ванная` и т. п.); мебель не связывается со всеми комнатами.

Подробные определения 20 work types находятся в `work_types_v2.csv`; activities, rooms, categories, stage mapping и migration представлены отдельными CSV. Все labels являются provisional weak annotations.

## Backend

Production enums не изменены. `ventilation_install`, `heating_climate_install`, furnishing/activity и v2 room types отсутствуют в backend. Adapter возвращает их в compatibility flags, а не молча отбрасывает. `plumbing_fixture_install` явно отображается в backend `plumbing_install`. Для production-расширения enum требуется отдельное одобрение.

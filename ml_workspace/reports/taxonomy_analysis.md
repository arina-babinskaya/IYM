# Анализ многомерной таксономии

## Результат

Таксономия разделена на четыре независимых задачи: product family, renovation work type, room suitability и usage context. Наличие product-family label не делает товар участником ремонтной сметы.

Рекомендуемый состав: 20 содержательных product families + `other/unknown`, 17 work types, 12 room labels + fallbacks, 12 usage labels + fallbacks. Primary product family взаимоисключающий; `barbecue_grilling` дополнительно сохраняет parent `garden_outdoor`. Work/room/usage допускают multi-label.

Product family: `{"appliances": 553, "barbecue_grilling": 240, "building_materials": 1130, "doors_windows": 1980, "electrical_goods": 3217, "finishing_materials": 7935, "furniture": 5923, "garden_outdoor": 6500, "hardware_fasteners": 2642, "heating_climate_ventilation": 1222, "home_accessories": 2729, "home_textiles": 3344, "household_maintenance": 992, "kitchen_dining": 3812, "lighting": 6910, "other": 27132, "pest_protection": 221, "plumbing": 5534, "seasonal_leisure": 799, "storage_organization": 1030, "tools": 2704, "unknown": 2241}`.

Work types: `{"demolition": 66, "door_install": 571, "drywall_install": 227, "electrical_fittings": 904, "electrical_wiring": 1046, "floor_covering_install": 1977, "floor_screed": 49, "lighting_install": 3584, "plumbing_install": 1825, "plumbing_rough": 1421, "priming": 72, "tiling": 1448, "wall_painting": 458, "wall_plastering": 62, "wall_putty": 90, "wallpapering": 1392, "waterproofing": 115}`.

Room types: `{"balcony": 671, "bathroom": 20245, "bedroom": 3973, "children_room": 3554, "dining_room": 2535, "garden_outdoor": 17657, "hallway": 1319, "home_office": 647, "kitchen": 6279, "living_room": 3469, "other": 42414, "terrace": 448, "unknown": 3429, "utility_room": 1054}`.

Usage contexts: `{"barbecue": 578, "dacha": 4461, "dining": 3518, "food_preparation": 2055, "garden": 11492, "household_maintenance": 5442, "indoor": 4722, "insect_protection": 629, "other": 52920, "outdoor": 6132, "outdoor_leisure": 416, "plant_care": 6033, "storage": 5401, "unknown": 13}`.

## Семантика fallback

- `other`: карточка понятна, но поддерживаемый словарь конкретного измерения неприменим или не покрывает этот класс.
- `unknown`: сведений недостаточно либо равносильные свидетельства конфликтуют.
- Для work types пустой список сопровождается `verified_empty_candidate` или `unknown_needs_review`; это не одно и то же.

Stage/type ремонта остаются workflow metadata work type. «Белая отделка» по-прежнему трактуется как подготовка поверхности, но требует продуктового согласования. Backend не знает `door_install`, `lighting_install`, общий `floor_covering_install`, product families, usage contexts и context-dependent roles — production taxonomy/schema не изменялись.

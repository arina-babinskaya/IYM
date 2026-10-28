"""
work_type_materials_v2.py
=========================
Справочник позиций (материалов, инструментов, расходников, оборудования)
для каждого типа работ taxonomy_v2.

Структура каждой записи:
  "work_type_id": [
      {
          "item": "название позиции (ru)",
          "role": "primary_material | auxiliary_material | preparation_material |
                   consumable | tool | fastener | protective_equipment | finishing_material",
          "weight": float,   # важность позиции, сумма по work_type == 1.0
          "note": "краткий комментарий (опционально)"
      },
      ...
  ]

Правила весов:
  - Чем выше вес — тем важнее позиция для успешного выполнения работы.
  - Основной материал (primary_material) суммарно занимает наибольшую долю.
  - Инструменты / расходники имеют меньший, но ненулевой вес.
  - Сумма весов по каждому work_type == 1.0 (с точностью до 0.001 для float).

Таксономия: taxonomy_v2  (ml_workspace/taxonomy/taxonomy_v2.py)
"""

from __future__ import annotations

WORK_TYPE_MATERIALS: dict[str, list[dict]] = {

    # ────────────────────────────────────────────────────────────────────────
    # 1. demolition — Демонтаж
    # Стадия: preparation_demolition
    # ────────────────────────────────────────────────────────────────────────
    "demolition": [
        {"item": "перфоратор / отбойный молоток",    "role": "tool",               "weight": 0.25},
        {"item": "болгарка (УШМ)",                   "role": "tool",               "weight": 0.15},
        {"item": "лом и монтировка",                 "role": "tool",               "weight": 0.10},
        {"item": "молоток и зубило",                 "role": "tool",               "weight": 0.08},
        {"item": "строительный пылесос",             "role": "tool",               "weight": 0.07},
        {"item": "мешки для мусора",                 "role": "consumable",         "weight": 0.10},
        {"item": "респиратор / полумаска",           "role": "protective_equipment","weight": 0.08},
        {"item": "защитные очки",                    "role": "protective_equipment","weight": 0.05},
        {"item": "перчатки рабочие",                 "role": "protective_equipment","weight": 0.05},
        {"item": "скотч малярный / плёнка защитная", "role": "consumable",         "weight": 0.07},
    ],  # sum = 1.00

    # ────────────────────────────────────────────────────────────────────────
    # 2. electrical_wiring — Электромонтаж и прокладка проводки
    # Стадия: rough_work
    # ────────────────────────────────────────────────────────────────────────
    "electrical_wiring": [
        {"item": "кабель (ВВГнг-LS, NYM и пр.)",    "role": "primary_material",   "weight": 0.30},
        {"item": "кабель-канал / гофротруба",        "role": "auxiliary_material", "weight": 0.12},
        {"item": "распределительные коробки",        "role": "auxiliary_material", "weight": 0.08},
        {"item": "автоматические выключатели / УЗО", "role": "primary_material",   "weight": 0.10},
        {"item": "щиток электрический",              "role": "primary_material",   "weight": 0.07},
        {"item": "клеммники / соединительные гильзы","role": "fastener",           "weight": 0.06},
        {"item": "перфоратор / штроборез",           "role": "tool",               "weight": 0.08},
        {"item": "кримпер / инструмент обжима",      "role": "tool",               "weight": 0.05},
        {"item": "мультиметр / тестер",              "role": "tool",               "weight": 0.05},
        {"item": "крепёж (дюбели, скобы)",           "role": "fastener",           "weight": 0.05},
        {"item": "изолента / термоусадочная трубка", "role": "consumable",         "weight": 0.04},
    ],  # sum = 1.00

    # ────────────────────────────────────────────────────────────────────────
    # 3. plumbing_rough — Черновая сантехника
    # Стадия: rough_work
    # ────────────────────────────────────────────────────────────────────────
    "plumbing_rough": [
        {"item": "трубы (полипропилен / металлопластик / медь)", "role": "primary_material",   "weight": 0.30},
        {"item": "фитинги (угольники, тройники, муфты)",         "role": "auxiliary_material", "weight": 0.18},
        {"item": "шаровые краны / запорная арматура",            "role": "primary_material",   "weight": 0.10},
        {"item": "канализационные трубы и отводы",               "role": "primary_material",   "weight": 0.10},
        {"item": "паяльник для PP-труб / пресс-клещи",           "role": "tool",               "weight": 0.08},
        {"item": "труборез",                                      "role": "tool",               "weight": 0.05},
        {"item": "сантехнический лён / ФУМ-лента / герметик",   "role": "consumable",         "weight": 0.07},
        {"item": "крепёж для труб (хомуты, клипсы)",             "role": "fastener",           "weight": 0.06},
        {"item": "манометр / течеискатель",                       "role": "tool",               "weight": 0.04},
        {"item": "защитные перчатки",                             "role": "protective_equipment","weight": 0.02},
    ],  # sum = 1.00

    # ────────────────────────────────────────────────────────────────────────
    # 4. ventilation_install — Монтаж вентиляции и воздуховодов
    # Стадии: rough_work, final_stage
    # ────────────────────────────────────────────────────────────────────────
    "ventilation_install": [
        {"item": "воздуховоды (круглые / прямоугольные)",  "role": "primary_material",   "weight": 0.28},
        {"item": "вентиляционные решётки и диффузоры",     "role": "primary_material",   "weight": 0.12},
        {"item": "вытяжные / приточные вентиляторы",       "role": "primary_material",   "weight": 0.12},
        {"item": "соединительные фланцы и муфты",          "role": "auxiliary_material", "weight": 0.10},
        {"item": "алюминиевая клейкая лента",              "role": "consumable",         "weight": 0.08},
        {"item": "герметик (для воздуховодов)",            "role": "consumable",         "weight": 0.06},
        {"item": "крепёж (шпильки, хомуты, кронштейны)",  "role": "fastener",           "weight": 0.08},
        {"item": "электролобзик / ножницы по металлу",     "role": "tool",               "weight": 0.07},
        {"item": "перфоратор / дрель",                     "role": "tool",               "weight": 0.05},
        {"item": "рулетка, уровень",                       "role": "tool",               "weight": 0.04},
    ],  # sum = 1.00

    # ────────────────────────────────────────────────────────────────────────
    # 5. heating_climate_install — Монтаж отопления и климатических систем
    # Стадии: rough_work, final_stage
    # ────────────────────────────────────────────────────────────────────────
    "heating_climate_install": [
        {"item": "радиаторы отопления",                    "role": "primary_material",   "weight": 0.20},
        {"item": "комплект тёплого пола (мат/кабель/плёнка)","role": "primary_material", "weight": 0.15},
        {"item": "котёл / коллектор",                      "role": "primary_material",   "weight": 0.10},
        {"item": "трубы для отопления",                    "role": "auxiliary_material", "weight": 0.12},
        {"item": "регулирующая арматура (термостаты, вентили)", "role": "auxiliary_material","weight": 0.10,
         "note": "радиаторные термостатические клапаны и вентили на приборы отопления"},
        {"item": "теплоизоляция труб",                     "role": "auxiliary_material", "weight": 0.07},
        {"item": "крепёж радиаторов (кронштейны, дюбели)", "role": "fastener",           "weight": 0.06},
        {"item": "терморегулятор / датчик температуры",    "role": "primary_material",   "weight": 0.07,
         "note": "комнатный настенный терморегулятор или датчик теплого пола"},
        {"item": "паяльник / пресс-клещи",                 "role": "tool",               "weight": 0.07},
        {"item": "манометр / опрессовочный насос",         "role": "tool",               "weight": 0.04},
        {"item": "ФУМ-лента / герметик",                   "role": "consumable",         "weight": 0.02},
    ],  # sum = 1.00

    # ────────────────────────────────────────────────────────────────────────
    # 6. waterproofing — Гидроизоляция
    # Стадия: rough_work
    # ────────────────────────────────────────────────────────────────────────
    "waterproofing": [
        {"item": "обмазочная гидроизоляция (мастика, состав)", "role": "primary_material",   "weight": 0.35},
        {"item": "гидроизоляционная мембрана / плёнка",        "role": "primary_material",   "weight": 0.20},
        {"item": "гидроизоляционная лента (углы, стыки)",      "role": "auxiliary_material", "weight": 0.12},
        {"item": "грунтовка глубокого проникновения",          "role": "preparation_material","weight": 0.10},
        {"item": "валик / кисть / шпатель",                    "role": "tool",               "weight": 0.10},
        {"item": "строительный миксер",                        "role": "tool",               "weight": 0.05},
        {"item": "ёмкость для замеса",                         "role": "tool",               "weight": 0.04},
        {"item": "перчатки / защитные очки",                   "role": "protective_equipment","weight": 0.04},
    ],  # sum = 1.00

    # ────────────────────────────────────────────────────────────────────────
    # 7. floor_screed — Стяжка и выравнивание пола
    # Стадия: rough_work
    # ────────────────────────────────────────────────────────────────────────
    "floor_screed": [
        {"item": "цементно-песчаная стяжка / ровнитель",   "role": "primary_material",   "weight": 0.35},
        {"item": "наливной пол (самовыравнивающаяся смесь)","role": "primary_material",   "weight": 0.15},
        {"item": "грунтовка",                               "role": "preparation_material","weight": 0.10},
        {"item": "демпферная лента",                        "role": "auxiliary_material", "weight": 0.07},
        {"item": "маяки для стяжки",                        "role": "auxiliary_material", "weight": 0.08},
        {"item": "правило / уровень",                       "role": "tool",               "weight": 0.09},
        {"item": "строительный миксер / бетономешалка",    "role": "tool",               "weight": 0.08},
        {"item": "игольчатый валик (для дегазации)",        "role": "tool",               "weight": 0.04},
        {"item": "плёнка полиэтиленовая (подстилка)",       "role": "auxiliary_material", "weight": 0.04},
    ],  # sum = 1.00

    # ────────────────────────────────────────────────────────────────────────
    # 8. wall_plastering — Оштукатуривание
    # Стадия: rough_work
    # ────────────────────────────────────────────────────────────────────────
    "wall_plastering": [
        {"item": "штукатурная смесь (гипсовая / цементная)", "role": "primary_material",   "weight": 0.40},
        {"item": "грунтовка",                                 "role": "preparation_material","weight": 0.12},
        {"item": "маяки штукатурные (перфорированные рейки)", "role": "auxiliary_material", "weight": 0.10},
        {"item": "армирующая сетка (серпянка)",               "role": "auxiliary_material", "weight": 0.07},
        {"item": "правило / полутёрок",                       "role": "tool",               "weight": 0.08},
        {"item": "кельма / шпатель",                          "role": "tool",               "weight": 0.07},
        {"item": "строительный миксер",                       "role": "tool",               "weight": 0.06},
        {"item": "уровень / отвес",                           "role": "tool",               "weight": 0.08},
        {"item": "ёмкость для замеса",                        "role": "tool",               "weight": 0.02},
    ],  # sum = 1.00

    # ────────────────────────────────────────────────────────────────────────
    # 9. drywall_install — Монтаж гипсокартона
    # Стадия: rough_work
    # ────────────────────────────────────────────────────────────────────────
    "drywall_install": [
        {"item": "листы гипсокартона (ГКЛ / ГКЛВ / ГКЛО)",  "role": "primary_material",   "weight": 0.30},
        {"item": "металлический профиль (UD, CD, CW, UW)",   "role": "primary_material",   "weight": 0.20},
        {"item": "саморезы по металлу (чёрные)",             "role": "fastener",           "weight": 0.10},
        {"item": "дюбели / анкеры для крепления каркаса",    "role": "fastener",           "weight": 0.07},
        {"item": "серпянка (стекловолоконная лента)",         "role": "auxiliary_material", "weight": 0.07},
        {"item": "шпаклёвка стартовая (для заделки швов)",   "role": "auxiliary_material", "weight": 0.06},
        {"item": "шуруповёрт",                               "role": "tool",               "weight": 0.07},
        {"item": "нож для гипсокартона",                     "role": "tool",               "weight": 0.05},
        {"item": "уровень / отвес",                          "role": "tool",               "weight": 0.05},
        {"item": "рулетка / карандаш",                       "role": "tool",               "weight": 0.03},
    ],  # sum = 1.00

    # ────────────────────────────────────────────────────────────────────────
    # 10. wall_putty — Шпатлевание
    # Стадия: white_finish
    # ────────────────────────────────────────────────────────────────────────
    "wall_putty": [
        {"item": "шпаклёвка стартовая",             "role": "primary_material",   "weight": 0.30},
        {"item": "шпаклёвка финишная",              "role": "primary_material",   "weight": 0.25},
        {"item": "грунтовка",                       "role": "preparation_material","weight": 0.12},
        {"item": "армирующая сетка (серпянка)",     "role": "auxiliary_material", "weight": 0.07},
        {"item": "шпатель широкий (60–80 см)",      "role": "tool",               "weight": 0.10},
        {"item": "шпатель узкий (10–20 см)",        "role": "tool",               "weight": 0.05},
        {"item": "строительный миксер",             "role": "tool",               "weight": 0.05},
        {"item": "шлифовальная сетка / наждачная бумага", "role": "consumable",  "weight": 0.04},
        {"item": "ёмкость для замеса",              "role": "consumable",         "weight": 0.02},
    ],  # sum = 1.00

    # ────────────────────────────────────────────────────────────────────────
    # 11. priming — Грунтование
    # Стадия: white_finish
    # ────────────────────────────────────────────────────────────────────────
    "priming": [
        {"item": "грунтовка (глубокого проникновения / укрепляющая)", "role": "primary_material","weight": 0.55},
        {"item": "валик малярный",                  "role": "tool",               "weight": 0.15},
        {"item": "кисть (для углов и труднодоступных мест)", "role": "tool",      "weight": 0.10},
        {"item": "малярный лоток",                  "role": "tool",               "weight": 0.07},
        {"item": "малярная плёнка / скотч",         "role": "consumable",         "weight": 0.08},
        {"item": "перчатки резиновые",              "role": "protective_equipment","weight": 0.05},
    ],  # sum = 1.00

    # ────────────────────────────────────────────────────────────────────────
    # 12. wall_painting — Окраска стен и потолков
    # Стадия: finish_work
    # ────────────────────────────────────────────────────────────────────────
    "wall_painting": [
        {"item": "интерьерная краска",              "role": "primary_material",   "weight": 0.40},
        {"item": "грунтовка",                       "role": "preparation_material","weight": 0.10},
        {"item": "валик малярный",                  "role": "tool",               "weight": 0.12},
        {"item": "кисть малярная",                  "role": "tool",               "weight": 0.08},
        {"item": "малярный лоток",                  "role": "tool",               "weight": 0.05},
        {"item": "малярный скотч",                  "role": "consumable",         "weight": 0.08},
        {"item": "малярная плёнка / укрывной материал", "role": "consumable",     "weight": 0.07},
        {"item": "шлифовальная сетка (межслойная шлифовка)", "role": "consumable","weight": 0.05},
        {"item": "удлинитель для валика (телескопическая ручка)", "role": "tool", "weight": 0.05},
    ],  # sum = 1.00

    # ────────────────────────────────────────────────────────────────────────
    # 13. wallpapering — Оклейка обоями
    # Стадия: finish_work
    # ────────────────────────────────────────────────────────────────────────
    "wallpapering": [
        {"item": "обои",                            "role": "primary_material",   "weight": 0.60},
        {"item": "обойный клей",                    "role": "auxiliary_material", "weight": 0.10},
        {"item": "грунтовка",                       "role": "preparation_material","weight": 0.10},
        {"item": "шпатель / разглаживающий инструмент", "role": "tool",          "weight": 0.08},
        {"item": "валик для обоев",                 "role": "tool",               "weight": 0.08},
        {"item": "ножницы / строительный нож",      "role": "tool",               "weight": 0.04,
         "note": "нарезка обоев по раппорту"},
    ],  # sum = 1.00

    # ────────────────────────────────────────────────────────────────────────
    # 14. tiling — Облицовка плиткой
    # Стадия: finish_work
    # ────────────────────────────────────────────────────────────────────────
    "tiling": [
        {"item": "керамическая / керамогранитная плитка",  "role": "primary_material",   "weight": 0.38},
        {"item": "плиточный клей",                          "role": "auxiliary_material", "weight": 0.18},
        {"item": "затирка швов (фуга)",                     "role": "auxiliary_material", "weight": 0.08},
        {"item": "грунтовка",                               "role": "preparation_material","weight": 0.06},
        {"item": "СВП (система выравнивания плитки)",       "role": "auxiliary_material", "weight": 0.05},
        {"item": "плиткорез / болгарка с алмазным кругом", "role": "tool",               "weight": 0.08},
        {"item": "зубчатый шпатель",                        "role": "tool",               "weight": 0.05},
        {"item": "резиновый молоток",                       "role": "tool",               "weight": 0.04},
        {"item": "крестики / клинья для зазоров",           "role": "consumable",         "weight": 0.04},
        {"item": "губка / тряпка (для очистки)",            "role": "consumable",         "weight": 0.02},
        {"item": "уровень / правило",                       "role": "tool",               "weight": 0.02},
    ],  # sum = 1.00

    # ────────────────────────────────────────────────────────────────────────
    # 15. floor_covering_install — Укладка напольных покрытий
    # Стадия: finish_work
    # ────────────────────────────────────────────────────────────────────────
    "floor_covering_install": [
        {"item": "ламинат / SPC / LVT / линолеум",  "role": "primary_material",   "weight": 0.40},
        {"item": "подложка под напольное покрытие",  "role": "auxiliary_material", "weight": 0.12},
        {"item": "плинтус / порожек",               "role": "finishing_material",  "weight": 0.10},
        {"item": "клей / двусторонний скотч (для линолеума)", "role": "auxiliary_material","weight": 0.07},
        {"item": "скоба / дюбель (крепление плинтуса)", "role": "fastener",        "weight": 0.06},
        {"item": "электролобзик / торцовочная пила", "role": "tool",               "weight": 0.08},
        {"item": "молоток / добойник",               "role": "tool",               "weight": 0.06},
        {"item": "клинья (монтажные зазоры)",        "role": "consumable",         "weight": 0.05},
        {"item": "рулетка / угольник",               "role": "tool",               "weight": 0.04},
        {"item": "строительный нож",                 "role": "tool",               "weight": 0.02},
    ],  # sum = 1.00

    # ────────────────────────────────────────────────────────────────────────
    # 16. door_window_install — Монтаж дверей и окон
    # Стадия: finish_work
    # ────────────────────────────────────────────────────────────────────────
    "door_window_install": [
        {"item": "дверное полотно / блок",          "role": "primary_material",   "weight": 0.28},
        {"item": "оконный блок / стеклопакет",      "role": "primary_material",   "weight": 0.15},
        {"item": "дверная коробка",                 "role": "primary_material",   "weight": 0.10},
        {"item": "монтажная пена",                  "role": "auxiliary_material", "weight": 0.10},
        {"item": "наличники / откосы",              "role": "finishing_material",  "weight": 0.08},
        {"item": "петли / фурнитура",               "role": "auxiliary_material", "weight": 0.08},
        {"item": "анкерные болты / рамные дюбели",  "role": "fastener",           "weight": 0.07},
        {"item": "уровень / отвес",                 "role": "tool",               "weight": 0.05},
        {"item": "монтажный пистолет (для пены)",   "role": "tool",               "weight": 0.05},
        {"item": "шуруповёрт / перфоратор",         "role": "tool",               "weight": 0.04},
    ],  # sum = 1.00

    # ────────────────────────────────────────────────────────────────────────
    # 17. electrical_fittings — Установка розеток и выключателей
    # Стадия: final_stage
    # ────────────────────────────────────────────────────────────────────────
    "electrical_fittings": [
        {"item": "розетки",                         "role": "primary_material",   "weight": 0.28},
        {"item": "выключатели",                     "role": "primary_material",   "weight": 0.20},
        {"item": "установочные коробки (подрозетники)", "role": "auxiliary_material","weight": 0.12},
        {"item": "клеммники / колпачки СИЗ",        "role": "fastener",           "weight": 0.08},
        {"item": "отвёртка / шуруповёрт",           "role": "tool",               "weight": 0.10},
        {"item": "индикаторная отвёртка / мультиметр", "role": "tool",            "weight": 0.10},
        {"item": "изолента",                        "role": "consumable",         "weight": 0.07},
        {"item": "гипсовый раствор (закрепить подрозетник)", "role": "auxiliary_material","weight": 0.05},
    ],  # sum = 1.00

    # ────────────────────────────────────────────────────────────────────────
    # 18. plumbing_fixture_install — Установка сантехнических приборов
    # Стадия: final_stage
    # ────────────────────────────────────────────────────────────────────────
    "plumbing_fixture_install": [
        {"item": "смеситель / кран",                "role": "primary_material",   "weight": 0.22},
        {"item": "унитаз / инсталляция",            "role": "primary_material",   "weight": 0.18},
        {"item": "ванна / душевой поддон",          "role": "primary_material",   "weight": 0.15},
        {"item": "раковина / умывальник",           "role": "primary_material",   "weight": 0.12},
        {"item": "гибкая подводка / шланги",        "role": "auxiliary_material", "weight": 0.08},
        {"item": "силиконовый герметик (сантехнический)", "role": "consumable",   "weight": 0.07},
        {"item": "ФУМ-лента / сантехнический лён",  "role": "consumable",         "weight": 0.05},
        {"item": "разводной ключ / трубный ключ",   "role": "tool",               "weight": 0.07},
        {"item": "дюбели / крепёж",                 "role": "fastener",           "weight": 0.04},
        {"item": "уровень",                         "role": "tool",               "weight": 0.02},
    ],  # sum = 1.00

    # ────────────────────────────────────────────────────────────────────────
    # 19. lighting_install — Установка освещения
    # Стадия: final_stage
    # ────────────────────────────────────────────────────────────────────────
    "lighting_install": [
        {"item": "светильник / люстра / встраиваемый спот", "role": "primary_material","weight": 0.40},
        {"item": "лампы (LED, E27, GU10 и пр.)",     "role": "primary_material",   "weight": 0.15},
        {"item": "монтажная планка / крюк / кронштейн", "role": "auxiliary_material","weight": 0.10},
        {"item": "клеммники / распределительная коробка", "role": "fastener",           "weight": 0.10},
        {"item": "дюбели / шурупы",                 "role": "fastener",           "weight": 0.07},
        {"item": "изолента / термоусадка",          "role": "consumable",         "weight": 0.06},
        {"item": "отвёртка / шуруповёрт",           "role": "tool",               "weight": 0.07},
        {"item": "индикаторная отвёртка / мультиметр", "role": "tool",            "weight": 0.05},
    ],  # sum = 1.00

    # ────────────────────────────────────────────────────────────────────────
    # 20. decorative_finish_install — Декоративная отделка и монтаж
    # Стадии: finish_work, final_stage
    # ────────────────────────────────────────────────────────────────────────
    "decorative_finish_install": [
        {"item": "декоративные панели (МДФ, ПВХ, гипс, 3D)", "role": "primary_material","weight": 0.30},
        {"item": "молдинги / карнизы / плинтусы",    "role": "primary_material",   "weight": 0.15},
        {"item": "монтажный клей / жидкие гвозди",   "role": "auxiliary_material", "weight": 0.15},
        {"item": "декоративная штукатурка / венецианка", "role": "primary_material","weight": 0.10},
        {"item": "саморезы / дюбели / финишные гвозди", "role": "fastener",        "weight": 0.08},
        {"item": "акриловый герметик (для швов)",    "role": "consumable",         "weight": 0.07},
        {"item": "электролобзик / торцовочная пила", "role": "tool",               "weight": 0.07},
        {"item": "шуруповёрт",                       "role": "tool",               "weight": 0.05},
        {"item": "уровень",                          "role": "tool",               "weight": 0.03},
    ],  # sum = 1.00
}


def validate_weights(data: dict = WORK_TYPE_MATERIALS, tol: float = 0.005) -> None:
    """
    Проверяет, что сумма весов по каждому work_type == 1.0 (с допуском tol).
    Вызывается при импорте для раннего обнаружения ошибок.
    """
    errors: list[str] = []
    for wt, items in data.items():
        total = round(sum(i["weight"] for i in items), 6)
        if abs(total - 1.0) > tol:
            errors.append(f"{wt}: сумма весов = {total:.4f} (ожидается 1.0)")
    if errors:
        raise ValueError("Ошибки в весах work_type_materials_v2:\n" + "\n".join(errors))


validate_weights()

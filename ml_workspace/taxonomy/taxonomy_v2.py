"""Canonical executable taxonomy_v2; production backend enums are unchanged."""
from __future__ import annotations

STAGES = [
 {"id":"preparation_demolition","ru_name":"Подготовительный этап (демонтаж)","description":"Обследование, защита зоны, отключение и удаление старых покрытий/конструкций."},
 {"id":"rough_work","ru_name":"Черновые работы","description":"Скрытые инженерные сети, основания и конструкции до подготовки под декоративное покрытие."},
 {"id":"white_finish","ru_name":"Белая отделка","description":"Подготовка ровного, сухого и загрунтованного основания: базовое/финишное шпатлевание, шлифование и грунтование. Это уже не конструктивные черновые работы, но ещё не видимое финишное покрытие."},
 {"id":"finish_work","ru_name":"Чистовая отделка","description":"Монтаж видимых покрытий стен, пола и потолка, плитки, дверей и декоративных материалов."},
 {"id":"final_stage","ru_name":"Финальный этап","description":"Установка видимых приборов, электроустановочных изделий, освещения, сантехники и завершающего декора."},
]

TAXONOMY_VERSION="taxonomy_v2"
ACTIVITIES=[
 {"id":"renovation","ru_name":"Ремонт и монтаж","definition":"Работы пяти стадий ремонта."},
 {"id":"room_furnishing","ru_name":"Меблировка и обустройство комнаты","definition":"Подбор мебели и размещаемых интерьерных аксессуаров после ремонта."},
]
WORK_TYPES=[
 ("demolition","Демонтаж","Удаление покрытий и конструкций",["preparation_demolition"]),
 ("electrical_wiring","Электромонтаж и прокладка проводки","Силовые кабели, проводка, каналы, коробки и защита",["rough_work"]),
 ("plumbing_rough","Черновая сантехника","Трубы, фитинги, арматура и канализация",["rough_work"]),
 ("ventilation_install","Монтаж вентиляции и воздуховодов","Воздуховоды, соединители, решётки, фланцы и вытяжные вентиляторы",["rough_work","final_stage"]),
 ("heating_climate_install","Монтаж отопления и климатических систем","Радиаторы, тёплый пол, котлы и монтажные компоненты",["rough_work","final_stage"]),
 ("waterproofing","Гидроизоляция","Обмазочные составы, мембраны и ленты",["rough_work"]),
 ("floor_screed","Стяжка и выравнивание пола","Стяжка, ровнители и наливной пол",["rough_work"]),
 ("wall_plastering","Оштукатуривание","Черновое выравнивание стен и потолков",["rough_work"]),
 ("drywall_install","Монтаж гипсокартона","ГКЛ/ГВЛ, каркас и крепёж",["rough_work"]),
 ("wall_putty","Шпатлевание","Базовая и финишная подготовка основания",["white_finish"]),
 ("priming","Грунтование","Грунтование перед покрытием",["white_finish"]),
 ("wall_painting","Окраска стен и потолков","Интерьерная окраска",["finish_work"]),
 ("wallpapering","Оклейка обоями","Обои и специализированные материалы",["finish_work"]),
 ("tiling","Облицовка плиткой","Плитка, клей, затирка и СВП",["finish_work"]),
 ("floor_covering_install","Укладка напольных покрытий","Ламинат, линолеум, SPC/LVT и плинтусы",["finish_work"]),
 ("door_window_install","Монтаж дверей и окон","Полотна, коробки, окна и монтажная фурнитура",["finish_work"]),
 ("electrical_fittings","Установка розеток и выключателей","Финальные электроустановочные изделия",["final_stage"]),
 ("plumbing_fixture_install","Установка сантехнических приборов","Смесители, санитарная керамика, ванны и душ",["final_stage"]),
 ("lighting_install","Установка освещения","Стационарное освещение",["final_stage"]),
 ("decorative_finish_install","Декоративная отделка и монтаж","Панели, молдинги, карнизы и монтируемый декор",["finish_work","final_stage"]),
]
PRODUCT_CATEGORIES=[
 "primer","paint","putty","plaster","drywall","tile","floor_covering","waterproofing_material",
 "adhesive","sealant","construction_mix","fasteners","hand_tools","power_tools","tool_accessories",
 "consumables","protective_equipment","plumbing","electrical_goods","ventilation","heating_climate",
 "lighting","doors_windows","decorative_panels","decorative_materials","installation_accessories",
 "insulation","lumber_sheet_material","tables","seating","shelving_storage","cabinets_wardrobes","beds",
 "countertops","mirrors","interior_accessories","decorative_objects","other_renovation_material",
]
ROOM_TYPES=["kitchen","dining_room","living_room","bedroom","bathroom","hallway","home_office","utility_room","balcony","general_indoor"]
MATERIAL_ROLES=["primary_material","preparation_material","auxiliary_material","consumable","fastener","tool","protective_equipment","finishing_material"]
WORK_ROLE_MAP={w:(["tool","consumable"] if w=="demolition" else ["primary_material","auxiliary_material","tool","fastener"]) for w,*_ in WORK_TYPES}
WORK_TO_STAGES={w:stages for w,_,_,stages in WORK_TYPES}; WORK_IDS=[x[0] for x in WORK_TYPES]
V1_TO_V2={
 **{w:w for w in ["demolition","electrical_wiring","plumbing_rough","waterproofing","floor_screed","wall_plastering","drywall_install","wall_putty","priming","wall_painting","wallpapering","tiling","floor_covering_install","door_window_install","electrical_fittings","plumbing_fixture_install","lighting_install","decorative_finish_install"]},
 "tools":"hand_tools","other_renovation_material":"other_renovation_material",
}
def stages_for_work_types(work_types:list[str])->list[str]:
 unknown=sorted(set(work_types)-set(WORK_IDS))
 if unknown: raise ValueError(f"Unknown work types: {unknown}")
 order=[s["id"] for s in STAGES]; selected={s for w in work_types for s in WORK_TO_STAGES[w]}
 return [s for s in order if s in selected]

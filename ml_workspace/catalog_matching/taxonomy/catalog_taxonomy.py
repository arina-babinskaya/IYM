"""Stable taxonomy for Maxidom catalog products; unrelated to renovation work types."""
from __future__ import annotations

from dataclasses import dataclass, asdict

TAXONOMY_VERSION = "catalog-taxonomy-v2"

@dataclass(frozen=True)
class Category:
    id: str
    name: str
    parent_id: str
    definition: str
    excludes: str = "Исключаются товары, соответствующие определению другого специализированного листа taxonomy v1."

_SPECS = [
    ("building.lumber", "Пиломатериалы", "building", "Доски, брус, рейки и древесные плиты"),
    ("building.sheet_materials", "Листовые материалы", "building", "ГКЛ, фанера, OSB и строительные листы"),
    ("building.dry_mix", "Сухие строительные смеси", "building", "Цемент, кладочные и выравнивающие смеси"),
    ("building.insulation", "Изоляция", "building", "Тепло-, звуко-, гидро- и пароизоляция"),
    ("building.roofing", "Кровля и водосток", "building", "Кровельные покрытия и водосточные системы"),
    ("building.facade", "Фасадные материалы", "building", "Сайдинг, фасадные панели и элементы"),
    ("building.masonry", "Кирпич и блоки", "building", "Кирпич, газобетон и строительные блоки"),
    ("finishing.primer", "Грунтовки", "finishing", "Грунтующие составы"),
    ("finishing.putty_plaster", "Шпатлёвки и штукатурки", "finishing", "Шпатлёвочные и штукатурные составы"),
    ("finishing.paint", "Краски", "finishing", "Краски для минеральных, деревянных и металлических поверхностей"),
    ("finishing.coatings", "Лаки, масла и защитные покрытия", "finishing", "Лаки, масла, пропитки и антисептики"),
    ("finishing.wallpaper", "Обои", "finishing", "Рулонные и жидкие обои"),
    ("finishing.decor", "Декоративная отделка", "finishing", "Молдинги, панели, лепнина и декоративные покрытия"),
    ("finishing.adhesive_sealant", "Клеи и герметики", "finishing", "Монтажные клеи, пены и герметики"),
    ("finishing.painting_tools", "Малярные инструменты", "finishing", "Кисти, валики, шпатели, малярные ленты и вспомогательные инструменты"),
    ("tile.wall", "Настенная плитка", "tile", "Керамическая настенная плитка"),
    ("tile.floor_porcelain", "Напольная плитка и керамогранит", "tile", "Напольная керамика и керамогранит"),
    ("tile.mosaic", "Мозаика", "tile", "Мозаичная плитка"),
    ("tile.installation", "Материалы для укладки плитки", "tile", "Плиточный клей, затирка, профили и системы укладки"),
    ("flooring.laminate", "Ламинат", "flooring", "Ламинированные напольные покрытия"),
    ("flooring.linoleum", "Линолеум", "flooring", "Рулонный линолеум"),
    ("flooring.vinyl", "Виниловые покрытия", "flooring", "SPC, ПВХ и кварц-виниловая плитка"),
    ("flooring.wood", "Деревянные напольные покрытия", "flooring", "Паркетная, инженерная и массивная доска"),
    ("flooring.carpet", "Ковровые покрытия", "flooring", "Ковролин и ковровая плитка"),
    ("flooring.accessories", "Плинтусы и аксессуары для пола", "flooring", "Плинтусы, пороги и подложки"),
    ("doors_windows.doors", "Двери", "doors_windows", "Межкомнатные, входные и складные двери"),
    ("doors_windows.windows", "Окна и подоконники", "doors_windows", "Окна, подоконники и оконные элементы"),
    ("doors_windows.hardware", "Дверная и оконная фурнитура", "doors_windows", "Ручки, замки, петли и комплектующие"),
    ("electrical.cable", "Кабель и провод", "electrical", "Электрические кабели, провода и кабель-каналы"),
    ("electrical.switch_socket", "Розетки и выключатели", "electrical", "Розетки, выключатели, рамки и механизмы"),
    ("electrical.protection", "Электрощитовое оборудование", "electrical", "Автоматы, УЗО, щиты и счётчики"),
    ("electrical.power", "Удлинители и питание", "electrical", "Удлинители, вилки, блоки питания и батарейки"),
    ("electrical.smart_security", "Безопасность и умный дом", "electrical", "Сигнализация, камеры, датчики и звонки"),
    ("electrical.components", "Электромонтажные компоненты", "electrical", "Клеммы, патроны, монтажные коробки, разъёмы и изоляционные материалы"),
    ("lighting.indoor", "Интерьерные светильники", "lighting", "Люстры, бра, споты и комнатные светильники"),
    ("lighting.outdoor", "Уличное освещение", "lighting", "Фасадные, садовые и грунтовые светильники"),
    ("lighting.decorative", "Гирлянды и декоративный свет", "lighting", "Световые гирлянды, ленты и декор"),
    ("lighting.bulbs", "Лампы", "lighting", "Сменные электрические лампы"),
    ("lighting.work", "Фонари и рабочий свет", "lighting", "Ручные фонари и прожекторы"),
    ("plumbing.faucets", "Смесители", "plumbing", "Смесители для кухни и ванной"),
    ("plumbing.sanitary", "Санфаянс", "plumbing", "Унитазы, раковины, биде и инсталляции"),
    ("plumbing.bath_shower", "Ванны и душевые", "plumbing", "Ванны, душевые кабины и поддоны"),
    ("plumbing.pipes_fittings", "Трубы и фитинги", "plumbing", "Трубы, фитинги и арматура водоснабжения"),
    ("plumbing.sinks", "Кухонные мойки", "plumbing", "Мойки и аксессуары к ним"),
    ("plumbing.accessories", "Аксессуары для ванной", "plumbing", "Полки, держатели и сантехнические аксессуары"),
    ("plumbing.water_treatment", "Фильтры и очистка воды", "plumbing", "Фильтры воды, картриджи и сменные модули"),
    ("heating.radiators", "Радиаторы и отопление", "heating", "Радиаторы, конвекторы и элементы отопления"),
    ("heating.boilers", "Котлы и водонагреватели", "heating", "Котлы, бойлеры и водонагреватели"),
    ("heating.ventilation", "Вентиляция", "heating", "Вентиляторы, воздуховоды и решётки"),
    ("tools.hand", "Ручной инструмент", "tools", "Ручной слесарный, столярный и измерительный инструмент"),
    ("tools.power", "Электроинструмент", "tools", "Сетевой и аккумуляторный электроинструмент"),
    ("tools.accessories", "Оснастка для инструмента", "tools", "Свёрла, диски, биты и расходная оснастка"),
    ("tools.workwear", "Спецодежда и защита", "tools", "Рабочая одежда, обувь и средства защиты"),
    ("hardware.fasteners", "Крепёж", "hardware", "Саморезы, дюбели, болты, гайки и гвозди"),
    ("hardware.furniture", "Мебельная фурнитура", "hardware", "Ручки, направляющие, опоры и мебельные механизмы"),
    ("hardware.metal", "Металлопрокат и крепёжные элементы", "hardware", "Уголки, профили, сетки и металлические элементы"),
    ("garden.seeds", "Семена и посадочный материал", "garden", "Семена, луковицы и посадочный материал"),
    ("garden.plants", "Растения и саженцы", "garden", "Живые комнатные и садовые растения"),
    ("garden.soils", "Грунты и субстраты", "garden", "Грунты, торф, дренаж и субстраты"),
    ("garden.fertilizers", "Удобрения и защита растений", "garden", "Удобрения и средства ухода/защиты"),
    ("garden.pots", "Горшки и кашпо", "garden", "Ёмкости для растений и рассады"),
    ("garden.accessories", "Аксессуары для растений и сада", "garden", "Опоры, подставки, садовый декор и оборудование для размещения растений"),
    ("garden.tools", "Садовый инструмент", "garden", "Инструмент и инвентарь для сада"),
    ("garden.watering", "Полив", "garden", "Шланги, лейки и системы полива"),
    ("garden.machinery", "Садовая техника", "garden", "Газонокосилки, триммеры и садовые машины"),
    ("outdoor.furniture", "Садовая мебель", "outdoor", "Уличная мебель, качели и гамаки"),
    ("outdoor.leisure", "Отдых и туризм", "outdoor", "Пикник, кемпинг, бассейны и спорт"),
    ("outdoor.grill", "Мангалы и грили", "outdoor", "Грили, мангалы, копчение и аксессуары"),
    ("outdoor.structures", "Теплицы, навесы и ограждения", "outdoor", "Садовые конструкции и ограждения"),
    ("home.decor", "Декор интерьера", "home", "Декоративные аксессуары, картины и фоторамки"),
    ("home.textiles", "Домашний текстиль", "home", "Шторы, полотенца, постельные принадлежности"),
    ("home.rugs", "Ковры и придверные коврики", "home", "Ковры, дорожки и коврики"),
    ("home.storage", "Хранение и организация", "home", "Контейнеры, корзины, органайзеры и вешалки"),
    ("home.household", "Хозяйственные товары", "home", "Бытовой инвентарь и хозяйственные принадлежности"),
    ("kitchen.tableware", "Посуда для сервировки", "kitchen", "Тарелки, чашки, бокалы и столовые приборы"),
    ("kitchen.cookware", "Посуда для приготовления", "kitchen", "Кастрюли, сковороды и формы"),
    ("kitchen.utensils", "Кухонные принадлежности", "kitchen", "Ножи, доски и кухонные аксессуары"),
    ("kitchen.appliances", "Бытовая техника", "kitchen", "Мелкая и крупная бытовая техника"),
    ("furniture.kitchen", "Кухонная мебель", "furniture", "Кухонные фасады, шкафы, тумбы и столешницы"),
    ("furniture.bathroom", "Мебель для ванной", "furniture", "Тумбы, шкафы и зеркала для ванной"),
    ("furniture.home", "Мебель для дома", "furniture", "Шкафы, столы, стулья, кровати и полки"),
    ("furniture.components", "Мебельные детали и компоненты", "furniture", "Мебельные щиты, полки, фасады и конструктивные детали, не относящиеся только к кухне"),
    ("cleaning.chemicals", "Бытовая химия", "cleaning", "Средства для уборки, стирки и мытья"),
    ("cleaning.equipment", "Инвентарь для уборки", "cleaning", "Швабры, щётки, губки и уборочный инвентарь"),
    ("auto.accessories", "Автотовары", "auto", "Автомобильные принадлежности, химия и расходники"),
    ("pets.supplies", "Товары для животных", "pets", "Корма, уход и аксессуары для питомцев"),
    ("personal_care.hygiene", "Гигиена и уход", "personal_care", "Средства личной гигиены, ухода за волосами, лицом, телом и полостью рта"),
    ("apparel.clothing_footwear", "Одежда и обувь", "apparel", "Повседневная одежда, обувь и носочно-чулочные изделия; спецодежда исключена"),
    ("stationery.office_school", "Канцелярские товары", "stationery", "Бумага, тетради, письменные принадлежности и товары для учёбы и офиса"),
    ("seasonal.holiday", "Праздничные и сезонные товары", "seasonal", "Новогодний и праздничный декор"),
    ("review.unresolved", "Требует классификации", "review", "Временная категория для неоднозначных и не сопоставленных товаров"),
]

CATEGORIES = tuple(Category(*x) for x in _SPECS)
CATEGORY_BY_ID = {x.id: x for x in CATEGORIES}
PARENT_NAMES = {"building":"Строительство", "finishing":"Отделка", "tile":"Плитка", "flooring":"Напольные покрытия", "doors_windows":"Двери и окна", "electrical":"Электрика", "lighting":"Освещение", "plumbing":"Сантехника", "heating":"Отопление и вентиляция", "tools":"Инструменты", "hardware":"Крепёж и фурнитура", "garden":"Сад и растения", "outdoor":"Дача и отдых", "home":"Товары для дома", "kitchen":"Кухня", "furniture":"Мебель", "cleaning":"Уборка", "auto":"Автотовары", "pets":"Зоотовары", "personal_care":"Личная гигиена", "apparel":"Одежда и обувь", "stationery":"Канцелярские товары", "seasonal":"Сезонные товары", "review":"Ручная проверка"}

def get_category(category_id: str) -> Category:
    return CATEGORY_BY_ID[category_id]

def snapshot() -> dict:
    return {"version": TAXONOMY_VERSION, "parents": PARENT_NAMES, "categories": [asdict(x) for x in CATEGORIES]}

def validate() -> None:
    ids = [x.id for x in CATEGORIES]
    assert len(ids) == len(set(ids)), "duplicate category ID"
    assert all(x.name and x.definition and x.parent_id and x.excludes for x in CATEGORIES)

validate()

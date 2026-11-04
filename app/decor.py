"""Подбор декора: помещение + стиль → по одному товару на каждую позицию (свет, шторы, ковёр, картина…).

Позиции находятся по категориям каталога, стиль — по характеристикам товара. Многие группы уже размечены
в каталоге («Стиль» у светильников, «Стиль интерьера» у мебели, «Дизайн ковров», «Дизайн часов»),
остальное определяется по цвету, материалу и словам в названии.
"""
from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Product, ProductCharacteristic
from app.schemas import ROOM_TITLES, RoomType

R = RoomType


def rx(pattern: str) -> re.Pattern:
    return re.compile(pattern, re.IGNORECASE)


@dataclass(frozen=True)
class Style:
    title: str
    description: str
    palette: tuple[str, ...]
    attr: re.Pattern       # значения «Стиль», «Стиль интерьера», «Дизайн …»
    colors: re.Pattern
    materials: re.Pattern
    words: re.Pattern      # название, коллекция, рисунок
    avoid: re.Pattern
    compatible: re.Pattern | None = None  # метки каталога, которые стилю не противоречат
    families: frozenset[str] = frozenset()  # цвета, из которых складывается стиль
    playful: bool = False  # тематический стиль: животные и мотивы в принтах уместны
    cartoons: bool = False  # мультяшные персонажи тоже уместны (детская)


STYLES: dict[str, Style] = {
    "modern": Style(
        "Современный", "Чистые линии, нейтральные цвета, стекло и металл, минимум декора.",
        ("#F5F5F4", "#A8A29E", "#44403C", "#1C1917"),
        rx(r"модерн|современ|контемпорари|минимал"),
        rx(r"\bбел(?!ь)|\bсер(ый|ая|ое|ые|о-)|черн|чёрн|хром|графит|антрацит|никель|прозрачн"),
        rx(r"стекл|металл|алюмин|акрил|сталь|блэкаут|сатин|микрофибр|вельвет|велюр"),
        rx(r"модерн|modern|минимал|геометр|хай-тек|однотон|без рисунка|абстракц|графич"),
        rx(r"классич|винтаж|прованс|кантри|хрустал|барокко|ампир|детск|рококо|кружев"),
        rx(r"хай-тек"),
        families=frozenset({"white", "grey", "black", "beige"}),
    ),
    "scandi": Style(
        "Скандинавский", "Светло и уютно: белый, серый, светлое дерево, хлопок, шерсть, живые растения.",
        ("#FFFFFF", "#E7E5E4", "#D6C4A8", "#9CA3AF"),
        rx(r"сканди|скандинав"),
        rx(r"\bбел(?!ь)|светло-сер|\bсер(ый|ая|ое|ые)|беж|молоч|натурал|светл\w* дуб|белен|берез|слонов|мятн|пудров"),
        rx(r"дерев|берез|сосн|дуб|хлоп|\bл[её]н(?!т)|льнян|рогожк|шерст|войлок|керамик|фанер"),
        rx(r"сканди|scandi|nordic|норд|хюгге|hygge|ботаник|минимал|графич"),
        rx(r"золот|хрустал|бархат|барокко|ампир|рококо|детск|позолот"),
        rx(r"модерн|современ|контемпорари"),
        families=frozenset({"white", "grey", "beige", "wood", "green"}),
    ),
    "loft": Style(
        "Лофт", "Индустриальный характер: чёрный металл, тёмное дерево, бетон, кирпич, открытые лампы.",
        ("#1F2937", "#57534E", "#92400E", "#B45309"),
        rx(r"лофт|loft|индустр"),
        rx(r"черн|чёрн|графит|антрацит|бронз|медь|медн|бетон|коричн|ржав|венге|\bсер(ый|ая|ое|ые|о-)|терракот"),
        rx(r"металл|сталь|бетон|кирпич|массив|кож|чугун|рогожк|канвас|вельвет|деним|войлок"),
        rx(r"лофт|loft|эдисон|edison|филамент|кирпич|бетон|индустр|город|граффити|машин"),
        rx(r"золот|хрустал|прованс|кантри|детск|кружев|барокко|рококо|лаванд"),
        families=frozenset({"black", "grey", "brown", "bronze", "wood", "terracotta"}),
    ),
    "classic": Style(
        "Классический", "Торжественно и тепло: золото, бронза, хрусталь, бархат, сливочные и благородные цвета.",
        ("#FEF3C7", "#D4AF37", "#7C2D12", "#065F46"),
        rx(r"классич|классика|хрустал"),
        rx(r"золот|бронз|латун|беж|крем|слонов|ванил|шампан|бордо|изумруд|айвори|ivory|патин"),
        rx(r"хрустал|бархат|жаккард|латун|фарфор|велюр"),
        rx(r"классик|classic|вензел|багет|барокко|ампир|рококо|\\bверсаль|\bантик|вит(ая|ые|ой)|royal|натюрморт|пейзаж"),
        rx(r"лофт|loft|хай-тек|детск|сканди|индустр"),
        rx(r"арт-деко|ар-деко"),
        families=frozenset({"gold", "bronze", "white", "beige", "brown", "green", "red"}),
    ),
    "provence": Style(
        "Прованс", "Деревенский уют: лаванда, мята, молочный, цветочные узоры, клетка, состаренные вещи.",
        ("#E9D5FF", "#A78BFA", "#D1FAE5", "#FFF7ED"),
        rx(r"прованс|кантри|винтаж|флористик|шебби"),
        rx(r"лаванд|сирен|мятн|пудров|молоч|крем|олив|голуб|розов|состарен"),
        rx(r"хлоп|\bл[её]н(?!т)|льнян|керамик|кружев|ротанг|жаккард|тюль(?!п)|тюлев|вуал"),
        rx(r"прованс|кантри|лаванд|цвет(оч|ы|ок)|клетк|кружев|шебби|винтаж|полев|ретро"),
        rx(r"хай-тек|лофт|loft|детск|индустр|хром"),
        rx(r"флористик|винтаж|классич"),
        families=frozenset({"white", "beige", "purple", "green", "blue", "pink", "wood"}),
    ),
    "eco": Style(
        "Эко / бохо", "Натуральные материалы: джут, ротанг, бамбук, дерево, глина, тёплые природные оттенки.",
        ("#D6C4A8", "#A16207", "#65A30D", "#78350F"),
        rx(r"\bэко(?!ном)|этно|растительн"),
        rx(r"натурал|беж|терракот|олив|зелен|корич|песоч|горчич|дерев|орех|какао"),
        rx(r"джут|ротанг|бамбук|сизал|морск\w* трав|лоз|\bив(а|ы)\b|дерев|массив|хлоп|\bл[её]н(?!т)|глин|кокос|макраме|рогоз|водоросл|льнян|рогожк"),
        rx(r"бохо|boho|\bэко(?!ном)|джут|ротанг|бамбук|плетен|макраме|натурал|этно"),
        rx(r"хай-тек|хрустал|глянц|детск|хром"),
        rx(r"модерн|современ|флористик"),
        families=frozenset({"beige", "brown", "wood", "green", "terracotta", "white"}),
    ),
    "marine": Style(
        "Морской", "Белый и синий, полоска, светлое дерево, джут и канат, ракушки, якоря и маяки.",
        ("#FFFFFF", "#1E3A8A", "#60A5FA", "#E7D8B9"),
        rx(r"морск|средиземномор|прибреж"),
        rx(r"\bбел(?!ь)|\bсин|голуб|бирюз|лазур|аквамарин|морск\w* волн|индиго|песоч|беж|белен"),
        rx(r"джут|канат|\bл[её]н(?!т)|льнян|морск\w* трав|ракуш|белен\w* (дуб|дерев)"),
        rx(r"морск|якор|ракуш|маяк|\bволн|полоск|тельняш|\bрыб|\bкит\b|краб|корабл|парус|штурвал|чайк|ocean|sea\b|marine|nautic"),
        rx(r"хрустал|барокко|ампир|рококо|золот|позолот|лофт|loft|детск"),
        rx(r"модерн|современ|прованс"),
        families=frozenset({"white", "blue", "beige", "wood"}),
        playful=True,
    ),
    "forest": Style(
        "Лесной", "Как в домике у леса: зелёный и коричневый, дерево и лён, шишки, листья, олени и папоротник.",
        ("#14532D", "#4D7C0F", "#78350F", "#D6C4A8"),
        rx(r"\bэко(?!ном)|растительн|флористик"),
        rx(r"зелен|олив|хвой|изумруд|мох|корич|дерев|натурал|орех|шоколад|беж|хаки"),
        rx(r"дерев|массив|сосн|\bдуб|берез|\bл[её]н(?!т)|льнян|шерст|войлок|кам(ень|ня)|джут|кор[аы]\b"),
        rx(r"\bлес|олен|лис(а|ы|ичк)|медвед|сов(а|ы|ушк)|\bсосн|\bел(ь|ка|и)\b|шишк|папоротн|\bмох|лист|ветк|гриб"
           r"|берез|forest|woodland|природ|ботаник|хвой"),
        rx(r"хай-тек|хрустал|глянц|барокко|ампир|рококо|хром|золот|детск"),
        rx(r"модерн|современ|эко|прованс|винтаж"),
        families=frozenset({"green", "brown", "wood", "beige"}),
        playful=True,
    ),
    "kids": Style(
        "Детский", "Ярко и весело: пастельные и сочные цвета, звёзды, облака, зверята и любимые герои мультиков.",
        ("#FBCFE8", "#BAE6FD", "#FDE68A", "#BBF7D0"),
        rx(r"детск"),
        rx(r"розов|голуб|желт|мятн|бирюз|мульти|разноцвет|салатов|оранж|сиренев|пудров|персик|\bбел(?!ь)"),
        rx(r"плюш|войлок|фетр|флис|махр"),
        rx(r"детск|kids|baby|бэби|мульт(?!и)|сказ|звезд|облак|радуг|машинк|ракет|космос|принцесс|единорог|динозавр|зайч|мишк"
           r"|медвеж|\bкот|котик|котен|лис(а|ы|ичк)|слон|жираф|панд|сова|совушк|олен[её]нок|пингвин|лабубу|ночник"),
        rx(r"хрустал|барокко|ампир|рококо|лофт|loft|бетон|индустр|позолот"),
        families=frozenset({"pink", "blue", "white", "green", "yellow", "terracotta", "purple", "multi"}),
        playful=True,
        cartoons=True,
    ),
    "artdeco": Style(
        "Арт-деко", "Роскошь 1920-х: чёрный с золотом, изумруд и сапфир, бархат, мрамор, латунь и геометрия.",
        ("#111827", "#D4AF37", "#065F46", "#1E3A8A"),
        rx(r"арт-деко|ар-деко"),
        rx(r"золот|латун|черн|чёрн|изумруд|сапфир|темно-син|тёмно-син|бордо|шампан|мрамор"),
        rx(r"бархат|велюр|латун|мрамор|хрустал"),
        rx(r"арт-деко|ар-деко|art deco|\bдеко\b|геометр|гэтсби|gatsby|веер|мрамор|ромб"),
        rx(r"детск|прованс|кантри|лофт|loft|бохо|ротанг|джут|сканди"),
        rx(r"классич|классика|хрустал|модерн"),
        families=frozenset({"gold", "black", "green", "blue", "white", "red"}),
    ),
    "hitech": Style(
        "Хай-тек", "Технологично и строго: хром, стекло, глянец, чёрный и белый, светодиодная подсветка.",
        ("#F8FAFC", "#94A3B8", "#111827", "#38BDF8"),
        rx(r"хай-тек|hi-tech"),
        rx(r"хром|серебр|металлик|черн|чёрн|графит|\bбел(?!ь)|\bсер(ый|ая|ое|ые|о-)"),
        rx(r"хром|алюмин|акрил|глянц|нержаве"),
        rx(r"хай-тек|hi-tech|техно|\bled\b|светодиод|глянц|хром|smart|умн(ый|ая|ое)|сенсор|подсветк"),
        rx(r"классич|прованс|кантри|винтаж|ретро|ротанг|джут|бархат|детск|позолот|кружев|лофт|loft"),
        rx(r"модерн|современ"),
        families=frozenset({"white", "black", "grey"}),
    ),
    "vintage": Style(
        "Винтаж / ретро", "Вещи с историей: состаренная бронза и латунь, лампы Эдисона, кожа, тёплые приглушённые цвета.",
        ("#FEF3C7", "#92400E", "#B45309", "#7F1D1D"),
        rx(r"винтаж|ретро|ковка"),
        rx(r"бронз|\bмед(ь|н)|латун|патин|состарен|антик|крем|бордо|горчич|корич|слонов|оливк|охр"),
        rx(r"латун|\bмед(ь|н)|чугун|кож(а|ан)|бархат|ковк|кован"),
        rx(r"винтаж|vintage|ретро|retro|эдисон|edison|филамент|\bантик|состарен|патин|граммофон|ковк|кован|старин"),
        rx(r"хай-тек|детск|\bled\b|глянц|минимал|сканди"),
        rx(r"классич|прованс|лофт|флористик"),
        families=frozenset({"bronze", "brown", "beige", "white", "red", "green", "gold", "terracotta"}),
    ),
}


@dataclass(frozen=True)
class Slot:
    title: str
    categories: re.Pattern
    exclude: re.Pattern | None = None
    qty: int = 1
    only: re.Pattern | None = None  # оставить только товары с такими словами в названии
    lead: re.Pattern | None = None  # главные товары раздела, показываем первыми
    any_style: bool = False  # у товара нет стиля (матрас): берём лучший по рейтингу и цене


SLOTS: dict[str, Slot] = {
    "chandelier": Slot("Люстра или подвесной светильник", rx(r"^(люстр|[cс]ветильники подвесн)"),
                       rx(r"для растени|трек")),
    "ceiling_light": Slot("Светильник", rx(r"^светильники настенно-потолочн")),
    "sconce": Slot("Бра", rx(r"^(бpa|бра)\b")),
    "floor_lamp": Slot("Торшер", rx(r"^(тоpшер|торшер)")),
    "table_lamp": Slot("Настольная лампа или ночник", rx(r"^(лампы настольн|ночники)"), rx(r"для растени")),
    "curtains": Slot("Шторы", rx(r"^шторы$")),
    "curtain_rod": Slot("Карниз", rx(r"^карнизы$")),
    "roller_blind": Slot("Рулонная штора", rx(r"^(шторы рулонные|жалюзи)$")),
    "rug": Slot("Ковёр", rx(r"^(ковры|циновки|ковры детские)$")),
    "doormat": Slot("Придверный коврик", rx(r"^коврики припорогов")),
    "cushions": Slot("Декоративные подушки", rx(r"^(подушки декоративн|декоративные наволочки)"), qty=2),
    "throw": Slot("Плед или покрывало", rx(r"^(пледы|покрывала)")),
    "wall_art": Slot("Картина", rx(r"^(репродукции|картины)")),
    "frames": Slot("Фоторамки", rx(r"^фоторамки"), qty=2),
    "mirror": Slot("Зеркало", rx(r"^зеркала$")),
    "bath_mirror": Slot("Зеркало", rx(r"^зеркала в ванную")),
    "clock": Slot("Часы", rx(r"^часы настенн")),
    "vase": Slot("Ваза", rx(r"^вазы$")),
    "candles": Slot("Свечи и ароматы", rx(r"^(свечи|подсвечники|аромадиффузор)"), rx(r"новогод")),
    "plant": Slot("Растение", rx(r"^растения (комнатн|искусственн)")),
    "pot": Slot("Кашпо", rx(r"^кашпо, горшки для комнатн")),
    "balcony_box": Slot("Балконный ящик для цветов", rx(r"^ящики балконн")),
    "coffee_table": Slot("Журнальный столик", rx(r"^столы журнальн")),
    "pouf": Slot("Пуф", rx(r"^пуфы")),
    "wall_shelf": Slot("Полка", rx(r"^полки настенн")),
    "hanger": Slot("Вешалка", rx(r"^вешалки настенн")),
    "basket": Slot("Корзина для хранения", rx(r"^(корзины плетен|контейнеры, корзинки|корзины для белья)")),
    "bath_curtain": Slot("Занавеска для ванной", rx(r"^(занавески для ванн|шторки для ванн)")),
    "bath_mat": Slot("Коврик для ванной", rx(r"^коврики декоративн")),
    "towels": Slot("Полотенца", rx(r"^полотенца$"), qty=2),
    "soap_dispenser": Slot("Дозатор для мыла", rx(r"^дозаторы")),
    "tooth_cup": Slot("Стакан для щёток", rx(r"^стаканы для ванной")),
    "tablecloth": Slot("Скатерть или салфетки", rx(r"^(скатерти текстильн|салфетки сервировочн)")),
    "plates": Slot("Тарелки", rx(r"^тарелки$"), rx(r"одноразов|детск|пластмасс|опорн"), qty=4),
    "mugs": Slot("Кружки", rx(r"^кружки$"), rx(r"детск"), qty=4),
    "kitchen_towels": Slot("Кухонные полотенца", rx(r"^полотенца, салфетки кухонн")),
    "garland": Slot("Гирлянда", rx(r"^гирлянды электр")),
    # мебель: подбирается, если выбрано «Декор и мебель»
    "sofa": Slot("Диван", rx(r"^диваны")),
    "armchair": Slot("Кресло", rx(r"^кресла( плетеные)?$")),
    "bookcase": Slot("Стеллаж", rx(r"^стеллажи$"), rx(r"металл|гараж|склад")),
    "bed": Slot("Кровать", rx(r"^кровати")),
    "mattress": Slot("Матрас", rx(r"^матрасы"), any_style=True),
    "nightstand": Slot("Прикроватная тумба", rx(r"^тумбы прикроватн"), qty=2),
    "wardrobe": Slot("Шкаф", rx(r"^(шкафы распашные|шкафы-купе готовые)"),
                     rx(r"^(комплект|фурнитур|петл|направляющ|профил|корпус|двер|фасад|полк|штанг|наполнен)"),
                     only=rx(r"^шкаф")),  # модульные серии: антресоли, секции и стеллажи сюда не берём
    "dresser": Slot("Комод", rx(r"^комоды")),
    "dining_table": Slot("Обеденный стол", rx(r"^столы для столовой")),
    "dining_chairs": Slot("Стулья", rx(r"^стулья для столовой"), qty=4),
    "dish_cabinet": Slot("Шкаф для посуды", rx(r"^шкафы для посуды")),
    "desk": Slot("Письменный стол", rx(r"^столы письменн")),
    "office_chair": Slot("Рабочее кресло", rx(r"^кресла офисн")),
    "shoe_cabinet": Slot("Обувница", rx(r"^(тумбы обувные|полки обувные)"), rx(r"каркас|фасад|дверц")),
    "bath_vanity": Slot("Тумба в ванную", rx(r"^тумбы в ванную")),
    "bath_cabinet": Slot("Шкаф или пенал для ванной", rx(r"^(шкафы для ванной|пеналы)"),
                         rx(r"кухон|духов|холодильн|посудомо|бутылочн|каркас|фасад")),
}

ROOM_SLOTS: dict[str, list[str]] = {
    R.living_room: ["chandelier", "floor_lamp", "curtains", "curtain_rod", "rug", "cushions", "throw", "coffee_table",
                    "wall_art", "mirror", "clock", "vase", "plant", "pot", "candles"],
    R.bedroom: ["chandelier", "table_lamp", "curtains", "curtain_rod", "rug", "cushions", "throw", "wall_art",
                "mirror", "frames", "plant", "pot", "candles"],
    R.kitchen: ["chandelier", "roller_blind", "tablecloth", "plates", "mugs", "kitchen_towels", "clock", "plant", "pot"],
    R.dining_room: ["chandelier", "curtains", "curtain_rod", "tablecloth", "plates", "vase", "candles", "wall_art",
                    "clock"],
    R.bathroom: ["ceiling_light", "bath_mirror", "bath_curtain", "bath_mat", "towels", "soap_dispenser", "tooth_cup",
                 "candles"],
    R.hallway: ["ceiling_light", "mirror", "doormat", "hanger", "clock", "basket"],
    R.home_office: ["table_lamp", "roller_blind", "wall_shelf", "wall_art", "clock", "plant", "pot", "basket"],
    R.utility_room: ["ceiling_light", "wall_shelf", "basket"],
    R.balcony: ["garland", "balcony_box", "plant", "pot", "rug", "throw", "candles"],
    R.general_indoor: ["chandelier", "curtains", "curtain_rod", "rug", "cushions", "wall_art", "mirror", "plant",
                       "pot"],
    "kids_room": ["chandelier", "table_lamp", "curtains", "curtain_rod", "rug", "cushions", "throw", "wall_art",
                  "frames", "clock", "wall_shelf", "basket"],
}
# Крупная мебель по комнатам: добавляется в подборку первой, декор подстраивается под её цвет.
ROOM_FURNITURE: dict[str, list[str]] = {
    R.living_room: ["sofa", "armchair", "bookcase"],
    R.bedroom: ["bed", "mattress", "nightstand", "wardrobe", "dresser"],
    R.kitchen: ["dining_table", "dining_chairs"],
    R.dining_room: ["dining_table", "dining_chairs", "dish_cabinet"],
    R.bathroom: ["bath_vanity", "bath_cabinet"],
    R.hallway: ["shoe_cabinet", "wardrobe"],
    R.home_office: ["desk", "office_chair", "bookcase"],
    R.general_indoor: ["sofa", "armchair", "bookcase"],
    "kids_room": ["bed", "mattress", "wardrobe", "desk", "bookcase"],
}
DECOR_ROOMS = {**{r.value: t for r, t in ROOM_TITLES.items()}, "kids_room": "Детская"}

@dataclass(frozen=True)
class Zone:
    title: str
    description: str
    groups: dict[str, Slot]
    seasonal: bool = False  # сезонные товары показываем и без наличия, с пометкой «нет в наличии»


# Огород, сад и мангальная зона: стиль не выбирается, предлагаем всё, что там может пригодиться.
ZONES: dict[str, Zone] = {
    "vegetable_garden": Zone("Огород", "Семена, рассада, грунт, удобрения, полив, теплицы и инструмент.", {
        "seeds": Slot("Семена овощей", rx(r"^(семена овощей|луковичные овощные|семена сидератов)"), lead=rx(r"томат|огур|перец|морков|капуст|кабач|свекл|редис|зелен|укроп|петрушк|салат|лук")),
        "seedlings": Slot("Рассада и всё для неё", rx(r"^(рассада|горшки для рассады|кассеты для рассады|минипарники)"), lead=rx(r"рассад|кассет|горш|минипарник")),
        "soil": Slot("Грунт и мульча", rx(r"^(готовые почвогрунты|мульча)"), lead=rx(r"грунт|субстрат")),
        "fertilizers": Slot("Удобрения и стимуляторы", rx(r"^(удобрения|регуляторы роста)")),
        "protection": Slot("Защита от вредителей и болезней", rx(r"^(средства защиты от (насекомых|болезней)|препараты защиты от грызунов)")),
        "greenhouse": Slot("Теплицы и укрывной материал", rx(r"^(готовые парники|пленка парниковая|дуги для парников|сопутствующие товары для теплиц|нетканые укрывные|укрывные защитные)")),
        "watering": Slot("Полив", rx(r"^(шланги для полива|соединители шланговые|лейки$|комплектующие для капельного|наборы капельного|пистолеты-распылители|катушки и тележки для шлангов|держатели для шлангов|краны садовые)"), lead=rx(r"^(шланг|лейк|набор (для )?(капельн|полив)|комплект капельн|пистолет|катушк|тележк|дождевател)")),
        "tools": Slot("Инструмент", rx(r"^(лопаты штыковые|лопаты совковые|грабли прямые|вилы|мотыжки|лопатки|черенки|вилки посадочные|конусы посадочные|комплекты садового инструмента|тачки садовые|ведра садовые)"), rx(r"^лопатка(?!.*(садов|посадоч|совков|рассад|цвет))|повар|cuoco|кулинар|для сковород"), lead=rx(r"^(лопата|грабл|вил[ыа]|тяпк|мотыг|тачк|комплект садов|набор садов)")),
        "supports": Slot("Опоры и ограждения грядок", rx(r"^(опоры|заборчики и ограды для клумб|сетка для ограждений)")),
        "machinery": Slot("Культиваторы и рыхлители", rx(r"^(культиваторы)"), lead=rx(r"^культиватор")),
    }),
    "garden": Zone("Сад", "Саженцы и цветы, газон, уход за деревьями, садовый декор, свет и мебель для отдыха.", {
        "trees": Slot("Саженцы", rx(r"^саженцы")),
        "flowers": Slot("Цветы: семена и луковицы", rx(r"^(семена цветов|луковичные цветы)")),
        "lawn": Slot("Газон", rx(r"^(семена газонных|газонокосилки|триммеры для травы|лески для триммеров|дождеватели)"), lead=rx(r"^(газонокосилк|триммер|семена газон|газон)")),
        "pruning": Slot("Уход за деревьями и кустами", rx(r"^(секаторы|ножницы-кусторезы|кусторезы|грабли веерные|опрыскиватели|насадки для опрыскивателей|вары садовые)"), lead=rx(r"^(секатор|сучкорез|кусторез|ножниц|опрыскивател)")),
        "decor": Slot("Садовый декор", rx(r"^(садовые фигуры|подставки для цветов|кашпо, вазоны уличные|модульные покрытия для сада|заборчики и ограды для клумб)"), rx(r"якорь|форма для"), lead=rx(r"фигур|гном|кашпо|вазон|подставк")),
        "lighting": Slot("Садовое освещение", rx(r"^(фонари садовые|светильники на солнечных|светильники акцентного освещения садовые|гирлянды и свечи садовые)")),
        "furniture": Slot("Мебель для отдыха", rx(r"^(комплекты садовой мебели|качели для дачи|гамаки|шезлонги|столы садовые|стулья пластиковые садовые|зонты садовые)"), lead=rx(r"^(комплект|качел|гамак|шезлонг|стол|кресл)")),
        "pump": Slot("Насосы", rx(r"^насосы садовые")),
    }),
    "grill": Zone("Мангальная зона", "Мангал или гриль, всё для готовки на огне, розжиг, мебель, свет и защита от комаров.", {
        "grills": Slot("Мангалы и грили", rx(r"^(мангалы|грили, барбекю|коптильни)"), lead=rx(r"^(мангал|гриль|барбекю|коптильн)")),
        "tools": Slot("Решётки, шампуры, принадлежности", rx(r"^(решетки для барбекю|шампуры|принадлежности для гриля|комплектующие для мангалов)"), lead=rx(r"^(решетк|решётк|шампур|набор)")),
        "fuel": Slot("Розжиг и щепа", rx(r"^(жидкости для розжига|щепа для копчения)")),
        "furniture": Slot("Мебель и тень", rx(r"^(комплекты садовой мебели|столы садовые|стулья пластиковые садовые|шатры, тенты|зонты садовые|качели для дачи)"), lead=rx(r"^(комплект|стол|кресл|стул|шат[её]р|тент)")),
        "lighting": Slot("Свет", rx(r"^(фонари садовые|светильники на солнечных|гирлянды и свечи садовые)")),
        "tableware": Slot("Посуда для пикника", rx(r"^(тарелки, миски одноразовые|столовые приборы одноразовые|наборы одноразовой посуды)")),
        "mosquito": Slot("Защита от комаров", rx(r"^(фумигаторы|средства защиты от насекомых)"), only=rx(r"комар|мошк|москит|фумигатор|репеллент|спирал")),
    }),
    "holidays": Zone("Новый год", "Ёлка и игрушки, гирлянды, новогодний декор для дома и упаковка подарков.", {
        "trees": Slot("Ёлки", rx(r"^([её]лки|ели) искусственн")),
        "balls": Slot("Шары и игрушки", rx(r"^(шары елочные|игрушки елочные)")),
        "top": Slot("Верхушки", rx(r"^верхушки елочные")),
        "tinsel": Slot("Мишура, дождик, бусы", rx(r"^(мишура новогодняя|дождик новогодний|бусы новогодние)")),
        "lights": Slot("Гирлянды", rx(r"^(гирлянды электрические|гирлянды еловые)")),
        "decor": Slot("Новогодний декор", rx(r"^(композиции (искусственные )?новогодние|венки новогодние|фигуры новогодние|ветки новогодние|сувениры новогодние|букеты и праздничные)")),
        "candles": Slot("Свечи и подсвечники", rx(r"^(свечи новогодние|подсвечники новогодние)")),
        "wrap": Slot("Упаковка подарков", rx(r"^(бумага, целлофан|лента, банты|коробки$|пакеты$|мешки новогодние)")),
    }, seasonal=True),
}
@dataclass(frozen=True)
class KitItem:
    title: str
    group: str                       # раздел зоны, из которого берём товар
    only: re.Pattern | None = None   # какие именно товары раздела подходят
    qty: int = 1


@dataclass(frozen=True)
class Kit:
    title: str
    description: str
    items: dict[str, KitItem]


# Готовые наборы для дачи: по одному товару на позицию, как подборка для комнаты.
KITS: dict[str, dict[str, Kit]] = {
    "vegetable_garden": {
        "season": Kit("Начать сезон", "Всё, чтобы вырастить рассаду и посадить первые грядки.", {
            "tomato": KitItem("Семена томатов", "seeds", rx(r"томат")),
            "cucumber": KitItem("Семена огурцов", "seeds", rx(r"огур")),
            "greens": KitItem("Зелень", "seeds", rx(r"укроп|петрушк|салат|базилик|кинз")),
            "carrot": KitItem("Семена моркови", "seeds", rx(r"морков")),
            "soil": KitItem("Грунт для рассады", "soil", rx(r"грунт|субстрат")),
            "cassette": KitItem("Кассеты или горшки для рассады", "seedlings", rx(r"кассет|горш")),
            "fertilizer": KitItem("Удобрение", "fertilizers", rx(r"удобрени")),
            "can": KitItem("Лейка", "watering", rx(r"^лейк")),
            "spade": KitItem("Лопата", "tools", rx(r"^лопата")),
            "rake": KitItem("Грабли", "tools", rx(r"^грабл")),
        }),
        "greenhouse": Kit("Теплица", "Ранний урожай: теплица или парник, укрытие, опоры и капельный полив.", {
            "house": KitItem("Теплица или парник", "greenhouse", rx(r"теплиц|парник")),
            "cover": KitItem("Укрывной материал", "greenhouse", rx(r"укрывн|спанбонд|агроволок")),
            "supports": KitItem("Опоры для томатов", "supports", rx(r"опор|колыш|шпалер")),
            "drip": KitItem("Капельный полив", "watering", rx(r"капельн")),
            "fertilizer": KitItem("Удобрение для томатов и огурцов", "fertilizers", rx(r"томат|огур|овощ")),
        }),
        "watering": Kit("Полив", "Шланг с пистолетом и всё, чтобы поливать без вёдер.", {
            "hose": KitItem("Шланг", "watering", rx(r"^шланг")),
            "gun": KitItem("Пистолет-распылитель", "watering", rx(r"^пистолет")),
            "connectors": KitItem("Соединители для шланга", "watering", rx(r"соединит|коннектор|адаптер")),
            "reel": KitItem("Катушка для шланга", "watering", rx(r"катушк|тележк")),
            "sprinkler": KitItem("Дождеватель", "watering", rx(r"дождеват")),
        }),
        "protection": Kit("Защита урожая", "От вредителей, болезней, птиц и заморозков.", {
            "pests": KitItem("Средство от вредителей", "protection", rx(r"инсектицид|вредител|колорад|тл[яи]")),
            "disease": KitItem("Средство от болезней", "protection", rx(r"фунгицид|болезн|фитофтор")),
            "cover": KitItem("Укрывной материал", "greenhouse", rx(r"укрывн|спанбонд")),
            "fence": KitItem("Ограждение грядки", "supports", rx(r"забор|оград|сетк|бордюр")),
        }),
    },
    "garden": {
        "lawn": Kit("Газон", "Посеять газон и ухаживать за ним.", {
            "seeds": KitItem("Семена газона", "lawn", rx(r"газон")),
            "mower": KitItem("Газонокосилка", "lawn", rx(r"^газонокосилк")),
            "trimmer": KitItem("Триммер для краёв", "lawn", rx(r"^триммер")),
            "rake": KitItem("Веерные грабли", "pruning", rx(r"грабли веерн")),
            "sprinkler": KitItem("Дождеватель", "lawn", rx(r"дождеват")),
        }),
        "orchard": Kit("Плодовый сад", "Саженцы плодовых и всё, чтобы они прижились.", {
            "apple": KitItem("Саженец яблони", "trees", rx(r"яблон")),
            "cherry": KitItem("Саженец вишни или груши", "trees", rx(r"вишн|черешн|груш|слив")),
            "berry": KitItem("Ягодный куст", "trees", rx(r"смородин|малин|крыжовн|голубик|жимолост")),
            "pruner": KitItem("Секатор", "pruning", rx(r"^секатор")),
            "sprayer": KitItem("Опрыскиватель", "pruning", rx(r"^опрыскивател")),
        }),
        "flowerbed": Kit("Цветник", "Клумба у дома: цветы, луковицы, ограждение и садовый декор.", {
            "annuals": KitItem("Семена однолетников", "flowers", rx(r"^семена")),
            "bulbs": KitItem("Луковицы", "flowers", rx(r"тюльпан|нарцисс|лили|гладиолус|георгин|крокус|гиацинт")),
            "border": KitItem("Бордюр для клумбы", "decor", rx(r"бордюр|заборч|оград")),
            "planter": KitItem("Уличное кашпо", "decor", rx(r"кашпо|вазон")),
            "figure": KitItem("Садовая фигура", "decor", rx(r"фигур|гном")),
        }),
        "rest": Kit("Место для отдыха", "Мебель, тень и вечерний свет.", {
            "set": KitItem("Комплект садовой мебели", "furniture", rx(r"^комплект")),
            "swing": KitItem("Качели или гамак", "furniture", rx(r"^(качел|гамак)")),
            "umbrella": KitItem("Зонт от солнца", "furniture", rx(r"зонт")),
            "lights": KitItem("Светильники на солнечных батареях", "lighting", rx(r"солнечн"), qty=4),
            "garland": KitItem("Гирлянда", "lighting", rx(r"гирлянд")),
        }),
    },
    "grill": {
        "shashlik": Kit("Шашлык на компанию", "Мангал, шампуры, розжиг, посуда и защита от комаров.", {
            "grill": KitItem("Мангал", "grills", rx(r"^мангал")),
            "skewers": KitItem("Шампуры", "tools", rx(r"шампур")),
            "grate": KitItem("Решётка", "tools", rx(r"решетк|решётк")),
            "fuel": KitItem("Жидкость для розжига", "fuel", rx(r"розжиг")),
            "plates": KitItem("Одноразовые тарелки", "tableware", rx(r"тарел")),
            "cutlery": KitItem("Одноразовые приборы", "tableware", rx(r"вилк|нож|ложк|прибор")),
            "mosquito": KitItem("От комаров", "mosquito"),
        }),
        "bbq": Kit("Гриль и копчение", "Гриль или барбекю, коптильня, щепа и принадлежности.", {
            "grill": KitItem("Гриль или барбекю", "grills", rx(r"гриль|барбекю")),
            "smoker": KitItem("Коптильня", "grills", rx(r"коптильн")),
            "chips": KitItem("Щепа для копчения", "fuel", rx(r"щепа")),
            "grate": KitItem("Решётка", "tools", rx(r"решетк|решётк")),
            "tools": KitItem("Принадлежности для гриля", "tools", rx(r"щипц|лопатк|кисть|набор|перчат|опахал")),
        }),
        "evening": Kit("Вечер на улице", "Стол, стулья, шатёр от дождя и свет.", {
            "table": KitItem("Стол", "furniture", rx(r"^(стол|комплект)")),
            "chairs": KitItem("Стулья", "furniture", rx(r"^(стул|кресл)"), qty=4),
            "tent": KitItem("Шатёр или тент", "furniture", rx(r"шат[её]р|тент")),
            "lights": KitItem("Садовые фонари", "lighting", rx(r"фонар|светильник"), qty=2),
            "mosquito": KitItem("От комаров", "mosquito"),
        }),
    },
    "holidays": {
        "tree": Kit("Нарядить ёлку", "Ёлка, шары, игрушки, верхушка, гирлянда и мишура.", {
            "tree": KitItem("Искусственная ёлка", "trees"),
            "balls": KitItem("Набор шаров", "balls", rx(r"набор|шар")),
            "toys": KitItem("Ёлочные игрушки", "balls", rx(r"игрушк|фигур|подвеск"), qty=3),
            "top": KitItem("Верхушка", "top"),
            "garland": KitItem("Гирлянда", "lights", rx(r"гирлянд")),
            "tinsel": KitItem("Мишура или бусы", "tinsel"),
        }),
        "home": Kit("Праздничный дом", "Новогодний декор без ёлки: композиция, венок, свечи и огоньки.", {
            "composition": KitItem("Новогодняя композиция", "decor", rx(r"композиц|букет")),
            "wreath": KitItem("Венок или ветки", "decor", rx(r"вен(ок|к)|ветк")),
            "figure": KitItem("Новогодняя фигура", "decor", rx(r"фигур|сувенир")),
            "candles": KitItem("Свечи", "candles", rx(r"свеч"), qty=2),
            "garland": KitItem("Гирлянда на окно", "lights", rx(r"бахром|занавес|штор|сетк|нить|гирлянд")),
        }),
        "gifts": Kit("Упаковать подарки", "Бумага, ленты, пакеты и коробки.", {
            "paper": KitItem("Упаковочная бумага", "wrap", rx(r"бумаг|пленк|плёнк")),
            "ribbon": KitItem("Лента и банты", "wrap", rx(r"лент|бант")),
            "bags": KitItem("Подарочные пакеты", "wrap", rx(r"пакет"), qty=3),
            "box": KitItem("Подарочная коробка", "wrap", rx(r"коробк")),
        }),
    },
}

ZONE_GROUPS = {f"{z}:{g}": slot for z, zone in ZONES.items() for g, slot in zone.groups.items()}

FIT = 3  # хватает метки каталога, слова в названии или пары «цвет + материал»
BUDGETS = {"economy": 0.15, "standard": 0.5, "premium": 0.85}

_STYLE_CHAR = rx(r"^(стиль|стиль интерьера|дизайн|дизайн ковров|дизайн зеркала|дизайн часов)$")
_COLOR_CHAR = rx(r"цвет|оттенок")
_MATERIAL_CHAR = rx(r"материал|состав|тип ткани|обивка")
_WORD_CHAR = rx(r"коллекц|рисунок|дизайн|серия")
_NOT_COLOR = rx(r"температур")
COLOR_FAMILIES = {
    "multi": rx(r"мульти|разноцвет|в ассорт|ассорти|пестр|принт|микс"),
    "gold": rx(r"золот|латун|шампан"),
    "bronze": rx(r"бронз|\bмед(ь|н)|патин"),
    "black": rx(r"черн|чёрн|графит|антрацит"),
    "white": rx(r"\bбел(?!ь)|молоч|слонов|айвори|ivory|крем|ванил"),
    "beige": rx(r"беж|песоч|экрю|капучин|кашемир|льнян"),
    "grey": rx(r"\bсер(ый|ая|ое|ые|о-|ого|ой)|серебр|хром|никел|стал(ь|ьн)|асфальт|бетон"),
    "brown": rx(r"корич|шоколад|венге|орех|какао|мокко"),
    "wood": rx(r"дерев|натурал|\bдуб|сосн|берез|ясен"),
    "green": rx(r"зелен|олив|изумруд|мятн|нефрит|хаки"),
    "blue": rx(r"\bсин|голуб|бирюз|аквамарин|морск\w* волн|индиго"),
    "purple": rx(r"лаванд|сирен|фиолет"),
    "pink": rx(r"розов|пудров|пыльн\w* роз"),
    "yellow": rx(r"желт|лимон|солнеч"),
    "terracotta": rx(r"терракот|горчич|оранж|рыж|охр"),
    "red": rx(r"красн|бордо|вишн"),
}
NEUTRAL_FAMILIES = {"white", "beige"}
# весёлые принты (котики, единороги) не подходят ни одному стилю взрослой комнаты
_PRINTS = rx(r"\bкот(ик\w*|ы|ята|[её]нок|ики)?\b|кошк|собак|\bп[её]с\b|единорог|лабубу|динозавр|мульт(?!и)|смайл|прикол"
             r"|funny|зайч|кролик|[её]жик|пингвин|олен[её]нок|\bтакс[аы]\b|\bлам[аы]\b|\bпанд")

# в морском и лесном звери уместны, а мультяшки и домашние котики — нет
_CARTOON_PETS = rx(r"единорог|лабубу|динозавр|мульт(?!и)|смайл|прикол|funny|\bкот(ик\w*|ы|ята|[её]нок|ики)?\b|кошк|собак|\bп[её]с\b")


def family(item: "Item") -> str | None:
    """Основной цвет товара: из характеристики «Цвет», а если её нет — из названия."""
    for text in (item.colors, item.name):
        found = [(m.start(), name) for name, pattern in COLOR_FAMILIES.items() if (m := pattern.search(text))]
        if found:
            return min(found)[1]
    return None


_NOVELTY = rx(r"детск|единорог|новогод|ёлоч|елоч|мульт(?!и)|лабубу|rgb")
_STYLE_SIGNAL = rx(r"модерн|хай-тек|лофт|классич|классика|арт-деко|прованс|сканди|эко|винтаж|флористик|детск|контемпорари")


@dataclass
class Item:
    id: int
    name: str
    price: Decimal
    rating: float
    picture_url: str | None
    url_key: str | None
    brand: str | None
    attrs: str = ""
    colors: str = ""
    materials: str = ""
    words: str = ""
    in_stock: bool = True


@dataclass
class Scored:
    item: Item
    score: float
    why: list[str] = field(default_factory=list)
    strong: bool = False  # есть признак стиля кроме цвета: метка каталога, слово или материал


def _first(pattern: re.Pattern, text: str) -> str | None:
    """Найденное слово целиком: «бронз» → «бронза»."""
    m = pattern.search(text)
    if not m:
        return None
    start, end = m.start(), m.end()
    while start > 0 and (text[start - 1].isalnum() or text[start - 1] == "-"):
        start -= 1
    while end < len(text) and (text[end].isalnum() or text[end] == "-"):
        end += 1
    return text[start:end].lower()


def score(item: Item, style: Style) -> Scored:
    """Сколько признаков стиля у товара. Явная разметка каталога весит больше, слово в названии — меньше."""
    s, why, strong = 0.0, [], False
    if item.attrs:
        if hit := _first(style.attr, item.attrs):
            s += 5
            strong = True
            why.append(f"в каталоге отмечен стиль «{hit}»")
        elif _STYLE_SIGNAL.search(item.attrs) and not (style.compatible and style.compatible.search(item.attrs)):
            s -= 3  # каталог явно отнёс товар к другому стилю
    if hit := _first(style.words, f"{item.name} {item.words}"):
        s += 3
        strong = True
        why.append(f"в описании: «{hit}»")
    if hit := _first(style.materials, f"{item.materials} {item.name}"):
        s += 2
        strong = True
        why.append(f"материал: {hit}")
    if hit := _first(style.colors, f"{item.colors} {item.name}"):
        s += 2
        why.append(f"цвет: {hit}")
    if style.avoid.search(f"{item.name} {item.attrs} {item.words}"):
        s -= 6
    name = re.sub(re.escape(item.brand), " ", item.name, flags=re.I) if item.brand else item.name
    if not style.cartoons and (_CARTOON_PETS if style.playful else _PRINTS).search(f"{name} {item.words}"):
        s -= 5
    if style.families and (f := family(item)):
        s += 1 if f in style.families else -3  # цвет вне палитры стиля
    return Scored(item, s, why, strong)



class DecorIndex:
    """Товары декора по позициям; строится один раз и обновляется, когда меняется каталог."""

    def __init__(self) -> None:
        self.version: tuple | None = None
        self.by_slot: dict[str, list[Item]] = {}
        self._lock = threading.Lock()  # фоновый прогрев при старте и первый запрос не строят индекс дважды

    def ensure(self, session: Session) -> None:
        version = tuple(session.execute(select(func.count(Product.id), func.max(Product.last_seen_run),
                                               func.max(Product.ingested_at))).one())
        if version == self.version:
            return
        with self._lock:
            if version != self.version:
                self.by_slot = self._build(session)
                self.version = version

    @staticmethod
    def _build(session: Session) -> dict[str, list[Item]]:
        slots = SLOTS | ZONE_GROUPS
        slot_ids: dict[str, list[int]] = {k: [] for k in slots}
        seasonal = {f"{z}:{g}" for z, zone in ZONES.items() if zone.seasonal for g in zone.groups}
        rows = session.execute(select(Product.id, Product.categories, Product.in_stock).where(
            Product.status.isnot(False), Product.result_price.isnot(None), Product.result_price > 0)).all()
        kids: set[int] = set()
        for pid, categories, in_stock in rows:
            names = [str(n).strip() for n in (categories or {}).values()]
            if any("детск" in n.lower() for n in names):
                kids.add(pid)
            for key, slot in slots.items():
                if in_stock is False and key not in seasonal:
                    continue
                if any(slot.categories.search(n) and not (slot.exclude and slot.exclude.search(n)) for n in names):
                    slot_ids[key].append(pid)
        ids = sorted({i for v in slot_ids.values() for i in v})
        items: dict[int, Item] = {}
        for i in range(0, len(ids), 900):
            chunk = ids[i:i + 900]
            for p in session.execute(select(Product.id, Product.name, Product.result_price, Product.rating,
                                            Product.recsys_rating, Product.picture_url, Product.url_key,
                                            Product.brand_name, Product.in_stock).where(Product.id.in_(chunk))):
                items[p.id] = Item(p.id, p.name or "", p.result_price, float(p.rating or p.recsys_rating or 0),
                                   p.picture_url, p.url_key, p.brand_name,
                                   words=" детский" if p.id in kids else "", in_stock=p.in_stock is not False)  # «Люстры для детских» и т. п.
            for pid, name, value in session.execute(
                    select(ProductCharacteristic.product_id, ProductCharacteristic.name,
                           ProductCharacteristic.value_raw).where(ProductCharacteristic.product_id.in_(chunk))):
                item, name, value = items.get(pid), name or "", (value or "").strip()
                if not item or not value:
                    continue
                if _STYLE_CHAR.search(name):
                    item.attrs += " " + value
                if _COLOR_CHAR.search(name) and not _NOT_COLOR.search(name):
                    item.colors += " " + value
                if _MATERIAL_CHAR.search(name):
                    item.materials += " " + value
                if _WORD_CHAR.search(name):
                    item.words += " " + value
        out = {}
        for key, pids in slot_ids.items():
            slot_items = [items[i] for i in pids if i in items]
            if exclude := slots[key].exclude:
                slot_items = [x for x in slot_items if not exclude.search(x.name)]
            if only := slots[key].only:
                slot_items = [x for x in slot_items if only.search(x.name)]
            out[key] = slot_items
        return out

    def zone_items(self, zone: str, group: str) -> list[Item]:
        """Товары раздела зоны: сначала с хорошим рейтингом и картинкой, потом дешевле."""
        items = self.by_slot.get(f"{zone}:{group}", [])
        lead = ZONES[zone].groups[group].lead
        return sorted(items, key=lambda x: (not x.in_stock, not (lead and lead.search(x.name)), -x.rating,
                                            x.picture_url is None, x.price))

    def kit_items(self, zone: str, kit: str, key: str) -> list[Item]:
        """Подходящие товары для позиции набора, главные первыми."""
        item = KITS[zone][kit].items[key]
        return [i for i in self.zone_items(zone, item.group) if not item.only or item.only.search(i.name)]

    def kit_pick(self, zone: str, kit: str, key: str, budget: str) -> tuple[Item | None, int]:
        """Товар под бюджет из 30 лучших по рейтингу: эконом — дешёвый, премиум — дорогой."""
        items = self.kit_items(zone, kit, key)
        if not items:
            return None, 0
        top = sorted(items[:30], key=lambda i: i.price)
        return top[min(len(top) - 1, int(BUDGETS[budget] * len(top)))], len(items)

    def ranked(self, slot: str, style: Style) -> list[Scored]:
        """Товары позиции в этом стиле, лучшие первыми. Если в стиле нет ничего — нейтральные."""
        scored = [score(x, style) for x in self.by_slot.get(slot, [])]
        fitting = [x for x in scored if x.score >= FIT and x.strong]  # один цвет стиль не делает
        if not fitting:
            fitting = [x for x in scored if x.score >= 0 and not _NOVELTY.search(f"{x.item.name} {x.item.attrs} {x.item.words}")
                       and family(x.item) in style.families | NEUTRAL_FAMILIES | {None}]
            note = "подходит к любому стилю" if SLOTS.get(slot) and SLOTS[slot].any_style \
                else "нейтральный вариант: в этом стиле ничего нет"
            for x in fitting:
                x.why = [note]
        return sorted(fitting, key=lambda x: (-x.score, -x.item.rating, x.item.price))

    def pick(self, slot: str, style: Style, budget: str,
             room_colors: set[str] = frozenset()) -> tuple[Scored | None, int]:
        """Один товар на позицию: из самых стильных выбираем по цене под бюджет.

        `room_colors` — основные цвета уже подобранных вещей: новые позиции держим в той же гамме,
        чтобы комната выглядела цельно, а не набором случайных цветов.
        """
        ranked = self.ranked(slot, style)
        if not ranked:
            return None, 0
        best = ranked[0].score
        top = [x for x in ranked if x.score >= max(FIT, best - 4)] or ranked
        if len(top) < 10:
            top = ranked[:10]  # иначе бюджету не из чего выбирать
        if room_colors:
            same = [x for x in top if family(x.item) in room_colors | NEUTRAL_FAMILIES | {None}]
            if len(same) >= 3:
                top = same
        by_price = sorted(top, key=lambda x: (x.item.price, -x.score))
        chosen = by_price[min(len(by_price) - 1, int(BUDGETS[budget] * len(by_price)))]
        return chosen, len(ranked)


INDEX = DecorIndex()

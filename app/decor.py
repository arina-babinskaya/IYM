"""Подбор декора: помещение + стиль → по одному товару на каждую позицию (свет, шторы, ковёр, картина…).

Позиции находятся по категориям каталога, стиль — по характеристикам товара. Многие группы уже размечены
в каталоге («Стиль» у светильников, «Стиль интерьера» у мебели, «Дизайн ковров», «Дизайн часов»),
остальное определяется по цвету, материалу и словам в названии.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Product, ProductCharacteristic
from app.schemas import RoomType

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


STYLES: dict[str, Style] = {
    "modern": Style(
        "Современный", "Чистые линии, нейтральные цвета, стекло и металл, минимум декора.",
        ("#F5F5F4", "#A8A29E", "#44403C", "#1C1917"),
        rx(r"модерн|хай-тек|современ|контемпорари|минимал"),
        rx(r"\bбел|\bсер(ый|ая|ое|ые|о-)|черн|чёрн|хром|графит|антрацит|никель|прозрачн"),
        rx(r"стекл|металл|алюмин|акрил|сталь|блэкаут|сатин|микрофибр|вельвет|велюр"),
        rx(r"модерн|modern|минимал|геометр|хай-тек|однотон|без рисунка|абстракц|графич"),
        rx(r"классич|винтаж|прованс|кантри|хрустал|барокко|ампир|детск|рококо|кружев"),
        families=frozenset({"white", "grey", "black", "beige"}),
    ),
    "scandi": Style(
        "Скандинавский", "Светло и уютно: белый, серый, светлое дерево, хлопок, шерсть, живые растения.",
        ("#FFFFFF", "#E7E5E4", "#D6C4A8", "#9CA3AF"),
        rx(r"сканди|скандинав"),
        rx(r"\bбел|светло-сер|\bсер(ый|ая|ое|ые)|беж|молоч|натурал|светл\w* дуб|белен|берез|слонов|мятн|пудров"),
        rx(r"дерев|берез|сосн|дуб|хлоп|\bл[её]н(?!т)|льн|рогожк|шерст|войлок|керамик|фанер"),
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
        rx(r"классич|классика|арт-деко|ар-деко|хрустал"),
        rx(r"золот|бронз|латун|беж|крем|слонов|ванил|шампан|бордо|изумруд|айвори|ivory|патин"),
        rx(r"хрустал|бархат|жаккард|латун|фарфор|велюр"),
        rx(r"классик|classic|вензел|багет|барокко|ампир|рококо|версаль|\bантик|вит(ая|ые|ой)|royal|натюрморт|пейзаж"),
        rx(r"лофт|loft|хай-тек|детск|сканди|индустр"),
        families=frozenset({"gold", "bronze", "white", "beige", "brown", "green", "red"}),
    ),
    "provence": Style(
        "Прованс", "Деревенский уют: лаванда, мята, молочный, цветочные узоры, клетка, состаренные вещи.",
        ("#E9D5FF", "#A78BFA", "#D1FAE5", "#FFF7ED"),
        rx(r"прованс|кантри|винтаж|флористик|шебби"),
        rx(r"лаванд|сирен|мятн|пудров|молоч|крем|олив|голуб|розов|состарен"),
        rx(r"хлоп|\bл[её]н(?!т)|льн|керамик|кружев|ротанг|жаккард|тюл|вуал"),
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
        rx(r"джут|ротанг|бамбук|сизал|морск\w* трав|лоз|\bив(а|ы)\b|дерев|массив|хлоп|\bл[её]н(?!т)|глин|кокос|макраме|рогоз|водоросл|льн|рогожк"),
        rx(r"бохо|boho|\bэко(?!ном)|джут|ротанг|бамбук|плетен|макраме|натурал|этно"),
        rx(r"хай-тек|хрустал|глянц|детск|хром"),
        rx(r"модерн|современ|флористик"),
        families=frozenset({"beige", "brown", "wood", "green", "terracotta", "white"}),
    ),
}


@dataclass(frozen=True)
class Slot:
    title: str
    categories: re.Pattern
    exclude: re.Pattern | None = None
    qty: int = 1


SLOTS: dict[str, Slot] = {
    "chandelier": Slot("Люстра или подвесной светильник", rx(r"^(люстр|[cс]ветильники подвесн)"),
                       rx(r"для растени|трек|детск")),
    "ceiling_light": Slot("Светильник", rx(r"^светильники настенно-потолочн"), rx(r"детск")),
    "sconce": Slot("Бра", rx(r"^(бpa|бра)\b"), rx(r"детск")),
    "floor_lamp": Slot("Торшер", rx(r"^(тоpшер|торшер)")),
    "table_lamp": Slot("Настольная лампа", rx(r"^лампы настольн"), rx(r"для растени")),
    "curtains": Slot("Шторы", rx(r"^шторы$")),
    "curtain_rod": Slot("Карниз", rx(r"^карнизы$")),
    "roller_blind": Slot("Рулонная штора", rx(r"^(шторы рулонные|жалюзи)$")),
    "rug": Slot("Ковёр", rx(r"^(ковры|циновки)$")),
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
    "pouf": Slot("Пуф или кресло", rx(r"^(пуфы|кресла)")),
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
}

ROOM_SLOTS: dict[RoomType, list[str]] = {
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
}

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
    "white": rx(r"\bбел|молоч|слонов|айвори|ivory|крем|ванил"),
    "beige": rx(r"беж|песоч|экрю|капучин|кашемир|льнян"),
    "grey": rx(r"\bсер(ый|ая|ое|ые|о-|ого|ой)|серебр|хром|никел|стал(ь|ьн)|асфальт|бетон"),
    "brown": rx(r"корич|шоколад|венге|орех|какао|мокко"),
    "wood": rx(r"дерев|натурал|\bдуб|сосн|берез|ясен"),
    "green": rx(r"зелен|олив|изумруд|мятн|нефрит|хаки"),
    "blue": rx(r"\bсин|голуб|бирюз|аквамарин|морск\w* волн|индиго"),
    "purple": rx(r"лаванд|сирен|фиолет"),
    "pink": rx(r"розов|пудров|пыльн\w* роз"),
    "terracotta": rx(r"терракот|горчич|оранж|рыж|охр"),
    "red": rx(r"красн|бордо|вишн"),
}
NEUTRAL_FAMILIES = {"white", "beige"}
# весёлые принты (котики, единороги) не подходят ни одному стилю взрослой комнаты
_PRINTS = rx(r"\bкот(ик\w*|ы|ята|[её]нок|ики)?\b|кошк|собак|\bп[её]с\b|единорог|лабубу|динозавр|мульт|смайл|прикол"
             r"|funny|зайч|кролик|[её]жик|пингвин|олен[её]нок|\bтакс[аы]\b|\bлам[аы]\b|\bпанд")


def family(item: "Item") -> str | None:
    """Основной цвет товара: из характеристики «Цвет», а если её нет — из названия."""
    for text in (item.colors, item.name):
        found = [(m.start(), name) for name, pattern in COLOR_FAMILIES.items() if (m := pattern.search(text))]
        if found:
            return min(found)[1]
    return None


_NOVELTY = rx(r"детск|единорог|новогод|ёлоч|елоч|мульт|лабубу|rgb")
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


@dataclass
class Scored:
    item: Item
    score: float
    why: list[str] = field(default_factory=list)


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
    s, why = 0.0, []
    if item.attrs:
        if hit := _first(style.attr, item.attrs):
            s += 5
            why.append(f"в каталоге отмечен стиль «{hit}»")
        elif _STYLE_SIGNAL.search(item.attrs) and not (style.compatible and style.compatible.search(item.attrs)):
            s -= 3  # каталог явно отнёс товар к другому стилю
    if hit := _first(style.words, f"{item.name} {item.words}"):
        s += 3
        why.append(f"в описании: «{hit}»")
    if hit := _first(style.materials, f"{item.materials} {item.name}"):
        s += 2
        why.append(f"материал: {hit}")
    if hit := _first(style.colors, f"{item.colors} {item.name}"):
        s += 2
        why.append(f"цвет: {hit}")
    if style.avoid.search(f"{item.name} {item.attrs} {item.words}"):
        s -= 6
    name = re.sub(re.escape(item.brand), " ", item.name, flags=re.I) if item.brand else item.name
    if _PRINTS.search(f"{name} {item.words}"):
        s -= 5
    if style.families and (f := family(item)):
        s += 1 if f in style.families else -3  # цвет вне палитры стиля
    return Scored(item, s, why)



class DecorIndex:
    """Товары декора по позициям; строится один раз и обновляется, когда меняется каталог."""

    def __init__(self) -> None:
        self.version: tuple | None = None
        self.by_slot: dict[str, list[Item]] = {}

    def ensure(self, session: Session) -> None:
        version = tuple(session.execute(select(func.count(Product.id), func.max(Product.last_seen_run),
                                               func.max(Product.ingested_at))).one())
        if version != self.version:
            self.by_slot = self._build(session)
            self.version = version

    @staticmethod
    def _build(session: Session) -> dict[str, list[Item]]:
        slot_ids: dict[str, list[int]] = {k: [] for k in SLOTS}
        rows = session.execute(select(Product.id, Product.categories).where(
            Product.status.isnot(False), Product.in_stock.isnot(False),
            Product.result_price.isnot(None), Product.result_price > 0)).all()
        for pid, categories in rows:
            names = [str(n).strip() for n in (categories or {}).values()]
            for key, slot in SLOTS.items():
                if any(slot.categories.search(n) and not (slot.exclude and slot.exclude.search(n)) for n in names):
                    slot_ids[key].append(pid)
        ids = sorted({i for v in slot_ids.values() for i in v})
        items: dict[int, Item] = {}
        for i in range(0, len(ids), 900):
            chunk = ids[i:i + 900]
            for p in session.execute(select(Product.id, Product.name, Product.result_price, Product.rating,
                                            Product.recsys_rating, Product.picture_url, Product.url_key,
                                            Product.brand_name).where(Product.id.in_(chunk))):
                items[p.id] = Item(p.id, p.name or "", p.result_price, float(p.rating or p.recsys_rating or 0),
                                   p.picture_url, p.url_key, p.brand_name)
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
            if exclude := SLOTS[key].exclude:
                slot_items = [x for x in slot_items if not exclude.search(x.name)]
            out[key] = slot_items
        return out

    def ranked(self, slot: str, style: Style) -> list[Scored]:
        """Товары позиции в этом стиле, лучшие первыми. Если в стиле нет ничего — нейтральные."""
        scored = [score(x, style) for x in self.by_slot.get(slot, [])]
        fitting = [x for x in scored if x.score >= FIT]
        if not fitting:
            fitting = [x for x in scored if x.score >= 0 and not _NOVELTY.search(f"{x.item.name} {x.item.attrs} {x.item.words}")
                       and family(x.item) in style.families | NEUTRAL_FAMILIES | {None}]
            for x in fitting:
                x.why = ["нейтральный вариант: в этом стиле ничего нет"]
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

"""Из разговора с консультантом — в смету: GigaChat достаёт параметры для калькулятора, мы их проверяем.

Ответ модели — только черновик: помещения, виды ремонта, материалы пожеланий сверяются со справочниками,
размеры должны быть положительными, а то, чего в разговоре не было, либо берётся по умолчанию (высота
потолка, типичные окна и двери, работы по умолчанию), либо попадает в список «не хватает».
"""
from __future__ import annotations

import json
import re
from decimal import Decimal

from pydantic import BaseModel, ValidationError, field_validator

from app.llm.gigachat import GigaChatError
from app.plans import OPTIONS, Option, work_materials, works_for_room
from app.schemas import ROOM_DEFAULT_OPENINGS, ROOM_TITLES, RoomInput, RoomType
from app.taxonomy import RENOVATION_TITLES, WORKS, Material, RenovationType

# пожелания можно давать к любому материалу сметы: обоям, ламинату, светильникам, розеткам, плитке…
WISH_MATERIALS = sorted((m for m in Material if m.value != "other"), key=lambda m: m.value)
ROOM_ALIASES = {"kids_room": RoomType.bedroom, "nursery": RoomType.bedroom, "children_room": RoomType.bedroom}
DEFAULT_HEIGHT = Decimal("2.7")
SURFACES = {"floor": "пол", "wall": "стены", "ceiling": "потолок"}


def work_title(o: Option) -> str:
    extra = o.variant or (SURFACES.get(o.surface.value) if o.surface else None)
    return WORKS[o.work].title + (f" ({extra})" if extra else "")


# все варианты работ из справочника калькулятора: ключ «работа:поверхность:вариант» → название
WORK_CHOICES = {o.key: work_title(o) for opts in OPTIONS.values() for o in opts}

# отделка стен «или-или»: если человек хочет обои, покраска стен по умолчанию уходит, и наоборот
CONFLICTS = {"wallpapering:wall:": ["wall_painting:wall:"], "wall_painting:wall:": ["wallpapering:wall:"]}

# пожелание к материалу включает свою работу: «бежевые обои» — значит, нужна оклейка обоями
WISH_WORK = {Material.wallpaper: "wallpapering:wall:", Material.paint: "wall_painting:wall:",
             Material.laminate: "floor_covering_install:floor:ламинат",
             Material.linoleum: "floor_covering_install:floor:линолеум",
             Material.decorative: "decorative_finish_install:wall:"}
TEXT_MATERIAL = [(re.compile(r"обо[июе]", re.I), Material.wallpaper),
                 (re.compile(r"краск|покрас|окрас", re.I), Material.paint),
                 (re.compile(r"ламинат", re.I), Material.laminate), (re.compile(r"линолеум", re.I), Material.linoleum),
                 (re.compile(r"плитк|кафел|керамогранит", re.I), Material.tile)]
# к какому материалу относится пожелание — определяем сами по словам, чтобы не слать модели весь справочник
WISH_TEXT_MATERIAL = TEXT_MATERIAL + [
    (re.compile(r"светильник|люстр|\bбра\b|подсветк|спот", re.I), Material.lighting),
    (re.compile(r"\bламп", re.I), Material.lamps), (re.compile(r"розетк", re.I), Material.socket),
    (re.compile(r"выключат", re.I), Material.switch), (re.compile(r"плинтус|порог", re.I), Material.skirting),
    (re.compile(r"\bдвер", re.I), Material.doors), (re.compile(r"грунт", re.I), Material.primer),
    (re.compile(r"шпакл|шпатл", re.I), Material.putty), (re.compile(r"штукатур", re.I), Material.plaster),
    (re.compile(r"гипсокартон|\bгкл", re.I), Material.drywall), (re.compile(r"затирк", re.I), Material.grout),
    (re.compile(r"подложк", re.I), Material.underlay), (re.compile(r"гидроизол", re.I), Material.waterproofing),
    (re.compile(r"смесител|раковин|унитаз|душев|\bванн[уаы]\b|полотенцесуш", re.I), Material.plumbing),
    (re.compile(r"\bокн[оа]\b|подоконник", re.I), Material.windows),
]

# вид ремонта засчитываем, только если клиент его действительно назвал (модель любит додумывать)
RENOVATION_WORDS = {
    RenovationType.cosmetic: re.compile(r"космет|освеж|лёгк\w* ремонт|легк\w* ремонт|небольш\w* ремонт", re.I),
    RenovationType.capital: re.compile(r"капитал|с нуля|полн\w* ремонт|голы\w* стен|черн\w* отделк|демонтаж", re.I),
    RenovationType.euro: re.compile(r"евро|под ключ|элитн|премиум", re.I),
    RenovationType.rental: re.compile(r"под сдачу|сдава|аренд|квартирант", re.I),
}


def _positive(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if 0 < x < 100 else None


class BriefOpening(BaseModel):
    kind: str = "window"
    width_m: float | None = None
    height_m: float | None = None
    count: int = 1

    _num = field_validator("width_m", "height_m", mode="before")(lambda v: _positive(v))


class BriefWish(BaseModel):
    text: str = ""
    materials: list[str] = []


class BriefRoom(BaseModel):
    room_type: str | None = None
    name: str | None = None
    length_m: float | None = None
    width_m: float | None = None
    height_m: float | None = None
    area_m2: float | None = None  # площадь пола, если человек назвал её вместо длины и ширины (комната буквой Г и т.п.)
    windows: int | None = None
    doors: int | None = None
    openings: list[BriefOpening] = []
    wishes: list[BriefWish] = []
    add_works: list[str] = []
    remove_works: list[str] = []
    only_works: bool = False  # «просто покрасить стены»: нужны только названные работы, не ремонт целиком

    _num = field_validator("length_m", "width_m", "height_m", "area_m2", mode="before")(lambda v: _positive(v))


class BriefDraft(BaseModel):
    renovation_type: str | None = None
    rooms: list[BriefRoom] = []
    notes: list[str] = []  # предупреждения для клиента, которые нашли при сверке со словами клиента


def prompt(transcript: str) -> list[dict[str, str]]:
    rooms = ", ".join(f"{r.value} ({t})" for r, t in ROOM_TITLES.items())
    renovations = ", ".join(f"{r.value} ({t})" for r, t in RENOVATION_TITLES.items())
    system = (
        "Ты помогаешь перенести разговор о ремонте в калькулятор сметы. Извлеки из разговора только то, что "
        "человек сказал сам; ничего не придумывай. Неизвестное — null или пустой список.\n"
        f"room_type — один из: {rooms}; детскую считай bedroom.\n"
        f"renovation_type — один из: {renovations}.\n"
        "Размеры в метрах: length_m и width_m — длина и ширина пола, height_m — высота потолка; "
        "area_m2 — площадь пола в м², если человек назвал площадь.\n"
        "windows и doors — количество окон и дверей; если названы размеры, добавь их в openings "
        "(kind: window или door, width_m, height_m, count).\n"
        "wishes — пожелания к отделке: что хочет человек и что посоветовал консультант, если человек согласился или "
        "не возражал; переноси все характеристики (цвет, тип, свойства), например «бежевые моющиеся флизелиновые обои», "
        "«ламинат 33 класса под светлый дуб»; "
        "add_works — работы, которые человек прямо попросил сделать; remove_works — которые прямо сказал не делать "
        "(например «проводку не трогаем»). Только ключи из списка, ничего не додумывай:\n"
        + "\n".join(f"- {k} — {t}" for k, t in WORK_CHOICES.items()) + "\n"
        "only_works — true ТОЛЬКО если человек прямо отказался от ремонта целиком и сказал, что нужны лишь эти работы "
        "(«ремонт не нужен, только покрасить стены», «больше ничего не надо, только поменять ламинат»). "
        "Если человек просто назвал работу, а про вид ремонта ничего не сказал, — false.\n"
        'Ответь только JSON: {"renovation_type": "...", "rooms": [{"room_type": "...", "name": "...", '
        '"length_m": 0, "width_m": 0, "height_m": 0, "area_m2": 0, "windows": 0, "doors": 0, "openings": [], '
        '"wishes": [{"text": "..."}], "add_works": [], "remove_works": [], "only_works": false}]}'
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": "Разговор:\n" + transcript}]


def transcript(messages: list[tuple[str, str]], limit_chars: int = 8000) -> str:
    """Разговор для проверки данных, в хронологическом порядке.

    Слова клиента важнее всего (там размеры, вид ремонта, работы) и они короткие — оставляем их целиком,
    даже из начала длинного чата. Старые ответы консультанта сокращаем: из них нужно только то,
    с чем клиент согласился, а это обычно видно по двум последним ответам.
    """
    assistant_at = [i for i, (role, _) in enumerate(messages) if role != "user"]
    recent = set(assistant_at[-2:])
    lines = []
    for i, (role, content) in enumerate(messages):
        text = content.strip()
        if role == "user":
            lines.append(["Клиент", text[:1500]])
        else:
            cap = 2000 if i in recent else 300
            lines.append(["Консультант", text if len(text) <= cap else text[:cap].rstrip() + "…"])
    size = sum(len(a) + len(b) + 2 for a, b in lines)
    while size > limit_chars and len(lines) > 1:  # сначала убираем старые ответы консультанта, потом старые слова клиента
        drop = next((k for k, (who, _) in enumerate(lines) if who == "Консультант"), 0)
        size -= len(lines[drop][0]) + len(lines[drop][1]) + 2
        del lines[drop]
    return "\n".join(f"{who}: {text}" for who, text in lines)


def parse(content: str) -> BriefDraft:
    m = re.search(r"\{.*\}", content, re.DOTALL)
    if not m:
        raise GigaChatError("GigaChat не вернул параметры сметы", kind="schema_validation")
    try:
        return BriefDraft.model_validate(json.loads(m.group(0)))
    except (ValueError, ValidationError) as exc:
        raise GigaChatError("GigaChat вернул параметры в неожиданном формате", kind="schema_validation") from exc


def _room_type(value: str | None) -> RoomType | None:
    if value in ROOM_ALIASES:
        return ROOM_ALIASES[value]
    try:
        return RoomType(value)
    except ValueError:
        return None


def _matching(key: str, options: dict[str, Option]) -> list[str]:
    """Ключ от модели → ключи работ этой комнаты: точное совпадение или та же работа и поверхность."""
    if key in options:
        return [key]
    work, _, rest = key.partition(":")
    surface = rest.partition(":")[0]
    return [k for k, o in options.items() if o.work.value == work and (not surface or (o.surface and o.surface.value == surface))]


# в каком порядке пробуем виды ремонта, когда человеку нужны только отдельные работы
RENOVATION_ORDER = [RenovationType.cosmetic, RenovationType.rental, RenovationType.capital, RenovationType.euro]


def renovation_for(room: RoomType, add: list[str]) -> RenovationType | None:
    """Самый простой вид ремонта, в котором есть все названные работы (или хотя бы большинство)."""
    best, best_hits = None, 0
    for reno in RENOVATION_ORDER:
        options = {o.key: o for o, _ in works_for_room(room, reno)}
        hits = sum(1 for k in add if _matching(k, options))
        if hits == len(add) and hits:
            return reno
        if hits > best_hits:
            best, best_hits = reno, hits
    return best


def choose_works(room: RoomType, renovation: RenovationType, add: list[str], remove: list[str], only: bool = False):
    """Работы по умолчанию для комнаты и вида ремонта, плюс то, что человек попросил, минус то, от чего отказался.

    `only` — человеку нужны только названные работы: начинаем не с работ по умолчанию, а с пустого списка.
    """
    pairs = works_for_room(room, renovation)
    options = {o.key: o for o, _ in pairs}
    chosen = [] if only else [o.key for o, default in pairs if default]
    added, removed, replaced = [], [], []
    for key in remove:
        for k in _matching(key, options):
            if k in chosen:
                chosen.remove(k)
                removed.append(work_title(options[k]))
    for key in add:
        found = _matching(key, options)
        if not found or any(k in chosen for k in found):
            continue
        k = found[0]
        o = options[k]
        # ламинат и линолеум — варианты одной работы, обои и покраска стен — «или-или»: новое заменяет прежнее
        rivals = [c for c in chosen if options[c].work == o.work and options[c].surface == o.surface]
        rivals += [c for c in CONFLICTS.get(k, []) if c in chosen and c not in add]
        for other in rivals:
            chosen.remove(other)
            replaced.append(f"{work_title(options[other])} → {work_title(o)}")
        chosen.append(k)
        if not rivals:
            added.append(work_title(o))
    order = [o.key for o, _ in pairs]
    works = [{"work_type": options[k].work.value, "surface": options[k].surface.value if options[k].surface else None,
              "materials": [m.value for m in work_materials(options[k].work, options[k].materials)]}
             for k in sorted(chosen, key=order.index)]
    return works, added, removed, replaced


def _said(value: float | None, text: str) -> bool:
    """Число действительно есть в словах клиента: «4», «3,5», «3.5» или «350» (в сантиметрах)."""
    if value is None:
        return False
    forms = {f"{value:g}", f"{value:g}".replace(".", ","), str(round(value * 100))}
    return any(re.search(rf"(?<![\d.,]){re.escape(f)}(?![\d]|[.,]\d)", text) for f in forms)


_N = r"(\d+(?:[.,]\d+)?)"
SIZE_PATTERNS = {
    "length_m": re.compile(rf"длин\w*\s*(?:[-—:=]\s*)?{_N}", re.I),
    "width_m": re.compile(rf"ширин\w*\s*(?:[-—:=]\s*)?{_N}", re.I),
    "height_m": re.compile(rf"высот\w*\s*(?:потолк\w*\s*)?(?:[-—:=]\s*)?{_N}", re.I),
    "area_m2": re.compile(rf"площад\w*\s*(?:[-—:=]\s*)?{_N}|{_N}\s*(?:кв\.?\s*м|м2|м²|квадрат)", re.I),
}
BY_PATTERN = re.compile(rf"(?<![\d.,]){_N}\s*(?:на|x|х|×|\*)\s*{_N}(?![\d]|[.,]\d)(?!\s*(?:на|x|х|×|\*|тыс|руб|₽|недел|дн|час|мес|%))", re.I)


def _num(text: str) -> float | None:
    value = float(text.replace(",", "."))
    if value >= 100:  # «350 на 400» — в сантиметрах
        value /= 100
    return value if 0 < value < 100 else None


def sizes_from_text(text: str) -> dict[str, float]:
    """Размеры из слов клиента: «длина 4 ширина 2», «4 на 2,5», «площадь 8», «высота 2,7». Последнее сказанное важнее."""
    found: dict[str, float] = {}
    for field, rx in SIZE_PATTERNS.items():
        hits = [next(g for g in m.groups() if g) for m in rx.finditer(text)]
        if hits and (value := _num(hits[-1])):
            found[field] = value if field != "area_m2" else float(hits[-1].replace(",", "."))
    if "length_m" not in found and "width_m" not in found and (pairs := BY_PATTERN.findall(text)):
        a, b = (_num(x) for x in pairs[-1])
        if a and b:
            found["length_m"], found["width_m"] = a, b
    return found


_V = r"(?:полож|улож|постел|стел|замен|помен|постав|установ|перенес|добав|сдела|провест|проложи|передел|повес|смонтир)\w*\s+(?:\S+\s+){0,2}"
# работы, которые клиент назвал сам: «покрасить стены», «поменять проводку», «положить плитку на пол»
TEXT_WORKS = [
    (re.compile(r"(?:по|о)крас\w*\s+(?:\S+\s+){0,2}потол", re.I), "wall_painting:ceiling:"),
    (re.compile(r"(?:по|о)крас\w*\b(?!\s+потол)", re.I), "wall_painting:wall:"),
    (re.compile(_V + r"потол|(?:обнов|отремонт)\w*\s+(?:\S+\s+){0,1}потол|\bтолько\s+потол|натяжн\w*\s+потол|потол\w*\s+натяжн", re.I),
     "wall_painting:ceiling:"),
    (re.compile(r"(?:по|пере|о)кле\w*|клеить\s+обо|обои\s+(?:поклеить|поменять|заменить)", re.I), "wallpapering:wall:"),
    (re.compile(_V + r"ламинат", re.I), "floor_covering_install:floor:ламинат"),
    (re.compile(_V + r"линолеум", re.I), "floor_covering_install:floor:линолеум"),
    (re.compile(_V + r"плитк\w*\s+(?:\S+\s+){0,1}(?:на\s+)?пол\b", re.I), "tiling:floor:"),
    (re.compile(_V + r"плитк\w*\b(?!\s+(?:\S+\s+){0,1}(?:на\s+)?пол\b)", re.I), "tiling:wall:"),
    (re.compile(_V + r"(?:проводк|электрик)", re.I), "electrical_wiring::"),
    (re.compile(_V + r"(?:розетк|выключател)", re.I), "electrical_fittings::"),
    (re.compile(_V + r"(?:светильник|люстр|свет\b|освещени|подсветк)", re.I), "lighting_install::"),
    (re.compile(_V + r"(?:унитаз|раковин|смесител|ванн[уы]?\b|душев|сантехник)", re.I), "plumbing_fixture_install::"),
    (re.compile(_V + r"(?:двер|окн|окон)", re.I), "door_window_install::"),
    (re.compile(r"стяжк", re.I), "floor_screed:floor:"), (re.compile(r"штукатур", re.I), "wall_plastering:wall:"),
    (re.compile(r"шпакл|шпатл", re.I), "wall_putty:wall:"), (re.compile(r"гидроизол", re.I), "waterproofing:floor:"),
    (re.compile(r"гипсокартон", re.I), "drywall_install:wall:"), (re.compile(r"демонтаж|снести\s+стен", re.I), "demolition::"),
]
_NEGATION = re.compile(r"(?:\bне|\bбез|\bкроме)\s+(?:\S+\s+){0,2}$", re.I)


def works_from_text(text: str) -> list[str]:
    """Работы, которые клиент прямо назвал; «не трогаем проводку» и «без плитки» не считаются."""
    found = []
    for rx, key in TEXT_WORKS:
        # отрицание ищем только в той же части фразы: «проводку не трогаем, только покрасить» — покраска нужна
        if any(not _NEGATION.search(re.split(r"[,.;:!?\n]|\bтолько\b|\bно\b", text[max(0, m.start() - 30):m.start()])[-1])
               for m in rx.finditer(text)):
            found.append(key)
    return list(dict.fromkeys(found))


def merge(prev: BriefDraft | None, new: BriefDraft) -> BriefDraft:
    """Новая проверка дополняет прошлую, а не начинает с нуля.

    GigaChat каждый раз отвечает чуть по-разному и может «забыть» уже сказанное — тогда кнопка расчёта
    пропадала бы. Что клиент назвал заново, берём новое; чего в новом ответе нет — оставляем из прошлого.
    """
    if prev is None:
        return new
    out = BriefDraft(renovation_type=new.renovation_type or prev.renovation_type, rooms=[])
    left = list(prev.rooms)
    for room in new.rooms:
        old = next((r for r in left if r.room_type == room.room_type and (not room.name or not r.name or r.name == room.name)), None)
        if old is None:
            out.rooms.append(room)
            continue
        left.remove(old)
        merged = room.model_copy()
        for field in ("name", "length_m", "width_m", "height_m", "area_m2", "windows", "doors"):
            if getattr(merged, field) is None:
                setattr(merged, field, getattr(old, field))
        for field in ("openings", "wishes", "add_works", "remove_works"):
            if not getattr(merged, field):
                setattr(merged, field, getattr(old, field))
        merged.only_works = room.only_works or old.only_works
        out.rooms.append(merged)
    out.rooms += left  # помещения, о которых в этот раз модель не упомянула, не теряем
    return out


ROOM_WORDS = [(re.compile(r"кухн", re.I), "kitchen"), (re.compile(r"столов", re.I), "dining_room"),
              (re.compile(r"гостин|зал\b", re.I), "living_room"), (re.compile(r"спальн|детск", re.I), "bedroom"),
              (re.compile(r"ванн|санузел|туалет", re.I), "bathroom"), (re.compile(r"прихож|коридор", re.I), "hallway"),
              (re.compile(r"кабинет", re.I), "home_office"), (re.compile(r"кладов|постироч", re.I), "utility_room"),
              (re.compile(r"балкон|лоджи", re.I), "balcony")]
# потолок, который калькулятор посчитать не может: в нём есть только окраска потолка
SPECIAL_CEILING = re.compile(r"натяжн|реечн|кассетн|армстронг", re.I)


def verify(draft: BriefDraft, client_text: str) -> BriefDraft:
    """Убираем то, чего клиент не говорил: вид ремонта без его слов, размеры, которых нет в переписке.

    Вызывается уже после merge(): так данные из прошлых проверок тоже сверяются со словами клиента,
    а пропущенное моделью добираем из этих слов.
    """
    try:
        reno = RenovationType(draft.renovation_type)
    except ValueError:
        reno = None
    if reno and not RENOVATION_WORDS[reno].search(client_text):
        draft.renovation_type = None
    if not draft.rooms:  # модель не назвала помещение — возьмём из слов клиента, если оно одно
        named = list(dict.fromkeys(t for rx, t in ROOM_WORDS if rx.search(client_text)))
        if len(named) == 1:
            draft.rooms = [BriefRoom(room_type=named[0])]
    for room in draft.rooms:
        for field in ("length_m", "width_m", "height_m", "area_m2"):
            if not _said(getattr(room, field), client_text):
                setattr(room, field, None)
        if not re.search(r"окн|окон", client_text, re.I):
            room.windows = None
        if not re.search(r"двер", client_text, re.I):
            room.doors = None
    if len(draft.rooms) == 1:  # одно помещение: размеры и работы, которые модель пропустила, берём прямо из слов клиента
        room, found = draft.rooms[0], sizes_from_text(client_text)
        for field, value in found.items():
            if getattr(room, field) is None:
                setattr(room, field, value)
        if draft.renovation_type is None:  # вида ремонта нет — может, человек назвал работы
            room.add_works = list(dict.fromkeys(room.add_works + [k for k in works_from_text(client_text)
                                                                  if k not in room.remove_works]))
    draft.notes = []
    if SPECIAL_CEILING.search(client_text) and re.search(r"потол", client_text, re.I):
        draft.notes.append("Натяжной и подвесной потолок калькулятор пока не считает — в смете окраска потолка; "
                           "натяжной обычно заказывают у монтажников под ключ")
    return draft


def _wish_works(wishes: list[dict]) -> list[str]:
    keys = []
    for w in wishes:
        mats = [Material(m) for m in (w["materials"] or [])] or [m for rx, m in TEXT_MATERIAL if rx.search(w["text"])]
        for m in mats:
            if m in WISH_WORK:
                keys.append(WISH_WORK[m])
            elif m == Material.tile:
                keys.append("tiling:floor:" if re.search(r"пол", w["text"], re.I) else "tiling:wall:")
    return keys


def build(draft: BriefDraft) -> dict:
    """Проверенный черновик → помещения для калькулятора, что взяли по умолчанию и чего не хватает."""
    missing, notes, rooms = [], [], []
    try:
        renovation = RenovationType(draft.renovation_type)
    except ValueError:
        renovation = None
    # вид ремонта нужен, только если человек говорит о ремонте целиком, а не об отдельных работах
    # если вид ремонта не назван, а работы названы, — считаем только эти работы
    if renovation is None and not all(r.add_works for r in draft.rooms):
        missing.append("вид ремонта: косметический, капитальный, евроремонт или под сдачу — или назовите, какие работы нужны")
    if not draft.rooms:
        missing.append("какое помещение ремонтируем")
    for raw in draft.rooms[:5]:
        room_type = _room_type(raw.room_type)
        title = raw.name or (ROOM_TITLES[room_type] if room_type else "помещение")
        if room_type is None:
            missing.append(f"тип помещения «{title}»")
            continue
        length, width, area, perimeter = raw.length_m, raw.width_m, None, None
        if not (length and width) and raw.area_m2:
            # только площадь (комната буквой Г и т.п.): считаем стены как у квадратной комнаты такой площади
            side = round(raw.area_m2 ** 0.5, 2)
            length, width, area, perimeter = side, side, raw.area_m2, round(4 * side, 2)
            notes.append(f"{title}: известна только площадь {raw.area_m2:g} м² — стены посчитали как у квадратной "
                         f"комнаты такой площади. Если форма сложная, нарисуйте её в калькуляторе на шаге «Помещения»")
        if not (length and width):
            missing.append(f"{title}: длина и ширина комнаты (или площадь, если форма сложная)")
            continue
        first_note = len(notes)
        openings = [o for o in raw.openings if o.kind in ("window", "door") and o.width_m and o.height_m]
        windows, doors = raw.windows, raw.doors
        if not openings and windows is None and doors is None:
            windows, doors = ROOM_DEFAULT_OPENINGS.get(room_type, (1, 1))
            notes.append(f"{title}: окна и двери не обсуждали — взяли типичные (окон: {windows}, дверей: {doors})")
        height = raw.height_m or float(DEFAULT_HEIGHT)
        if not raw.height_m:
            notes.append(f"{title}: высоту потолка не называли — взяли {DEFAULT_HEIGHT} м")
        wishes = []
        for w in raw.wishes[:5]:
            mats = [m for m in w.materials if m in {x.value for x in WISH_MATERIALS}] \
                or list(dict.fromkeys(m.value for rx, m in WISH_TEXT_MATERIAL if rx.search(w.text)))
            if w.text.strip():
                wishes.append({"text": w.text.strip()[:120], "materials": mats or None})
        only = bool(raw.add_works) and (raw.only_works or renovation is None)
        room_reno = renovation
        if only and room_reno is None:
            room_reno = renovation_for(room_type, raw.add_works)
            if room_reno:
                notes.append(f"{title}: вы назвали отдельные работы — считаем только их (цены как для «{RENOVATION_TITLES[room_reno]}»). "
                             "Если нужен ремонт целиком, скажите консультанту вид ремонта")
        if room_reno is None:
            if only:
                missing.append(f"{title}: какие именно работы нужны")
            continue
        data = {"name": raw.name, "room_type": room_type.value, "renovation_type": room_reno.value,
                "length_m": length, "width_m": width, "height_m": height,
                "custom_floor_area": area, "custom_perimeter": perimeter,
                "windows": windows, "doors": doors, "wishes": wishes,
                "openings": [o.model_dump() for o in openings] or None}
        options = {o.key: o for o, _ in works_for_room(room_type, room_reno)}
        for w in wishes:
            for k in _wish_works([w]):
                if not _matching(k, options):
                    notes.append(f"{title}: «{w['text']}» — такой работы для этого помещения в калькуляторе нет")
        asked = list(dict.fromkeys(raw.add_works + _wish_works(wishes)))
        data["works"], added, removed, replaced = choose_works(room_type, room_reno, asked, raw.remove_works, only)
        if not data["works"]:
            missing.append(f"{title}: какие именно работы нужны")
            continue
        room = RoomInput.model_validate(data).model_dump(mode="json", exclude_none=True)
        # для пометки на шаге «Работы»: что добавили и убрали по разговору, что взяли по умолчанию
        room["auto"] = {"added": added, "removed": removed, "replaced": replaced, "notes": notes[first_note:],
                        "only": only}
        rooms.append(room)
    renovation = renovation or (RenovationType(rooms[0]["renovation_type"]) if rooms else None)
    if rooms and draft.notes:  # видно и в полоске под чатом, и на шаге «Работы»
        rooms[0]["auto"]["notes"] = list(draft.notes) + rooms[0]["auto"]["notes"]
    notes = list(draft.notes) + notes
    return {"ready": not missing and bool(rooms), "missing": missing, "notes": notes,
            "renovation_type": renovation.value if renovation else None, "rooms": rooms}


# чат → (id последнего сообщения, последняя проверка): пока разговор не продолжился, GigaChat повторно не спрашиваем
CACHE: dict[str, tuple[int, object]] = {}
TURNS: dict[str, int] = {}
DRAFTS: dict[str, BriefDraft] = {}  # последний проверенный черновик чата — следующая проверка его дополняет  # сколько сообщений клиента было в разговоре на момент последней проверки
ASK_AFTER = 4  # после стольких сообщений клиента недостающее консультант спрашивает обязательно


def missing_hint(chat_id: str) -> str:
    """Чего ещё не хватает для сметы по последней проверке разговора — подсказка консультанту для следующего ответа."""
    hit = CACHE.get(chat_id)
    if not hit or hit[1].ready or not hit[1].missing:
        return ""
    missing = "; ".join(hit[1].missing)
    if TURNS.get(chat_id, 0) >= ASK_AFTER:
        # разговор уже длинный, а данных для сметы всё нет — больше не откладываем
        return ("\n\nВАЖНО: разговор идёт уже долго, а для расчёта сметы всё ещё не хватает: " + missing + ". "
                "В этом ответе обязательно спроси об этом: сначала коротко ответь на сообщение клиента, затем "
                "отдельной строкой задай один короткий вопрос сразу про всё недостающее. Не переспрашивай то, "
                "что клиент уже сказал. Если клиент говорит, что не знает размеров, попроси примерную площадь.")
    return ("\n\nДля расчёта сметы по этому разговору пока не хватает: " + missing
            + ". Если это уместно, спроси об этом в ответе — коротко, одним-двумя вопросами, не повторяя уже известное.")

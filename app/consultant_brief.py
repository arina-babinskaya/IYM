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
    """Последние реплики, которые помещаются в лимит, в хронологическом порядке."""
    lines, size = [], 0
    for role, content in reversed(messages):
        line = f"{'Клиент' if role == 'user' else 'Консультант'}: {content.strip()}"
        if size + len(line) > limit_chars:
            break
        lines.append(line)
        size += len(line)
    return "\n".join(reversed(lines))


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


def verify(draft: BriefDraft, client_text: str) -> BriefDraft:
    """Убираем то, чего клиент не говорил: вид ремонта без его слов, размеры, которых нет в переписке."""
    try:
        reno = RenovationType(draft.renovation_type)
    except ValueError:
        reno = None
    if reno and not RENOVATION_WORDS[reno].search(client_text):
        draft.renovation_type = None
    for room in draft.rooms:
        for field in ("length_m", "width_m", "height_m", "area_m2"):
            if not _said(getattr(room, field), client_text):
                setattr(room, field, None)
    if len(draft.rooms) == 1:  # одно помещение: размеры, которые модель пропустила, берём прямо из слов клиента
        room, found = draft.rooms[0], sizes_from_text(client_text)
        for field, value in found.items():
            if getattr(room, field) is None:
                setattr(room, field, value)
        if not re.search(r"окн|окон", client_text, re.I):
            room.windows = None
        if not re.search(r"двер", client_text, re.I):
            room.doors = None
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
    if renovation is None and not all(r.only_works and r.add_works for r in draft.rooms):
        missing.append("вид ремонта: косметический, капитальный, евроремонт или под сдачу — или скажите, что нужны только отдельные работы")
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
        only = raw.only_works and bool(raw.add_works)
        room_reno = renovation
        if only and room_reno is None:
            room_reno = renovation_for(room_type, raw.add_works)
            if room_reno:
                notes.append(f"{title}: нужны только отдельные работы — посчитаем их в рамках «{RENOVATION_TITLES[room_reno]}»")
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
    return {"ready": not missing and bool(rooms), "missing": missing, "notes": notes,
            "renovation_type": renovation.value if renovation else None, "rooms": rooms}


# чат → (id последнего сообщения, последняя проверка): пока разговор не продолжился, GigaChat повторно не спрашиваем
CACHE: dict[str, tuple[int, object]] = {}


def missing_hint(chat_id: str) -> str:
    """Чего ещё не хватает для сметы по последней проверке разговора — подсказка консультанту для следующего ответа."""
    hit = CACHE.get(chat_id)
    if not hit or hit[1].ready or not hit[1].missing:
        return ""
    return ("\n\nДля расчёта сметы по этому разговору пока не хватает: " + "; ".join(hit[1].missing)
            + ". Если это уместно, спроси об этом в ответе — коротко, одним-двумя вопросами, не повторяя уже известное.")

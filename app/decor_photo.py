"""Поиск мебели и декора по фото: GigaChat описывает предметы на снимке, каталог подбирает похожие товары.

1. Фото загружается в GigaChat (`POST /files`) и уходит в чат вложением (`attachments`).
2. GigaChat возвращает JSON: стиль комнаты и предметы — позиция из нашего списка, цвет, материал, детали.
3. Для каждого предмета берём товары этой позиции и сортируем по сходству: цвет, материал, слова, стиль.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

from pydantic import BaseModel, ValidationError

from app.config import get_settings
from app.decor import INDEX, SLOTS, STYLES, Item, family, score
from app.llm.gigachat import GigaChatClient, GigaChatError

logger = logging.getLogger(__name__)

# позиции, которые имеет смысл искать на фото интерьера (без посуды, полотенец и мелочей)
PHOTO_SLOTS = ["sofa", "armchair", "pouf", "coffee_table", "bookcase", "bed", "nightstand", "wardrobe", "dresser",
               "dining_table", "dining_chairs", "desk", "office_chair", "shoe_cabinet", "bath_vanity",
               "chandelier", "ceiling_light", "sconce", "floor_lamp", "table_lamp", "curtains", "roller_blind",
               "rug", "cushions", "throw", "wall_art", "mirror", "clock", "vase", "plant", "pot", "wall_shelf",
               "basket", "candles"]


class PhotoObject(BaseModel):
    slot: str
    name: str = ""
    color: str = ""
    material: str = ""
    details: str = ""


class PhotoAnalysis(BaseModel):
    style: str | None = None
    objects: list[PhotoObject] = []


def prompt() -> str:
    slots = "\n".join(f"- {k}: {SLOTS[k].title}" for k in PHOTO_SLOTS)
    styles = ", ".join(f"{k} ({s.title})" for k, s in STYLES.items())
    return (
        "На фото интерьер. Перечисли мебель и предметы декора, которые хорошо видно, не больше 10.\n"
        "Для каждого укажи позицию строго из списка (ключ слева):\n" + slots + "\n"
        "и по-русски: name — что это (например, «угловой диван»), color — основной цвет, "
        "material — материал или ткань, details — форма и заметные детали.\n"
        f"Определи общий стиль комнаты, один ключ из: {styles}; если не понятно — null.\n"
        'Ответь только JSON без пояснений: {"style": "...", "objects": [{"slot": "...", "name": "...", '
        '"color": "...", "material": "...", "details": "..."}]}'
    )


def parse(content: str) -> PhotoAnalysis:
    """JSON из ответа модели: без ```-обёрток, только известные позиции и стили, без повторов."""
    m = re.search(r"\{.*\}", content, re.DOTALL)
    if not m:
        raise GigaChatError("GigaChat не вернул описание предметов", kind="schema_validation")
    try:
        result = PhotoAnalysis.model_validate(json.loads(m.group(0)))
    except (ValueError, ValidationError) as exc:
        raise GigaChatError("GigaChat вернул описание в неожиданном формате", kind="schema_validation") from exc
    if result.style not in STYLES:
        result.style = None
    seen, objects = set(), []
    for obj in result.objects:
        key = (obj.slot, obj.color.lower(), obj.material.lower())
        if obj.slot in PHOTO_SLOTS and key not in seen:
            seen.add(key)
            objects.append(obj)
    result.objects = objects[:10]
    return result


async def analyze(image: bytes, filename: str, content_type: str, transport=None) -> PhotoAnalysis:
    settings = get_settings()
    client = GigaChatClient(settings.model_copy(update={"gigachat_model": settings.decor_photo_model}), transport)
    if not client.configured:
        raise GigaChatError("GigaChat is not configured", kind="backend_configuration")
    api = settings.gigachat_api_url.rstrip("/")
    async with client._http() as http:
        token = await client._authenticate(http)
        response = await http.post(f"{api}/files", headers={"Authorization": f"Bearer {token}"},
                                   files={"file": (filename, image, content_type)}, data={"purpose": "general"})
        if response.status_code >= 400:
            raise GigaChatError(f"GigaChat file upload HTTP {response.status_code}", kind="api_error",
                                diagnostic={"step": "file_upload", "status_code": response.status_code})
        file_id = response.json().get("id")
    try:
        data, _ = await client._chat("decor_photo", [
            {"role": "user", "content": prompt(), "attachments": [file_id]},
        ], 1500)
        return parse(client._content(data))
    finally:
        try:  # файл больше не нужен; ошибка удаления не мешает ответу
            async with client._http() as http:
                await http.post(f"{api}/files/{file_id}/delete", headers={"Authorization": f"Bearer {token}"})
        except Exception:
            logger.info("decor photo: could not delete uploaded file")


_WORD = re.compile(r"[а-яёa-z]{4,}", re.IGNORECASE)


def _stems(text: str) -> set[str]:
    return {w.lower()[:5] for w in _WORD.findall(text or "")}


@dataclass
class Match:
    item: Item
    score: float
    why: list[str]


def match(obj: PhotoObject, style: str | None) -> list[Match]:
    """Товары позиции, самые похожие на предмет с фото — первыми."""
    want_color = family(Item(0, obj.color, 0, 0, None, None, None, colors=obj.color)) if obj.color else None
    want_material = _stems(obj.material)
    want_words = _stems(f"{obj.name} {obj.details}") - want_material
    out = []
    for item in INDEX.by_slot.get(obj.slot, []):
        s, why = 0.0, []
        if want_color and (have := family(item)):
            if have == want_color:
                s += 3
                why.append(f"цвет как на фото: {obj.color}")
            else:
                s -= 1
        if hits := want_material & _stems(f"{item.materials} {item.name}"):
            s += 2 * len(hits)
            why.append(f"материал: {obj.material}")
        if hits := want_words & _stems(f"{item.name} {item.words} {item.attrs}"):
            s += min(len(hits), 4)
            why.append("похоже по описанию")
        if style:
            st = score(item, STYLES[style])
            if st.strong and st.score > 0:
                s += min(st.score, 8) / 2
                why.append(f"стиль: {STYLES[style].title.lower()}")
        out.append(Match(item, s + item.rating / 10, why or ["та же позиция"]))
    return sorted(out, key=lambda m: (-m.score, m.item.price))

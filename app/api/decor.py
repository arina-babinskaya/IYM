import base64
import binascii
from collections import Counter
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import decor_photo as decor_photo_service
from app.config import get_settings
from app.db import get_session
from app.decor import DECOR_ROOMS, FIT, INDEX, KITS, ROOM_FURNITURE, NEUTRAL_FAMILIES, ROOM_SLOTS, SLOTS, STYLES, ZONES, Item, Scored, family
from app.llm.gigachat import GigaChatError

router = APIRouter(prefix="/api/v1/decor", tags=["decor"])
Budget = Literal["economy", "standard", "premium"]


class DecorStyleOut(BaseModel):
    id: str
    title: str
    description: str
    palette: list[str]
    slots_found: int
    slots_total: int


class DecorProduct(BaseModel):
    id: int
    name: str
    price: Decimal
    picture_url: str | None = None
    url_key: str | None = None
    brand: str | None = None
    why: list[str] = []
    in_stock: bool = True


class DecorLine(BaseModel):
    slot: str
    title: str
    qty: int
    product: DecorProduct | None = None
    cost: Decimal = Decimal(0)
    choices: int = 0
    furniture: bool = False


class DecorRequest(BaseModel):
    room_type: str
    style: str
    budget: Budget = "standard"
    picks: dict[str, int] = {}
    skip: list[str] = []
    furniture: bool = False  # «Декор и мебель»: сначала мебель, потом декор в её цветах


class DecorResponse(BaseModel):
    room_type: str
    room_title: str
    style: str
    style_title: str
    budget: Budget
    items: list[DecorLine]
    total: Decimal


def _style(style: str):
    if style not in STYLES:
        raise HTTPException(404, f"Неизвестный стиль: {style}")
    return STYLES[style]


def _product(x: Scored) -> DecorProduct:
    i = x.item
    return DecorProduct(id=i.id, name=i.name, price=i.price, picture_url=i.picture_url, url_key=i.url_key,
                        brand=i.brand, why=x.why, in_stock=i.in_stock)


class DecorRoomOut(BaseModel):
    id: str
    title: str


def _room(room_type: str, furniture: bool = False) -> list[str]:
    if room_type not in ROOM_SLOTS:
        raise HTTPException(404, f"Неизвестное помещение: {room_type}")
    return (ROOM_FURNITURE.get(room_type, []) if furniture else []) + ROOM_SLOTS[room_type]


@router.get("/rooms", response_model=list[DecorRoomOut])
def decor_rooms() -> list[DecorRoomOut]:
    """Помещения для декора: те же, что в калькуляторе, плюс детская."""
    return [DecorRoomOut(id=k, title=v) for k, v in DECOR_ROOMS.items() if k in ROOM_SLOTS]


@router.get("/styles", response_model=list[DecorStyleOut])
def decor_styles(room_type: str, furniture: bool = False,
                 session: Session = Depends(get_session)) -> list[DecorStyleOut]:
    """Стили для помещения и сколько позиций в каждом удаётся собрать из каталога.

    Детский стиль предлагается только для детской, и там он первый.
    """
    slots = _room(room_type, furniture)
    INDEX.ensure(session)
    out = []
    for key, style in STYLES.items():
        if key == "kids" and room_type != "kids_room":
            continue
        found = sum(1 for s in slots if any(x.score >= FIT and x.strong for x in INDEX.ranked(s, style)))
        out.append(DecorStyleOut(id=key, title=style.title, description=style.description,
                                 palette=list(style.palette), slots_found=found, slots_total=len(slots)))
    return sorted(out, key=lambda s: (s.id != "kids", -s.slots_found))


@router.post("", response_model=DecorResponse)
def decor_pick(req: DecorRequest, session: Session = Depends(get_session)) -> DecorResponse:
    """Подборка: по товару на каждую позицию комнаты. `picks` — выбранные вручную товары, `skip` — убранные позиции."""
    style = _style(req.style)
    INDEX.ensure(session)
    lines, colors = [], Counter()
    furniture = set(ROOM_FURNITURE.get(req.room_type, [])) if req.furniture else set()
    for key in _room(req.room_type, req.furniture):
        if key in req.skip:
            continue
        slot = SLOTS[key]
        ranked = INDEX.ranked(key, style)
        chosen = None
        if pid := req.picks.get(key):
            chosen = next((x for x in ranked if x.item.id == pid), None)
            if chosen is None:
                chosen = next((Scored(i, 0, ["выбрано вручную"]) for i in INDEX.by_slot.get(key, []) if i.id == pid), None)
        if chosen is None:
            chosen, _ = INDEX.pick(key, style, req.budget, {c for c, _ in colors.most_common(2)})
        if chosen and (f := family(chosen.item)) and f not in NEUTRAL_FAMILIES:
            colors[f] += 1
        lines.append(DecorLine(slot=key, title=slot.title, qty=slot.qty, choices=len(ranked), furniture=key in furniture,
                               product=_product(chosen) if chosen else None,
                               cost=chosen.item.price * slot.qty if chosen else Decimal(0)))
    return DecorResponse(room_type=req.room_type, room_title=DECOR_ROOMS[req.room_type], style=req.style,
                         style_title=style.title, budget=req.budget, items=lines,
                         total=sum((x.cost for x in lines), Decimal(0)))


@router.get("/options", response_model=list[DecorProduct])
def decor_options(style: str, slot: str, q: str | None = None, limit: int = 40,
                  session: Session = Depends(get_session)) -> list[DecorProduct]:
    """Варианты для замены товара в позиции: сначала самые подходящие стилю."""
    if slot not in SLOTS:
        raise HTTPException(404, f"Неизвестная позиция: {slot}")
    INDEX.ensure(session)
    ranked = INDEX.ranked(slot, _style(style))
    if q:
        ranked = [x for x in ranked if q.lower() in x.item.name.lower()]
    return [_product(x) for x in ranked[:max(1, min(limit, 200))]]


class ZoneGroupOut(BaseModel):
    id: str
    title: str
    total: int
    products: list[DecorProduct]


class KitOut(BaseModel):
    id: str
    title: str
    description: str
    positions: int


class ZoneOut(BaseModel):
    id: str
    title: str
    description: str
    total: int
    groups: list[ZoneGroupOut] = []
    kits: list[KitOut] = []


class KitRequest(BaseModel):
    budget: Budget = "standard"
    picks: dict[str, int] = {}
    skip: list[str] = []


class KitResponse(BaseModel):
    zone: str
    zone_title: str
    kit: str
    kit_title: str
    budget: Budget
    items: list[DecorLine]
    total: Decimal


def _plain(i: Item) -> DecorProduct:
    return DecorProduct(id=i.id, name=i.name, price=i.price, picture_url=i.picture_url, url_key=i.url_key,
                        brand=i.brand, in_stock=i.in_stock)


@router.get("/zones", response_model=list[ZoneOut])
def decor_zones(counts: bool = True, session: Session = Depends(get_session)) -> list[ZoneOut]:
    """Огород, сад, мангальная зона и сколько для них товаров в каталоге.

    `counts=false` отвечает сразу, без обращения к каталогу: так карточки зон рисуются вместе с помещениями.
    """
    if counts:
        INDEX.ensure(session)
    return [ZoneOut(id=k, title=z.title, description=z.description, kits=_kits(k),
                    total=sum(len(INDEX.zone_items(k, g)) for g in z.groups) if counts else 0)
            for k, z in ZONES.items()]


def _kits(zone: str) -> list[KitOut]:
    return [KitOut(id=k, title=kit.title, description=kit.description, positions=len(kit.items))
            for k, kit in KITS.get(zone, {}).items()]


def _kit(zone: str, kit: str):
    if zone not in KITS or kit not in KITS[zone]:
        raise HTTPException(404, "Неизвестный набор")
    return KITS[zone][kit]


@router.post("/zones/{zone}/kits/{kit}", response_model=KitResponse)
def decor_kit(zone: str, kit: str, req: KitRequest, session: Session = Depends(get_session)) -> KitResponse:
    """Готовый набор для дачи: по товару на позицию под бюджет, с заменами и убранными позициями."""
    k = _kit(zone, kit)
    INDEX.ensure(session)
    lines = []
    for key, item in k.items.items():
        if key in req.skip:
            continue
        choices = INDEX.kit_items(zone, kit, key)
        chosen = next((i for i in choices if i.id == req.picks.get(key)), None)
        if chosen is None:
            chosen, _ = INDEX.kit_pick(zone, kit, key, req.budget)
        lines.append(DecorLine(slot=key, title=item.title, qty=item.qty, choices=len(choices),
                               product=_plain(chosen) if chosen else None,
                               cost=chosen.price * item.qty if chosen else Decimal(0)))
    return KitResponse(zone=zone, zone_title=ZONES[zone].title, kit=kit, kit_title=k.title, budget=req.budget,
                       items=lines, total=sum((x.cost for x in lines), Decimal(0)))


@router.get("/zones/{zone}/kits/{kit}/{item}", response_model=list[DecorProduct])
def decor_kit_options(zone: str, kit: str, item: str, q: str | None = None, limit: int = 60,
                      session: Session = Depends(get_session)) -> list[DecorProduct]:
    """Чем заменить товар в позиции набора."""
    if item not in _kit(zone, kit).items:
        raise HTTPException(404, "Неизвестная позиция")
    INDEX.ensure(session)
    items = INDEX.kit_items(zone, kit, item)
    if q:
        items = [i for i in items if q.lower() in i.name.lower()]
    return [_plain(i) for i in items[:max(1, min(limit, 200))]]


@router.get("/zones/{zone}", response_model=ZoneOut)
def decor_zone(zone: str, per_group: int = 8, session: Session = Depends(get_session)) -> ZoneOut:
    """Все разделы зоны, в каждом — первые товары и сколько их всего."""
    if zone not in ZONES:
        raise HTTPException(404, f"Неизвестная зона: {zone}")
    INDEX.ensure(session)
    z = ZONES[zone]
    groups = []
    for g, slot in z.groups.items():
        items = INDEX.zone_items(zone, g)
        if items:
            groups.append(ZoneGroupOut(id=g, title=slot.title, total=len(items),
                                       products=[_plain(i) for i in items[:max(1, min(per_group, 50))]]))
    return ZoneOut(id=zone, title=z.title, description=z.description, total=sum(x.total for x in groups),
                   groups=groups, kits=_kits(zone))


@router.get("/zones/{zone}/{group}", response_model=list[DecorProduct])
def decor_zone_group(zone: str, group: str, q: str | None = None, offset: int = 0, limit: int = 40,
                     session: Session = Depends(get_session)) -> list[DecorProduct]:
    """Товары одного раздела зоны постранично, с поиском по названию."""
    if zone not in ZONES or group not in ZONES[zone].groups:
        raise HTTPException(404, "Неизвестный раздел")
    INDEX.ensure(session)
    items = INDEX.zone_items(zone, group)
    if q:
        items = [i for i in items if q.lower() in i.name.lower()]
    return [_plain(i) for i in items[max(0, offset):max(0, offset) + max(1, min(limit, 200))]]


class PhotoRequest(BaseModel):
    image: str  # картинка в base64, можно с префиксом data:image/...;base64,
    filename: str = "photo.jpg"


class PhotoLine(BaseModel):
    slot: str
    title: str
    detected: dict[str, str]
    product: DecorProduct | None = None
    alternatives: list[DecorProduct] = []


class PhotoResponse(BaseModel):
    style: str | None = None
    style_title: str | None = None
    objects: list[PhotoLine]


@router.post("/photo", response_model=PhotoResponse)
async def decor_photo(req: PhotoRequest, session: Session = Depends(get_session)) -> PhotoResponse:
    """Найти по фото: GigaChat описывает мебель и декор на снимке, для каждого предмета — похожие товары каталога."""
    header, _, payload = req.image.partition(",") if req.image.startswith("data:") else ("", "", req.image)
    try:
        image = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(422, "Не удалось прочитать картинку")
    if len(image) > get_settings().decor_photo_max_mb * 1024 * 1024:
        raise HTTPException(413, f"Фото больше {get_settings().decor_photo_max_mb} МБ")
    content_type = header[5:].split(";")[0] if header else "image/jpeg"
    if content_type not in ("image/jpeg", "image/png", "image/webp", "image/bmp", "image/tiff"):
        raise HTTPException(422, "Нужна картинка в формате JPG или PNG")
    INDEX.ensure(session)
    try:
        analysis = await decor_photo_service.analyze(image, req.filename, content_type)
    except GigaChatError as exc:
        if exc.kind == "backend_configuration" or "credentials" in str(exc) or "disabled" in str(exc):
            raise HTTPException(503, "Поиск по фото работает через GigaChat: добавьте ключ в .env")
        raise HTTPException(502, "GigaChat не смог разобрать фото, попробуйте ещё раз или другое фото")
    lines = []
    for obj in analysis.objects:
        matches = decor_photo_service.match(obj, analysis.style)
        products = [DecorProduct(id=m.item.id, name=m.item.name, price=m.item.price, picture_url=m.item.picture_url,
                                 url_key=m.item.url_key, brand=m.item.brand, why=m.why, in_stock=m.item.in_stock)
                    for m in matches[:30]]
        lines.append(PhotoLine(slot=obj.slot, title=SLOTS[obj.slot].title,
                               detected={"name": obj.name, "color": obj.color, "material": obj.material,
                                         "details": obj.details},
                               product=products[0] if products else None, alternatives=products))
    return PhotoResponse(style=analysis.style, style_title=STYLES[analysis.style].title if analysis.style else None,
                         objects=lines)

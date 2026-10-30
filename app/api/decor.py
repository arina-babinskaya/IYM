from collections import Counter
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_session
from app.decor import FIT, INDEX, NEUTRAL_FAMILIES, ROOM_SLOTS, SLOTS, STYLES, Scored, family
from app.schemas import ROOM_TITLES, RoomType

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


class DecorLine(BaseModel):
    slot: str
    title: str
    qty: int
    product: DecorProduct | None = None
    cost: Decimal = Decimal(0)
    choices: int = 0


class DecorRequest(BaseModel):
    room_type: RoomType
    style: str
    budget: Budget = "standard"
    picks: dict[str, int] = {}
    skip: list[str] = []


class DecorResponse(BaseModel):
    room_type: RoomType
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
                        brand=i.brand, why=x.why)


@router.get("/styles", response_model=list[DecorStyleOut])
def decor_styles(room_type: RoomType, session: Session = Depends(get_session)) -> list[DecorStyleOut]:
    """Стили для помещения и сколько позиций в каждом удаётся собрать из каталога."""
    INDEX.ensure(session)
    slots = ROOM_SLOTS[room_type]
    out = []
    for key, style in STYLES.items():
        found = sum(1 for s in slots if any(x.score >= FIT for x in INDEX.ranked(s, style)))
        out.append(DecorStyleOut(id=key, title=style.title, description=style.description,
                                 palette=list(style.palette), slots_found=found, slots_total=len(slots)))
    return sorted(out, key=lambda s: -s.slots_found)


@router.post("", response_model=DecorResponse)
def decor_pick(req: DecorRequest, session: Session = Depends(get_session)) -> DecorResponse:
    """Подборка: по товару на каждую позицию комнаты. `picks` — выбранные вручную товары, `skip` — убранные позиции."""
    style = _style(req.style)
    INDEX.ensure(session)
    lines, colors = [], Counter()
    for key in ROOM_SLOTS[req.room_type]:
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
        lines.append(DecorLine(slot=key, title=slot.title, qty=slot.qty, choices=len(ranked),
                               product=_product(chosen) if chosen else None,
                               cost=chosen.item.price * slot.qty if chosen else Decimal(0)))
    return DecorResponse(room_type=req.room_type, room_title=ROOM_TITLES[req.room_type], style=req.style,
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

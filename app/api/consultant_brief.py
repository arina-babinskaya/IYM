from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import consultant_brief as brief
from app.api.consultant import _chat_or_404, _messages, _owner
from app.api.deps import get_gigachat
from app.db import get_session
from app.llm.gigachat import GigaChatError

router = APIRouter(prefix="/api/v1/consultant", tags=["consultant"])



class BriefOut(BaseModel):
    ready: bool
    missing: list[str]
    notes: list[str]
    renovation_type: str | None = None
    rooms: list[dict[str, Any]]
    stale: bool = False  # GigaChat недоступен — показан результат по одному из прошлых сообщений


@router.post("/chats/{chat_id}/brief", response_model=BriefOut)
async def chat_brief(chat_id: str, request: Request, response: Response, db: Session = Depends(get_session),
                     gigachat=Depends(get_gigachat)) -> BriefOut:
    """Параметры для калькулятора из разговора: помещения, размеры, окна и двери, вид ремонта, пожелания.

    Если чего-то не хватает, `ready` = false и в `missing` написано, что спросить у клиента.
    """
    chat = _chat_or_404(db, chat_id, _owner(request, response))
    stored = _messages(db, chat.id)
    history = [(m.role, m.content) for m in stored]
    last_id = stored[-1].id if stored else 0
    db.rollback()  # не держим соединение с базой, пока ждём GigaChat
    if (hit := brief.CACHE.get(chat.id)) and hit[0] == last_id:
        return hit[1]
    if not any(role == "user" for role, _ in history):
        return BriefOut(ready=False, missing=["расскажите консультанту, что ремонтируете"], notes=[], rooms=[])
    try:
        data, _ = await gigachat._chat("consultant_brief", brief.prompt(brief.transcript(history)), 700)
        # сверяем с тем, что клиент написал сам: придуманные вид ремонта и размеры отбрасываем
        client_text = "\n".join(content for role, content in history if role == "user")
        draft = brief.verify(brief.merge(brief.DRAFTS.get(chat.id), brief.parse(gigachat._content(data))), client_text)
    except GigaChatError as exc:
        if exc.kind == "backend_configuration" or "credentials" in str(exc) or "disabled" in str(exc):
            raise HTTPException(503, "Консультант пока не настроен: нужен ключ GigaChat в .env")
        if exc.kind in ("rate_limit", "budget"):
            # проверка данных — второстепенный запрос: при лимите отдаём прошлый результат с пометкой, а не ошибку
            if hit:
                return hit[1].model_copy(update={"stale": True})
            if exc.kind == "budget":
                raise HTTPException(429, "исчерпан лимит токенов проекта (RC_GIGACHAT_TOKEN_BUDGET в .env)") from exc
            raise HTTPException(429, "GigaChat занят, проверю данные после следующего ответа") from exc
        raise HTTPException(502, "Не удалось разобрать разговор, попробуйте ещё раз")
    result = BriefOut(**brief.build(draft))
    brief.CACHE[chat.id] = (last_id, result)
    brief.DRAFTS[chat.id] = draft
    brief.TURNS[chat.id] = sum(1 for role, _ in history if role == "user")
    return result

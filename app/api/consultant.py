"""Persistent, anonymously isolated renovation consultant API."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import logging
import secrets
import time
import uuid
from datetime import datetime

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.api.deps import get_gigachat
from app.config import get_settings
from app.consultant_brief import missing_hint
from app.consultant_prompt import CONSULTANT_SYSTEM_PROMPT, automatic_chat_title, bounded_messages
from app.db import get_session
from app.llm.gigachat import GigaChatError
from app.models import ConsultantChat, ConsultantMessage

router = APIRouter(prefix="/api/v1/consultant", tags=["consultant"])
COOKIE = "repaircalc_consultant_session"
_locks: dict[str, asyncio.Lock] = {}
logger = logging.getLogger(__name__)
_LAST_UNSET = object()


class ChatCreate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=120)


class ChatRename(BaseModel):
    title: str = Field(min_length=1, max_length=120)


class MessageIn(BaseModel):
    content: str = Field(min_length=1)
    request_id: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


class MessageEdit(BaseModel):
    content: str = Field(min_length=1)
    request_id: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    expected_last_message_id: int = Field(ge=1)


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    role: str
    content: str
    created_at: datetime


class ChatOut(BaseModel):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime
    preview: str | None = None
    last_message_id: int | None = None
    title_source: str
    messages: list[MessageOut] | None = None


def _signature(token: str) -> str:
    digest = hmac.new(
        get_settings().consultant_session_secret.encode(), token.encode(), hashlib.sha256
    ).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def _owner(request: Request, response: Response) -> str:
    raw = request.cookies.get(COOKIE, "")
    token, _, signature = raw.partition(".")
    if not token or not hmac.compare_digest(signature, _signature(token)):
        token = secrets.token_urlsafe(32)
        response.set_cookie(
            COOKIE, f"{token}.{_signature(token)}", httponly=True, samesite="lax",
            secure=get_settings().consultant_cookie_secure, max_age=60 * 60 * 24 * 365,
        )
    return hashlib.sha256(token.encode()).hexdigest()


def _chat_or_404(db: Session, chat_id: str, owner: str) -> ConsultantChat:
    chat = db.scalar(select(ConsultantChat).where(
        ConsultantChat.id == chat_id, ConsultantChat.owner_hash == owner
    ))
    if chat is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Чат не найден")
    return chat


def _messages(db: Session, chat_id: str) -> list[ConsultantMessage]:
    return list(db.scalars(select(ConsultantMessage).where(
        ConsultantMessage.chat_id == chat_id
    ).order_by(ConsultantMessage.id)).all())


def _chat_out(db: Session, chat: ConsultantChat, *, include_messages: bool = False,
              last: ConsultantMessage | None | object = _LAST_UNSET) -> ChatOut:
    messages = _messages(db, chat.id) if include_messages else None
    if include_messages:
        last = messages[-1] if messages else None
    elif last is _LAST_UNSET:
        last = db.scalar(select(ConsultantMessage).where(
            ConsultantMessage.chat_id == chat.id
        ).order_by(ConsultantMessage.id.desc()).limit(1))
    assert last is None or isinstance(last, ConsultantMessage)
    return ChatOut(
        id=chat.id, title=chat.title, title_source=chat.title_source,
        created_at=chat.created_at, updated_at=chat.updated_at,
        preview=last.content[:100] if last else None,
        last_message_id=last.id if last else None,
        messages=[MessageOut.model_validate(x) for x in messages] if messages is not None else None,
    )


def _provider_error(exc: BaseException) -> None:
    if isinstance(exc, (httpx.TimeoutException, asyncio.TimeoutError)):
        raise HTTPException(504, "Консультант не успел ответить. Попробуйте ещё раз.") from exc
    assert isinstance(exc, GigaChatError)
    text = str(exc).lower()
    if "credentials" in text or "disabled" in text or exc.kind == "backend_configuration":
        raise HTTPException(503, "Консультант пока не настроен. Обратитесь к администратору.") from exc
    if exc.kind == "authentication":
        raise HTTPException(503, "Не удалось авторизовать консультанта. Администратор уже может проверить настройки.") from exc
    if exc.kind == "ssl":
        raise HTTPException(503, "Не удалось установить защищённое соединение с консультантом.") from exc
    if exc.kind == "connection":
        raise HTTPException(503, "Сервис консультанта сейчас недоступен по сети. Попробуйте позже.") from exc
    if exc.kind in ("rate_limit", "budget"):
        raise HTTPException(429, "Слишком много запросов. Немного подождите и повторите.") from exc
    if exc.kind == "timeout":
        raise HTTPException(504, "Консультант не успел ответить. Попробуйте ещё раз.") from exc
    if exc.kind == "invalid_request":
        raise HTTPException(502, "Сервис консультанта не принял запрос. Обратитесь к администратору.") from exc
    raise HTTPException(503, "GigaChat временно недоступен. Ваше сообщение не потеряно — повторите позже.") from exc


@router.get("/chats", response_model=list[ChatOut])
def list_chats(request: Request, response: Response, db: Session = Depends(get_session)) -> list[ChatOut]:
    started = time.perf_counter(); owner = _owner(request, response); db_started = time.perf_counter()
    last_message_id = select(func.max(ConsultantMessage.id)).where(
        ConsultantMessage.chat_id == ConsultantChat.id
    ).correlate(ConsultantChat).scalar_subquery()
    rows = db.execute(
        select(ConsultantChat, ConsultantMessage)
        .outerjoin(ConsultantMessage, ConsultantMessage.id == last_message_id)
        .where(ConsultantChat.owner_hash == owner)
        .order_by(ConsultantChat.updated_at.desc())
    ).all()
    db_ms = int((time.perf_counter() - db_started) * 1000)
    result = [_chat_out(db, chat, last=last) for chat, last in rows]
    total_ms = int((time.perf_counter() - started) * 1000)
    response.headers["Server-Timing"] = f"db;dur={db_ms}, total;dur={total_ms}"
    logger.debug("Consultant chat list owner_prefix=%s chats=%s db_ms=%s total_ms=%s",
                 owner[:8], len(result), db_ms, total_ms)
    if total_ms >= 250:
        logger.warning("Slow consultant chat list chats=%s db_ms=%s total_ms=%s", len(result), db_ms, total_ms)
    return result


@router.post("/chats", response_model=ChatOut, status_code=status.HTTP_201_CREATED)
def create_chat(body: ChatCreate, request: Request, response: Response,
                db: Session = Depends(get_session)) -> ChatOut:
    owner = _owner(request, response)
    supplied = body.title.strip() if body.title else None
    chat = ConsultantChat(id=str(uuid.uuid4()), owner_hash=owner, title=supplied or "Новый чат",
                          title_source="manual" if supplied else "auto")
    db.add(chat); db.commit(); db.refresh(chat)
    return _chat_out(db, chat)


@router.get("/chats/{chat_id}", response_model=ChatOut)
def get_chat(chat_id: str, request: Request, response: Response,
             db: Session = Depends(get_session)) -> ChatOut:
    started = time.perf_counter(); owner = _owner(request, response); db_started = time.perf_counter()
    chat = _chat_or_404(db, chat_id, owner); result = _chat_out(db, chat, include_messages=True)
    db_ms = int((time.perf_counter() - db_started) * 1000)
    total_ms = int((time.perf_counter() - started) * 1000)
    response.headers["Server-Timing"] = f"db;dur={db_ms}, total;dur={total_ms}"
    logger.debug("Consultant history chat_id=%s messages=%s db_ms=%s total_ms=%s",
                 chat_id, len(result.messages or []), db_ms, total_ms)
    if total_ms >= 250:
        logger.warning("Slow consultant history chat_id=%s messages=%s db_ms=%s total_ms=%s",
                       chat_id, len(result.messages or []), db_ms, total_ms)
    return result


@router.patch("/chats/{chat_id}", response_model=ChatOut)
def rename_chat(chat_id: str, body: ChatRename, request: Request, response: Response,
                db: Session = Depends(get_session)) -> ChatOut:
    owner = _owner(request, response); chat = _chat_or_404(db, chat_id, owner)
    chat.title = body.title.strip(); chat.title_source = "manual"; db.commit(); db.refresh(chat)
    return _chat_out(db, chat)


@router.delete("/chats/{chat_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_chat(chat_id: str, request: Request, response: Response,
                      db: Session = Depends(get_session)) -> None:
    owner = _owner(request, response); chat = _chat_or_404(db, chat_id, owner)
    lock = _locks.setdefault(chat_id, asyncio.Lock())
    async with lock:
        chat = _chat_or_404(db, chat_id, owner)
        db.execute(delete(ConsultantMessage).where(ConsultantMessage.chat_id == chat.id))
        db.delete(chat); db.commit()
    _locks.pop(chat_id, None)


@router.post("/chats/{chat_id}/messages", response_model=MessageOut)
async def send_message(chat_id: str, body: MessageIn, request: Request, response: Response,
                       db: Session = Depends(get_session), gigachat=Depends(get_gigachat)) -> MessageOut:
    started = time.perf_counter(); settings = get_settings()
    if len(body.content) > settings.consultant_max_message_chars:
        raise HTTPException(422, f"Сообщение длиннее {settings.consultant_max_message_chars} символов")
    owner = _owner(request, response); chat = _chat_or_404(db, chat_id, owner)
    ownership_ms = int((time.perf_counter() - started) * 1000)
    lock = _locks.setdefault(chat_id, asyncio.Lock())
    lock_started = time.perf_counter()
    async with lock:
        lock_wait_ms = int((time.perf_counter() - lock_started) * 1000)
        chat = _chat_or_404(db, chat_id, owner)
        existing = db.scalar(select(ConsultantMessage).where(
            ConsultantMessage.chat_id == chat.id,
            ConsultantMessage.exchange_id == body.request_id,
            ConsultantMessage.role == "assistant",
        ))
        if existing:
            return MessageOut.model_validate(existing)
        db_started = time.perf_counter(); stored = _messages(db, chat.id)
        context = bounded_messages(
            [{"role": x.role, "content": x.content} for x in stored],
            settings.consultant_context_messages, settings.consultant_context_chars,
        )
        messages = [{"role": "system", "content": CONSULTANT_SYSTEM_PROMPT + missing_hint(chat.id)}, *context,
                    {"role": "user", "content": body.content.strip()}]
        was_empty = not stored; title_source = chat.title_source
        context_ms = int((time.perf_counter() - db_started) * 1000)
        # The context is now immutable. End the read transaction and return its connection to the
        # pool before waiting on the external provider; history reads must remain independent.
        db.rollback()
        provider_started = time.perf_counter()
        try:
            answer = await gigachat.consultant_chat(messages)
        except (httpx.TimeoutException, asyncio.TimeoutError, GigaChatError) as exc:
            logger.warning("Consultant provider failure chat_id=%s request_id=%s kind=%s step=%s status_code=%s",
                           chat.id, body.request_id, getattr(exc, "kind", "timeout"),
                           getattr(exc, "diagnostic", {}).get("step", "unknown"),
                           getattr(exc, "diagnostic", {}).get("status_code"))
            _provider_error(exc)
        provider_ms = int((time.perf_counter() - provider_started) * 1000)
        write_started = time.perf_counter()
        chat = _chat_or_404(db, chat_id, owner)
        user = ConsultantMessage(chat_id=chat.id, exchange_id=body.request_id,
                                 role="user", content=body.content.strip())
        assistant = ConsultantMessage(chat_id=chat.id, exchange_id=body.request_id,
                                      role="assistant", content=answer)
        db.add_all([user, assistant])
        if was_empty and title_source == "auto" and chat.title_source == "auto":
            chat.title = automatic_chat_title(body.content)
        chat.updated_at = datetime.now().astimezone(); db.commit(); db.refresh(assistant)
        write_ms = int((time.perf_counter() - write_started) * 1000)
        logger.info("Consultant request complete chat_id=%s request_id=%s ownership_ms=%s lock_wait_ms=%s context_ms=%s provider_ms=%s write_ms=%s total_ms=%s context_messages=%s context_chars=%s",
                    chat.id, body.request_id, ownership_ms, lock_wait_ms, context_ms, provider_ms, write_ms,
                    int((time.perf_counter() - started) * 1000), len(messages),
                    sum(len(x["content"]) for x in messages))
        return MessageOut.model_validate(assistant)


@router.patch("/chats/{chat_id}/messages/{message_id}", response_model=ChatOut)
async def edit_message(chat_id: str, message_id: int, body: MessageEdit, request: Request, response: Response,
                       db: Session = Depends(get_session), gigachat=Depends(get_gigachat)) -> ChatOut:
    settings = get_settings(); content = body.content.strip()
    if not content:
        raise HTTPException(422, "Сообщение не может быть пустым")
    if len(content) > settings.consultant_max_message_chars:
        raise HTTPException(422, f"Сообщение длиннее {settings.consultant_max_message_chars} символов")
    owner = _owner(request, response); chat = _chat_or_404(db, chat_id, owner)
    lock = _locks.setdefault(chat_id, asyncio.Lock())
    async with lock:
        chat = _chat_or_404(db, chat_id, owner)
        target = db.scalar(select(ConsultantMessage).where(
            ConsultantMessage.id == message_id, ConsultantMessage.chat_id == chat.id
        ))
        if target is None:
            raise HTTPException(404, "Сообщение не найдено")
        if target.role != "user":
            raise HTTPException(403, "Можно изменять только свои сообщения")
        duplicate = db.scalar(select(ConsultantMessage).where(
            ConsultantMessage.chat_id == chat.id, ConsultantMessage.exchange_id == body.request_id,
            ConsultantMessage.role == "assistant",
        ))
        if duplicate and target.exchange_id == body.request_id:
            return _chat_out(db, chat, include_messages=True)
        stored = _messages(db, chat.id); current_last_id = stored[-1].id
        if current_last_id != body.expected_last_message_id:
            raise HTTPException(409, "История чата изменилась. Обновите чат и повторите редактирование.")
        before = [x for x in stored if x.id < target.id]
        editing_first_user = not any(x.role == "user" for x in before)
        context = bounded_messages(
            [{"role": x.role, "content": x.content} for x in before],
            settings.consultant_context_messages, settings.consultant_context_chars,
        )
        messages = [{"role": "system", "content": CONSULTANT_SYSTEM_PROMPT + missing_hint(chat.id)}, *context,
                    {"role": "user", "content": content}]
        db.rollback()
        try:
            answer = await gigachat.consultant_chat(messages)
        except (httpx.TimeoutException, asyncio.TimeoutError, GigaChatError) as exc:
            logger.warning("Consultant regeneration failed chat_id=%s message_id=%s request_id=%s kind=%s",
                           chat.id, message_id, body.request_id, getattr(exc, "kind", "timeout"))
            _provider_error(exc)
        # Re-read after the provider call. Nothing has been mutated yet, so a concurrent append
        # produces a conflict and leaves the complete original branch intact.
        db.expire_all(); chat = _chat_or_404(db, chat_id, owner)
        latest = _messages(db, chat.id)
        if not latest or latest[-1].id != body.expected_last_message_id:
            raise HTTPException(409, "История чата изменилась. Изменения не применены.")
        target = db.scalar(select(ConsultantMessage).where(
            ConsultantMessage.id == message_id, ConsultantMessage.chat_id == chat.id,
            ConsultantMessage.role == "user",
        ))
        if target is None:
            raise HTTPException(409, "Сообщение уже изменено")
        db.execute(delete(ConsultantMessage).where(
            ConsultantMessage.chat_id == chat.id, ConsultantMessage.id > target.id
        ))
        target.content = content; target.exchange_id = body.request_id
        db.add(ConsultantMessage(chat_id=chat.id, exchange_id=body.request_id,
                                 role="assistant", content=answer))
        if chat.title_source == "auto" and editing_first_user:
            chat.title = automatic_chat_title(content)
        chat.updated_at = datetime.now().astimezone()
        db.commit(); db.refresh(chat)
        return _chat_out(db, chat, include_messages=True)

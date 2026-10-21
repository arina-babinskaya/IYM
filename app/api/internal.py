from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.llm.client import LLMError, get_llm

router = APIRouter(prefix="/internal/llm", tags=["internal-llm"])


class ChatIn(BaseModel):
    messages: list[dict[str, str]]
    temperature: float = 0.0
    json_schema: dict[str, Any] | None = Field(None, description="JSON-схема структурированного ответа")
    max_tokens: int | None = None


class EmbedIn(BaseModel):
    texts: list[str] = Field(min_length=1, max_length=2048)
    kind: Literal["query", "passage"] | None = None


@router.post("/chat")
async def chat(req: ChatIn) -> dict[str, Any]:
    try:
        content = await get_llm().chat(
            req.messages, format=req.json_schema, temperature=req.temperature, max_tokens=req.max_tokens
        )
    except LLMError as e:
        raise HTTPException(503, str(e)) from e
    return {"content": content, "model": get_llm().s.llm_model}


@router.post("/embed")
async def embed(req: EmbedIn) -> dict[str, Any]:
    try:
        vectors = await get_llm().embed(req.texts, kind=req.kind)
    except LLMError as e:
        raise HTTPException(503, str(e)) from e
    return {"embeddings": vectors, "model": get_llm().s.embed_model, "dim": len(vectors[0]) if vectors else 0}


@router.get("/health")
async def health() -> dict[str, Any]:
    return await get_llm().health()

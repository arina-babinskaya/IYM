import asyncio
import json

import httpx
from pydantic import BaseModel

from app.config import Settings
from app.llm.client import LLMClient, LLMError


class Answer(BaseModel):
    room: str
    area: float


def make(handler) -> LLMClient:
    s = Settings(ollama_url="http://ollama", llm_retries=2, embed_model="multilingual-e5-large")
    return LLMClient(s, transport=httpx.MockTransport(handler))


def test_chat_retries_and_cache():
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503, text="loading model")
        return httpx.Response(200, json={"message": {"content": "ok"}})

    llm = make(handler)
    msgs = [{"role": "user", "content": "привет"}]
    assert asyncio.run(llm.chat(msgs)) == "ok"
    assert asyncio.run(llm.chat(msgs)) == "ok"
    assert calls["n"] == 2


def test_chat_json_fixes_invalid():
    replies = iter(['{"room": "ванная"}', '{"room": "ванная", "area": 6}'])
    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        seen.append(body)
        assert body["format"]["title"] == "Answer"
        return httpx.Response(200, json={"message": {"content": next(replies)}})

    obj = asyncio.run(make(handler).chat_json([{"role": "user", "content": "x"}], Answer))
    assert obj == Answer(room="ванная", area=6)
    assert "не прошёл проверку" in seen[1]["messages"][-1]["content"]


def test_unavailable_raises():
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    try:
        asyncio.run(make(handler).chat([{"role": "user", "content": "x"}]))
    except LLMError:
        pass
    else:
        raise AssertionError("ожидали LLMError")


def test_embed_prefix_batch_and_cache():
    inputs = []

    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        inputs.append(body["input"])
        return httpx.Response(200, json={"embeddings": [[float(len(t))] for t in body["input"]]})

    llm = make(handler)
    v1 = asyncio.run(llm.embed(["a", "bb"], kind="passage"))
    v2 = asyncio.run(llm.embed(["bb", "ccc"], kind="passage"))
    assert inputs == [["passage: a", "passage: bb"], ["passage: ccc"]]
    assert v1[1] == v2[0]

import json

from fastapi.testclient import TestClient

from app.api.deps import get_gigachat
from app.consultant_brief import build, parse, transcript
from app.db import get_sessionmaker
from app.main import app
from app.models import ConsultantMessage

READY = {
    "renovation_type": "cosmetic",
    "rooms": [{"room_type": "kids_room", "name": "Детская", "length_m": 4, "width_m": "3.5", "windows": 1,
               "doors": 1, "wishes": [{"text": "светлые обои", "materials": ["wallpaper", "spaceship"]}]}],
}


def test_brief_builds_calculator_rooms_with_defaults():
    r = build(parse("Вот параметры:\n```json\n" + json.dumps(READY, ensure_ascii=False) + "\n```"))
    assert r["ready"] and r["missing"] == []
    room = r["rooms"][0]
    assert room["room_type"] == "bedroom" and room["renovation_type"] == "cosmetic"
    assert float(room["height_m"]) == 2.7 and any("высоту потолка" in n for n in r["notes"])
    assert room["wishes"] == [{"text": "светлые обои", "materials": ["wallpaper"]}]
    assert room["works"] and all("work_type" in w for w in room["works"])
    assert float(room["openings_area_m2"]) > 0


def test_brief_lists_what_is_missing():
    r = build(parse('{"rooms": [{"room_type": "kitchen", "length_m": -3}]}'))
    assert not r["ready"] and r["rooms"] == []
    assert any("вид ремонта" in m for m in r["missing"]) and any("Кухня: длина" in m for m in r["missing"])
    r = build(parse('{"renovation_type": "capital", "rooms": [{"room_type": "bathroom", "length_m": 2, "width_m": 2}]}'))
    assert r["ready"] and r["rooms"][0]["doors"] == 1 and any("типичные" in n for n in r["notes"])


def test_transcript_keeps_client_words_from_the_start_of_a_long_chat():
    chat = [("user", "ванная 4 на 2, капитальный ремонт")]
    for k in range(12):  # длинный разговор: консультант отвечает подробно
        chat += [("assistant", f"совет {k} " + "очень подробно " * 60), ("user", f"вопрос {k}")]
    t = transcript(chat, limit_chars=8000)
    assert len(t) <= 8000 and t.splitlines()[0] == "Клиент: ванная 4 на 2, капитальный ремонт"
    assert all(f"Клиент: вопрос {k}" in t for k in range(12))
    assert ("совет 11 " + "очень подробно " * 60).strip() in t  # последние ответы консультанта целиком
    # совсем тесно: сначала уходят ответы консультанта, потом самые старые слова клиента
    t = transcript([("user", "a" * 50), ("assistant", "ответ"), ("user", "спальня 4 на 3")], limit_chars=60)
    assert t.splitlines() == ["Клиент: спальня 4 на 3"]


class FakeGigaChat:
    def __init__(self, answer):
        self.answer, self.seen = answer, None

    async def _chat(self, kind, messages, max_tokens, schema=None):
        self.seen = messages
        return {"choices": [{"message": {"content": self.answer}}]}, "key"

    @staticmethod
    def _content(data):
        return data["choices"][0]["message"]["content"]


def test_brief_endpoint_reads_own_chat_only(db):
    fake = FakeGigaChat(json.dumps(READY, ensure_ascii=False))
    app.dependency_overrides[get_gigachat] = lambda: fake
    try:
        with TestClient(app) as client:
            chat = client.post("/api/v1/consultant/chats", json={}).json()
            empty = client.post(f"/api/v1/consultant/chats/{chat['id']}/brief").json()
            assert not empty["ready"] and fake.seen is None
            with get_sessionmaker()() as s:
                s.add_all([ConsultantMessage(chat_id=chat["id"], exchange_id="e1", role="user",
                                             content="Детская 4 на 3,5, косметика, хочу светлые обои"),
                           ConsultantMessage(chat_id=chat["id"], exchange_id="e1", role="assistant",
                                             content="Хорошо, подберу светлые флизелиновые обои")])
                s.commit()
            r = client.post(f"/api/v1/consultant/chats/{chat['id']}/brief").json()
            assert r["ready"] and r["rooms"][0]["length_m"] == 4
            assert "Клиент: Детская 4 на 3,5" in fake.seen[1]["content"]
            with TestClient(app) as stranger:
                assert stranger.post(f"/api/v1/consultant/chats/{chat['id']}/brief").status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_brief_rooms_are_accepted_by_estimate(ingested):
    r = build(parse(json.dumps(READY, ensure_ascii=False)))
    with TestClient(app) as client:
        est = client.post("/api/v1/estimate", json={"renovation_type": r["renovation_type"], "rooms": r["rooms"],
                                                    "explain": False})
    assert est.status_code == 200, est.text
    assert est.json()["rooms"][0]["room"]["wishes"][0]["text"] == "светлые обои"


def test_brief_adjusts_default_works_by_what_was_asked():
    draft = dict(READY, rooms=[dict(READY["rooms"][0], room_type="bedroom",
                                    add_works=["floor_covering_install:floor:линолеум", "wall_painting:wall:",
                                               "no_such_work"],
                                    remove_works=["priming:wall:"])])
    room = build(parse(json.dumps(draft, ensure_ascii=False)))["rooms"][0]
    works = [w["work_type"] for w in room["works"]]
    assert "floor_covering_install" in works and "wall_painting" in works and "priming" not in works
    assert "wallpapering" in works  # default stays
    assert room["auto"]["added"] == ["Укладка напольных покрытий (линолеум)", "Окраска стен и потолков (стены)"]
    assert room["auto"]["removed"] == ["Грунтование (стены)"]
    assert room["auto"]["notes"] == ["Детская: высоту потолка не называли — взяли 2.7 м"]
    floor = next(w for w in room["works"] if w["work_type"] == "floor_covering_install")
    assert "linoleum" in floor["materials"]


def test_brief_variant_replaces_default_variant():
    from app.consultant_brief import choose_works
    from app.schemas import RoomType
    from app.taxonomy import RenovationType

    works, added, _, replaced = choose_works(RoomType.bedroom, RenovationType.capital, ["floor_covering_install:floor:линолеум"], [])
    floors = [w for w in works if w["work_type"] == "floor_covering_install"]
    assert len(floors) == 1 and "linoleum" in floors[0]["materials"] and not added
    assert replaced == ["Укладка напольных покрытий (ламинат) → Укладка напольных покрытий (линолеум)"]
    works, added, _, _ = choose_works(RoomType.bedroom, RenovationType.capital, ["floor_covering_install:floor:"], [])
    assert not added  # already in defaults (laminate)


def test_named_works_are_enough_without_renovation_type():
    no_works = {"rooms": [{"room_type": "bedroom", "length_m": 4, "width_m": 3}]}
    r = build(parse(json.dumps(no_works)))
    assert not r["ready"] and "вид ремонта" in r["missing"][0]
    # человек назвал работы, а не вид ремонта — считаем только их
    one_work = {"rooms": [dict(no_works["rooms"][0], add_works=["wall_painting:wall:"])]}
    r = build(parse(json.dumps(one_work)))
    assert r["ready"] and r["renovation_type"] == "cosmetic"
    room = r["rooms"][0]
    assert [w["work_type"] for w in room["works"]] == ["wall_painting"] and room["auto"]["only"] is True
    tiles = {"renovation_type": "capital", "rooms": [{"room_type": "bathroom", "length_m": 2, "width_m": 2,
                                                     "add_works": ["tiling:floor:"], "only_works": True}]}
    room = build(parse(json.dumps(tiles)))["rooms"][0]
    assert room["renovation_type"] == "capital" and [(w["work_type"], w["surface"]) for w in room["works"]] == [("tiling", "floor")]


def test_wish_switches_wall_finish_and_invented_facts_are_dropped():
    from app.consultant_brief import verify

    # kitchen, cosmetic: painting by default; the client wants beige wallpaper
    draft = parse(json.dumps({"renovation_type": "cosmetic", "rooms": [
        {"room_type": "kitchen", "length_m": 2, "width_m": 2.5, "wishes": [{"text": "бежевые обои"}]}]}))
    room = build(verify(draft, "кухня 2 на 2,5, косметический ремонт, хочу бежевые обои"))["rooms"][0]
    works = [w["work_type"] for w in room["works"]]
    assert "wallpapering" in works and "wall_painting" not in works
    assert room["auto"]["replaced"] == ["Окраска стен и потолков (стены) → Оклейка обоями (стены)"]
    # the model invented renovation type and size: the client never said them
    draft = parse(json.dumps({"renovation_type": "capital", "rooms": [
        {"room_type": "bedroom", "length_m": 5, "width_m": 4, "windows": 2}]}))
    r = build(verify(draft, "хочу обновить спальню, обои бежевые"))
    assert not r["ready"] and any("вид ремонта" in m for m in r["missing"]) and any("длина" in m for m in r["missing"])
    assert parse(json.dumps({"rooms": [{"length_m": 3.5}]})).rooms[0].length_m == 3.5
    from app.consultant_brief import _said
    assert _said(3.5, "комната 3,5 на 4") and _said(4, "3,5 на 4 метра") and _said(3.5, "350 см")
    assert not _said(4, "комната 3,5 на 14")


def test_wish_for_unavailable_work_is_explained():
    draft = parse(json.dumps({"renovation_type": "cosmetic", "rooms": [
        {"room_type": "bathroom", "length_m": 2, "width_m": 2, "wishes": [{"text": "бежевые обои"}]}]}))
    room = build(draft)["rooms"][0]
    assert "wall_painting" in [w["work_type"] for w in room["works"]]
    assert any("такой работы для этого помещения в калькуляторе нет" in n for n in room["auto"]["notes"])


def test_wish_warnings_say_honestly_what_was_not_applied():
    from types import SimpleNamespace

    from app.api.picker import wish_warnings
    from app.schemas import RoomInput

    room = RoomInput(room_type="bedroom", length_m=4, width_m=3, wishes=[
        {"text": "светлые обои", "materials": ["wallpaper"]}, {"text": "обои в горошек", "materials": ["wallpaper"]},
        {"text": "светильник IP44", "materials": ["lighting"]}, {"text": "плитка под мрамор", "materials": ["tile"]}])
    items = [SimpleNamespace(material="wallpaper", product=object()), SimpleNamespace(material="tile", product=None)]
    out = wish_warnings(room, items, {"светлые обои"})
    assert out == ["Спальня: «обои в горошек» — точно такого товара в каталоге не нашлось, выбран ближайший",
                   "Спальня: «светильник IP44» — в смете нет работ с этим материалом",
                   "Спальня: «плитка под мрамор» — товара для этой позиции в каталоге нет"]


def test_wishes_can_target_any_material():
    r = build(parse(json.dumps({"renovation_type": "capital", "rooms": [{
        "room_type": "bathroom", "length_m": 2, "width_m": 2,
        "wishes": [{"text": "светильники с защитой IP44", "materials": ["lighting"]}]}]})))
    assert r["rooms"][0]["wishes"] == [{"text": "светильники с защитой IP44", "materials": ["lighting"]}]


def test_consultant_gets_missing_data_hint_and_frame_first_prompt(db):
    from app.consultant_brief import CACHE, missing_hint
    from app.api.consultant_brief import BriefOut
    from app.consultant_prompt import CONSULTANT_SYSTEM_PROMPT

    assert CONSULTANT_SYSTEM_PROMPT.index("сначала коротко выясни общую картину") < CONSULTANT_SYSTEM_PROMPT.index("Определи намерение")
    assert "Не называй конкретные бренды" in CONSULTANT_SYSTEM_PROMPT
    CACHE["chat-x"] = (5, BriefOut(ready=False, missing=["вид ремонта", "Спальня: длина и ширина комнаты"], notes=[], rooms=[]))
    hint = missing_hint("chat-x")
    assert "вид ремонта; Спальня: длина и ширина комнаты" in hint
    CACHE["chat-x"] = (6, BriefOut(ready=True, missing=[], notes=[], rooms=[]))
    assert missing_hint("chat-x") == "" and missing_hint("unknown") == ""
    CACHE.pop("chat-x")


def test_hint_is_sent_to_gigachat_with_next_message(db):
    from app.api.consultant_brief import BriefOut
    from app.consultant_brief import CACHE

    seen = []

    class Recorder(FakeGigaChat):
        async def consultant_chat(self, messages):
            seen.append(messages)
            return "Какой ремонт планируете и какие размеры спальни?"

    app.dependency_overrides[get_gigachat] = lambda: Recorder("{}")
    try:
        with TestClient(app) as client:
            chat = client.post("/api/v1/consultant/chats", json={}).json()
            CACHE[chat["id"]] = (1, BriefOut(ready=False, missing=["вид ремонта"], notes=[], rooms=[]))
            r = client.post(f"/api/v1/consultant/chats/{chat['id']}/messages",
                            json={"content": "хочу ремонт спальни", "request_id": "req-hint-1"})
            assert r.status_code == 200, r.text
            assert seen[0][0]["role"] == "system" and "пока не хватает: вид ремонта" in seen[0][0]["content"]
    finally:
        app.dependency_overrides.clear()
        CACHE.clear()


def test_wish_materials_are_inferred_from_words():
    r = build(parse(json.dumps({"renovation_type": "capital", "rooms": [{
        "room_type": "bathroom", "length_m": 2, "width_m": 2,
        "wishes": [{"text": "светильники с защитой IP44"}, {"text": "белая затирка"}]}]})))
    assert [w["materials"] for w in r["rooms"][0]["wishes"]] == [["lighting"], ["grout"]]
    from app.consultant_brief import prompt
    assert len(prompt("")[0]["content"]) < 3500  # every check costs tokens: keep the instruction short


def test_brief_rate_limit_returns_previous_result(monkeypatch):
    from app.api import consultant_brief as api_brief
    from app.llm.gigachat import GigaChatError
    import asyncio
    from fastapi import HTTPException

    class Busy:
        async def _chat(self, *a, **k):
            raise GigaChatError("GigaChat HTTP 429", kind="rate_limit")

    class Msg:
        def __init__(self, i, role, content): self.id, self.role, self.content = i, role, content

    class Chat: id = "c-busy"
    monkeypatch.setattr(api_brief, "_chat_or_404", lambda *a: Chat())
    monkeypatch.setattr(api_brief, "_owner", lambda *a: "o")
    msgs = [Msg(1, "user", "кухня 3 на 3"), Msg(2, "assistant", "ок")]
    monkeypatch.setattr(api_brief, "_messages", lambda *a: msgs)

    class Db:
        def rollback(self): pass
    run = lambda: asyncio.run(api_brief.chat_brief("c-busy", None, None, Db(), Busy()))
    api_brief.brief.CACHE.pop("c-busy", None)
    try:
        run(); assert False
    except HTTPException as exc:
        assert exc.status_code == 429
    prev = api_brief.BriefOut(ready=False, missing=["вид ремонта"], notes=[], rooms=[])
    api_brief.brief.CACHE["c-busy"] = (1, prev)
    got = run()
    assert got.stale and got.missing == prev.missing
    api_brief.brief.CACHE.pop("c-busy", None)


def test_sizes_from_client_words():
    from app.consultant_brief import sizes_from_text
    assert sizes_from_text("площадь 8 высота стандартная\nдлина 4 ширина 2") == {"length_m": 4, "width_m": 2, "area_m2": 8}
    assert sizes_from_text("кухня 3 x 2,5, высота 2,6") == {"length_m": 3, "width_m": 2.5, "height_m": 2.6}
    assert sizes_from_text("350 на 400") == {"length_m": 3.5, "width_m": 4}
    assert sizes_from_text("бюджет 100 на 200 тысяч") == {}


def test_model_missed_sizes_taken_from_words():
    from app.consultant_brief import BriefDraft, build, verify
    draft = verify(BriefDraft.model_validate({"renovation_type": "capital", "rooms": [{"room_type": "bathroom"}]}),
                   "хочу ремонт ванной\nкапитальный\nдлина 4 ширина 2")
    out = build(draft)
    assert out["ready"] and out["rooms"][0]["length_m"] == 4 and out["rooms"][0]["width_m"] == 2


def test_area_only_room_is_estimated():
    from app.consultant_brief import BriefDraft, build, verify
    draft = verify(BriefDraft.model_validate({"renovation_type": "cosmetic", "rooms": [{"room_type": "living_room", "area_m2": 16}]}),
                   "гостиная буквой г, площадь 16, косметический ремонт")
    out = build(draft)
    room = out["rooms"][0]
    assert out["ready"] and float(room["custom_floor_area"]) == 16 and float(room["custom_perimeter"]) == 16
    assert any("только площадь" in n for n in out["notes"] + room["auto"]["notes"])


def test_works_named_in_words_count_when_model_missed_them():
    from app.consultant_brief import verify, works_from_text
    assert works_from_text("проводку не трогаем, только покрасить потолок") == ["wall_painting:ceiling:"]
    assert works_from_text("хочу покрасить стены и положить ламинат") == ["wall_painting:wall:", "floor_covering_install:floor:ламинат"]
    assert works_from_text("положить плитку на пол") == ["tiling:floor:"]
    assert works_from_text("без плитки") == [] and works_from_text("хочу обновить спальню, обои бежевые") == []
    draft = verify(parse(json.dumps({"rooms": [{"room_type": "bathroom"}]})),
                   "ванная 2 на 2, надо поменять унитаз и положить плитку на пол")
    r = build(draft)
    room = r["rooms"][0]
    assert r["ready"] and sorted(w["work_type"] for w in room["works"]) == ["plumbing_fixture_install", "tiling"]
    assert any("вы назвали отдельные работы" in n for n in room["auto"]["notes"] + r["notes"])


def test_hint_becomes_mandatory_in_a_long_chat():
    from app.api.consultant_brief import BriefOut
    from app.consultant_brief import ASK_AFTER, CACHE, TURNS, missing_hint
    CACHE["chat-long"] = (9, BriefOut(ready=False, missing=["вид ремонта"], notes=[], rooms=[]))
    TURNS["chat-long"] = ASK_AFTER - 1
    assert "Если это уместно" in missing_hint("chat-long")
    TURNS["chat-long"] = ASK_AFTER
    hint = missing_hint("chat-long")
    assert "обязательно спроси" in hint and "вид ремонта" in hint
    CACHE["chat-long"] = (10, BriefOut(ready=True, missing=[], notes=[], rooms=[]))
    assert missing_hint("chat-long") == ""  # всё собрано — не давим
    CACHE.pop("chat-long"); TURNS.pop("chat-long")


def test_new_check_does_not_forget_what_was_collected():
    from app.consultant_brief import merge
    first = parse(json.dumps({"renovation_type": "capital", "rooms": [
        {"room_type": "bathroom", "length_m": 4, "width_m": 2, "wishes": [{"text": "голубая плитка"}]}]}))
    assert build(first)["ready"]
    # следующий ответ модели «забыл» вид ремонта и размеры, но человек сказал новое — высоту
    later = parse(json.dumps({"rooms": [{"room_type": "bathroom", "height_m": 2.5}]}))
    assert not build(later)["ready"]
    merged = merge(first, later)
    r = build(merged)
    room = r["rooms"][0]
    assert r["ready"] and room["length_m"] == 4 and room["height_m"] == 2.5 and room["wishes"][0]["text"] == "голубая плитка"
    # человек передумал: новое значение важнее прошлого
    assert build(merge(first, parse(json.dumps({"rooms": [{"room_type": "bathroom", "length_m": 3}]}))))["rooms"][0]["length_m"] == 3
    # модель не упомянула второе помещение — оно не пропадает
    two = parse(json.dumps({"renovation_type": "cosmetic", "rooms": [
        {"room_type": "kitchen", "length_m": 3, "width_m": 3}, {"room_type": "hallway", "length_m": 2, "width_m": 1}]}))
    assert len(build(merge(two, parse(json.dumps({"rooms": [{"room_type": "kitchen"}]}))))["rooms"]) == 2


def test_only_ceiling_chat_from_a_real_conversation():
    from app.consultant_brief import merge, verify
    said = "\n".join(["хочу ремонт кухни", "хочу поменять потолки", "только потолок без всего другого любой",
                      "любые высота обычная", "5000 ничего не хочу", "натяжной", "нет", "кухня 4 на 5"])
    prev = verify(parse(json.dumps({"rooms": [{"room_type": "kitchen"}]})), said)
    # модель в этот раз не вернула помещение — размеры и работа всё равно из слов клиента
    r = build(verify(merge(prev, parse('{"rooms": []}')), said))
    room = r["rooms"][0]
    assert r["ready"] and room["length_m"] == 4 and room["width_m"] == 5
    assert [(w["work_type"], w["surface"]) for w in room["works"]] == [("wall_painting", "ceiling")]
    assert any("Натяжной" in n for n in room["auto"]["notes"])
    # модель совсем не назвала помещение, а клиент говорил только про кухню
    assert build(verify(parse('{"rooms": []}'), said))["rooms"][0]["room_type"] == "kitchen"


def test_invented_windows_are_dropped_in_every_room():
    from app.consultant_brief import verify
    two = parse(json.dumps({"renovation_type": "cosmetic", "rooms": [
        {"room_type": "kitchen", "length_m": 3, "width_m": 3, "windows": 4},
        {"room_type": "hallway", "length_m": 2, "width_m": 1, "doors": 3}]}))
    d = verify(two, "косметический, кухня 3 на 3 и коридор 2 на 1")
    assert all(r.windows is None and r.doors is None for r in d.rooms)

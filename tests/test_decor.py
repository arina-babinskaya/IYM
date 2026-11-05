from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base, get_session
from app.decor import INDEX, STYLES, Item, score
from app.main import app
from app.models import Product, ProductCharacteristic

LAMPS = "Люстры потолочные"


def add(session, pid, name, category, price, **chars):
    session.add(Product(id=pid, name=name, categories={"1": category}, result_price=Decimal(price),
                        price=Decimal(price), status=True))
    for code, value in chars.items():
        session.add(ProductCharacteristic(product_id=pid, code=code, name=code.replace("_", " ").capitalize(),
                                          value_raw=value))


@pytest.fixture
def client(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'decor.sqlite'}")
    Base.metadata.create_all(engine)
    make = sessionmaker(bind=engine)
    with make() as s:
        add(s, 1, "люстра потолочная Дэла 5х60Вт E27 металл черный", LAMPS, 5000, стиль="лофт", цвет_арматуры="черный")
        add(s, 2, "люстра потолочная Лайма 6х60Вт хрусталь золото", LAMPS, 9000, стиль="классический")
        add(s, 3, "люстра потолочная Бриз LED 60Вт белая", LAMPS, 3000, стиль="модерн", цвет_арматуры="белый")
        add(s, 4, "люстра подвесная Винтаж E27 бронза", LAMPS, 7000, стиль="лофт", цвет_арматуры="бронза")
        add(s, 5, "люстра потолочная Ретро E27 черная", LAMPS, 2000, стиль="лофт", цвет_арматуры="черный")
        add(s, 6, "светильник подвесной для растений", "Светильники подвесные для растений", 900, стиль="лофт")
        add(s, 10, "ковер Лофт 800х1500мм полипропилен", "Ковры", 3000, дизайн_ковров="современный",
            цвет_ковровых_изделий="серый")
        add(s, 11, "ковер Оливия 1600х2300мм бежевый", "Ковры", 6000, дизайн_ковров="классический",
            цвет_ковровых_изделий="бежевый")
        add(s, 20, "ваза стеклянная прозрачная", "Вазы", 800, материал="стекло", цвет="прозрачный")
        add(s, 30, "мангал разборный 3мм", "Мангалы", 4500)
        add(s, 31, "набор шампуров 6шт", "Шампуры", 600)
        add(s, 32, "семена Томат Бычье сердце", "Семена овощей", 40)
        add(s, 33, "семена Огурец Кураж", "Семена овощей", 60)
        add(s, 50, "диван прямой Нильс 200см рогожка черный", "Диваны", 30000, стиль_интерьера="лофт", цвет="черный")
        add(s, 51, "диван Версаль бархат золото", "Диваны", 60000, стиль_интерьера="классика", цвет="золотой")
        s.add(Product(id=40, name="мишура новогодняя 2м", categories={"1": "Мишура новогодняя"},
                      result_price=Decimal(150), price=Decimal(150), status=True, in_stock=False))
        s.add(Product(id=41, name="люстра потолочная лофт нет в наличии", categories={"1": LAMPS},
                      result_price=Decimal(100), price=Decimal(100), status=True, in_stock=False))
        s.commit()

    def session():
        with make() as s:
            yield s

    INDEX.version = None
    app.dependency_overrides[get_session] = session
    yield TestClient(app)
    app.dependency_overrides.clear()
    INDEX.version = None


def test_catalog_style_label_outweighs_colour_words():
    loft = Item(1, "люстра металл черный", Decimal(1), 0, None, None, None, attrs="лофт", colors="черный")
    modern = Item(2, "люстра металл черный", Decimal(1), 0, None, None, None, attrs="модерн", colors="черный")
    assert score(loft, STYLES["loft"]).score > score(modern, STYLES["loft"]).score
    assert "в каталоге отмечен стиль «лофт»" in score(loft, STYLES["loft"]).why
    crystal = Item(3, "люстра хрусталь золото", Decimal(1), 0, None, None, None, attrs="классический")
    assert score(crystal, STYLES["loft"]).score < 0


def test_pick_follows_style_and_budget(client):
    lines = {}
    for budget in ("economy", "premium"):
        r = client.post("/api/v1/decor", json={"room_type": "living_room", "style": "loft", "budget": budget})
        assert r.status_code == 200
        lines[budget] = {x["slot"]: x for x in r.json()["items"]}
    assert lines["economy"]["chandelier"]["product"]["id"] == 5
    assert lines["premium"]["chandelier"]["product"]["id"] == 4
    assert lines["economy"]["chandelier"]["choices"] == 3  # plant lamp is excluded, classic and modern do not fit
    assert lines["economy"]["rug"]["product"]["id"] == 10


def test_classic_room_and_empty_slots(client):
    r = client.post("/api/v1/decor", json={"room_type": "living_room", "style": "classic"}).json()
    items = {x["slot"]: x for x in r["items"]}
    assert items["chandelier"]["product"]["id"] == 2
    assert items["rug"]["product"]["id"] == 11
    assert items["mirror"]["product"] is None and Decimal(str(items["mirror"]["cost"])) == 0
    assert Decimal(str(r["total"])) == sum(Decimal(str(x["cost"])) for x in r["items"])


def test_manual_pick_skip_and_options(client):
    r = client.post("/api/v1/decor", json={"room_type": "living_room", "style": "loft",
                                           "picks": {"chandelier": 1}, "skip": ["rug"]}).json()
    items = {x["slot"]: x for x in r["items"]}
    assert items["chandelier"]["product"]["id"] == 1 and "rug" not in items
    options = client.get("/api/v1/decor/options?style=loft&slot=chandelier").json()
    assert [x["id"] for x in options][:3] == [1, 4, 5] or {x["id"] for x in options} == {1, 4, 5}
    assert client.get("/api/v1/decor/options?style=nope&slot=chandelier").status_code == 404


def test_styles_report_how_many_slots_are_covered(client):
    styles = {s["id"]: s for s in client.get("/api/v1/decor/styles?room_type=living_room").json()}
    assert set(styles) == set(STYLES) - {"kids"}
    assert styles["loft"]["slots_found"] >= 2
    assert styles["loft"]["slots_total"] == 15


def test_prints_and_off_palette_colours_lose():
    from app.decor import family

    def item(name, **kw):
        return Item(1, name, Decimal(1), 0, None, None, kw.pop("brand", None), **kw)

    classic = STYLES["classic"]
    velvet = item("штора бархат бежевая", materials="бархат", colors="бежевый")
    cat = item("занавеска для ванной с котиками бежевая", colors="бежевый")
    grey = item("занавеска для ванной Classic серая", colors="серый")
    assert score(velvet, classic).score > score(cat, classic).score
    assert score(grey, classic).score < score(item("занавеска для ванной Classic бежевая", colors="бежевый"),
                                              classic).score
    assert family(item("люстра", colors="золотой, белый")) == "gold"
    branded = item("штора-плиссе РЫЖИЙ КОТ Сканди белая", brand="РЫЖИЙ КОТ", colors="белый")
    assert score(branded, STYLES["scandi"]).score >= 3  # the brand name is not a cat print


def test_outdoor_zones_list_everything_without_style(client):
    zones = {z["id"]: z for z in client.get("/api/v1/decor/zones").json()}
    assert zones["grill"]["total"] == 2 and zones["vegetable_garden"]["total"] == 2
    grill = client.get("/api/v1/decor/zones/grill").json()
    assert [(g["id"], g["total"]) for g in grill["groups"]] == [("grills", 1), ("tools", 1)]
    seeds = client.get("/api/v1/decor/zones/vegetable_garden/seeds?q=томат").json()
    assert [x["id"] for x in seeds] == [32]
    assert client.get("/api/v1/decor/zones/nope").status_code == 404


def test_zone_kit_picks_one_product_per_position(client):
    r = client.post("/api/v1/decor/zones/grill/kits/shashlik", json={"budget": "standard"}).json()
    items = {x["slot"]: x for x in r["items"]}
    assert r["kit_title"] == "Шашлык на компанию"
    assert items["grill"]["product"]["id"] == 30 and items["skewers"]["product"]["id"] == 31
    assert items["fuel"]["product"] is None
    assert Decimal(str(r["total"])) == Decimal(4500 + 600)
    r = client.post("/api/v1/decor/zones/grill/kits/shashlik", json={"skip": ["grill"]}).json()
    assert "grill" not in {x["slot"] for x in r["items"]}
    seeds = client.get("/api/v1/decor/zones/vegetable_garden/kits/season/tomato").json()
    assert [x["id"] for x in seeds] == [32]
    zones = {z["id"]: z for z in client.get("/api/v1/decor/zones").json()}
    assert {k["id"] for k in zones["grill"]["kits"]} == {"shashlik", "bbq", "evening"}
    assert client.post("/api/v1/decor/zones/grill/kits/nope", json={}).status_code == 404


def test_themed_styles_accept_motifs_but_not_cartoons():
    def item(name, colors):
        return Item(1, name, Decimal(1), 0, None, None, None, colors=colors)

    marine, forest = STYLES["marine"], STYLES["forest"]
    assert score(item("подушка декоративная Якорь синяя", "синий"), marine).score >= 3
    assert score(item("подушка декоративная Олень", "зеленый"), forest).score >= 3
    assert score(item("подушка декоративная Единорог", "зеленый"), forest).score < 3
    assert score(item("ваза хрусталь золото", "золотой"), marine).score < 0


def test_kids_room_offers_kids_style_first(client):
    rooms = {r["id"]: r["title"] for r in client.get("/api/v1/decor/rooms").json()}
    assert rooms["kids_room"] == "Детская" and "living_room" in rooms
    styles = client.get("/api/v1/decor/styles?room_type=kids_room").json()
    assert styles[0]["id"] == "kids"
    r = client.post("/api/v1/decor", json={"room_type": "kids_room", "style": "kids"})
    assert r.status_code == 200 and r.json()["room_title"] == "Детская"
    assert client.get("/api/v1/decor/styles?room_type=nope").status_code == 404
    unicorn = Item(1, "ночник Единорог LED", Decimal(1), 0, None, None, None, colors="розовый")
    assert score(unicorn, STYLES["kids"]).score >= 3 and score(unicorn, STYLES["modern"]).score < 0


def test_colour_alone_does_not_make_a_style():
    white_candle = Item(1, "свеча-столбик белая", Decimal(1), 0, None, None, None, colors="белый")
    anchor = Item(2, "подушка декоративная Якорь белая", Decimal(1), 0, None, None, None, colors="белый")
    assert not score(white_candle, STYLES["marine"]).strong
    assert score(anchor, STYLES["marine"]).strong
    lamp = Item(3, "светильник подвесной журнальный напольный", Decimal(1), 0, None, None, None)
    assert not score(lamp, STYLES["marine"]).why  # «льн» inside words is not linen


def test_hitech_vintage_and_new_year():
    def item(name, attrs="", colors=""):
        return Item(1, name, Decimal(1), 0, None, None, None, attrs=attrs, colors=colors)

    chrome = item("люстра LED хром", attrs="хай-тек", colors="хром")
    edison = item("светильник подвесной Эдисон бронза", colors="бронза")
    assert score(chrome, STYLES["hitech"]).strong and score(chrome, STYLES["vintage"]).score < 0
    assert score(edison, STYLES["vintage"]).strong and score(edison, STYLES["hitech"]).score < 0
    assert score(chrome, STYLES["modern"]).score > 0  # hi-tech label does not push it out of modern


def test_new_year_zone_has_kits(client):
    zones = {z["id"]: z for z in client.get("/api/v1/decor/zones?counts=false").json()}
    assert {k["id"] for k in zones["holidays"]["kits"]} == {"tree", "home", "gifts"}
    r = client.post("/api/v1/decor/zones/holidays/kits/tree", json={}).json()
    assert [x["slot"] for x in r["items"]][:2] == ["tree", "balls"]


def test_seasonal_zone_shows_out_of_stock_items_rooms_do_not(client):
    tinsel = client.get("/api/v1/decor/zones/holidays/tinsel").json()
    assert [(x["id"], x["in_stock"]) for x in tinsel] == [(40, False)]
    lamps = client.get("/api/v1/decor/options?style=loft&slot=chandelier").json()
    assert 41 not in {x["id"] for x in lamps}


def test_furniture_option_puts_furniture_first(client):
    plain = client.post("/api/v1/decor", json={"room_type": "living_room", "style": "loft"}).json()
    assert "sofa" not in {x["slot"] for x in plain["items"]}
    r = client.post("/api/v1/decor", json={"room_type": "living_room", "style": "loft", "furniture": True}).json()
    assert r["items"][0]["slot"] == "sofa" and r["items"][0]["furniture"] is True
    assert r["items"][0]["product"]["id"] == 50
    assert not any(x["furniture"] for x in r["items"] if x["slot"] == "chandelier")
    classic = client.post("/api/v1/decor", json={"room_type": "living_room", "style": "classic", "furniture": True}).json()
    assert classic["items"][0]["product"]["id"] == 51
    styles = {x["id"]: x for x in client.get("/api/v1/decor/styles?room_type=living_room&furniture=true").json()}
    assert styles["loft"]["slots_total"] == 18


def test_photo_answer_is_parsed_and_cleaned():
    from app.decor_photo import parse

    r = parse('```json\n{"style": "loft", "objects": [{"slot": "sofa", "name": "диван", "color": "черный", '
              '"material": "рогожка"}, {"slot": "sofa", "name": "диван", "color": "черный", "material": "рогожка"}, '
              '{"slot": "spaceship", "name": "?"}]}\n```')
    assert r.style == "loft" and [o.slot for o in r.objects] == ["sofa"]
    assert parse('{"style": "cyberpunk", "objects": []}').style is None


def test_photo_search_ranks_similar_products_first(client, monkeypatch):
    import base64 as b64

    from app import decor_photo
    from app.decor_photo import PhotoAnalysis, PhotoObject

    async def fake(image, filename, content_type):
        assert image == b"fake-image" and content_type == "image/png"
        return PhotoAnalysis(style="loft", objects=[
            PhotoObject(slot="sofa", name="прямой диван", color="черный", material="рогожка"),
            PhotoObject(slot="chandelier", name="люстра", color="бронза", material="металл"),
        ])

    monkeypatch.setattr(decor_photo, "analyze", fake)
    image = "data:image/png;base64," + b64.b64encode(b"fake-image").decode()
    r = client.post("/api/v1/decor/photo", json={"image": image}).json()
    assert r["style_title"] == "Лофт"
    sofa, lamp = r["objects"]
    assert sofa["product"]["id"] == 50 and [x["id"] for x in sofa["alternatives"]][-1] == 51
    assert "цвет как на фото: черный" in sofa["product"]["why"]
    assert lamp["product"]["id"] == 4  # bronze loft chandelier


def test_photo_search_without_gigachat_key_explains_why(client):
    import base64 as b64

    r = client.post("/api/v1/decor/photo", json={"image": b64.b64encode(b"x").decode()})
    assert r.status_code == 503 and "GigaChat" in r.json()["detail"]
    assert client.post("/api/v1/decor/photo", json={"image": "not base64!"}).status_code == 422


def test_photo_is_uploaded_and_sent_as_attachment(tmp_path, monkeypatch):
    import asyncio
    import json as js

    import httpx

    from app import decor_photo
    from app.config import Settings

    settings = Settings(gigachat_enabled=True, gigachat_credentials="key", gigachat_cache_path=tmp_path / "c.sqlite")
    monkeypatch.setattr(decor_photo, "get_settings", lambda: settings)
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path.endswith("/oauth"):
            return httpx.Response(200, json={"access_token": "t", "expires_at": 9999999999999})
        if request.url.path.endswith("/files"):
            assert b"image-bytes" in request.content and b'name="purpose"' in request.content
            return httpx.Response(200, json={"id": "file-1"})
        if request.url.path.endswith("/chat/completions"):
            body = js.loads(request.content)
            assert body["model"] == "GigaChat-2-Max" and body["messages"][0]["attachments"] == ["file-1"]
            answer = '{"style": "scandi", "objects": [{"slot": "rug", "name": "ковёр", "color": "серый"}]}'
            return httpx.Response(200, json={"choices": [{"message": {"content": answer}}]})
        return httpx.Response(200, json={})

    r = asyncio.run(decor_photo.analyze(b"image-bytes", "room.jpg", "image/jpeg", httpx.MockTransport(handler)))
    assert r.style == "scandi" and r.objects[0].slot == "rug"
    assert calls[-1].endswith("/files/file-1/delete")

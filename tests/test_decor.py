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
    assert set(styles) == set(STYLES)
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

from decimal import Decimal as D

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.catalog.json_catalog import iter_json
from app.catalog.loader import load_catalog
from app.catalog.yml import product_id
from app.db import get_sessionmaker
from app.main import app
from app.models import Category, IngestRun, Product, ProductCharacteristic
from scripts.evaluate_matching import evaluate
from tests.conftest import SAMPLE, SAMPLE_JSON

N_OFFERS = 27


def test_yml_load(ingested):
    assert ingested.offers == N_OFFERS and ingested.categories == 14
    with get_sessionmaker()() as s:
        assert s.scalar(select(func.count()).select_from(Product)) == N_OFFERS
        p = s.get(Product, 96611)
        assert p.result_price == D("1650.00") and p.old_price == D("1800.00")
        assert p.unit == "упак." and p.package_area == D("1.44") and p.quantity_in_package == D("4")
        assert p.categories_tree[-1]["name"] == "Плитка и керамогранит"
        assert s.get(Product, 96627).in_stock is False
        wallpaper = s.get(Product, 96615)
        assert wallpaper.specs["width_m"] == "1.06" and wallpaper.specs["rapport_m"] == "0.64"
        ch = s.get(ProductCharacteristic, (96620, "Длина, мм"))
        assert ch.value_raw == "2500" and ch.value_num == D("2.5") and ch.unit == "m"
        assert s.get(Category, 33).path[0]["name"] == "Отделочные материалы"


def test_yml_partial_and_deactivation(tmp_path, ingested):
    trimmed = tmp_path / "feed.xml"
    text = SAMPLE.read_text(encoding="utf-8")
    start = text.index('  <offer id="96626"')
    end = text.index("</offer>", start) + len("</offer>\n")
    trimmed.write_text(text[:start] + text[end:], encoding="utf-8")
    with get_sessionmaker()() as s:
        stats = load_catalog(s, trimmed)
        assert stats.offers == N_OFFERS - 1 and stats.deactivated == 1
        assert s.get(Product, 96626).status is False
        assert s.scalars(select(IngestRun.status).order_by(IngestRun.id.desc())).first() == "ok"
        load_catalog(s, SAMPLE)
        assert s.get(Product, 96626).status is True


def test_json_load_matches_yml(ingested):
    with get_sessionmaker()() as s:
        before = {p.id: (p.result_price, p.unit, p.package_area, p.specs) for p in s.query(Product)}
        stats = load_catalog(s, SAMPLE_JSON)
        assert stats.format == "json" and stats.offers == N_OFFERS and stats.deactivated == 0
        after = {p.id: (p.result_price, p.unit, p.package_area, p.specs) for p in s.query(Product)}
        assert after == before
        assert s.get(Product, 96627).in_stock is False and s.get(Product, 96611).in_stock is None
        load_catalog(s, SAMPLE)


def test_iter_json_streams_small_chunks(tmp_path):
    f = tmp_path / "c.json"
    f.write_text('{"products": [ {"id": 1, "name": "a [x]", "characteristics": []},\n'
                 '{"id": 2, "name": "b", "categories": {"5": "Кат"}} ]}', encoding="utf-8")
    assert [o["id"] for o in iter_json(f, chunk_size=7)] == [1, 2]


def test_real_format_item():
    from app.catalog.json_catalog import product_rows

    item = {"id": 13, "cod_good": "1001367025", "name": "панель кухонная Камень 244х61см МДФ", "price": 2573,
            "currency": "RUB", "brand": {"id": 961, "name": "NOVITA"}, "categories": {"4106": "Стеновые панели"},
            "unit": "шт.", "characteristics": [
                {"name": "Размер", "value": "2440х610х4"}, {"name": "Длина", "value": "2440"},
                {"name": "Ширина", "value": "610"}, {"name": "Толщина", "value": "3"},
                {"name": "Площадь покрытия упаковкой", "value": "4.9504"},
                {"name": "Количество в упаковке", "value": "8"},
                {"name": "Маркетинговое описание товара", "value": "длинный текст"}]}
    row, chars, links = product_rows(item, {})
    assert row["id"] == 13 and row["unit"] == "шт." and row["result_price"] == D("2573")
    assert row["package_area"] == D("4.9504") and row["quantity_in_package"] == D("8")
    assert row["specs"]["length_m"] == "2.44" and "length_m" in row["specs"]["guessed"]
    assert {c["code"] for c in chars} == {"Размер", "Длина", "Ширина", "Толщина", "Площадь покрытия упаковкой",
                                          "Количество в упаковке"}
    assert links == [{"product_id": 13, "category_id": 4106}]


def test_product_id():
    assert product_id("96611") == 96611
    assert product_id("ABC-1") == product_id("ABC-1") > 0


def test_api_flow(ingested):
    with TestClient(app) as client:
        stats = client.post("/api/v1/admin/autobind").json()
        assert stats["bound_ml"] >= 20 and stats["auto_bound_share"] > 0.7

        tax = client.get("/api/v1/taxonomy").json()
        assert [s["id"] for s in tax["stages"]] == ["preparation_demolition", "rough_work", "white_finish", "finish_work", "final_stage"]
        assert {r["id"] for r in tax["renovation_types"]} == {"cosmetic", "capital", "euro", "rental"}

        rows = client.get("/api/v1/admin/products", params={"only_unbound": False, "q": "Грунтовка"}).json()
        primer = rows[0]["suggestion"]
        assert primer["material"] == "primer" and {"tiling", "wall_painting", "priming"} <= set(primer["work_types"])

        r = client.put("/api/v1/admin/products/96612/binding",
                       json={"material": "tile", "work_types": ["tiling"], "room_types": ["bathroom"],
                             "flags": {"moisture_resistant": True}})
        assert r.status_code == 200 and r.json()["confirmed"] is True

        body = client.post("/api/v1/product/96612/calc", json={"length_m": 2, "width_m": 2.7}).json()
        assert body["packages"] == 4 and body["total_cost"] == 5160.0 and body["material"] == "tile"

        body = client.post("/api/v1/product/96617/calc", json={"length_m": 5, "width_m": 4, "layers": 2}).json()
        assert body["packages"] == 3 and body["required_unit"] == "л"

        assert client.post("/api/v1/product/1/calc", json={"length_m": 1, "width_m": 1}).status_code == 404
        assert client.post("/api/v1/product/96624/calc", json={"length_m": 1, "width_m": 1}).status_code == 422
        assert client.post("/api/v1/estimate", json={"rooms": [{"room_type": "bathroom", "area_m2": 6}]}).status_code == 422

        est = client.post("/api/v1/estimate", json={
            "object_type": "apartment", "renovation_type": "capital",
            "rooms": [{"room_type": "bathroom", "length_m": 2, "width_m": 3, "height_m": 2.5}],
        }).json()
        items = est["rooms"][0]["items"]
        stages = [i["stage"] for i in items]
        assert stages == sorted(stages, key=["preparation_demolition", "rough_work", "white_finish", "finish_work", "final_stage"].index)
        by_mat = {(i["material"], i["surface"]): i for i in items}
        assert by_mat[("drywall", "wall")]["product"]["id"] == 96620
        assert by_mat[("tile", "floor")]["product"]["id"] == 96611 and by_mat[("tile", "wall")]["product"]["id"] == 96612
        assert by_mat[("tile", "floor")]["packages"] > 0 and by_mat[("grout", "floor")]["packages"] > 0
        assert by_mat[("waterproofing", "floor")]["product"]["id"] == 96632
        assert est["total"] > 0

        rental = client.post("/api/v1/estimate", json={
            "renovation_type": "rental", "rooms": [{"room_type": "living_room", "length_m": 4, "width_m": 3}],
        }).json()
        assert {i["work_type"] for i in rental["rooms"][0]["items"]} == {"wall_painting", "floor_covering_install"}
        assert "linoleum" in {i["material"] for i in rental["rooms"][0]["items"]}

        card = client.get("/api/v1/products/96615").json()
        assert card["characteristics"] and card["specs"]["length_m"] == "10"

        health = client.get("/health").json()
        assert health["db"]["ok"] is True and health["llm"]["ok"] is False


def test_evaluate_matching(ingested):
    import json

    gold = [json.loads(line) for line in open(SAMPLE.parent / "sample_gold.jsonl", encoding="utf-8")]
    res = evaluate(gold)
    assert res["items"] == N_OFFERS
    assert 0 < res["macro_f1"] <= res["micro_f1"] <= 1


def test_step_by_step(ingested):
    from app.plans import DEFAULTS, OPTIONS
    from app.taxonomy import WorkType

    assert len(WorkType) == 20
    for (_, group), works in DEFAULTS.items():
        assert set(works) <= set(OPTIONS[group])

    with TestClient(app) as client:
        rooms = {r["id"] for r in client.get("/api/v1/taxonomy").json()["room_types"]}
        assert rooms == {"kitchen", "dining_room", "living_room", "bedroom", "bathroom", "hallway", "home_office",
                         "utility_room", "balcony", "general_indoor"}

        opts = client.get("/api/v1/works", params={"room_type": "bedroom", "renovation_type": "cosmetic"}).json()
        works = [w for st in opts["stages"] for w in st["works"]]
        titles = {w["title"] for w in works}
        assert {"Окраска стен и потолков — стены", "Окраска стен и потолков — потолок", "Оклейка обоями",
                "Укладка напольных покрытий — ламинат", "Укладка напольных покрытий — линолеум"} <= titles
        assert "Демонтаж" not in titles and "Монтаж гипсокартона" not in titles
        assert {w["work_type"] for w in works if w["default"]} == {"priming", "wallpapering"}

        bath = client.get("/api/v1/works", params={"room_type": "bathroom", "renovation_type": "capital"}).json()
        assert [st["stage"] for st in bath["stages"]] == ["preparation_demolition", "rough_work", "white_finish",
                                                          "finish_work", "final_stage"]
        tiles = [w for st in bath["stages"] for w in st["works"] if w["work_type"] == "tiling"]
        assert {w["surface"] for w in tiles} == {"floor", "wall"}
        assert {"ventilation_install", "plumbing_fixture_install"} <= {w["work_type"] for st in bath["stages"]
                                                                       for w in st["works"]}
        assert client.get("/api/v1/works", params={"room_type": "toilet", "renovation_type": "cosmetic"}).status_code == 422

        est = client.post("/api/v1/estimate", json={"rooms": [{
            "room_type": "bedroom", "renovation_type": "cosmetic", "length_m": 4, "width_m": 3,
            "works": [{"work_type": "wall_painting", "surface": "ceiling"},
                      {"work_type": "floor_covering_install", "materials": ["linoleum"]}, "lighting_install"],
        }]}).json()
        items = est["rooms"][0]["items"]
        assert {i["work_type"] for i in items} == {"wall_painting", "floor_covering_install", "lighting_install"}
        mats = {(i["material"], i["surface"]) for i in items}
        assert ("paint", "ceiling") in mats and ("linoleum", "floor") in mats and ("laminate", "floor") not in mats

        plain = client.post("/api/v1/estimate", json={"rooms": [{
            "room_type": "bedroom", "renovation_type": "cosmetic", "length_m": 4, "width_m": 3,
            "works": ["floor_covering_install"]}]}).json()["rooms"][0]["items"]
        assert {i["material"] for i in plain} == {"laminate", "underlay", "skirting", "fasteners"}

        demo = client.post("/api/v1/estimate", json={"rooms": [{
            "room_type": "kitchen", "renovation_type": "capital", "length_m": 3, "width_m": 3,
            "works": [{"work_type": "demolition", "materials": []}, "electrical_wiring"]}]})
        assert demo.status_code == 200
        assert {i["work_type"] for i in demo.json()["rooms"][0]["items"]} == {"electrical_wiring"}




def test_admin_manual_product_and_status_filter(ingested):
    from app.catalog.repository import MANUAL_ID_START

    with TestClient(app) as client:
        created = client.post("/api/v1/admin/products", json={
            "name": "Краска интерьерная моющаяся тестовая 2,5л", "price": 999, "unit": "шт",
            "characteristics": [{"name": "Расход материала", "value": "0,12"}],
        })
        assert created.status_code == 201
        row = created.json()
        pid = row["product"]["id"]
        assert pid >= MANUAL_ID_START and row["manual"] and row["binding"] is None
        assert row["suggestion"]["material"] == "paint"

        unbound = client.get("/api/v1/admin/products", params={"status": "unbound"}).json()
        assert pid in {r["product"]["id"] for r in unbound}

        s = row["suggestion"]
        client.put(f"/api/v1/admin/products/{pid}/binding", json={
            "material": s["material"], "work_types": s["work_types"], "room_types": s["room_types"], "flags": s["flags"]})
        confirmed = client.get("/api/v1/admin/products", params={"status": "confirmed"}).json()
        assert pid in {r["product"]["id"] for r in confirmed}
        assert pid not in {r["product"]["id"] for r in client.get("/api/v1/admin/products", params={"status": "ml"}).json()}

        card = client.get(f"/api/v1/products/{pid}").json()
        assert card["specs"]["volume_l"] == "2.5" and card["specs"]["consumption"]["unit"] == "l/m2"

        with get_sessionmaker()() as s2:
            load_catalog(s2, SAMPLE)
        assert client.get(f"/api/v1/products/{pid}").json()["name"].startswith("Краска")
        assert pid in {r["product"]["id"] for r in client.get("/api/v1/admin/products", params={"status": "confirmed"}).json()}

        assert client.delete("/api/v1/admin/products/96611").status_code == 404
        assert client.delete(f"/api/v1/admin/products/{pid}").status_code == 204
        assert client.get(f"/api/v1/products/{pid}").status_code == 404
        assert client.post("/api/v1/admin/products", json={"name": "x", "price": 0}).status_code == 422

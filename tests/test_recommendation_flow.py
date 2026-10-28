from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api import routes
from app.api.deps import get_repo
from app.catalog.loader import load_catalog
from app.catalog.repository import CatalogRepo
from app.db import Base
from app.main import app
from app.ml.baseline import KeywordClassifier


SAMPLE = Path(__file__).resolve().parents[1] / "mock_catalog" / "sample_catalog.json"


def test_real_estimate_recommendation_matches_catalog_product_and_alternatives(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'recommendations.sqlite'}",
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    load_catalog(session, SAMPLE)
    repo = CatalogRepo(session)
    monkeypatch.setattr(routes, "get_classifier", lambda: KeywordClassifier())
    app.dependency_overrides[get_repo] = lambda: repo
    try:
        with TestClient(app) as client:
            bound = client.post("/api/v1/admin/autobind", params={"use_gigachat": False})
            assert bound.status_code == 200 and bound.json()["bound_ml"] > 0
            response = client.post("/api/v1/estimate", json={"explain": False, "rooms": [{
                "room_type": "bathroom", "length_m": 2, "width_m": 3, "height_m": 2.5,
                "works": [{"work_type": "tiling", "surface": "wall",
                           "materials": ["tile", "tile_adhesive"]}],
            }]})
            changed = client.post("/api/v1/estimate", json={"explain": False, "rooms": [{
                "room_type": "bathroom", "length_m": 2, "width_m": 4, "height_m": 2.5,
                "works": [{"work_type": "tiling", "surface": "wall", "materials": ["tile"]}],
            }]})
        assert response.status_code == 200
        items = response.json()["rooms"][0]["items"]
        assert len([item for item in items if item["product"]]) == 2
        item = next(item for item in items if item["material"] == "tile")
        stored = repo.get(item["product"]["id"])
        assert stored is not None
        assert item["product"]["name"] == stored.name
        assert item["product"]["result_price"] == float(stored.result_price)
        assert item["packages"] > 0 and item["cost"] == item["packages"] * item["unit_price"]
        assert item["why"] and all(isinstance(reason, str) for reason in item["why"])
        evidence = item["recommendation_evidence"]
        assert evidence["product_id"] == item["product"]["id"]
        assert evidence["work_type"] == "tiling" and evidence["material"] == "tile"
        assert item["recommendation_explanation"].startswith("Материал «Плитка, керамогранит» нужен для работы")
        assert "фасов" not in item["recommendation_explanation"].lower()
        assert "луч" not in item["recommendation_explanation"].lower()
        assert item["alternatives"]
        assert all(alt["id"] != item["product"]["id"] for alt in item["alternatives"])
        assert all(repo.get(alt["id"]).name == alt["name"] for alt in item["alternatives"])
        changed_item = changed.json()["rooms"][0]["items"][0]
        assert changed_item["required_amount"] != item["required_amount"]
        assert changed_item["packages"] != item["packages"]

        with TestClient(app) as client:
            picked = client.post("/api/v1/estimate", json={"explain": False, "rooms": [{
                "room_type": "bathroom", "length_m": 2, "width_m": 3, "height_m": 2.5,
                "picks": [item["product"]["id"]],
                "works": [{"work_type": "tiling", "surface": "wall", "materials": ["tile"]}],
            }]}).json()["rooms"][0]["items"][0]
        assert any(fact["code"] == "user_pick" for fact in picked["recommendation_evidence"]["facts"])
        assert "пользовательский выбор" in picked["recommendation_explanation"]
        assert "лучше альтернатив" in picked["recommendation_explanation"]
    finally:
        app.dependency_overrides.pop(get_repo, None)
        session.close()
        engine.dispose()

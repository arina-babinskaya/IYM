from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.deps import get_repo
from app.catalog.repository import CatalogRepo
from app.db import Base
from app.main import app
from app.models import Product, ProductBinding
from app.taxonomy import Material, WorkType


def _repo(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'estimate.sqlite'}",
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    return engine, session, CatalogRepo(session)


def test_no_bindings_returns_explicit_unavailable_estimate(tmp_path):
    engine, session, repo = _repo(tmp_path)
    session.add(Product(id=1, name="Краска без привязки", status=True, in_stock=True,
                        result_price=Decimal("100"), package_area=Decimal("5")))
    session.commit()
    app.dependency_overrides[get_repo] = lambda: repo
    try:
        with TestClient(app) as client:
            response = client.post("/api/v1/estimate", json={"explain": False, "rooms": [{
                "room_type": "bedroom", "length_m": 4, "width_m": 3,
                "works": [{"work_type": "wall_painting", "surface": "wall", "materials": ["paint"]}],
            }]})
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "unavailable" and body["total"] == 0
        assert body["priced_items"] == 0 and body["missing_items"] == 1
        assert body["rooms"][0]["items"][0]["product"] is None
        assert any("Смета не рассчитана" in warning for warning in body["warnings"])
    finally:
        app.dependency_overrides.pop(get_repo, None)
        session.close()
        engine.dispose()


def test_bound_real_product_produces_serialized_nonzero_total(tmp_path):
    engine, session, repo = _repo(tmp_path)
    session.add(Product(id=2, name="Краска интерьерная", status=True, in_stock=True,
                        result_price=Decimal("100"), package_area=Decimal("5"), unit="шт."))
    session.add(ProductBinding(product_id=2, product_category="paint", material="paint",
        work_types=["wall_painting"], room_types=[], flags={}, source="ml", confidence=.9, confirmed=False))
    session.commit()
    app.dependency_overrides[get_repo] = lambda: repo
    try:
        with TestClient(app) as client:
            body = client.post("/api/v1/estimate", json={"explain": False, "rooms": [{
                "room_type": "bedroom", "length_m": 4, "width_m": 3,
                "works": [{"work_type": "wall_painting", "surface": "wall", "materials": ["paint"]}],
            }]}).json()
        item = body["rooms"][0]["items"][0]
        assert body["status"] == "complete" and body["total"] == 1600
        assert body["priced_items"] == 1 and body["missing_items"] == 0
        assert item["product"]["id"] == 2 and item["packages"] == 16
        assert item["unit_price"] == 100 and item["cost"] == 1600
    finally:
        app.dependency_overrides.pop(get_repo, None)
        session.close()
        engine.dispose()


def test_confirmed_legacy_material_binding_is_compatible_but_automatic_category_only_is_not(tmp_path):
    engine, session, repo = _repo(tmp_path)
    for pid in (10, 11, 12):
        session.add(Product(id=pid, name=f"Краска {pid}", status=True, in_stock=True,
                            result_price=Decimal("100"), package_area=Decimal("5")))
    session.add_all([
        ProductBinding(product_id=10, material="paint", work_types=[], room_types=[], flags={},
                       source="manual", confidence=None, confirmed=True),
        ProductBinding(product_id=11, material="paint", work_types=[], room_types=[], flags={},
                       source="ml", confidence=.9, confirmed=False),
        ProductBinding(product_id=12, material="paint", work_types=["wall_painting"], room_types=[], flags={},
                       source="ml", confidence=.9, confirmed=False),
    ])
    session.commit()
    rows = repo.candidates(Material.paint, WorkType.wall_painting, min_confidence=.7)
    assert {product.id for product, _ in rows} == {10, 12}
    session.close()
    engine.dispose()


def test_material_only_bindings_fill_an_otherwise_empty_work(tmp_path):
    engine, session, repo = _repo(tmp_path)
    for pid in (20, 21, 22):
        session.add(Product(id=pid, name=f"Саморез {pid}", status=True, in_stock=True, result_price=Decimal("50")))
    session.add_all([
        ProductBinding(product_id=20, material="fasteners", work_types=[], room_types=[], flags={},
                       source="ml", confidence=.9, confirmed=False),
        ProductBinding(product_id=21, material="fasteners", work_types=["plumbing_rough"], room_types=[], flags={},
                       source="ml", confidence=.9, confirmed=False),
    ])
    session.commit()
    assert {p.id for p, _ in repo.candidates(Material.fasteners, WorkType.drywall_install, min_confidence=.7)} == {20}
    assert {p.id for p, _ in repo.candidates(Material.fasteners, WorkType.plumbing_rough, min_confidence=.7)} == {21}
    session.close()
    engine.dispose()

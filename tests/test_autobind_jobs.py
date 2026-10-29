import time

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api import routes
from app.catalog.loader import load_catalog
from app.catalog.repository import CatalogRepo
from app.config import Settings
from app.db import Base
from app.main import app
from app.ml.baseline import KeywordClassifier
from app.models import Product, ProductBinding
from app.schemas import Suggestion
from app.taxonomy import Material, ProductCategory, WorkType
from tests.conftest import SAMPLE


def _wait(client: TestClient, timeout: float = 5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = client.get("/api/v1/admin/autobind/status")
        assert result.status_code == 200
        body = result.json()
        if body["status"] != "running":
            return body
        time.sleep(.01)
    raise AssertionError("autobind job did not finish")


def _isolated_sessionmaker(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'autobind.sqlite'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions() as session:
        load_catalog(session, SAMPLE)
    return engine, sessions


def _reset_job_state():
    routes._autobind_task = None
    routes._autobind_job = None
    routes._job_started.clear()


def test_background_autobind_reports_progress_and_reuses_active_job(tmp_path, monkeypatch):
    engine, sessions = _isolated_sessionmaker(tmp_path)

    class SlowClassifier(KeywordClassifier):
        def predict(self, products):
            time.sleep(.08)
            return super().predict(products)

    _reset_job_state()
    monkeypatch.setattr(routes, "get_sessionmaker", lambda: sessions)
    monkeypatch.setattr(routes, "get_classifier", lambda: SlowClassifier())
    monkeypatch.setattr(routes, "get_settings", lambda: Settings(gigachat_enabled=False))
    try:
        with TestClient(app) as client:
            first = client.post("/api/v1/admin/autobind?background=true&batch=5&use_gigachat=false")
            second = client.post("/api/v1/admin/autobind?background=true&batch=5&use_gigachat=false")
            assert first.status_code == second.status_code == 202
            assert first.json()["id"] == second.json()["id"]

            done = _wait(client)
            assert done["status"] == "completed"
            assert done["processed"] == 27
            assert done["batches"] == 6
            assert done["bound"] == done["stats"]["bound_ml"]
            assert done["candidates"] == done["bound"]
            assert done["rejected"] == done["processed"] - done["candidates"]
            assert sum(done["rejection_reasons"].values()) == done["rejected"]
            assert done["classifier_ms"] >= 400
    finally:
        _reset_job_state()
        engine.dispose()


def test_background_autobind_surfaces_classifier_failure(tmp_path, monkeypatch):
    engine, sessions = _isolated_sessionmaker(tmp_path)

    class BrokenClassifier:
        def predict(self, products):
            raise RuntimeError("fixture classifier failed")

    _reset_job_state()
    monkeypatch.setattr(routes, "get_sessionmaker", lambda: sessions)
    monkeypatch.setattr(routes, "get_classifier", lambda: BrokenClassifier())
    monkeypatch.setattr(routes, "get_settings", lambda: Settings(gigachat_enabled=False))
    try:
        with TestClient(app) as client:
            started = client.post("/api/v1/admin/autobind?background=true&use_gigachat=false")
            assert started.status_code == 202
            failed = _wait(client)
            assert failed["status"] == "failed"
            assert failed["phase"] == "failed"
            assert "fixture classifier failed" in failed["error"]
            assert failed["stats"] is None
    finally:
        _reset_job_state()
        engine.dispose()


def test_renovation_autobind_is_not_exposed_as_the_admin_ml_button():
    with TestClient(app) as client:
        html = client.get("/").text
    assert "/api/v1/admin/catalog/categorize" in html
    assert "/api/v1/admin/catalog/categorize/status" in html
    assert "/api/v1/admin/autobind?" not in html
    assert "job.status !== \"completed\"" in html
    assert "Каталог уже категоризирован" in html
    assert "await loadAdmin()" in html


def test_binding_persistence_rejections_stats_and_repeat_are_accurate(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'controlled.sqlite'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions() as session:
        session.add_all([
            Product(id=1, name="Краска интерьерная"),
            Product(id=2, name="Семена моркови"),
            Product(id=3, name="Грунтовка с неясной карточкой"),
        ])
        session.commit()

    class ControlledClassifier:
        def predict(self, products):
            output = []
            for product in products:
                if product.id == 1:
                    output.append(Suggestion(product_category=ProductCategory.paint, material=Material.paint,
                        work_types=[WorkType.wall_painting], confidence=.91,
                        flags={"domain_renovation": True}, model="controlled-renovation"))
                elif product.id == 2:
                    output.append(Suggestion(material=Material.other, confidence=.99,
                        flags={"domain_non_renovation": True}, model="controlled-renovation"))
                else:
                    output.append(Suggestion(product_category=ProductCategory.primer, material=Material.primer,
                        work_types=[WorkType.priming], confidence=.69,
                        flags={"domain_renovation": True}, model="controlled-renovation"))
            return output

    _reset_job_state()
    monkeypatch.setattr(routes, "get_sessionmaker", lambda: sessions)
    monkeypatch.setattr(routes, "get_classifier", lambda: ControlledClassifier())
    monkeypatch.setattr(routes, "get_catalog_matching_classifier",
                        lambda: (_ for _ in ()).throw(AssertionError("catalog matcher must stay independent")))
    monkeypatch.setattr(routes, "get_settings", lambda: Settings(gigachat_enabled=False, autobind_min_confidence=.7))
    try:
        with TestClient(app) as client:
            assert client.post("/api/v1/admin/autobind?background=true&use_gigachat=false").status_code == 202
            first = _wait(client)
            assert first["status"] == "completed"
            assert first["processed"] == 3 and first["candidates"] == 1 and first["bound"] == 1
            assert first["rejected"] == first["skipped"] == 2
            assert first["rejection_reasons"] == {
                "outside_renovation_domain": 1, "below_confidence_threshold": 1,
            }
            assert first["persistence_conflicts"] == 0
            assert first["stats"]["bound_ml"] == 1 and first["stats"]["unbound"] == 2

            assert client.post("/api/v1/admin/autobind?background=true&use_gigachat=false").status_code == 202
            second = _wait(client)
            assert second["processed"] == 2 and second["candidates"] == second["bound"] == 0
            assert second["rejected"] == 2 and second["stats"]["bound_ml"] == 1

        with sessions() as session:
            binding = session.get(ProductBinding, 1)
            assert binding.material == "paint" and binding.work_types == ["wall_painting"]
            assert binding.confidence == .91 and binding.source == "ml" and binding.confirmed is False
            assert session.get(ProductBinding, 2) is None
            assert session.get(ProductBinding, 3) is None
            duplicate = Suggestion(product_category=ProductCategory.tile, material=Material.tile,
                                   work_types=[WorkType.tiling], confidence=.99,
                                   flags={"domain_renovation": True})
            assert CatalogRepo(session).save_ml_bindings([(1, duplicate)]) == 0
            session.refresh(binding)
            assert binding.material == "paint" and binding.confidence == .91
    finally:
        _reset_job_state()
        engine.dispose()


def test_malformed_classifier_batch_fails_with_clear_error(tmp_path, monkeypatch):
    engine, sessions = _isolated_sessionmaker(tmp_path)

    class ShortClassifier:
        def predict(self, products):
            return []

    _reset_job_state()
    monkeypatch.setattr(routes, "get_sessionmaker", lambda: sessions)
    monkeypatch.setattr(routes, "get_classifier", lambda: ShortClassifier())
    monkeypatch.setattr(routes, "get_settings", lambda: Settings(gigachat_enabled=False))
    try:
        with TestClient(app) as client:
            client.post("/api/v1/admin/autobind?background=true&use_gigachat=false")
            failed = _wait(client)
            assert failed["status"] == "failed"
            assert "classifier returned 0 validatable outputs for 27 products" in failed["error"]
            assert failed["bound"] == 0 and failed["stats"] is None
    finally:
        _reset_job_state()
        engine.dispose()

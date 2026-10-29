import time

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.api import catalog_admin, routes
from app.catalog.matching_repository import CatalogMatchingRepo
from app.catalog.repository import CatalogRepo
from app.db import Base
from app.main import app
from app.ml.catalog_matching import CatalogMatchResult
from app.models import CatalogCategoryAssignment, Product, ProductBinding
from app.taxonomy import Material, WorkType
from ml_workspace.catalog_matching.inference.predictor import Alternative, CategoryPrediction


def _result(product, category_id, category_name, score, *, review=False):
    prediction = CategoryPrediction(
        category_id=category_id,
        category_name=category_name,
        confidence=score,
        alternatives=(
            Alternative("home.household", "Хозяйственные товары", .03),
            Alternative("review.unresolved", "Требует классификации", .01),
        ),
        model="fixture-catalog-tfidf",
        needs_review=review,
    )
    return CatalogMatchResult(product.id, prediction, "catalog-taxonomy-v2", "/fixture/artifact")


class FixtureCatalogClassifier:
    def predict_batch(self, products, top_k=3):
        return [self.predict_one(product, top_k) for product in products]

    def predict_one(self, product, top_k=3):
        if product.name == "Семена моркови":
            return _result(product, "garden.seeds", "Семена и посадочный материал", .96)
        if product.name == "Ножницы для живой изгороди":
            return _result(product, "garden.tools", "Садовый инструмент", .94)
        if product.name == "Неясный предмет":
            return _result(product, "home.household", "Хозяйственные товары", .12, review=True)
        if not product.name.strip():
            raise ValueError("empty fixture product name")
        return _result(product, "finishing.paint", "Краски", .91)


def _wait(client, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = client.get("/api/v1/admin/catalog/categorize/status").json()
        if body["status"] != "running":
            return body
        time.sleep(.01)
    raise AssertionError("catalog categorization did not finish")


def _reset():
    catalog_admin._catalog_task = None
    catalog_admin._catalog_job = None
    catalog_admin._catalog_started.clear()


def _database(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'catalog-admin.sqlite'}",
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions() as session:
        session.add_all([
            Product(id=1, name="Семена моркови", status=True),
            Product(id=2, name="Ножницы для живой изгороди", status=True),
            Product(id=3, name="Краска интерьерная", status=True, result_price=100),
            Product(id=4, name="Неясный предмет", status=True),
            Product(id=5, name="", status=True),
        ])
        # Ranking state must remain byte-for-byte independent of catalog assignments.
        session.add(ProductBinding(product_id=3, product_category="paint", material="paint",
            work_types=["wall_painting"], room_types=[], flags={"domain_renovation": True},
            source="ml", confidence=.91, confirmed=False))
        session.commit()
    return engine, sessions


def test_catalog_taxonomy_api_exposes_90_trainable_categories():
    with TestClient(app) as client:
        body = client.get("/api/v1/admin/catalog/taxonomy").json()
    assert body["version"] == "catalog-taxonomy-v2"
    assert body["category_count"] == len(body["categories"]) == 90
    assert "garden.seeds" in {item["id"] for item in body["categories"]}
    assert "review.unresolved" not in {item["id"] for item in body["categories"]}
    assert all(item["parent_name"] and item["definition"] for item in body["categories"])


def test_bulk_catalog_workflow_review_manual_precedence_filters_and_ranking_isolation(tmp_path, monkeypatch):
    engine, sessions = _database(tmp_path)

    def repo_override():
        with sessions() as session:
            yield CatalogMatchingRepo(session)

    _reset()
    monkeypatch.setattr(catalog_admin, "get_sessionmaker", lambda: sessions)
    monkeypatch.setattr(catalog_admin, "get_catalog_matching_classifier", lambda: FixtureCatalogClassifier())
    monkeypatch.setattr(routes, "get_classifier",
                        lambda: (_ for _ in ()).throw(AssertionError("renovation classifier must not run")))
    app.dependency_overrides[catalog_admin.get_catalog_repo] = repo_override
    try:
        with sessions() as session:
            binding_before = session.get(ProductBinding, 3)
            binding_state = (binding_before.material, list(binding_before.work_types), binding_before.confidence)
            ranking_candidates_before = [
                product.id for product, _ in CatalogRepo(session).candidates(
                    Material.paint, WorkType.wall_painting, min_confidence=.7
                )
            ]

        with TestClient(app) as client:
            first_start = client.post("/api/v1/admin/catalog/categorize?batch=2")
            assert first_start.status_code == 202
            first = _wait(client)
            assert first["status"] == "completed"
            assert first["total"] == first["processed"] == 5
            assert first["categorized"] == first["inserted"] == 4
            assert first["errors"] == 1 and first["needs_review"] == 1
            assert first["stats"] == {
                "products_total": 5, "assigned": 4, "model_suggestions": 4,
                "manual_confirmed": 0, "needs_review": 1, "unassigned": 1, "coverage": .8,
            }

            seeds = client.get("/api/v1/admin/catalog/products", params={"q": "1"}).json()
            assert len(seeds) == 1 and seeds[0]["assignment"]["category_id"] == "garden.seeds"
            assert len(seeds[0]["assignment"]["top_3"]) == 3
            review = client.get("/api/v1/admin/catalog/products",
                                params={"assignment_status": "review"}).json()
            assert [row["product"]["id"] for row in review] == [4]
            garden = client.get("/api/v1/admin/catalog/products",
                                params={"category_id": "garden.tools"}).json()
            assert [row["product"]["id"] for row in garden] == [2]

            confirmed = client.put("/api/v1/admin/catalog/products/1/category",
                                   json={"category_id": "garden.seeds"}).json()
            corrected = client.put("/api/v1/admin/catalog/products/2/category",
                                   json={"category_id": "tools.hand"}).json()
            assert confirmed["status"] == "confirmed" and confirmed["source"] == "manual"
            assert corrected["status"] == "corrected" and corrected["source"] == "manual"

            client.post("/api/v1/admin/catalog/categorize?batch=5")
            second = _wait(client)
            assert second["inserted"] == second["updated"] == 0
            assert second["manual_preserved"] == 2
            assert second["processed"] == second["total"] == 5
            assert second["unchanged"] == 4 and second["errors"] == 1
            stats = client.get("/api/v1/admin/catalog/stats").json()
            assert stats["assigned"] == 4 and stats["manual_confirmed"] == 2
            assert stats["model_suggestions"] == 2 and stats["unassigned"] == 1

        with sessions() as session:
            assert session.scalar(select(func.count()).select_from(CatalogCategoryAssignment)) == 4
            assert session.get(CatalogCategoryAssignment, 1).category_id == "garden.seeds"
            assert session.get(CatalogCategoryAssignment, 2).category_id == "tools.hand"
            binding_after = session.get(ProductBinding, 3)
            assert (binding_after.material, binding_after.work_types, binding_after.confidence) == binding_state
            assert session.scalar(select(func.count()).select_from(ProductBinding)) == 1
            ranking_candidates_after = [
                product.id for product, _ in CatalogRepo(session).candidates(
                    Material.paint, WorkType.wall_painting, min_confidence=.7
                )
            ]
            assert ranking_candidates_after == ranking_candidates_before == [3]
    finally:
        app.dependency_overrides.pop(catalog_admin.get_catalog_repo, None)
        _reset()
        engine.dispose()


def test_catalog_job_reuses_active_job_and_surfaces_artifact_failure(tmp_path, monkeypatch):
    engine, sessions = _database(tmp_path)

    class SlowClassifier(FixtureCatalogClassifier):
        def predict_batch(self, products, top_k=3):
            time.sleep(.08)
            return super().predict_batch(products, top_k)

    _reset()
    monkeypatch.setattr(catalog_admin, "get_sessionmaker", lambda: sessions)
    monkeypatch.setattr(catalog_admin, "get_catalog_matching_classifier", lambda: SlowClassifier())
    try:
        with TestClient(app) as client:
            first = client.post("/api/v1/admin/catalog/categorize?batch=1")
            second = client.post("/api/v1/admin/catalog/categorize?batch=1")
            assert first.json()["id"] == second.json()["id"]
            assert _wait(client)["status"] == "completed"

        _reset()
        monkeypatch.setattr(catalog_admin, "get_catalog_matching_classifier",
                            lambda: (_ for _ in ()).throw(RuntimeError("artifact unavailable")))
        with TestClient(app) as client:
            client.post("/api/v1/admin/catalog/categorize")
            failed = _wait(client)
            assert failed["status"] == "failed"
            assert "artifact unavailable" in failed["error"]
    finally:
        _reset()
        engine.dispose()


def test_admin_frontend_restores_single_original_ml_workflow():
    with TestClient(app) as client:
        html = client.get("/").text
    assert html.count('id="autobind"') == 1
    assert "Привязать (ML)" in html
    assert "/api/v1/admin/catalog/categorize" in html
    assert "/api/v1/admin/catalog/taxonomy" in html
    assert 'let adminStatus = "ml"' in html
    assert "Категории каталога (90)" not in html
    assert "Привязать к ремонтным работам" not in html
    assert 'id="admin-system"' not in html and 'id="catalog-categorize"' not in html
    assert "/api/v1/admin/autobind?" not in html

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_catalog_matching_classifier
from app.config import get_settings
from app.db import get_sessionmaker
from app.main import app
from app.models import ProductBinding


def test_catalog_match_api_is_read_only_and_uses_isolated_contract(ingested):
    if not get_settings().catalog_matching_artifact_path.exists():
        pytest.skip("catalog_matching model is not in the repository (ml_workspace/catalog_matching/data is gitignored)")
    get_catalog_matching_classifier.cache_clear()
    with get_sessionmaker()() as session:
        before = session.get(ProductBinding, 96617)
        before_state = None if before is None else before.__dict__.copy()
    try:
        with TestClient(app) as client:
            response = client.get("/api/v1/admin/products/96617/catalog-match")
        assert response.status_code == 200
        assert set(response.json()) == {
            "product_id", "category_id", "category_name", "score", "top_3",
            "review_recommended", "score_type", "model", "taxonomy_version",
        }
        with get_sessionmaker()() as session:
            after = session.get(ProductBinding, 96617)
            after_state = None if after is None else after.__dict__.copy()
        for state in (before_state, after_state):
            if state is not None:
                state.pop("_sa_instance_state", None)
        assert after_state == before_state
    finally:
        get_catalog_matching_classifier.cache_clear()

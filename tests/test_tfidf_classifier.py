import json
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_classifier
from app.config import get_settings
from app.db import get_sessionmaker
from app.main import app
from app.ml.tfidf import ClassifierArtifactError, TfidfClassifier, prediction_to_suggestion, product_to_input
from app.models import Product
from ml_workspace.ml_api import ProductInput, load_model, predict
from ml_workspace.ml_api.types import Prediction


ARTIFACT = Path(__file__).parents[1] / "ml_workspace/model/tfidf_logreg/model"


@pytest.fixture(scope="module")
def model():
    if not ARTIFACT.is_dir():
        pytest.skip("downloaded TF-IDF artifact is unavailable")
    return load_model(ARTIFACT, "taxonomy_v2", trusted=True)


def test_artifact_load_single_batch_optional_and_multilabel(model):
    products = [
        ProductInput(1, "Кабель ВВГнг 3x2.5", "Кабели и провода", "Электротовары",
                     description="Силовой кабель для электропроводки"),
        ProductInput(2, "Корм для кошек", "Товары для животных"),
        ProductInput(
            7254, "шпатлевка полимерная для внутр.работ КРЕПС KР 20кг",
            "Шпатлевки сухие полимерные", '["Шпатлевки сухие полимерные"]',
            "Основа смеси: полимерная\nПрименение: для внутренних работ",
            "Для выравнивания стен, гипсовых штукатурок и заделки стыков гипсокартонных листов.",
            {"применение": ["для внутренних работ"]}, 988.0, "шт.", "КРЕПС",
        ),
    ]
    result = predict(model, products)
    assert len(result) == 3
    assert isinstance(result[0].work_types, list)
    assert result[1].status == "non_renovation"
    assert result[2].work_types == ["drywall_install", "wall_putty"]
    assert all(result[2].scores[label] >= model.thresholds[label] for label in result[2].work_types)
    # Prediction remains JSON-serializable without reducing labels to one value.
    encoded = json.dumps(result[2].__dict__)
    assert json.loads(encoded)["work_types"] == result[2].work_types
    assert predict(model, products[0]).work_types == result[0].work_types


def test_product_conversion_handles_missing_fields():
    item = product_to_input(Product(id=10, name="Неизвестный товар"))
    assert item.name == "Неизвестный товар" and item.description == ""
    assert item.characteristics == {} and item.price is None


def test_adapter_batch_and_backend_schema(model):
    classifier = TfidfClassifier(ARTIFACT)
    products = [
        Product(id=1, name="Ламинат дуб 8 мм", categories={"0": "Напольные покрытия", "1": "Ламинат"}),
        Product(id=2, name="Смеситель для ванной", categories={"2": "Сантехника"}, description="для раковины"),
    ]
    suggestions = classifier.predict(products)
    assert len(suggestions) == 2
    assert suggestions[0].material.value == "laminate"
    assert isinstance(suggestions[0].work_types, list)
    assert all(item.model == classifier.name for item in suggestions)
    assert all(0 <= item.confidence <= 1 for item in suggestions)
    assert all(item.model_dump(mode="json") for item in suggestions)


def test_unsupported_labels_are_explicit_not_silently_dropped():
    raw = Prediction(1, ["lighting_install"], {"lighting_install": 0.91}, "predicted",
                     work_types=["lighting_install"])
    suggestion = prediction_to_suggestion(raw, Product(id=1, name="Светильник"))
    assert suggestion.work_types == []
    assert suggestion.flags["unsupported_work_type__lighting_install"] is True


def test_invalid_artifact_path_has_meaningful_error(tmp_path):
    with pytest.raises(ClassifierArtifactError, match="missing"):
        TfidfClassifier(tmp_path / "missing")


def test_trained_is_default_and_cached(monkeypatch):
    if not ARTIFACT.is_dir():
        pytest.skip("local selected v3 artifact is unavailable")
    monkeypatch.delenv("RC_ML_CLASSIFIER_BACKEND", raising=False)
    monkeypatch.delenv("RC_ML_CLASSIFIER_ARTIFACT_PATH", raising=False)
    get_classifier.cache_clear(); get_settings.cache_clear()
    try:
        first = get_classifier()
        assert isinstance(first, TfidfClassifier)
        assert get_classifier() is first
    finally:
        get_classifier.cache_clear(); get_settings.cache_clear()


def test_trained_backend_name_loads_selected_v3_artifact(monkeypatch):
    if not ARTIFACT.is_dir():
        pytest.skip("local selected v3 artifact is unavailable")
    monkeypatch.setenv("RC_ML_CLASSIFIER_BACKEND", "trained")
    monkeypatch.setenv("RC_ML_CLASSIFIER_ARTIFACT_PATH", str(ARTIFACT))
    get_classifier.cache_clear(); get_settings.cache_clear()
    try:
        classifier = get_classifier()
        assert isinstance(classifier, TfidfClassifier)
        assert get_classifier() is classifier
    finally:
        monkeypatch.delenv("RC_ML_CLASSIFIER_BACKEND", raising=False)
        monkeypatch.delenv("RC_ML_CLASSIFIER_ARTIFACT_PATH", raising=False)
        get_classifier.cache_clear(); get_settings.cache_clear()


def test_real_admin_endpoint_with_tfidf(monkeypatch, ingested):
    monkeypatch.setenv("RC_ML_CLASSIFIER_BACKEND", "tfidf")
    monkeypatch.setenv("RC_ML_CLASSIFIER_ARTIFACT_PATH", str(ARTIFACT))
    get_classifier.cache_clear(); get_settings.cache_clear()
    try:
        with TestClient(app) as client:
            response = client.get("/api/v1/admin/products/96617/suggest")
        assert response.status_code == 200
        body = response.json()
        assert set(body) == {"material", "work_types", "work_scores", "room_types", "flags", "confidence", "model"}
        assert body["model"] == "tfidf-logreg-taxonomy-v2"
    finally:
        monkeypatch.delenv("RC_ML_CLASSIFIER_BACKEND", raising=False)
        monkeypatch.delenv("RC_ML_CLASSIFIER_ARTIFACT_PATH", raising=False)
        get_classifier.cache_clear(); get_settings.cache_clear()


def test_admin_suggestion_with_complete_and_minimal_metadata(monkeypatch, ingested):
    if not ARTIFACT.is_dir():
        pytest.skip("local selected v3 artifact is unavailable")
    complete = Product(
        id=990001, sku="LOCAL-COMPLETE", name="Шпатлевка полимерная для внутренних работ",
        description="Для стен и заделки стыков гипсокартонных листов", brand_name="КРЕПС",
        price=Decimal("988.00"), result_price=Decimal("950.00"), unit="шт.",
        categories={"0": "Стройматериалы", "1": "Шпатлевки сухие полимерные"},
        specs={"основа": "полимерная"},
        raw={"characteristics": [{"name": "Применение", "value": "внутренние работы"}],
             "marketing_description": "Финишное выравнивание стен"},
    )
    minimal = Product(id=990002, name="Неизвестный локальный товар")
    with get_sessionmaker()() as session:
        session.merge(complete); session.merge(minimal); session.commit()

    monkeypatch.setenv("RC_ML_CLASSIFIER_BACKEND", "trained")
    monkeypatch.setenv("RC_ML_CLASSIFIER_ARTIFACT_PATH", str(ARTIFACT))
    get_classifier.cache_clear(); get_settings.cache_clear()
    try:
        with TestClient(app) as client:
            complete_response = client.get("/api/v1/admin/products/990001/suggest")
            minimal_response = client.get("/api/v1/admin/products/990002/suggest")
        assert complete_response.status_code == 200
        assert minimal_response.status_code == 200
        for response in (complete_response, minimal_response):
            body = response.json()
            assert set(body) == {"material", "work_types", "work_scores", "room_types",
                                 "flags", "confidence", "model"}
            assert body["model"] == "tfidf-logreg-taxonomy-v2"
            assert isinstance(body["work_types"], list)
    finally:
        monkeypatch.delenv("RC_ML_CLASSIFIER_BACKEND", raising=False)
        monkeypatch.delenv("RC_ML_CLASSIFIER_ARTIFACT_PATH", raising=False)
        get_classifier.cache_clear(); get_settings.cache_clear()
        with get_sessionmaker()() as session:
            for product_id in (990001, 990002):
                product = session.get(Product, product_id)
                if product is not None:
                    session.delete(product)
            session.commit()

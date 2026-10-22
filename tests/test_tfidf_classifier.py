import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_classifier
from app.config import get_settings
from app.main import app
from app.ml.baseline import KeywordClassifier
from app.ml.tfidf import ClassifierArtifactError, TfidfClassifier, prediction_to_suggestion, product_to_input
from app.models import Product
from ml_workspace.ml_api import ProductInput, load_model, predict
from ml_workspace.ml_api.types import Prediction


ARTIFACT = Path(__file__).parents[1] / "ml_workspace/artifacts/models/tfidf_logreg_v2"


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
            79552, "ключ для крана Маевского", "Предохранительная арматура для трубопроводов",
            '["Предохранительная арматура для трубопроводов"]',
            "Вид: \nРезьба: \nЦвет: Белый\nМатериал: Пластик\nДополнительно:", "",
            [{"name": "Комплектация", "value": "Ключ Универсальный"},
             {"name": "Цвет", "value": "Белый"}, {"name": "Материал", "value": "пластик"}],
            7.0, "шт.", "",
        ),
    ]
    result = predict(model, products)
    assert len(result) == 3
    assert result[0].work_types == ["electrical_wiring"]
    assert result[1].status == "non_renovation"
    assert result[2].work_types == ["electrical_wiring", "plumbing_rough"]
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
        Product(id=1, name="Ламинат дуб 8 мм", categories={"1": "Ламинат"}),
        Product(id=2, name="Смеситель для ванной", categories={"2": "Сантехника"}, description="для раковины"),
    ]
    suggestions = classifier.predict(products)
    assert len(suggestions) == 2
    assert suggestions[0].material.value == "laminate"
    assert suggestions[0].work_types == ["laminate_laying"]
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


def test_baseline_is_default_and_cached(monkeypatch):
    monkeypatch.delenv("RC_ML_CLASSIFIER_BACKEND", raising=False)
    get_classifier.cache_clear(); get_settings.cache_clear()
    first = get_classifier()
    assert isinstance(first, KeywordClassifier)
    assert get_classifier() is first


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

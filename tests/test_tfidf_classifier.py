import json
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_classifier
from app.config import get_settings
from app.db import get_sessionmaker
from app.main import app
from app.ml.tfidf import ClassifierArtifactError, TfidfClassifier, prediction_to_suggestion, product_to_input, publishable
from app.models import Product
from app.schemas import Suggestion
from app.taxonomy import Material, ProductCategory, WorkType
from ml_workspace.ml_api import ProductInput, load_model, predict
from ml_workspace.ml_api.types import Prediction


ARTIFACT = Path(__file__).parents[1] / "ml_workspace/model/tfidf_logreg"


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


def test_wallpaper_category_translation_uses_direct_product_evidence():
    prediction = Prediction(product_id=77, labels=["wallpapering"], status="predicted", domain_label="renovation",
        product_category="other_renovation_material", work_types=["wallpapering"],
        dimension_scores={"domain": {"renovation": .95},
                          "product_category": {"other_renovation_material": .9}},
        scores={"wallpapering": .88})
    product = Product(id=77, name="Обои виниловые на флизелиновой основе",
                      categories={"1": "Обои"})
    result = prediction_to_suggestion(prediction, product)
    assert result.material == Material.wallpaper
    assert result.work_types == [WorkType.wallpapering]
    assert publishable(result, .7)


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


def test_lighting_is_supported_consistently():
    raw = Prediction(1, ["lighting_install"], {"lighting_install": 0.91}, "predicted",
                     domain_label="renovation", product_category="lighting", work_types=["lighting_install"],
                     dimension_scores={"domain": {"renovation": .96}, "product_category": {"lighting": .94}})
    suggestion = prediction_to_suggestion(raw, Product(id=1, name="Светильник"))
    assert suggestion.material.value == "lighting"
    assert suggestion.work_types == ["lighting_install"]
    assert suggestion.confidence == .94


def test_material_confidence_does_not_drop_to_zero_without_work_type():
    raw = Prediction(1, [], {"lighting_install": .2}, "predicted", domain_label="renovation",
                     product_category="lighting", dimension_scores={
                         "domain": {"renovation": .93}, "product_category": {"lighting": .91}})
    suggestion = prediction_to_suggestion(raw, Product(id=1, name="Светильник потолочный"))
    assert suggestion.material.value == "lighting"
    assert suggestion.confidence == .91
    assert suggestion.work_types == ["lighting_install"]
    assert suggestion.flags["work_type_inferred"] is True


def test_backend_product_categories_exactly_match_model(model):
    assert {item.value for item in ProductCategory} == set(model.task_classes["product_category"])


def test_category_scoped_hints_prevent_cross_category_assignments():
    cable_tie = Prediction(1, [], {}, "predicted", domain_label="renovation",
                           product_category="construction_mix", dimension_scores={
                               "domain": {"renovation": .8}, "product_category": {"construction_mix": .75}})
    result = prediction_to_suggestion(cable_tie, Product(id=1, name="Стяжка кабельная нейлоновая"))
    assert result.material.value == "construction_mix"

    handle = Prediction(2, ["door_window_install"], {"door_window_install": .8}, "predicted",
                        domain_label="renovation", product_category="other_renovation_material",
                        work_types=["door_window_install"], dimension_scores={
                            "domain": {"renovation": .8},
                            "product_category": {"other_renovation_material": .7}})
    result = prediction_to_suggestion(handle, Product(id=2, name="Ручка дверная на розетке"))
    assert result.material.value == "other"
    assert result.product_category.value == "other_renovation_material"
    assert not publishable(result, .7)


def test_automatic_circuit_breaker_is_not_mapped_to_wall_switch():
    raw = Prediction(149, ["electrical_wiring"], {"electrical_wiring": .91}, "predicted",
                     domain_label="renovation", product_category="electrical_goods",
                     work_types=["electrical_wiring"], dimension_scores={
                         "domain": {"renovation": .95}, "product_category": {"electrical_goods": .82}})
    suggestion = prediction_to_suggestion(
        raw,
        Product(id=149, name="выключатель автоматический 1P 16А", categories={"1": "Автоматы защиты"}),
    )
    assert suggestion.material == Material.circuit_breakers
    assert suggestion.work_types == [WorkType.electrical_wiring]
    assert not suggestion.flags.get("taxonomy_inconsistent", False)
    assert publishable(suggestion, .7)


def _renovation_prediction(product_id: int, category: str = "other_renovation_material",
                           work_types: list[str] | None = None, confidence: float = .9) -> Prediction:
    works = work_types or []
    return Prediction(product_id, works, {work: confidence for work in works}, "predicted",
                      domain_label="renovation", product_category=category, work_types=works,
                      dimension_scores={"domain": {"renovation": .95},
                                        "product_category": {category: confidence}})


@pytest.mark.parametrize("name,category", [
    ("Подложка пробковая AMORIM 3мм рулон 10м2", "Подложка пробковая"),
    ("Подложка СОЛИД 3мм XPS 10м2", "Подложка пластиковая"),
    ("Подложка хвойная 5мм 7м2", "Подложка пробковая"),
    ("Подложка под SPC PLANKER 1,5мм EVA", "Подложка пластиковая"),
])
def test_standalone_floor_underlays_are_specialized_and_publishable(name, category):
    suggestion = prediction_to_suggestion(
        _renovation_prediction(8126, "other_renovation_material"),
        Product(id=8126, name=name, categories={"730": category}),
    )
    assert suggestion.material == Material.underlay
    assert suggestion.work_types == [WorkType.floor_covering_install]
    assert suggestion.flags["adapter_rule__standalone_floor_underlay"] is True
    assert publishable(suggestion, .7)


@pytest.mark.parametrize("name", [
    "Плитка SPC ROYCE Ultima 1200х180х5мм 2,16м2 с подложкой",
    "SPC напольное покрытие со встроенной подложкой",
    "Кварц-винил дуб с акустической подложкой",
])
def test_flooring_with_incidental_underlay_reference_is_not_underlay(name):
    suggestion = prediction_to_suggestion(
        _renovation_prediction(102747, "floor_covering", ["floor_covering_install"]),
        Product(id=102747, name=name, categories={"748": "Плитка SPC"}),
    )
    assert suggestion.material == Material.floor_covering
    assert suggestion.material != Material.underlay
    assert suggestion.flags["adapter_rule__spc_flooring_object"] is True


def test_laminate_with_attached_underlay_reference_remains_laminate():
    suggestion = prediction_to_suggestion(
        _renovation_prediction(9, "floor_covering", ["floor_covering_install"]),
        Product(id=9, name="Ламинат дуб 33 класс со встроенной подложкой",
                categories={"1": "Ламинат"}),
    )
    assert suggestion.material == Material.laminate
    assert suggestion.material != Material.underlay


def test_actual_electrical_box_excludes_accessories_and_gets_supported_works():
    raw = _renovation_prediction(11718, "installation_accessories")
    actual = prediction_to_suggestion(raw, Product(
        id=11718, name="подрозетник концевой ЭРА UniPost 68х45мм",
        categories={"2630": "Коробки монтажные"},
    ))
    assert actual.material == Material.electrical_boxes
    assert actual.work_types == [WorkType.electrical_wiring, WorkType.electrical_fittings]
    assert publishable(actual, .7)
    for product in (
        Product(id=2, name="крышка для установочной коробки ЭРА D68", categories={"2630": "Коробки монтажные"}),
        Product(id=3, name="соединитель для подрозетников пластик", categories={"2630": "Коробки монтажные"}),
        Product(id=4, name="комплект шаблонов для подрозетников", categories={"2626": "Шаблоны"}),
    ):
        assert prediction_to_suggestion(raw, product).material != Material.electrical_boxes


def test_breaker_serpyanka_and_floor_skirting_direct_evidence():
    breaker = prediction_to_suggestion(
        _renovation_prediction(476, "electrical_goods"),
        Product(id=476, name="выключатель автоматический IEK 2Р 50А",
                categories={"4138": "Автоматы защиты"}),
    )
    assert breaker.material == Material.circuit_breakers
    assert breaker.work_types == [WorkType.electrical_wiring]

    mesh = prediction_to_suggestion(
        _renovation_prediction(4403, "other_renovation_material"),
        Product(id=4403, name="лента стекловолоконная (серпянка) Folsen 48 мм x 45м",
                categories={"1038": "Сетки малярные, серпянка"}),
    )
    assert mesh.material == Material.reinforcing_mesh
    assert mesh.work_types == [WorkType.wall_plastering, WorkType.drywall_install, WorkType.wall_putty]

    for pid, name, category in (
        (1405, "плинтус ПВХ SALAG Lima 2500мм", "Плинтусы на основе ПВХ"),
        (17653, "плинтус МДФ Smartprofile 2400мм", "Плинтусы на основе МДФ"),
        (26561, "плинтус напольный керамический KERAMA MARAZZI", "Декоры и бордюры для керамогранита"),
    ):
        result = prediction_to_suggestion(
            _renovation_prediction(pid), Product(id=pid, name=name, categories={"1": category})
        )
        assert result.material == Material.skirting
        assert result.work_types == [WorkType.floor_covering_install]
        assert publishable(result, .7)


def test_floor_skirting_rule_rejects_other_plinth_families_and_accessories():
    raw = _renovation_prediction(1)
    for name, category in (
        ("плинтус потолочный СОЛИД 60х58мм", "Плинтусы потолочные"),
        ("плинтус для столешниц SALAG", "Плинтусы для столешниц"),
        ("угол наружный для плинтуса LIDER", "Комплектующие к плинтусам"),
        ("заглушка для плинтуса ПВХ", "Комплектующие к плинтусам"),
    ):
        assert prediction_to_suggestion(
            raw, Product(id=1, name=name, categories={"1": category})
        ).material != Material.skirting


@pytest.mark.parametrize("pid,name,category,material,works,rule", [
    (3484, "ровнитель FORMAN 31 базовый 20кг", "Смеси для выравнивания полов гипсовые",
     Material.screed_mix, [WorkType.floor_screed], "floor_screed_mix_object"),
    (52778, "лента демпферная НПЭ с фартуком рулон 15000х100х10мм", "Пенополиэтилен",
     Material.damper_tape, [WorkType.floor_screed], "floor_damper_tape_object"),
    (35051, "профиль маячковый KNAUF 3000х6х0,6мм", "Профили и аксессуары для гипсокартона",
     Material.beacons, [WorkType.floor_screed, WorkType.wall_plastering], "screed_plaster_beacon_object"),
    (1525, "система для выравнивания плитки Зажим 1мм 50шт + клин 50шт",
     "Системы выравнивания плитки", Material.tile_leveling, [WorkType.tiling], "tile_leveling_object"),
])
def test_direct_evidence_recovers_common_missing_materials(pid, name, category, material, works, rule):
    result = prediction_to_suggestion(
        _renovation_prediction(pid, "other_renovation_material", confidence=.2),
        Product(id=pid, name=name, categories={"1": category}),
    )
    assert result.material == material
    assert result.work_types == works
    assert result.flags[f"adapter_rule__{rule}"] is True
    assert publishable(result, .7)


def test_narrow_recovery_rules_reject_semantic_lookalikes():
    raw = _renovation_prediction(1, "other_renovation_material")
    products = [
        Product(id=1, name="стяжка кабельная нейлоновая", categories={"1": "Стяжки кабельные"}),
        Product(id=2, name="демпфер для мебели накладной", categories={"1": "Толкатели и амортизаторы"}),
        Product(id=3, name="крепления для маяков под штукатурку", categories={"1": "Крепления, проушины"}),
        Product(id=4, name="маяки для наливного пола TLS", categories={"1": "Системы выравнивания плитки"}),
    ]
    forbidden = [Material.screed_mix, Material.damper_tape, Material.beacons, Material.tile_leveling]
    for product, material in zip(products, forbidden, strict=True):
        assert prediction_to_suggestion(raw, product).material != material


def test_default_operating_threshold_is_point_seven(monkeypatch):
    monkeypatch.delenv("RC_AUTOBIND_MIN_CONFIDENCE", raising=False)
    get_settings.cache_clear()
    try:
        assert get_settings().autobind_min_confidence == .7
    finally:
        get_settings.cache_clear()


def test_publication_uses_configurable_boundary():
    suggestion = Suggestion(product_category=ProductCategory.paint, material=Material.paint,
                            confidence=.6, flags={"domain_renovation": True})
    assert publishable(suggestion, .6)
    assert not publishable(suggestion.model_copy(update={"confidence": .599}), .6)
    assert not publishable(suggestion, .7)


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
        assert set(body) == {"product_category", "material", "work_types", "work_scores", "room_types", "flags", "confidence", "model"}
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
            assert set(body) == {"product_category", "material", "work_types", "work_scores", "room_types",
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

import json
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api import routes
from app.api.deps import get_repo
from app.catalog.loader import load_catalog
from app.catalog.repository import CatalogRepo
from app.config import Settings
from app.db import Base
from app.llm.gigachat import GigaChatError, GigaClassification
from app.main import app
from app.schemas import BindingIn, Suggestion
from app.taxonomy import Material, ProductCategory, WorkType

SAMPLE = Path(__file__).resolve().parents[1] / "mock_catalog" / "sample_catalog.json"


class ScenarioClassifier:
    def predict(self, products):
        out=[]
        for p in products:
            if p.id == 96611:  # A: confident ML
                out.append(Suggestion(product_category=ProductCategory.tile,material=Material.tile,
                    work_types=[WorkType.tiling],confidence=.91,flags={"domain_renovation":True},model="tfidf"))
            elif p.id in {96612,96613,96614,96615}:  # B/C/D plus category-only
                out.append(Suggestion(product_category=ProductCategory.tile,material=Material.other,
                    work_types=[],confidence=.35,flags={"domain_renovation":True,"ml_unknown":True},model="tfidf"))
            else:
                out.append(Suggestion(product_category=None,material=Material.other,work_types=[],confidence=.99,
                    flags={"domain_non_renovation":True},model="tfidf"))
        return out


class ScenarioGigaChat:
    configured=True
    def __init__(self): self.seen=[]; self.explanation_signals=[]
    async def classify(self, product, existing=None):
        self.seen.append(product.id)
        if product.id == 96612:  # B: accepted fallback
            return GigaClassification(decision="accept",product_category="tile",material="tile",
                work_types=["tiling"],evidence=["Плитка настенная"],reason="явная плитка")
        if product.id == 96613:  # C: invalid structured output after client validation/repair
            raise GigaChatError("Invalid structured classification",kind="schema_validation")
        if product.id == 96614:  # D: outage
            raise GigaChatError("GigaChat unavailable",kind="api_error")
        return GigaClassification(decision="accept",product_category="floor_covering",reason="только категория")
    async def explain_estimate(self, response, signals):
        self.explanation_signals=signals
        return {x["item_id"]:"Выбран для облицовки: подходит по типу материала, есть цена и товар в наличии."
                for x in signals}


def test_isolated_hybrid_backend_to_retrieval_estimate_and_explanation(tmp_path,monkeypatch):
    engine=create_engine(f"sqlite:///{tmp_path/'hybrid.sqlite'}",connect_args={"check_same_thread":False})
    Base.metadata.create_all(engine); Session=sessionmaker(bind=engine,expire_on_commit=False); session=Session()
    load_catalog(session,SAMPLE); repo=CatalogRepo(session)
    # Existing confirmed binding is protected from automatic classification.
    repo.set_binding(96617,BindingIn(product_category=ProductCategory.paint,material=Material.paint,
        work_types=[WorkType.wall_painting]),"manual",None,True)
    giga=ScenarioGigaChat()
    settings=Settings(gigachat_enabled=True,gigachat_credentials="mock",autobind_min_confidence=.7,
        gigachat_autobind_max_products=10,gigachat_explanations=True,gigachat_explanation_max_items=30)
    monkeypatch.setattr(routes,"get_classifier",lambda:ScenarioClassifier())
    monkeypatch.setattr(routes,"get_gigachat",lambda:giga)
    monkeypatch.setattr(routes,"get_settings",lambda:settings)
    app.dependency_overrides[get_repo]=lambda:repo
    try:
        with TestClient(app) as client:
            bind_response=client.post("/api/v1/admin/autobind")
            assert bind_response.status_code==200
            assert bind_response.json()["bound_ml"]==2  # confident ML plus validated GigaChat

            a,b=repo.binding(96611),repo.binding(96612)
            assert a and a.source=="ml" and a.confidence==.91
            assert b and b.source=="gigachat" and b.work_types==["tiling"]
            assert repo.binding(96613) is None and repo.binding(96614) is None  # invalid/outage -> review
            assert repo.binding(96615) is None  # category-only cannot enter estimate slots
            assert repo.binding(96617).confirmed is True and repo.binding(96617).source=="manual"
            assert giga.seen==[96612,96613,96614,96615]

            retrieved=repo.candidates(Material.tile,WorkType.tiling,min_confidence=.7)
            assert {p.id for p,_ in retrieved}=={96611,96612}
            assert all(p.status is not False and p.result_price is not None for p,_ in retrieved)

            estimate=client.post("/api/v1/estimate",json={"renovation_type":"capital","explain":True,"rooms":[{
                "room_type":"bathroom","length_m":2,"width_m":3,"height_m":2.5,
                "works":[{"work_type":"tiling","surface":"wall","materials":["tile"]}]}]})
            assert estimate.status_code==200
            body=estimate.json(); item=body["rooms"][0]["items"][0]
            assert item["product"]["id"] in {96611,96612} and item["cost"]>0 and item["packages"]>0
            assert item["material"]=="tile" and item["work_type"]=="tiling"
            assert item["reason"].startswith("Выбран для облицовки")
            assert giga.explanation_signals
            signal=giga.explanation_signals[0]
            assert signal["product"]["id"]==item["product"]["id"]
            assert signal["product"]["specs"] and signal["selection_signals"]
    finally:
        app.dependency_overrides.pop(get_repo,None); session.close(); engine.dispose()

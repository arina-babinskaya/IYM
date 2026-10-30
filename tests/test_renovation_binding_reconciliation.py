from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.catalog.repository import CatalogRepo
from app.db import Base
from app.engine.baseline import BaselineEngine
from app.ml.ranker import ContextRanker
from app.ml.tfidf import prediction_to_suggestion
from app.models import Product, ProductBinding
from app.schemas import RoomInput, RoomType
from app.taxonomy import Material, WorkType
from ml_workspace.ml_api.types import Prediction
from scripts.reconcile_renovation_bindings import apply_plan, build_plan


class EvidenceClassifier:
    def predict(self, products):
        results = []
        for product in products:
            category = "floor_covering" if product.id in {8126, 102747} else "other_renovation_material"
            confidence = .8601340472444703 if product.id == 102747 else .9
            raw = Prediction(product.id, [], {}, "predicted", domain_label="renovation",
                             product_category=category,
                             dimension_scores={"domain": {"renovation": .95},
                                               "product_category": {category: confidence}})
            results.append(prediction_to_suggestion(raw, product))
        return results


def product(pid, name, category, price, area=None):
    return Product(id=pid, name=name, categories={"1": category}, status=True, in_stock=True,
                   result_price=Decimal(str(price)), price=Decimal(str(price)), unit="уп.",
                   package_area=Decimal(str(area)) if area else None)


def test_reconciliation_removes_47300_spc_underlay_failure_and_keeps_real_underlay(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'reconcile.sqlite'}")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        spc = product(102747, "плитка SPC ROYCE Ultima 1200х180х5мм 2,16м2 с подложкой",
                      "Плитка SPC", 4730, "2.16")
        cork = product(8126, "подложка пробковая AMORIM Go4Cork 3мм рулон 10м2",
                       "Подложка пробковая", 5889, "10")
        session.add_all([spc, cork, ProductBinding(
            product_id=102747, product_category="floor_covering", material="underlay",
            work_types=["floor_covering_install"], room_types=[], flags={}, source="ml",
            confidence=.8601340472444703, confirmed=False,
        )])
        session.commit()

        room = RoomInput(room_type=RoomType.living, length_m=Decimal("4"), width_m=Decimal("5"))
        engine_impl = BaselineEngine(ContextRanker())
        before = engine_impl._item(CatalogRepo(session), room, WorkType.floor_covering_install,
                                   Material.underlay, None, room.floor_area, Decimal("0"))
        assert before.product.id == 102747
        assert before.packages == 10
        assert before.cost == Decimal("47300.00")

        changes, skipped = build_plan(session, EvidenceClassifier(), products=[spc, cork])
        assert not skipped
        assert [(item.product_id, item.action, item.after["material"]) for item in changes] == [
            (102747, "update", "floor_covering"), (8126, "insert", "underlay")
        ]
        assert session.get(ProductBinding, 102747).material == "underlay"  # plan is dry-run
        assert apply_plan(session, changes) == 2

        candidates = CatalogRepo(session).candidates(
            Material.underlay, WorkType.floor_covering_install, min_confidence=.7
        )
        assert [item.id for item, _ in candidates] == [8126]
        after = engine_impl._item(CatalogRepo(session), room, WorkType.floor_covering_install,
                                  Material.underlay, None, room.floor_area, Decimal("0"))
        assert after.product.id == 8126
        assert after.product.id != 102747
        assert session.get(ProductBinding, 102747).material == "floor_covering"
        second_changes, second_skipped = build_plan(session, EvidenceClassifier(), products=[spc, cork])
        assert second_changes == [] and second_skipped == []


def test_reconciliation_is_idempotent_and_preserves_confirmed_binding(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'confirmed.sqlite'}")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        cork = product(8126, "подложка пробковая AMORIM 3мм", "Подложка пробковая", 5889, "10")
        session.add_all([cork, ProductBinding(
            product_id=8126, product_category="floor_covering", material="insulation",
            work_types=[], room_types=[], flags={}, source="manual", confidence=1, confirmed=True,
        )])
        session.commit()
        changes, skipped = build_plan(session, EvidenceClassifier(), products=[cork])
        assert changes == []
        assert skipped == [{"product_id": 8126, "reason": "confirmed_binding_preserved"}]
        assert session.get(ProductBinding, 8126).material == "insulation"


def test_reconciled_floor_preparation_products_reach_estimate_engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'floor-preparation.sqlite'}")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        primer = product(5941, "грунтовка глубокого проникновения 10л", "Грунтовка", 1239)
        waterproofing = product(381, "гидроизоляция полимерная 4кг", "Гидроизоляция полимерная", 2548)
        screed = product(3484, "ровнитель FORMAN 31 базовый 20кг",
                         "Смеси для выравнивания полов гипсовые", 439)
        damper = product(52778, "лента демпферная НПЭ с фартуком рулон 15000х100х10мм",
                         "Пенополиэтилен", 431)
        beacon = product(35051, "профиль маячковый KNAUF 3000х6х0,6мм",
                         "Профили и аксессуары для гипсокартона", 202)
        leveling = product(1525, "система для выравнивания плитки Зажим 1мм 50шт + клин 50шт",
                           "Системы выравнивания плитки", 452)
        session.add_all([primer, waterproofing, screed, damper, beacon, leveling])
        session.add_all([
            ProductBinding(product_id=5941, product_category="primer", material="primer",
                           work_types=["priming"], room_types=[], flags={}, source="ml",
                           confidence=.9, confirmed=False),
            ProductBinding(product_id=381, product_category="waterproofing_material", material="waterproofing",
                           work_types=["waterproofing"], room_types=[], flags={}, source="ml",
                           confidence=.9, confirmed=False),
            ProductBinding(product_id=3484, product_category="construction_mix", material="construction_mix",
                           work_types=["floor_screed"], room_types=[], flags={}, source="ml",
                           confidence=.8, confirmed=False),
            ProductBinding(product_id=35051, product_category="drywall", material="profile",
                           work_types=["drywall_install"], room_types=[], flags={}, source="ml",
                           confidence=.9, confirmed=False),
        ])
        session.commit()
        changes, skipped = build_plan(session, EvidenceClassifier(), products=[screed, damper, beacon, leveling])
        assert not skipped
        assert {item.after["material"] for item in changes} == {
            "screed_mix", "damper_tape", "beacons", "tile_leveling",
        }
        apply_plan(session, changes)

        room = RoomInput(room_type=RoomType.bathroom, length_m=Decimal("2"), width_m=Decimal("3"))
        impl = BaselineEngine(ContextRanker())
        items = [
            impl._item(CatalogRepo(session), room, work, material, None, room.floor_area, Decimal("0"))
            for work, material in (
                (WorkType.waterproofing, Material.waterproofing),
                (WorkType.waterproofing, Material.primer),
                (WorkType.floor_screed, Material.screed_mix),
                (WorkType.floor_screed, Material.damper_tape),
                (WorkType.floor_screed, Material.beacons),
            )
        ]
        assert [item.product.id for item in items] == [381, 5941, 3484, 52778, 35051]
        tile_rows = CatalogRepo(session).candidates(Material.tile_leveling, WorkType.tiling,
                                                    min_confidence=.7)
        assert [item.id for item, _ in tile_rows] == [1525]

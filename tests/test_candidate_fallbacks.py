from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.catalog.repository import CatalogRepo
from app.db import Base
from app.models import Product, ProductBinding
from app.taxonomy import Material, WorkType


def add(session, pid, material, works, *, price=100, stock=True, status=True,
        confidence=.9, confirmed=False, flags=None):
    session.add(Product(id=pid, name=f"product {pid}", status=status, in_stock=stock,
                        result_price=Decimal(str(price)), price=Decimal(str(price))))
    session.add(ProductBinding(product_id=pid, product_category="installation_accessories",
                               material=material.value, work_types=[work.value for work in works],
                               room_types=[], flags=flags or {}, source="ml", confidence=confidence,
                               confirmed=confirmed))


def test_exact_candidates_exclude_lower_fallback_tiers(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'exact.sqlite'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        add(session, 1, Material.primer, [WorkType.waterproofing])
        add(session, 2, Material.primer, [WorkType.priming])
        session.commit()
        rows = CatalogRepo(session).candidates(Material.primer, WorkType.waterproofing, min_confidence=.7)
        assert [product.id for product, _ in rows] == [1]
        assert not rows[0][1].flags.get("candidate_compatible_fallback")


def test_compatible_primer_fallback_has_provenance(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'primer.sqlite'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        add(session, 1, Material.primer, [WorkType.priming])
        session.commit()
        for work in (WorkType.waterproofing, WorkType.floor_screed, WorkType.tiling):
            rows = CatalogRepo(session).candidates(Material.primer, work, min_confidence=.7)
            assert [product.id for product, _ in rows] == [1]
            flags = rows[0][1].flags
            assert flags["candidate_compatible_fallback"] is True
            assert flags[f"candidate_requested_work__{work.value}"] is True


def test_material_only_fastener_fallback_and_wrong_material_rejection(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'fasteners.sqlite'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        add(session, 1, Material.fasteners, [])
        add(session, 2, Material.consumables, [])
        session.commit()
        rows = CatalogRepo(session).candidates(Material.fasteners, WorkType.floor_covering_install,
                                               min_confidence=.7)
        assert [product.id for product, _ in rows] == [1]
        assert rows[0][1].flags["candidate_material_only_fallback"] is True


def test_fallback_keeps_price_status_stock_confidence_and_flag_filters(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'filters.sqlite'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        add(session, 1, Material.fasteners, [], flags={"washable": True})
        add(session, 2, Material.fasteners, [], price=0)
        add(session, 3, Material.fasteners, [], stock=False)
        add(session, 4, Material.fasteners, [], status=False)
        add(session, 5, Material.fasteners, [], confidence=.69)
        add(session, 6, Material.fasteners, [], flags={})
        session.commit()
        rows = CatalogRepo(session).candidates(
            Material.fasteners, WorkType.floor_covering_install,
            required_flags=["washable"], min_confidence=.7,
        )
        assert [product.id for product, _ in rows] == [1]


def test_confirmed_legacy_binding_remains_eligible(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'confirmed.sqlite'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        add(session, 1, Material.fasteners, [], confidence=0, confirmed=True)
        session.commit()
        rows = CatalogRepo(session).candidates(Material.fasteners, WorkType.drywall_install,
                                               min_confidence=.7)
        assert [product.id for product, _ in rows] == [1]
        assert rows[0][1].confirmed is True


def test_accessory_only_exact_pool_is_extended_with_typical_fallback_products(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'profile.sqlite'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        add(session, 1, Material.profile, [WorkType.drywall_install])
        add(session, 2, Material.profile, [])
        add(session, 3, Material.profile, [])
        session.get(Product, 1).name = "лента уплотнительная НПЭ для профиля ГКЛ"
        session.get(Product, 2).name = "профиль направляющий ПН 100х40мм 3м"
        session.get(Product, 3).name = "заглушка для профиля"
        session.commit()
        rows = CatalogRepo(session).candidates(Material.profile, WorkType.drywall_install, min_confidence=.7)
        assert [product.id for product, _ in rows] == [1, 2]
        assert rows[1][1].flags["candidate_material_only_fallback"] is True

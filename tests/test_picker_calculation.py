from decimal import Decimal
import pytest

from app.catalog.repository import CatalogRepo
from app.api.picker import estimate_options
from app.engine.baseline import calc_product_for_room, packages_for_area
from app.models import Product, ProductBinding
from app.schemas import OptionsRequest, RoomInput, RoomType, Surface
from app.taxonomy import Material


def test_packages_for_area_does_not_treat_piece_goods_as_sheets():
    # Junction box with physical dimensions 110x110 mm
    box = Product(
        id=999901,
        name="Распределительная коробка 110мм",
        unit="шт",
        result_price=Decimal("623.00"),
        specs={"length_m": "0.11", "width_m": "0.11"},
    )
    # When passed with Material.electrical_boxes, it should NOT calculate 33.6 / (0.11 * 0.11)
    with pytest.raises(Exception):
        packages_for_area(box, Decimal("33.6"), Decimal("5"), material=Material.electrical_boxes)


def test_calc_product_for_room_electrical_boxes():
    box = Product(
        id=999902,
        name="Распределительная коробка 110мм",
        unit="шт",
        result_price=Decimal("600.00"),
        specs={"length_m": "0.11", "width_m": "0.11"},
    )
    # Room 4x3 m (floor area = 12 m2)
    room = RoomInput(
        room_type=RoomType.bedroom,
        length_m=Decimal("4.0"),
        width_m=Decimal("3.0"),
        height_m=Decimal("2.7"),
        openings_area_m2=Decimal("3.6"),
    )
    # Floor 12 m2 -> max(3, ceil(12/4) + 1) = 4 pcs
    n, need, unit, cost, _ = calc_product_for_room(
        box, Material.electrical_boxes, room, Surface.wall
    )
    assert n == 4
    assert need == Decimal("4")
    assert unit == "шт"
    assert cost == Decimal("2400.00")


def test_calc_product_for_room_door():
    door = Product(
        id=999903,
        name="Дверь межкомнатная 2000х800",
        unit="шт",
        result_price=Decimal("10000.00"),
        specs={"length_m": "2.0", "width_m": "0.8"},
    )
    room = RoomInput(
        room_type=RoomType.bedroom,
        length_m=Decimal("4.0"),
        width_m=Decimal("3.0"),
        height_m=Decimal("2.7"),
    )
    n, need, unit, cost, _ = calc_product_for_room(
        door, Material.doors, room, Surface.wall
    )
    assert n == 1
    assert need == Decimal("1")
    assert unit == "шт"
    assert cost == Decimal("10000.00")


def test_picker_options_electrical_boxes_realistic_cost(db):
    from app.db import get_sessionmaker
    with get_sessionmaker()() as session:
        # Add sample products
        box1 = Product(
            id=999911,
            name="Распределительная коробка 110мм бронза",
            unit="шт",
            result_price=Decimal("623.00"),
            price=Decimal("623.00"),
            status=True,
            in_stock=True,
            specs={"length_m": "0.11", "width_m": "0.11"},
        )
        box2 = Product(
            id=999912,
            name="Подрозетник промежуточный ЭРА UniPost 68х45мм",
            unit="шт",
            result_price=Decimal("30.00"),
            price=Decimal("30.00"),
            status=True,
            in_stock=True,
            specs={"length_m": "0.068", "width_m": "0.045"},
        )
        b1 = ProductBinding(
            product_id=999911,
            material=Material.electrical_boxes.value,
            confidence=1.0,
            confirmed=True,
            source="manual",
        )
        b2 = ProductBinding(
            product_id=999912,
            material=Material.electrical_boxes.value,
            confidence=1.0,
            confirmed=True,
            source="manual",
        )
        session.add_all([box1, box2, b1, b2])
        session.commit()

        repo = CatalogRepo(session)
        room = RoomInput(
            room_type=RoomType.bedroom,
            length_m=Decimal("5.65"),
            width_m=Decimal("5.65"),
            height_m=Decimal("2.7"),
            openings_area_m2=Decimal("3.6"),
        )
        req = OptionsRequest(room=room, material=Material.electrical_boxes, surface=Surface.wall, limit=5)
        resp = estimate_options(req, repo)
        assert resp.products, "Must return candidate electrical boxes"
        for opt in resp.products:
            assert opt.packages == 9
            assert opt.cost in (Decimal("5607.00"), Decimal("270.00")), f"Unexpected cost: {opt.cost}"

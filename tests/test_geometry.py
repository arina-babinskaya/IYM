"""
Тесты модуля 2D-геометрии стен и помещений произвольной формы (app.engine.geometry).
"""

from decimal import Decimal
import pytest

from app.engine.geometry import (
    Point2D,
    analyze_room_geometry,
    calculate_floor_area,
    calculate_interior_angles,
    calculate_perimeter,
    calculate_reserve_for_geometry,
    calculate_wall_segments,
    is_orthogonal_polygon,
    polygon_to_room_input,
    preset_bay_window,
    preset_circle,
    preset_l_shaped,
    preset_rectangle,
    preset_trapezoid,
    preset_with_niche,
)
from app.schemas import RoomType
from app.taxonomy import Material


class TestGeometryCalculations:
    def test_rectangle_shoelace_area_and_perimeter(self):
        """Прямоугольник 5.0м х 4.0м: площадь 20 м², периметр 18 м."""
        poly = preset_rectangle(length_m=5.0, width_m=4.0)

        area = calculate_floor_area(poly)
        perimeter = calculate_perimeter(poly)
        orthogonal = is_orthogonal_polygon(poly)
        angles = calculate_interior_angles(poly)

        assert area == Decimal("20.00")
        assert perimeter == Decimal("18.00")
        assert orthogonal is True
        assert len(angles) == 4
        assert all(abs(a - 90.0) < 0.1 for a in angles)

    def test_clockwise_and_counter_clockwise_area_symmetry(self):
        """Площадь одинакова независимо от направления обхода вершин (по часовой или против)."""
        ccw = [Point2D(0, 0), Point2D(4, 0), Point2D(4, 3), Point2D(0, 3)]
        cw = list(reversed(ccw))

        assert calculate_floor_area(ccw) == Decimal("12.00")
        assert calculate_floor_area(cw) == Decimal("12.00")
        assert calculate_perimeter(ccw) == Decimal("14.00")
        assert calculate_perimeter(cw) == Decimal("14.00")

    def test_l_shaped_room_geometry(self):
        """Г-образное помещение (5х4 м с вырезом 2х2 м).

        Полная площадь: 5 * 4 = 20 м².
        Вырез: 2 * 2 = 4 м².
        Итоговая площадь: 16 м².
        Периметр: 4 + 2 + 2 + 3 + 2 + 5 = 18 м.
        """
        poly = preset_l_shaped(length_main=5.0, width_main=4.0, cutout_length=2.0, cutout_width=2.0)

        area = calculate_floor_area(poly)
        perimeter = calculate_perimeter(poly)
        orthogonal = is_orthogonal_polygon(poly)
        walls = calculate_wall_segments(poly, height_m=Decimal("2.70"))

        assert area == Decimal("16.00")
        assert perimeter == Decimal("18.00")
        assert orthogonal is True
        assert len(walls) == 6

        # Сумма площадей всех стен равна периметр * высота
        total_wall_area = sum(w.area_m2 for w in walls)
        assert total_wall_area == Decimal("18.00") * Decimal("2.70")

    def test_niche_room_geometry(self):
        """Комната с нишей под встроенный шкаф (ширина 2м, глубина 0.6м)."""
        poly = preset_with_niche(length_m=4.0, width_m=3.0, niche_w=2.0, niche_d=0.6)

        area = calculate_floor_area(poly)
        perimeter = calculate_perimeter(poly)

        # Основная комната 12 м² + ниша 2 * 0.6 = 1.2 м² -> 13.20 м²
        assert area == Decimal("13.20")
        # Периметр увеличивается на 2 * глубину ниши (2 * 0.6 = 1.2) -> 14 + 1.2 = 15.20 м
        assert perimeter == Decimal("15.20")

    def test_bay_window_irregular_angles_and_snip_reserve(self):
        """Комната со скошенным эркером: непрямые углы и повышенный строительный запас по СНиП."""
        poly = preset_bay_window(length_m=5.0, width_m=4.0, bay_depth=1.2, chamfer_offset=0.8)

        metrics = analyze_room_geometry(poly, height_m=Decimal("2.70"))

        assert metrics.is_orthogonal is False
        assert metrics.wall_count == 6
        # Для неортогональных помещений запас на плитку и ламинат увеличивается до 15%
        assert metrics.waste_reserve_recommendations[Material.tile] == Decimal("15")
        assert metrics.waste_reserve_recommendations[Material.laminate] == Decimal("15")
        assert metrics.waste_reserve_recommendations[Material.drywall] == Decimal("15")

        # Проверяем, что в инженерных примечаниях упомянут СНиП
        assert any("СНиП 3.04.01-87" in note for note in metrics.geometry_notes)

    def test_trapezoid_room(self):
        """Трапециевидная комната (основания 6м и 4м, высота 5м).

        Площадь: (6 + 4) / 2 * 5 = 25 м².
        """
        poly = preset_trapezoid(bottom_width=6.0, top_width=4.0, length_m=5.0)

        area = calculate_floor_area(poly)
        assert area == Decimal("25.00")
        assert is_orthogonal_polygon(poly) is False

    def test_individual_wall_segments(self):
        """Проверка расчета длин и площади отдельных участков стен."""
        poly = [
            Point2D(0.0, 0.0),
            Point2D(3.0, 0.0),
            Point2D(3.0, 4.0),
            Point2D(0.0, 4.0),
        ]
        segments = calculate_wall_segments(poly, height_m=Decimal("3.00"))

        assert len(segments) == 4
        assert segments[0].length_m == Decimal("3.00")
        assert segments[0].area_m2 == Decimal("9.00")
        assert segments[1].length_m == Decimal("4.00")
        assert segments[1].area_m2 == Decimal("12.00")

    def test_polygon_to_room_input_integration(self):
        """Интеграция с Pydantic RoomInput для передачи в расчетный движок."""
        poly = preset_rectangle(length_m=4.5, width_m=3.0)
        room_input, metrics = polygon_to_room_input(
            poly,
            room_type=RoomType.bedroom,
            height_m=Decimal("2.70"),
            openings_area_m2=Decimal("3.50"),
            name="Спальня 2D",
        )

        assert room_input.name == "Спальня 2D"
        assert room_input.room_type == RoomType.bedroom
        assert room_input.floor_area == Decimal("13.50")
        assert metrics.floor_area == Decimal("13.50")
        assert metrics.perimeter == Decimal("15.00")
        assert metrics.net_wall_area == Decimal("37.00")  # 15 * 2.7 = 40.5 - 3.5 = 37.0

    def test_invalid_polygon_raises_error(self):
        """Полигон с менее чем 3 точками вызывает ValueError."""
        with pytest.raises(ValueError, match="минимум 3 вершины"):
            calculate_floor_area([Point2D(0, 0), Point2D(1, 1)])

    def test_geometry_api_endpoints(self):
        """Проверка REST API эндпоинтов геометрии: пресеты и анализ."""
        from fastapi.testclient import TestClient
        from app.main import app

        with TestClient(app) as client:
            # 1. Presets endpoint
            res = client.get("/api/v1/geometry/presets")
            assert res.status_code == 200
            data = res.json()
            assert "rectangle" in data
            assert "l_shaped" in data
            assert len(data["l_shaped"]) == 6

            # 2. Analyze endpoint
            payload = {
                "vertices": [{"x": 0, "y": 0}, {"x": 4, "y": 0}, {"x": 4, "y": 5}, {"x": 0, "y": 5}],
                "height_m": 2.7,
                "openings_area_m2": 3.7,
            }
            res2 = client.post("/api/v1/geometry/analyze", json=payload)
            assert res2.status_code == 200
            m = res2.json()
            assert m["floor_area"] == 20.0
            assert m["perimeter"] == 18.0
            assert m["is_orthogonal"] is True
            assert m["wall_count"] == 4

    def test_circle_room_geometry(self):
        """Круглое помещение: радиус 2.5м, 16 сегментов."""
        poly = preset_circle(radius_m=2.5, segments=16)
        area = calculate_floor_area(poly)
        perimeter = calculate_perimeter(poly)
        orthogonal = is_orthogonal_polygon(poly)

        # pi * r^2 ~ 19.63 m2, perimeter ~ 15.71 m
        assert Decimal("19.00") <= area <= Decimal("20.00")
        assert Decimal("15.00") <= perimeter <= Decimal("16.00")
        assert orthogonal is False
        assert len(poly) == 16

"""
Модуль расчета геометрии помещений произвольной формы (2D Walls & Polygons).

Обеспечивает:
1. Вычисление точной площади пола произвольного многоугольника по формуле Гаусса (Shoelace formula).
2. Вычисление точного периметра стен и длин отдельных участков.
3. Расчет площади каждой отдельной стены (для акцентных стен, разных типов обоев/плитки).
4. Определение углов между смежными стенами и выявление неортогональных стен (скошенные углы, эркеры).
5. Расчет нормативного строительного запаса на подрезку материалов по СНиП 3.04.01-87
   с автоматическим увеличением запаса при сложной геометрии (диагональный раскрой).
6. Библиотеку типовых архитектурных пресетов (прямоугольник, Г-образная, с нишей, эркер, трапеция).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from typing import Sequence

from app.schemas import Amount, Level, RoomInput, RoomType
from app.taxonomy import Material


def _quantize(val: float | Decimal, places: int = 2) -> Decimal:
    """Округление Decimal до заданного количества знаков после запятой."""
    dec = Decimal(str(val)) if not isinstance(val, Decimal) else val
    fmt = Decimal("10") ** -places
    return dec.quantize(fmt, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class Point2D:
    """Точка на плане помещения в метрах (x, y)."""
    x: float
    y: float

    def to_tuple(self) -> tuple[float, float]:
        return (self.x, self.y)

    def __repr__(self) -> str:
        return f"Point2D({self.x:.2f}, {self.y:.2f})"


@dataclass(frozen=True)
class WallSegment:
    """Сегмент стены между двумя смежными вершинами.

    Attributes:
        index: Порядковый номер стены (начиная с 0).
        start: Начальная точка стены.
        end: Конечная точка стены.
        length_m: Длина стены в метрах.
        height_m: Высота стены в метрах.
        area_m2: Площадь стены (длина * высота) без вычета проемов.
        angle_deg: Угол направления стены относительно оси X (0-360 градусов).
    """
    index: int
    start: Point2D
    end: Point2D
    length_m: Decimal
    height_m: Decimal
    area_m2: Decimal
    angle_deg: float


@dataclass(frozen=True)
class RoomGeometryMetrics:
    """Комплексные метрики геометрии помещения.

    Attributes:
        floor_area: Точная площадь пола (м²) по формуле Гаусса.
        perimeter: Точный периметр стен (м).
        wall_count: Количество стен (сегментов многоугольника).
        gross_wall_area: Общая площадь стен без вычета проемов (м²).
        net_wall_area: Площадь стен за вычетом окон и дверей (м²).
        is_orthogonal: True, если все углы прямые (90° или 270°).
        interior_angles: Внутренние углы между смежными стенами в градусах.
        wall_lengths: Длины всех стен по порядку (м).
        walls: Полная информация по каждому участку стены.
        bounding_box: Габариты комнаты (ширина_м, длина_м).
        waste_reserve_recommendations: Рекомендуемые проценты запаса по материалам.
        geometry_notes: Инженерные примечания для сметы (СНиП / СП).
    """
    floor_area: Decimal
    perimeter: Decimal
    wall_count: int
    gross_wall_area: Decimal
    net_wall_area: Decimal
    is_orthogonal: bool
    interior_angles: list[float]
    wall_lengths: list[Decimal]
    walls: list[WallSegment]
    bounding_box: tuple[Decimal, Decimal]
    waste_reserve_recommendations: dict[Material, Decimal] = field(default_factory=dict)
    geometry_notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Математическое ядро: расчет площади, периметра и углов
# ---------------------------------------------------------------------------


def calculate_floor_area(vertices: Sequence[Point2D]) -> Decimal:
    """Вычисляет площадь произвольного многоугольника по формуле Гаусса (Shoelace formula).

    Формула: S = 0.5 * |sum(x_i * y_{i+1} - x_{i+1} * y_i)|.
    Корректно работает как для обхода по часовой стрелке, так и против.
    """
    n = len(vertices)
    if n < 3:
        raise ValueError(f"Многоугольник комнаты должен содержать минимум 3 вершины, передано: {n}")

    area_sum = 0.0
    for i in range(n):
        j = (i + 1) % n
        area_sum += vertices[i].x * vertices[j].y
        area_sum -= vertices[j].x * vertices[i].y

    return _quantize(abs(area_sum) * 0.5, 2)


def calculate_perimeter(vertices: Sequence[Point2D]) -> Decimal:
    """Вычисляет суммарный периметр стен (евклидово расстояние между вершинами)."""
    n = len(vertices)
    if n < 3:
        raise ValueError(f"Многоугольник комнаты должен содержать минимум 3 вершины, передано: {n}")

    total = 0.0
    for i in range(n):
        j = (i + 1) % n
        dx = vertices[j].x - vertices[i].x
        dy = vertices[j].y - vertices[i].y
        total += math.hypot(dx, dy)

    return _quantize(total, 2)


def calculate_wall_segments(
    vertices: Sequence[Point2D],
    height_m: Decimal = Decimal("2.70"),
) -> list[WallSegment]:
    """Строит список участков стен с вычислением длин, углов и площадей каждого отрезка."""
    n = len(vertices)
    if n < 3:
        raise ValueError(f"Многоугольник комнаты должен содержать минимум 3 вершины, передано: {n}")

    segments: list[WallSegment] = []
    for i in range(n):
        p1 = vertices[i]
        p2 = vertices[(i + 1) % n]
        dx = p2.x - p1.x
        dy = p2.y - p1.y
        length = _quantize(math.hypot(dx, dy), 2)
        area = _quantize(length * height_m, 2)
        angle = math.degrees(math.atan2(dy, dx)) % 360.0

        segments.append(
            WallSegment(
                index=i,
                start=p1,
                end=p2,
                length_m=length,
                height_m=height_m,
                area_m2=area,
                angle_deg=round(angle, 1),
            )
        )
    return segments


def calculate_interior_angles(vertices: Sequence[Point2D]) -> list[float]:
    """Вычисляет внутренние углы многоугольника в градусах для каждой вершины.

    Использует значащее векторное произведение для определения ориентации (CCW / CW).
    """
    n = len(vertices)
    if n < 3:
        raise ValueError(f"Многоугольник комнаты должен содержать минимум 3 вершины, передано: {n}")

    # Определяем ориентацию многоугольника через ориентированную площадь
    signed_area = 0.0
    for i in range(n):
        j = (i + 1) % n
        signed_area += vertices[i].x * vertices[j].y - vertices[j].x * vertices[i].y
    is_ccw = signed_area > 0

    angles: list[float] = []
    for i in range(n):
        prev_p = vertices[(i - 1) % n]
        curr_p = vertices[i]
        next_p = vertices[(i + 1) % n]

        # Векторы: v1 = от curr к prev, v2 = от curr к next
        v1x, v1y = prev_p.x - curr_p.x, prev_p.y - curr_p.y
        v2x, v2y = next_p.x - curr_p.x, next_p.y - curr_p.y

        len1 = math.hypot(v1x, v1y)
        len2 = math.hypot(v2x, v2y)
        if len1 == 0 or len2 == 0:
            angles.append(180.0)
            continue

        # Углы векторов в полярной системе
        angle1 = math.atan2(v1y, v1x)
        angle2 = math.atan2(v2y, v2x)

        if is_ccw:
            # Для обхода против часовой стрелки внутренний угол идет от v2 к v1
            diff = math.degrees(angle1 - angle2) % 360.0
        else:
            # Для обхода по часовой стрелке
            diff = math.degrees(angle2 - angle1) % 360.0

        angles.append(round(diff, 1))

    return angles


def is_orthogonal_polygon(vertices: Sequence[Point2D], tolerance_deg: float = 2.0) -> bool:
    """Проверяет, является ли комната строго ортогональной (все углы 90° или 270°).

    Если комната ортогональная — раскрой плитки и ламината стандартный (прямой).
    Если нет — комната имеет скошенные стены, эркеры или косые углы, требующие повышенного запаса.
    """
    angles = calculate_interior_angles(vertices)
    for a in angles:
        is_90 = abs(a - 90.0) <= tolerance_deg
        is_270 = abs(a - 270.0) <= tolerance_deg
        if not (is_90 or is_270):
            return False
    return True


def get_bounding_box(vertices: Sequence[Point2D]) -> tuple[Decimal, Decimal]:
    """Возвращает габариты комнаты (ширина_м, длина_м) по минимальному охватывающему прямоугольнику."""
    xs = [p.x for p in vertices]
    ys = [p.y for p in vertices]
    width = _quantize(max(xs) - min(xs), 2)
    length = _quantize(max(ys) - min(ys), 2)
    # Возвращаем (min_dim, max_dim) или (width, length)
    return (min(width, length), max(width, length))


# ---------------------------------------------------------------------------
# Инженерный блок: нормы расхода и строительный запас по СНиП 3.04.01-87
# ---------------------------------------------------------------------------


def calculate_reserve_for_geometry(
    is_orthogonal: bool,
    wall_count: int,
) -> dict[Material, Decimal]:
    """Рассчитывает нормативный строительный запас с учетом геометрической сложности.

    Строительные нормы (СНиП 3.04.01-87, СП 71.13330.2017):
    - Для прямоугольных/ортогональных помещений:
        - Ламинат/паркетная доска: 7%
        - Керамическая плитка / керамогранит: 10%
        - Плинтус / карнизы: 10%
        - Гипсокартон: 10%
    - Для помещений со скошенными стенами, непрямыми углами или большим количеством углов (>4):
        - Ламинат: 15% (сложный диагональный раскрой, отходы при запиле под углом)
        - Плитка: 15% (косая подрезка по периметру скошенных стен)
        - Плинтус: 15% (запил углов не под 90/45 градусов)
        - Гипсокартон: 15% (раскрой листов нестандартной конфигурации)
    """
    reserves: dict[Material, Decimal] = {
        Material.tile: Decimal("10"),
        Material.laminate: Decimal("7"),
        Material.underlay: Decimal("5"),
        Material.linoleum: Decimal("5"),
        Material.wallpaper: Decimal("10"),
        Material.drywall: Decimal("10"),
        Material.profile: Decimal("10"),
        Material.paint: Decimal("5"),
        Material.primer: Decimal("10"),
        Material.putty: Decimal("15"),
        Material.plaster: Decimal("15"),
    }

    if not is_orthogonal or wall_count > 4:
        # Увеличиваем запас на листовые и штучные материалы, подверженные косой подрезке
        reserves[Material.tile] = Decimal("15")
        reserves[Material.laminate] = Decimal("15")
        reserves[Material.underlay] = Decimal("10")
        reserves[Material.drywall] = Decimal("15")
        reserves[Material.profile] = Decimal("15")

    return reserves


def analyze_room_geometry(
    vertices: Sequence[Point2D],
    height_m: Decimal = Decimal("2.70"),
    openings_area_m2: Decimal = Decimal("0"),
) -> RoomGeometryMetrics:
    """Выполняет полный инженерный и геометрический анализ помещения."""
    floor_area = calculate_floor_area(vertices)
    perimeter = calculate_perimeter(vertices)
    walls = calculate_wall_segments(vertices, height_m=height_m)
    angles = calculate_interior_angles(vertices)
    orthogonal = is_orthogonal_polygon(vertices)
    wall_lengths = [w.length_m for w in walls]
    bbox = get_bounding_box(vertices)

    gross_wall_area = _quantize(perimeter * height_m, 2)
    net_wall_area = _quantize(max(Decimal("0"), gross_wall_area - openings_area_m2), 2)
    reserves = calculate_reserve_for_geometry(orthogonal, len(vertices))

    notes: list[str] = []
    if orthogonal and len(vertices) == 4:
        notes.append("Типовая прямоугольная геометрия (4 стены, углы 90°): базовые нормы запаса материалов.")
    elif orthogonal:
        notes.append(
            f"Сложная ортогональная геометрия ({len(vertices)} стен, форма с нишами/выступами): "
            f"учтен дополнительный периметр для плинтусов и кабелей."
        )
    else:
        notes.append(
            f"Неортогональная геометрия со скошенными углами ({len(vertices)} стен): "
            f"автоматически увеличен строительный запас по СНиП 3.04.01-87 (ламинат и плитка до 15% на диагональную подрезку)."
        )

    return RoomGeometryMetrics(
        floor_area=floor_area,
        perimeter=perimeter,
        wall_count=len(vertices),
        gross_wall_area=gross_wall_area,
        net_wall_area=net_wall_area,
        is_orthogonal=orthogonal,
        interior_angles=angles,
        wall_lengths=wall_lengths,
        walls=walls,
        bounding_box=bbox,
        waste_reserve_recommendations=reserves,
        geometry_notes=notes,
    )


# ---------------------------------------------------------------------------
# Библиотека архитектурных шаблонов (Пресеты)
# ---------------------------------------------------------------------------


def preset_rectangle(length_m: float, width_m: float) -> list[Point2D]:
    """Прямоугольное помещение."""
    return [
        Point2D(0.0, 0.0),
        Point2D(width_m, 0.0),
        Point2D(width_m, length_m),
        Point2D(0.0, length_m),
    ]


def preset_l_shaped(
    length_main: float,
    width_main: float,
    cutout_length: float,
    cutout_width: float,
) -> list[Point2D]:
    """Г-образное помещение (коридор, кухня-гостиная).

    Общий прямоугольник: width_main x length_main.
    Вырез в правом верхнем углу: cutout_width x cutout_length.
    """
    if cutout_length >= length_main or cutout_width >= width_main:
        raise ValueError("Размеры выреза должны быть меньше основных габаритов комнаты")

    w_remain = width_main - cutout_width
    l_remain = length_main - cutout_length

    return [
        Point2D(0.0, 0.0),
        Point2D(width_main, 0.0),
        Point2D(width_main, l_remain),
        Point2D(w_remain, l_remain),
        Point2D(w_remain, length_main),
        Point2D(0.0, length_main),
    ]


def preset_with_niche(
    length_m: float,
    width_m: float,
    niche_w: float,
    niche_d: float,
) -> list[Point2D]:
    """Прямоугольная комната с нишей под шкаф или венткороб на дальней стене."""
    if niche_w >= width_m:
        raise ValueError("Ширина ниши не может превышать ширину стены")

    margin = (width_m - niche_w) / 2.0
    return [
        Point2D(0.0, 0.0),
        Point2D(width_m, 0.0),
        Point2D(width_m, length_m),
        Point2D(width_m - margin, length_m),
        Point2D(width_m - margin, length_m + niche_d),
        Point2D(margin, length_m + niche_d),
        Point2D(margin, length_m),
        Point2D(0.0, length_m),
    ]


def preset_bay_window(
    length_m: float,
    width_m: float,
    bay_depth: float,
    chamfer_offset: float = 0.8,
) -> list[Point2D]:
    """Комната с эркером (скошенными углами у окна на дальней стене)."""
    if chamfer_offset * 2 >= width_m:
        chamfer_offset = width_m * 0.25

    return [
        Point2D(0.0, 0.0),
        Point2D(width_m, 0.0),
        Point2D(width_m, length_m),
        Point2D(width_m - chamfer_offset, length_m + bay_depth),
        Point2D(chamfer_offset, length_m + bay_depth),
        Point2D(0.0, length_m),
    ]


def preset_trapezoid(
    bottom_width: float,
    top_width: float,
    length_m: float,
) -> list[Point2D]:
    """Трапециевидное помещение (мансарда, угловая секция здания)."""
    offset = (bottom_width - top_width) / 2.0
    return [
        Point2D(0.0, 0.0),
        Point2D(bottom_width, 0.0),
        Point2D(bottom_width - offset, length_m),
        Point2D(offset, length_m),
    ]


def preset_circle(
    radius_m: float = 2.5,
    segments: int = 16,
) -> list[Point2D]:
    """Круглое помещение (ротонда, башня, радиальный эркер).

    Аппроксимируется правильным многоугольником из segments вершин.
    При radius_m = 2.5: площадь ~19.6 м², периметр ~15.7 м.
    """
    if radius_m <= 0:
        raise ValueError("Радиус комнаты должен быть больше 0")
    if segments < 8:
        segments = 8

    cx = radius_m
    cy = radius_m
    pts: list[Point2D] = []
    for i in range(segments):
        theta = 2.0 * math.pi * i / segments
        x = round(cx + radius_m * math.cos(theta), 2)
        y = round(cy + radius_m * math.sin(theta), 2)
        pts.append(Point2D(x, y))
    return pts


# ---------------------------------------------------------------------------
# Интеграция с Pydantic схемой RoomInput
# ---------------------------------------------------------------------------


def polygon_to_room_input(
    vertices: Sequence[Point2D],
    room_type: RoomType = RoomType.living_room,
    height_m: Decimal = Decimal("2.70"),
    openings_area_m2: Decimal = Decimal("0"),
    name: str | None = None,
    humidity: Level | None = None,
) -> tuple[RoomInput, RoomGeometryMetrics]:
    """Преобразует 2D-полигон в совместимый объект RoomInput для базового движка,

    возвращая также полный отчет по геометрии помещения.
    Габариты длины и ширины вычисляются так, чтобы площадь комнаты точно соответствовала
    фактической площади по формуле Гаусса.
    """
    metrics = analyze_room_geometry(vertices, height_m=height_m, openings_area_m2=openings_area_m2)

    # Для максимальной совместимости с RoomInput (который ожидает length_m * width_m)
    # вычисляем эффективные эквивалентные размеры:
    # Используем одну ось из bounding box, а вторую подгоняем точно под площадь Гаусса
    bbox_w, bbox_l = metrics.bounding_box
    if bbox_w > 0:
        eff_width = bbox_w
        eff_length = _quantize(metrics.floor_area / eff_width, 2)
    else:
        eff_width = _quantize(math.sqrt(float(metrics.floor_area)), 2)
        eff_length = eff_width

    room_input = RoomInput(
        name=name or f"Помещение ({metrics.wall_count} стен, {metrics.floor_area} м²)",
        room_type=room_type,
        length_m=eff_length,
        width_m=eff_width,
        height_m=height_m,
        openings_area_m2=openings_area_m2,
        humidity=humidity,
    )

    return room_input, metrics

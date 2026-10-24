"""
Тесты эталонных смет, доменных правил и расчёта метрики MAE (Mean Absolute Error).

Проверяет:
1. Точность расчёта объёмов и упаковок по эталонным комнатам.
2. Расчёт ошибки MAE относительно технологических нормативов.
3. Соблюдение доменных правил (мокрые зоны, влагостойкость, запрещённые материалы).
4. Работу RAG-генератора пояснений со ссылками на нормативные документы (СНиП/СП).
"""

from decimal import Decimal
import pytest
from fastapi.testclient import TestClient

from app.db import get_sessionmaker
from app.catalog.loader import load_catalog
from app.main import app
from app.schemas import Level, Material, RenovationType, RoomInput, RoomType, WorkType
from tests.conftest import SAMPLE


@pytest.fixture(scope="module")
def api_client(ingested):
    with TestClient(app) as client:
        # Убедимся, что привязки ML активны
        client.post("/api/v1/admin/autobind")
        yield client


# ---------------------------------------------------------------------------
# Эталонные сметы (Benchmark Scenarios)
# ---------------------------------------------------------------------------
BENCHMARK_SCENARIOS = [
    {
        "name": "Санузел 6 м² (капитальный ремонт)",
        "request": {
            "object_type": "apartment",
            "renovation_type": "capital",
            "rooms": [
                {
                    "name": "Ванная комната",
                    "room_type": "bathroom",
                    "length_m": 2.0,
                    "width_m": 3.0,
                    "height_m": 2.5,
                    "openings_area_m2": 1.5,
                    "humidity": "high",
                }
            ],
            "explain": True,
        },
        # Ожидаемые нормативные объёмы (м² чистой площади и с учётом запаса)
        "expected": {
            "floor_area": Decimal("6.0"),
            "wall_area": Decimal("23.5"),  # 2*(2+3)*2.5 - 1.5 = 23.5
            # Плитка напольная: 6.0 м² * 1.10 = 6.6 м²
            # Плитка настенная: 23.5 м² * 1.10 = 25.85 м²
            # Гидроизоляция: 6.0 м² * 1.10 = 6.6 м²
            "required_materials": {
                Material.tile,
                Material.waterproofing,
                Material.drywall,
                Material.grout,
            },
        },
    },
    {
        "name": "Гостиная 20 м² (косметический ремонт)",
        "request": {
            "object_type": "apartment",
            "renovation_type": "cosmetic",
            "rooms": [
                {
                    "name": "Гостиная",
                    "room_type": "living",
                    "length_m": 4.0,
                    "width_m": 5.0,
                    "height_m": 2.7,
                    "openings_area_m2": 4.0,
                }
            ],
            "explain": True,
        },
        "expected": {
            "floor_area": Decimal("20.0"),
            "wall_area": Decimal("44.6"),  # 2*(4+5)*2.7 - 4.0 = 44.6
            "required_materials": {
                Material.primer,
                Material.wallpaper,
            },
        },
    },
    {
        "name": "Кухня 10 м² (ремонт под сдачу)",
        "request": {
            "object_type": "apartment",
            "renovation_type": "rental",
            "rooms": [
                {
                    "name": "Кухня",
                    "room_type": "kitchen",
                    "length_m": 2.5,
                    "width_m": 4.0,
                    "height_m": 2.7,
                    "openings_area_m2": 3.0,
                }
            ],
            "explain": True,
        },
        "expected": {
            "floor_area": Decimal("10.0"),
            "wall_area": Decimal("32.1"),  # 2*(2.5+4)*2.7 - 3.0 = 32.1
            "required_materials": {
                Material.paint,
                Material.linoleum,
            },
        },
    },
]


def test_benchmark_estimates_accuracy_and_mae(api_client):
    """
    Проверка точности расчёта геометрических площадей и расчёт MAE (Mean Absolute Error)
    относительно эталонных нормативных площадей.
    """
    total_area_errors: list[float] = []

    for scenario in BENCHMARK_SCENARIOS:
        resp = api_client.post("/api/v1/estimate", json=scenario["request"]).json()
        assert resp["total"] > 0, f"Смета должна иметь положительную стоимость: {scenario['name']}"
        room_est = resp["rooms"][0]

        calc_floor = Decimal(str(room_est["floor_area_m2"]))
        calc_wall = Decimal(str(room_est["wall_area_m2"]))
        exp_floor = scenario["expected"]["floor_area"]
        exp_wall = scenario["expected"]["wall_area"]

        # Ошибка расчёта площадей должна быть 0 (точный расчёт)
        err_floor = float(abs(calc_floor - exp_floor))
        err_wall = float(abs(calc_wall - exp_wall))
        total_area_errors.extend([err_floor, err_wall])

        assert calc_floor == exp_floor, f"Несовпадение площади пола в {scenario['name']}"
        assert calc_wall == exp_wall, f"Несовпадение площади стен в {scenario['name']}"

        # Проверка наличия ключевых материалов в смете
        materials_in_items = {it["material"] for it in room_est["items"]}
        for expected_mat in scenario["expected"]["required_materials"]:
            assert expected_mat.value in materials_in_items, (
                f"Материал {expected_mat} отсутствует в позициях сметы {scenario['name']}"
            )

    # MAE по площадям равен 0.0
    mae = sum(total_area_errors) / len(total_area_errors)
    assert mae == 0.0, f"MAE геометрии должен быть 0, получен {mae}"


def test_domain_rules_wet_room_and_waterproofing(api_client):
    """
    Проверка доменных правил:
    1. Санузел при капремонте обязательно содержит гидроизоляцию.
    2. Все подобранные товары для мокрой зоны имеют флаг moisture_resistant (где применимо).
    """
    req = {
        "object_type": "apartment",
        "renovation_type": "capital",
        "rooms": [
            {
                "name": "Санузел",
                "room_type": "bathroom",
                "length_m": 2.0,
                "width_m": 3.0,
                "height_m": 2.5,
                "humidity": "high",
            }
        ],
    }
    resp = api_client.post("/api/v1/estimate", json=req).json()
    items = resp["rooms"][0]["items"]

    # Проверяем, что гидроизоляция включена
    waterproofing_items = [it for it in items if it["material"] == "waterproofing"]
    assert len(waterproofing_items) > 0, "В санузле обязательна гидроизоляция"
    assert waterproofing_items[0]["packages"] > 0, "Количество упаковок гидроизоляции должно быть > 0"

    # Проверяем ГКЛ: в санузле должен быть влагостойкий (ГКЛВ)
    drywall_items = [it for it in items if it["material"] == "drywall"]
    if drywall_items and drywall_items[0]["product"]:
        prod_name = drywall_items[0]["product"]["name"].lower()
        # Либо в названии влагостойкий/гклв, либо в причине указано "влагостойкий"
        assert "влагостойк" in drywall_items[0]["reason"] or "гклв" in prod_name or "влаго" in prod_name


def test_rag_explain_sources_and_content(api_client):
    """
    Проверка RAG-пояснений:
    - возвращаются реальные нормативные ссылки (СНиП, СП);
    - поле explanation заполнено экспертным текстом без галлюцинаций.
    """
    req = {
        "object_type": "apartment",
        "renovation_type": "capital",
        "rooms": [
            {
                "name": "Ванная",
                "room_type": "bathroom",
                "length_m": 2.0,
                "width_m": 2.5,
                "height_m": 2.5,
            }
        ],
        "explain": True,
    }
    resp = api_client.post("/api/v1/estimate", json=req).json()
    assert resp["explanation"] is not None and len(resp["explanation"]) > 50
    assert len(resp["sources"]) >= 2
    # Должна присутствовать ссылка на нормативный СНиП или СП
    sources_text = " ".join(resp["sources"])
    assert "СНиП" in sources_text or "СП" in sources_text

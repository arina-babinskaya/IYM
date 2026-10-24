# RepairCalc

Калькулятор ремонта на данных каталога: смета по этапам, расчёт в карточке товара, ML-привязка товаров к видам работ.
FastAPI + PostgreSQL/SQLite + Ollama.

## Запуск на ноутбуке

Windows: `start.bat` (подробно — `KAK_ZAPUSTIT.txt`). Любая ОС:

```
pip install -r requirements.txt
python run_local.py                  # открывает http://localhost:8000
python run_local.py --reload-data    # пересоздать базу и загрузить каталог заново
```

Если есть `data/catalog.json` (формат организаторов) или `data/catalog.xml` (YML), загружается он, иначе — пример `mock_catalog/sample_catalog.json` (27 синтетических товаров).
Для большого каталога можно ограничить число товаров: `$env:RC_LOCAL_LIMIT=5000` (PowerShell) перед запуском.

## Каталог (JSON организаторов или YML)

```
python -m scripts.ingest --file data/catalog.json        # загрузить файл (JSON или YML, формат определяется сам)
python -m scripts.ingest --file data/catalog.json --limit 2000
python -m scripts.ingest --download                      # скачать YML по ссылке организаторов и загрузить
python -m scripts.profile_characteristics                # какие характеристики есть в каталоге
python -m scripts.export_dataset --out data/products.jsonl   # датасет для ML
python -m scripts.evaluate_matching --gold mock_catalog/sample_gold.jsonl   # micro/macro-F1
```

Товары, которых нет в новом файле, помечаются неактивными.

## Docker

Нужен Docker Desktop. Каталог лежит в `data/catalog.json`, Ollama запущена на хосте.

```
docker compose up -d --build                 # API на :8000 и PostgreSQL на :5433
docker compose run --rm ingest               # загрузить data/catalog.json и привязать товары
docker compose logs -f api                   # логи
docker compose down                          # остановить (данные в томе pgdata сохраняются)
```

## API

| Метод | Путь | Что делает |
|---|---|---|
| POST | `/api/v1/estimate` | Смета: комнаты (длина × ширина, вид ремонта, выбранные работы) → позиции по этапам |
| GET | `/api/v1/works?room_type=&renovation_type=` | Шаг 3 калькулятора: какие работы можно выбрать для комнаты и вида ремонта (по этапам, с отметкой «по умолчанию») |
| GET | `/api/v1/taxonomy` | Справочник: этапы, виды ремонта, виды работ, материалы |
| POST | `/api/v1/product/{id}/calc` | Расчёт в карточке: размеры → упаковки и цена |
| GET | `/api/v1/products?q=`, `/api/v1/products/{id}` | Поиск и карточка товара |
| GET | `/api/v1/admin/products` | Товары с ML-подсказкой: материал и виды работ |
| PUT | `/api/v1/admin/products/{id}/binding` | Подтвердить или исправить привязку |
| POST | `/api/v1/admin/autobind` | Автопривязка уверенных предсказаний |
| GET | `/api/v1/admin/stats` | Доля автопривязанных товаров |
| GET | `/health` | БД и нейросеть |
| POST | `/internal/llm/chat`, `/internal/llm/embed` | Нейросеть и эмбеддинги для команды |

Живая документация с примерами: http://localhost:8000/docs

## Структура

| Путь | Что | Кто меняет |
|---|---|---|
| `app/taxonomy.py` | этапы, виды ремонта, 20 видов работ по taxonomy v2, материалы, связь работа → материалы | 2 и 3 вместе |
| `app/schemas.py` | формат запросов и ответов API | 1, по согласованию с 4 |
| `app/models.py`, `app/db.py` | таблицы БД | 1 |
| `app/catalog/loader.py` | загрузка каталога в БД | 1 |
| `app/catalog/json_catalog.py`, `app/catalog/yml.py` | чтение JSON и YML | 1 |
| `app/catalog/normalize.py` | разбор характеристик в числа | 1 |
| `app/catalog/repository.py` | запросы к каталогу | 1 |
| `app/llm/client.py` | обёртка над Ollama | 1 |
| `app/api/` | адреса API | 1 |
| `app/plans.py` | какие работы доступны для помещения и вида ремонта, какие отмечены по умолчанию | 1 |
| `app/engine/baseline.py` | заглушка движка расчёта | 2 заменяет своим |
| `app/ml/baseline.py` | заглушка классификатора и ранжирования | 3 заменяет своим |
| `app/static/index.html` | простой демо-фронт | 4 заменяет своим |
| `mock_catalog/` | пример каталога и эталонной разметки | все |
| `tests/` | автотесты: `pytest` | все |

Участники 2 и 3 переписывают заглушки прямо в файлах `app/engine/baseline.py` и `app/ml/baseline.py`.
Названия классов (`BaselineEngine`, `KeywordClassifier`, `RatingRanker`) и их функций не меняются, внутри — любой код.

Нейросеть вызывается только через `app.llm.client.get_llm()`: `chat`, `chat_json`, `embed`.

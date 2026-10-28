import asyncio
import os
import sys
import threading
import webbrowser
from pathlib import Path

os.environ.setdefault("RC_DATABASE_URL", "sqlite:///./repaircalc_local.sqlite")
os.environ.setdefault("RC_LLM_MODEL", "qwen2.5:3b")
os.environ.setdefault("RC_RANKER_IMPL", "app.ml.ranker:ContextRanker")

import uvicorn
from sqlalchemy import func, select

from app.api.routes import admin_autobind
from app.catalog.repository import CatalogRepo
from app.catalog.loader import load_catalog
from app.config import get_settings
from app.db import get_sessionmaker, init_db
from app.models import Product, ProductBinding

PORT = 8000
SAMPLE = Path("mock_catalog/sample_catalog.json")


def seed() -> None:
    init_db()
    with get_sessionmaker()() as session:
        products = session.scalar(select(func.count()).select_from(Product)) or 0
        if not products:
            candidates = [Path(get_settings().catalog_path), Path("data/catalog.json"), Path("data/catalog.xml")]
            source = next((c for c in candidates if c.exists()), SAMPLE)
            limit = int(os.environ.get("RC_LOCAL_LIMIT", "0")) or None
            print(f"Первый запуск: загружаю каталог из {source}" + (f" (первые {limit} товаров)" if limit else "") + "…")
            stats = load_catalog(session, source, max_offers=limit)
            products = stats.offers
            print(f"Товаров: {stats.offers}, категорий: {stats.categories}")
        bindings = session.scalar(select(func.count()).select_from(ProductBinding)) or 0
        if products and not bindings:
            print("В каталоге нет привязок. Запускаю безопасную TF-IDF привязку без GigaChat…")
            result = asyncio.run(admin_autobind(
                min_confidence=get_settings().autobind_min_confidence, batch=1000,
                use_gigachat=False, repo=CatalogRepo(session)))
            print(f"Привязано автоматически: {result.bound_ml} из {result.products_total}")


if __name__ == "__main__":
    if "--reload-data" in sys.argv and Path("repaircalc_local.sqlite").exists():
        Path("repaircalc_local.sqlite").unlink()
    seed()
    from app.main import app

    url = f"http://localhost:{PORT}"
    print(f"\nОткрой в браузере: {url}   (документация API: {url}/docs)\nОстановить: Ctrl+C\n")
    threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")

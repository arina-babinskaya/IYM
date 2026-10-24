import argparse
import json
import logging
import time
from pathlib import Path

import httpx

from app.api.routes import admin_autobind
from app.catalog.loader import load_catalog
from app.catalog.repository import CatalogRepo
from app.config import get_settings
from app.db import get_sessionmaker, init_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("ingest")


def download(url: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".part")
    log.info("скачиваю %s", url)
    with httpx.stream("GET", url, timeout=get_settings().catalog_timeout_s, follow_redirects=True) as r:
        r.raise_for_status()
        with tmp.open("wb") as f:
            for chunk in r.iter_bytes(1 << 20):
                f.write(chunk)
    tmp.replace(dest)
    log.info("сохранено %s (%.1f МБ)", dest, dest.stat().st_size / 1e6)
    return dest


def main() -> None:
    s = get_settings()
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=s.catalog_path)
    ap.add_argument("--download", action="store_true")
    ap.add_argument("--url", default=s.catalog_yml_url)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--categories", type=int, nargs="*")
    ap.add_argument("--every", type=float)
    ap.add_argument("--no-autobind", action="store_true")
    args = ap.parse_args()

    init_db()
    while True:
        t0 = time.time()
        path = Path(args.file)
        if args.download:
            path = download(args.url, path.with_suffix(".xml"))
        with get_sessionmaker()() as session:
            stats = load_catalog(session, path, max_offers=args.limit,
                                 category_ids=set(args.categories) if args.categories else None)
            if not args.no_autobind:
                bound = admin_autobind(min_confidence=get_settings().autobind_min_confidence, batch=1000, repo=CatalogRepo(session))
                log.info("привязано автоматически: %d из %d", bound.bound_ml, bound.products_total)
        log.info("готово за %.0f с: %s", time.time() - t0, json.dumps(stats.__dict__, ensure_ascii=False))
        if not args.every:
            break
        time.sleep(max(0.0, args.every * 60 - (time.time() - t0)))


if __name__ == "__main__":
    main()

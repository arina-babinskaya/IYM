import logging
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import delete, update
from sqlalchemy.orm import Session

from app.catalog import json_catalog, yml
from app.db import upsert
from app.models import Category, IngestRun, Product, ProductCategory, ProductCharacteristic

log = logging.getLogger(__name__)

Rows = tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]


@dataclass
class LoadStats:
    format: str = ""
    categories: int = 0
    offers: int = 0
    skipped: int = 0
    deactivated: int = 0
    params_total: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass
class Format:
    name: str
    events: Callable[[Path], Iterator[tuple[str, dict[str, Any]]]]
    key: Callable[[dict[str, Any]], int]
    category_ids: Callable[[dict[str, Any]], list[str]]
    rows: Callable[[dict[str, Any], dict[str, list[dict[str, Any]]]], Rows]


YML = Format(
    "yml",
    yml.iter_yml,
    lambda o: yml.product_id(o["id"]) if o.get("id") else -1,
    lambda o: o["category_ids"],
    yml.offer_rows,
)
JSON = Format(
    "json",
    lambda p: (("offer", item) for item in json_catalog.iter_json(p)),
    lambda o: int(o["id"]) if o.get("id") is not None else -1,
    lambda o: [str(k) for k in (o.get("categories") or {})],
    json_catalog.product_rows,
)


def detect_format(path: Path) -> Format:
    if path.suffix.lower() == ".json":
        return JSON
    with path.open("rb") as f:
        head = f.read(512).lstrip()
    return JSON if head[:1] in (b"{", b"[") else YML


def load_catalog(
    session: Session,
    path: str | Path,
    max_offers: int | None = None,
    category_ids: set[int] | None = None,
    batch_size: int = 500,
    deactivate_missing: bool = True,
) -> LoadStats:
    path = Path(path)
    fmt = detect_format(path)
    stats = LoadStats(format=fmt.name)
    run = IngestRun(source=str(path), status="running")
    session.add(run)
    session.commit()
    run_id = run.id

    cats: dict[str, dict[str, Any]] = {}
    paths: dict[str, list[dict[str, Any]]] = {}
    known_categories: set[int] = set()
    seen: set[int] = set()
    batch: list[dict[str, Any]] = []

    def save_tree() -> None:
        paths.update(yml.category_paths(cats))
        rows = [
            {"id": int(cid), "parent_id": int(c["parent_id"]) if c["parent_id"] and c["parent_id"].isdigit() else None,
             "name": c["name"] or f"#{cid}", "path": paths.get(cid)}
            for cid, c in cats.items() if cid.isdigit()
        ]
        upsert(session, Category, rows, ["id"])
        session.commit()
        known_categories.update(r["id"] for r in rows)
        cats.clear()

    def wanted(record: dict[str, Any]) -> bool:
        if not category_ids:
            return True
        for cid in fmt.category_ids(record):
            nodes = paths.get(cid) or ([{"id": int(cid)}] if cid.isdigit() else [])
            if any(node["id"] in category_ids for node in nodes):
                return True
        return False

    def flush() -> None:
        if not batch:
            return
        products, chars, links, new_cats = {}, [], [], {}
        for record in batch:
            row, ch, ln = fmt.rows(record, paths)
            row["last_seen_run"] = run_id
            products[row["id"]] = row
            chars += ch
            links += ln
            for cid, name in row["categories"].items():
                if int(cid) not in known_categories:
                    new_cats[int(cid)] = {"id": int(cid), "parent_id": None, "name": name,
                                          "path": [{"id": int(cid), "name": name}]}
        if new_cats:
            upsert(session, Category, list(new_cats.values()), ["id"], update=False)
            known_categories.update(new_cats)
            stats.categories += len(new_cats)
        ids = list(products)
        upsert(session, Product, list(products.values()), ["id"])
        session.execute(delete(ProductCharacteristic).where(ProductCharacteristic.product_id.in_(ids)))
        upsert(session, ProductCharacteristic, chars, ["product_id", "code"])
        session.execute(delete(ProductCategory).where(ProductCategory.product_id.in_(ids)))
        upsert(session, ProductCategory, links, ["product_id", "category_id"])
        session.commit()
        stats.params_total += len(chars)
        batch.clear()
        log.info("товаров: %d", stats.offers)

    status, error = "failed", None
    try:
        for kind, record in fmt.events(path):
            if kind == "category":
                cats[record["id"]] = record
                continue
            if cats:
                save_tree()
            key = fmt.key(record)
            if key < 0 or not wanted(record):
                stats.skipped += 1
                continue
            if key in seen:
                continue
            seen.add(key)
            batch.append(record)
            stats.offers += 1
            if len(batch) >= batch_size:
                flush()
            if max_offers and stats.offers >= max_offers:
                break
        if cats:
            save_tree()
        flush()
        stats.categories = max(stats.categories, len(known_categories))
        if deactivate_missing and not max_offers and not category_ids and seen:
            res = session.execute(
                update(Product)
                .where(Product.status.is_(True))
                .where((Product.last_seen_run.is_(None)) | (Product.last_seen_run != run_id))
                .values(status=False)
            )
            stats.deactivated = res.rowcount or 0
            session.commit()
        status = "ok"
    except Exception as e:
        session.rollback()
        error = repr(e)
        raise
    finally:
        session.execute(
            update(IngestRun).where(IngestRun.id == run_id).values(
                status=status, error=error, finished_at=datetime.now(UTC),
                stats={k: v for k, v in stats.__dict__.items() if k != "errors"},
            )
        )
        session.commit()
    return stats

"""Narrow reconciliation for evidence-backed renovation bindings.

Dry-run is the default.  Applying requires both ``--apply`` and an explicit SQLite backup path.
The full-catalog classifier and ``catalog_category_assignments`` are never read or written.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_engine
from app.ml.tfidf import TfidfClassifier, _direct_material, publishable
from app.models import Product, ProductBinding
from app.schemas import Suggestion


@dataclass(frozen=True)
class Change:
    product_id: int
    name: str
    action: str
    reason: str
    before: dict[str, Any] | None
    after: dict[str, Any]


def binding_values(binding: ProductBinding | None) -> dict[str, Any] | None:
    if binding is None:
        return None
    return {
        "product_category": binding.product_category,
        "material": binding.material,
        "work_types": list(binding.work_types or []),
        "room_types": list(binding.room_types or []),
        "flags": dict(binding.flags or {}),
        "source": binding.source,
        "confidence": binding.confidence,
        "confirmed": bool(binding.confirmed),
    }


def suggestion_values(suggestion: Suggestion) -> dict[str, Any]:
    return {
        "product_category": suggestion.product_category.value if suggestion.product_category else None,
        "material": suggestion.material.value,
        "work_types": [item.value for item in suggestion.work_types],
        "room_types": [item.value for item in suggestion.room_types],
        "flags": dict(suggestion.flags),
        "source": "ml",
        "confidence": suggestion.confidence,
        "confirmed": False,
    }


def scoped_products(session: Session) -> list[Product]:
    """Find only products recognized by the audited direct-evidence rules."""
    products = session.scalars(select(Product).where(Product.status.isnot(False)).order_by(Product.id)).all()
    return [product for product in products if _direct_material(product)[0] is not None]


def build_plan(
    session: Session,
    classifier: Any,
    min_confidence: float = .7,
    products: Iterable[Product] | None = None,
) -> tuple[list[Change], list[dict[str, Any]]]:
    selected = list(products) if products is not None else scoped_products(session)
    changes: list[Change] = []
    skipped: list[dict[str, Any]] = []
    for start in range(0, len(selected), 500):
        batch = selected[start:start + 500]
        suggestions = classifier.predict(batch)
        if len(suggestions) != len(batch):
            raise RuntimeError(f"classifier returned {len(suggestions)} suggestions for {len(batch)} products")
        for product, suggestion in zip(batch, suggestions, strict=True):
            binding = session.get(ProductBinding, product.id)
            rule = next((key.removeprefix("adapter_rule__") for key, value in suggestion.flags.items()
                         if value and key.startswith("adapter_rule__")), "direct_evidence")
            if binding is not None and binding.confirmed:
                skipped.append({"product_id": product.id, "reason": "confirmed_binding_preserved"})
                continue
            if not publishable(suggestion, min_confidence):
                skipped.append({"product_id": product.id, "reason": "suggestion_not_publishable",
                                "confidence": suggestion.confidence, "rule": rule})
                continue
            before, after = binding_values(binding), suggestion_values(suggestion)
            comparable = ("product_category", "material", "work_types", "room_types")
            if before is not None and all(before[key] == after[key] for key in comparable):
                continue
            changes.append(Change(product.id, product.name, "insert" if binding is None else "update",
                                  rule, before, after))
    return changes, skipped


def apply_plan(session: Session, changes: Iterable[Change]) -> int:
    count = 0
    for change in changes:
        binding = session.get(ProductBinding, change.product_id)
        if binding is not None and binding.confirmed:
            continue
        if binding is None:
            binding = ProductBinding(product_id=change.product_id)
        for key, value in change.after.items():
            setattr(binding, key, value)
        session.add(binding)
        count += 1
    session.commit()
    return count


def backup_sqlite(database_path: Path, backup_path: Path) -> None:
    if backup_path.exists():
        raise FileExistsError(f"refusing to overwrite backup: {backup_path}")
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(f"file:{database_path}?mode=ro", uri=True) as source, sqlite3.connect(backup_path) as target:
        source.backup(target)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="apply the reported changes")
    parser.add_argument("--backup-path", type=Path, help="required new SQLite backup file when applying")
    parser.add_argument("--report", type=Path, help="optional JSON report path")
    args = parser.parse_args()
    settings = get_settings()
    if not settings.database_url.startswith("sqlite:///./"):
        raise SystemExit("this guarded tool currently supports local relative SQLite databases only")
    database_path = Path(settings.database_url.removeprefix("sqlite:///./")).resolve()
    classifier = TfidfClassifier(settings.ml_classifier_artifact_path)
    with Session(get_engine()) as session:
        changes, skipped = build_plan(session, classifier, settings.autobind_min_confidence)
        report = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "mode": "apply" if args.apply else "dry-run",
            "database": str(database_path),
            "changes": [asdict(item) for item in changes],
            "skipped": skipped,
        }
        rendered = json.dumps(report, ensure_ascii=False, indent=2, default=str)
        print(rendered)
        if args.report:
            args.report.write_text(rendered + "\n", encoding="utf-8")
        if not args.apply:
            return
        if args.backup_path is None:
            raise SystemExit("--apply requires --backup-path; no changes were made")
        backup_sqlite(database_path, args.backup_path.resolve())
        applied = apply_plan(session, changes)
        print(json.dumps({"applied": applied, "backup": str(args.backup_path.resolve())}, ensure_ascii=False))


if __name__ == "__main__":
    main()

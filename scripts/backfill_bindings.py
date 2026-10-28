"""Preview or safely persist missing deterministic TF-IDF product bindings.

GigaChat is never called by this command. Existing bindings are excluded and the repository uses
insert-on-conflict-do-nothing, so manually confirmed and historical rows cannot be overwritten.
"""
from __future__ import annotations

import argparse
import asyncio
import json

from app.api.deps import get_classifier
from app.api.routes import admin_autobind
from app.catalog.repository import CatalogRepo
from app.config import get_settings
from app.db import get_sessionmaker, init_db
from app.ml.tfidf import publishable


def preview(repo: CatalogRepo, threshold: float, batch: int) -> dict[str, int | float | bool]:
    classifier = get_classifier()
    scanned = eligible = 0
    after_id = -1
    while products := repo.unbound(batch, after_id):
        after_id = products[-1].id
        suggestions = classifier.predict(products)
        scanned += len(products)
        eligible += sum(publishable(item, threshold) for item in suggestions)
    total, manual, automatic = repo.binding_counts()
    return {
        "apply": False, "threshold": threshold, "products_total": total,
        "existing_manual": manual, "existing_automatic": automatic,
        "unbound_scanned": scanned, "eligible_new_bindings": eligible,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="persist missing safe TF-IDF bindings")
    parser.add_argument("--batch", type=int, default=1000)
    parser.add_argument("--threshold", type=float, default=get_settings().autobind_min_confidence)
    args = parser.parse_args()
    if not 0 <= args.threshold <= 1:
        parser.error("--threshold must be between 0 and 1")
    if not 1 <= args.batch <= 5000:
        parser.error("--batch must be between 1 and 5000")

    init_db()
    with get_sessionmaker()() as session:
        repo = CatalogRepo(session)
        if args.apply:
            result = asyncio.run(admin_autobind(min_confidence=args.threshold, batch=args.batch,
                                                use_gigachat=False, repo=repo))
            output = {"apply": True, "threshold": args.threshold, **result.model_dump()}
        else:
            output = preview(repo, args.threshold, args.batch)
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

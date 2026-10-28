"""Classify a small, explicit unbound subset with the optional GigaChat fallback.

Examples:
  python -m scripts.gigachat_fallback --limit 20                 # no API calls
  python -m scripts.gigachat_fallback --limit 20 --use-api       # call/cache, no DB writes
  python -m scripts.gigachat_fallback --ids 1 2 --use-api --apply
"""
from __future__ import annotations

import argparse
import asyncio
import json

from sqlalchemy import select

from app.api.deps import get_classifier, get_gigachat
from app.catalog.repository import CatalogRepo
from app.config import get_settings
from app.db import get_sessionmaker, init_db
from app.llm.gigachat import GigaChatError
from app.ml.hybrid import decide_hybrid, eligible_for_gigachat
from app.models import Product, ProductBinding
from app.schemas import Suggestion
from app.taxonomy import Material


async def run(args: argparse.Namespace) -> dict:
    settings = get_settings()
    if args.apply and not args.use_api:
        raise SystemExit("--apply requires --use-api")
    init_db()
    counts = {"selected": 0, "api": 0, "accepted": 0, "review": 0, "rejected": 0, "errors": 0, "saved": 0}
    with get_sessionmaker()() as session:
        repo = CatalogRepo(session)
        query = select(Product).outerjoin(ProductBinding).where(ProductBinding.product_id.is_(None))
        if args.ids:
            query = query.where(Product.id.in_(args.ids))
        products = list(session.scalars(query.order_by(Product.id).limit(args.limit)))
        base = get_classifier().predict(products)
        uncertain = [(p, s) for p, s in zip(products, base, strict=True)
                     if eligible_for_gigachat(s, settings.autobind_min_confidence)]
        counts["selected"] = len(uncertain)
        if not args.use_api:
            return {**counts, "dry_run": True, "candidate_ids": [p.id for p, _ in uncertain]}
        client = get_gigachat()
        for product, existing in uncertain:
            try:
                result = await client.classify(product, existing)
                counts["api"] += 1
            except GigaChatError:
                counts["errors"] += 1
                continue
            policy = decide_hybrid(existing, result, settings.autobind_min_confidence)
            if result.decision != "accept":
                counts["rejected" if result.decision == "reject" else "review"] += 1
                continue
            if policy.action != "accept_gigachat":
                counts["review"] += 1
                continue
            counts["accepted"] += 1
            if args.apply:
                suggestion = Suggestion(
                    product_category=result.product_category, material=result.material,
                    work_types=result.work_types, confidence=args.acceptance_score,
                    flags={"gigachat_validated": True}, model=f"gigachat:{settings.gigachat_model}",
                )
                repo.save_ml_bindings([(product.id, suggestion)])
                counts["saved"] += 1
        return {**counts, "dry_run": not args.apply, "client": client.stats}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ids", type=int, nargs="*")
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--use-api", action="store_true", help="perform sequential cached API calls")
    parser.add_argument("--apply", action="store_true", help="save accepted bindings; otherwise DB is unchanged")
    parser.add_argument("--acceptance-score", type=float, default=0.8,
                        help="policy score, not GigaChat self-confidence")
    parser.add_argument("--cache-namespace",
                        help="new namespace reruns the same products without deleting historical cache")
    args = parser.parse_args()
    if args.cache_namespace:
        get_settings().gigachat_cache_namespace = args.cache_namespace
    print(json.dumps(asyncio.run(run(args)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

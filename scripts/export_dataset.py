import argparse
import json
import re
from pathlib import Path

from sqlalchemy import select

from app.db import get_sessionmaker
from app.models import Product, ProductBinding, ProductCharacteristic

_TAGS = re.compile(r"<[^>]+>")


def product_text(p: Product, chars: list[ProductCharacteristic]) -> str:
    path = " / ".join(x.get("name", "") for x in (p.categories_tree or [])) or " / ".join((p.categories or {}).values())
    props = "; ".join(f"{c.name}: {c.value_raw}" for c in chars if c.value_raw)
    desc = _TAGS.sub(" ", p.description or "")[:500]
    return " | ".join(x for x in [p.name, path, p.brand_name or "", props, desc] if x)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/products.jsonl")
    ap.add_argument("--with-bindings-only", action="store_true")
    args = ap.parse_args()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    with get_sessionmaker()() as s, out.open("w", encoding="utf-8") as f:
        chars: dict[int, list[ProductCharacteristic]] = {}
        for c in s.scalars(select(ProductCharacteristic)):
            chars.setdefault(c.product_id, []).append(c)
        bindings = {b.product_id: b for b in s.scalars(select(ProductBinding))}
        n = 0
        for p in s.scalars(select(Product).where(Product.status.isnot(False)).order_by(Product.id)):
            b = bindings.get(p.id)
            if args.with_bindings_only and not b:
                continue
            row = {
                "id": p.id, "sku": p.sku, "name": p.name, "brand": p.brand_name,
                "categories": p.categories, "categories_tree": p.categories_tree,
                "characteristics": {c.code: {"name": c.name, "value": c.value_raw} for c in chars.get(p.id, [])},
                "specs": p.specs, "unit": p.unit,
                "result_price": float(p.result_price) if p.result_price is not None else None,
                "rating": float(p.rating) if p.rating is not None else None, "recsys_rating": p.recsys_rating,
                "in_stock": p.in_stock, "text": product_text(p, chars.get(p.id, [])),
                "label": None if not b else {"material": b.material, "work_types": b.work_types,
                                             "room_types": b.room_types, "flags": b.flags,
                                             "source": b.source, "confirmed": b.confirmed},
            }
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            n += 1
    print(f"{n} товаров → {out}")


if __name__ == "__main__":
    main()

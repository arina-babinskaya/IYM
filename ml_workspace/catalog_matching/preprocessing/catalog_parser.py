from __future__ import annotations

import json, re
from pathlib import Path
from typing import Iterator

TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")

def clean_text(value: object) -> str:
    return SPACE_RE.sub(" ", TAG_RE.sub(" ", str(value or ""))).strip()

def normalize_name(value: object) -> str:
    return SPACE_RE.sub(" ", re.sub(r"[^\w]+", " ", clean_text(value).casefold())).strip()

def source_category(product: dict) -> tuple[str, str]:
    categories = product.get("categories") or {}
    if not categories:
        return "", ""
    key, value = next(reversed(categories.items()))
    return str(key), clean_text(value)

def characteristics_text(product: dict) -> str:
    return " ".join(
        f"{clean_text(x.get('name'))}: {clean_text(x.get('value'))}"
        for x in (product.get("characteristics") or []) if isinstance(x, dict)
    )

def iter_products(path: str | Path) -> Iterator[dict]:
    # The supplied file is one JSON object, so stdlib parsing intentionally avoids a new dependency.
    with Path(path).open(encoding="utf-8") as fh:
        data = json.load(fh)
    products = data.get("products") if isinstance(data, dict) else data
    if not isinstance(products, list):
        raise ValueError("catalog JSON must contain a products list")
    yield from products

def inspection_row(product: dict) -> dict:
    source_id, source_name = source_category(product)
    return {
        "product_id": str(product.get("id", "")), "sku": str(product.get("cod_good", "")),
        "name": clean_text(product.get("name")), "description": clean_text(product.get("description")),
        "marketing_description": clean_text(product.get("marketing_description")),
        "brand": clean_text(product.get("brand")), "source_category_id": source_id,
        "source_category_name": source_name, "characteristics_text": characteristics_text(product),
    }

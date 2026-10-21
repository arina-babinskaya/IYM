import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from app.catalog import normalize as nz
from app.catalog.yml import PACK_AREA_PARAM, PACK_QTY_PARAM, UNIT_PARAM

SKIP_CHARACTERISTICS = {"Маркетинговое описание товара"}
WS = re.compile(r"[\s,]*")
NUMBER = re.compile(r"\d+(?:[.,]\d+)?")


def iter_json(path: str | Path, chunk_size: int = 1 << 20) -> Iterator[dict[str, Any]]:
    decoder = json.JSONDecoder()
    with open(path, encoding="utf-8") as f:
        buf = ""
        while "[" not in buf:
            data = f.read(chunk_size)
            if not data:
                return
            buf += data
        pos = buf.index("[") + 1
        eof = False
        while True:
            pos = WS.match(buf, pos).end()
            if pos < len(buf) and buf[pos] == "]":
                return
            try:
                obj, end = decoder.raw_decode(buf, pos)
            except json.JSONDecodeError:
                if eof:
                    raise
                data = f.read(chunk_size)
                eof = not data
                buf = buf[pos:] + data
                pos = 0
                continue
            yield obj
            pos = end
            if pos > chunk_size:
                buf, pos = buf[pos:], 0


def _first_number(value: str) -> Any:
    m = NUMBER.search(value or "")
    return nz.to_decimal(m.group()) if m else None


def product_rows(
    item: dict[str, Any], paths: dict[str, list[dict[str, Any]]]
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    pid = int(item["id"])
    characteristics, qty_in_pack, pack_area, unit = [], None, None, item.get("unit")
    for ch in item.get("characteristics") or []:
        name, value = (ch.get("name") or "").strip(), ch.get("value")
        if not name or value in (None, "") or name in SKIP_CHARACTERISTICS:
            continue
        value = str(value).strip()
        characteristics.append({"code": name, "name": name, "value": value})
        if UNIT_PARAM.search(name) and not unit:
            unit = value
        elif PACK_QTY_PARAM.search(name):
            qty_in_pack = _first_number(value)
        elif PACK_AREA_PARAM.search(name):
            pack_area = _first_number(value)

    categories = {str(k): v for k, v in (item.get("categories") or {}).items() if str(k).isdigit()}
    first = next(iter(categories), None)
    price = nz.to_decimal(item.get("price"))
    brand = item.get("brand") or {}
    row = {
        "id": pid,
        "sku": None,
        "cod_good": None if item.get("cod_good") is None else str(item["cod_good"]),
        "name": (item.get("name") or f"#{pid}")[:1024],
        "description": item.get("marketing_description") or item.get("description"),
        "url_key": item.get("url_key"),
        "picture_url": None,
        "brand_name": brand.get("name"),
        "status": True,
        "currency": item.get("currency") or "RUB",
        "price": price,
        "result_price": nz.to_decimal(item.get("result_price")) or price,
        "old_price": nz.to_decimal(item.get("old_price")),
        "unit": unit,
        "quantity_in_package": qty_in_pack,
        "package_area": pack_area,
        "in_stock": item.get("in_stock"),
        "categories": categories,
        "categories_tree": paths.get(first) or ([{"id": int(first), "name": categories[first]}] if first else []),
        "specs": nz.extract_specs(characteristics, pack_area, qty_in_pack),
        "raw": item,
    }
    links = [{"product_id": pid, "category_id": int(c)} for c in categories]
    return row, nz.characteristic_rows(pid, characteristics), links

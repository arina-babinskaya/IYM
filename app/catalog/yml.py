import hashlib
import logging
import re
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from app.catalog import normalize as nz

log = logging.getLogger(__name__)

UNIT_PARAM = re.compile(r"ед\.?\s*изм|единица\s+(измерения|продажи)", re.IGNORECASE)
PACK_QTY_PARAM = re.compile(r"(кол-во|количество)\s+(в|штук в)\s+упак", re.IGNORECASE)
PACK_AREA_PARAM = re.compile(r"площадь.*упаков|упаковк.*площад|м2 в упаковке|м² в упаковке", re.IGNORECASE)


def product_id(offer_id: str) -> int:
    if offer_id.isdigit() and len(offer_id) <= 15:
        return int(offer_id)
    return int(hashlib.sha1(offer_id.encode()).hexdigest()[:13], 16)


def _text(el: ET.Element | None) -> str | None:
    if el is None or el.text is None:
        return None
    return el.text.strip() or None


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def iter_yml(path: str | Path) -> Iterator[tuple[str, dict[str, Any]]]:
    for _, el in ET.iterparse(path, events=("end",)):
        tag = _local(el.tag)
        if tag == "category":
            cid = el.get("id")
            if cid:
                yield "category", {"id": cid, "parent_id": el.get("parentId"), "name": (el.text or "").strip()}
            el.clear()
        elif tag == "offer":
            yield "offer", _offer(el)
            el.clear()


def _offer(el: ET.Element) -> dict[str, Any]:
    params = []
    for p in el.findall("param"):
        name = (p.get("name") or "").strip()
        unit = (p.get("unit") or "").strip()
        value = (p.text or "").strip()
        if name and value:
            params.append({"name": name, "unit": unit or None, "value": value})
    name = _text(el.find("name"))
    if not name:
        parts = [_text(el.find(t)) for t in ("typePrefix", "vendor", "model")]
        name = " ".join(p for p in parts if p)
    return {
        "id": el.get("id") or "",
        "available": (el.get("available") or "true").lower() != "false",
        "name": name or None,
        "url": _text(el.find("url")),
        "price": _text(el.find("price")),
        "oldprice": _text(el.find("oldprice")),
        "currency": _text(el.find("currencyId")),
        "category_ids": [c.text.strip() for c in el.findall("categoryId") if c.text and c.text.strip()],
        "pictures": [p.text.strip() for p in el.findall("picture") if p.text],
        "vendor": _text(el.find("vendor")),
        "vendor_code": _text(el.find("vendorCode")),
        "description": _text(el.find("description")),
        "sales_notes": _text(el.find("sales_notes")),
        "params": params,
    }


def category_paths(cats: dict[str, dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    paths: dict[str, list[dict[str, Any]]] = {}

    def walk(cid: str, seen: frozenset[str] = frozenset()) -> list[dict[str, Any]]:
        if cid in paths:
            return paths[cid]
        c = cats.get(cid)
        if c is None or cid in seen:
            return []
        parent = c.get("parent_id")
        path = (walk(parent, seen | {cid}) if parent else []) + [{"id": int(cid), "name": c["name"]}]
        paths[cid] = path
        return path

    for cid in cats:
        walk(cid)
    return paths


def offer_rows(
    offer: dict[str, Any], paths: dict[str, list[dict[str, Any]]]
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    pid = product_id(offer["id"])
    characteristics = []
    unit = None
    qty_in_pack = None
    pack_area = None
    for p in offer["params"]:
        name = f"{p['name']}, {p['unit']}" if p["unit"] else p["name"]
        characteristics.append({"code": p["name"], "name": name, "value": p["value"]})
        if UNIT_PARAM.search(p["name"]):
            unit = p["value"]
        elif PACK_QTY_PARAM.search(p["name"]):
            m = re.search(r"\d+(?:[.,]\d+)?", p["value"])
            qty_in_pack = nz.to_decimal(m.group()) if m else None
        elif PACK_AREA_PARAM.search(p["name"]):
            m = nz.parse_measure(p["value"], p["unit"] or "м2")
            pack_area = m.value if m and m.unit == "m2" else nz.to_decimal(p["value"])

    cat_ids = [c for c in offer["category_ids"] if c.isdigit()]
    categories = {c: paths[c][-1]["name"] for c in cat_ids if c in paths}
    tree = paths.get(cat_ids[0], []) if cat_ids else []
    price = nz.to_decimal(offer["price"])
    row = {
        "id": pid,
        "sku": offer["vendor_code"],
        "cod_good": offer["id"],
        "name": (offer["name"] or f"#{offer['id']}")[:1024],
        "description": offer["description"],
        "url_key": offer["url"],
        "picture_url": offer["pictures"][0] if offer["pictures"] else None,
        "brand_name": offer["vendor"],
        "status": True,
        "currency": "RUB" if offer["currency"] in (None, "RUR", "RUB") else offer["currency"],
        "price": price,
        "result_price": price,
        "old_price": nz.to_decimal(offer["oldprice"]),
        "unit": unit,
        "quantity_in_package": qty_in_pack,
        "package_area": pack_area,
        "in_stock": offer["available"],
        "categories": categories,
        "categories_tree": tree,
        "specs": nz.extract_specs(characteristics, pack_area, qty_in_pack, offer.get("name")),
        "raw": offer,
    }
    links = [{"product_id": pid, "category_id": int(c)} for c in categories]
    return row, nz.characteristic_rows(pid, characteristics), links


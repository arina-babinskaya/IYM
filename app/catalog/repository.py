from collections.abc import Sequence

from typing import Literal

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session, defer

from app.catalog import normalize as nz
from app.db import upsert
from app.ml.ranker import has_flags, is_typical, preload
from app.models import Product, ProductBinding, ProductCategory, ProductCharacteristic
from app.schemas import BindingIn, BindingOut, Characteristic, ProductBrief, ProductCreate, ProductOut, Suggestion
from app.taxonomy import Material, WorkType, works_for_material

MANUAL_ID_START = 9_000_000_000_000
AdminStatus = Literal["unbound", "ml", "confirmed", "all"]

# A persisted work label describes where the classifier saw the strongest evidence; it is not an
# exhaustive list of every estimate slot in which an auxiliary material can be used.  These narrow
# relations are consulted only when an exact candidate pool is empty.  Material identity remains
# exact, so (for example) a paint product can never enter a primer slot.
COMPATIBLE_WORK_FALLBACKS: dict[tuple[Material, WorkType], frozenset[WorkType]] = {
    (Material.primer, WorkType.waterproofing): frozenset({WorkType.priming}),
    (Material.primer, WorkType.floor_screed): frozenset({WorkType.priming}),
    (Material.primer, WorkType.tiling): frozenset({WorkType.priming}),
    (Material.primer, WorkType.wall_plastering): frozenset({WorkType.priming}),
    (Material.primer, WorkType.wall_putty): frozenset({WorkType.priming}),
    (Material.primer, WorkType.wall_painting): frozenset({WorkType.priming}),
    (Material.primer, WorkType.wallpapering): frozenset({WorkType.priming}),
    (Material.electrical_boxes, WorkType.lighting_install): frozenset({
        WorkType.electrical_wiring, WorkType.electrical_fittings,
    }),
}


def fallback_binding(binding: ProductBinding, work_type: WorkType, tier: str) -> ProductBinding:
    """Create a detached ranking view with auditable fallback provenance."""
    flags = dict(binding.flags or {})
    flags[f"candidate_{tier}_fallback"] = True
    flags[f"candidate_requested_work__{work_type.value}"] = True
    return ProductBinding(
        product_id=binding.product_id, product_category=binding.product_category,
        material=binding.material, work_types=list(binding.work_types or []),
        room_types=list(binding.room_types or []), flags=flags, source=binding.source,
        confidence=binding.confidence, confirmed=binding.confirmed,
    )


def to_brief(p: Product) -> ProductBrief:
    return ProductBrief(
        id=p.id, sku=p.sku, name=p.name, url_key=p.url_key, picture_url=p.picture_url, brand=p.brand_name,
        unit=p.unit, result_price=p.result_price, currency=p.currency or "RUB", in_stock=p.in_stock,
    )




class CatalogRepo:
    def __init__(self, session: Session):
        self.session = session
        # One repo serves one request: the engine and the "!" hints ask for the same candidate lists.
        self._candidates: dict[tuple, list[tuple[Product, ProductBinding]]] = {}

    def get(self, product_id: int) -> Product | None:
        return self.session.get(Product, product_id)

    def binding(self, product_id: int) -> ProductBinding | None:
        return self.session.get(ProductBinding, product_id)

    def get_out(self, product_id: int) -> ProductOut | None:
        p = self.get(product_id)
        if p is None:
            return None
        chars = self.session.scalars(
            select(ProductCharacteristic).where(ProductCharacteristic.product_id == product_id)
        ).all()
        b = self.binding(product_id)
        return ProductOut(
            **to_brief(p).model_dump(),
            cod_good=p.cod_good,
            description=p.description,
            price=p.price,
            old_price=p.old_price,
            quantity_in_package=p.quantity_in_package,
            package_area=p.package_area,
            categories=p.categories or {},
            characteristics=[
                Characteristic(code=c.code, name=c.name, value=c.value_raw, value_num=c.value_num, unit=c.unit)
                for c in chars
            ],
            specs=p.specs or {},
            binding=BindingOut.model_validate(b) if b else None,
        )

    def search(
        self, q: str | None = None, category_id: int | None = None, limit: int = 50, offset: int = 0
    ) -> list[Product]:
        stmt = select(Product).where(Product.status.isnot(False))
        if q:
            stmt = stmt.where(or_(func.lower(Product.name).like(f"%{q.lower()}%"), Product.sku == q, Product.cod_good == q))
        if category_id is not None:
            stmt = stmt.join(ProductCategory, ProductCategory.product_id == Product.id).where(
                ProductCategory.category_id == category_id
            )
        return list(self.session.scalars(stmt.order_by(Product.id).limit(limit).offset(offset)))

    def candidates(
        self,
        material: Material,
        work_type: WorkType | None = None,
        required_flags: Sequence[str] = (),
        min_confidence: float = 0.0,
        in_stock_only: bool = True,
        limit: int = 200,
    ) -> list[tuple[Product, ProductBinding]]:
        key = (material, work_type, tuple(required_flags), min_confidence, in_stock_only, limit)
        if key not in self._candidates:
            self._candidates[key] = self._load_candidates(material, work_type, required_flags, min_confidence,
                                                          in_stock_only, limit)
        return list(self._candidates[key])

    def _load_candidates(
        self,
        material: Material,
        work_type: WorkType | None,
        required_flags: Sequence[str],
        min_confidence: float,
        in_stock_only: bool,
        limit: int,
    ) -> list[tuple[Product, ProductBinding]]:
        stmt = (
            select(Product, ProductBinding)
            .join(ProductBinding, ProductBinding.product_id == Product.id)
            # The full card is only needed for products the ranker has not profiled yet; it is then
            # loaded on access.
            .options(defer(Product.raw), defer(Product.description), defer(Product.categories),
                     defer(Product.categories_tree))
            .where(ProductBinding.material == material.value)
            .where(Product.status.isnot(False), Product.result_price.isnot(None), Product.result_price > 0)
            .where(or_(ProductBinding.confirmed.is_(True), ProductBinding.confidence >= min_confidence))
        )
        if in_stock_only:
            stmt = stmt.where(Product.in_stock.isnot(False))
        rows = [(p, b) for p, b in self.session.execute(stmt.limit(limit * 5))]
        if work_type is not None:
            # Old manually reviewed bindings may predate work-type persistence. Keep those usable
            # only when the authoritative material taxonomy confirms compatibility. Automatic
            # category/material-only bindings remain excluded from specific estimate slots.
            compatible_legacy = work_type in works_for_material(material)
            exact = [(p, b) for p, b in rows if work_type.value in (b.work_types or [])
                     or (b.confirmed and not (b.work_types or []) and compatible_legacy)]
            related = COMPATIBLE_WORK_FALLBACKS.get((material, work_type), frozenset())
            compatible = [
                (p, fallback_binding(b, work_type, "compatible")) for p, b in rows
                if any(item.value in (b.work_types or []) for item in related)
            ]
            # Nothing is bound to this work yet (e.g. fasteners, which the model binds by material
            # only): material-only bindings are better than an empty estimate line.
            material_only = [(p, fallback_binding(b, work_type, "material_only")) for p, b in rows
                             if not (b.work_types or [])] if compatible_legacy else []
            rows = exact or compatible or material_only
            if exact and not any(is_typical(material, p.name) for p, _ in exact):
                # The exact pool holds only accessories (a sealing tape bound to drywall profiles):
                # add the real products of this material from the fallback tiers.
                seen = {p.id for p, _ in exact}
                for p, b in compatible + material_only:
                    if p.id not in seen and is_typical(material, p.name):
                        seen.add(p.id)
                        rows.append((p, b))
        if required_flags:
            preload(rows)
            rows = [(p, b) for p, b in rows if has_flags(p, b, required_flags)]
        return rows[:limit]

    def set_binding(
        self, product_id: int, data: BindingIn, source: str, confidence: float | None, confirmed: bool
    ) -> ProductBinding:
        b = self.binding(product_id) or ProductBinding(product_id=product_id)
        if data.product_category is not None:
            b.product_category = data.product_category.value
        b.material = data.material.value
        b.work_types = [w.value for w in data.work_types]
        b.room_types = [r.value for r in data.room_types]
        b.flags = dict(data.flags)
        b.source, b.confidence, b.confirmed = source, confidence, confirmed
        self.session.add(b)
        self.session.commit()
        self._candidates.clear()
        return b

    def save_ml_bindings(self, pairs: Sequence[tuple[int, Suggestion]]) -> int:
        rows = [
            {
                "product_id": pid,
                "product_category": s.product_category.value if s.product_category else None,
                "material": s.material.value,
                "work_types": [w.value for w in s.work_types],
                "room_types": [r.value for r in s.room_types],
                "flags": dict(s.flags),
                "source": "gigachat" if s.flags.get("gigachat_validated") else "ml",
                "confidence": s.confidence,
                "confirmed": False,
            }
            for pid, s in pairs
        ]
        # Classification only fills missing bindings; it must never replace manual/confirmed data.
        inserted = upsert(self.session, ProductBinding, rows, ["product_id"], update=False)
        self.session.commit()
        self._candidates.clear()
        return inserted

    def admin_list(self, status: AdminStatus = "unbound", q: str | None = None, limit: int = 50,
                   offset: int = 0) -> list[Product]:
        stmt = (
            select(Product)
            .outerjoin(ProductBinding, ProductBinding.product_id == Product.id)
            .where(Product.status.isnot(False))
        )
        if status == "unbound":
            stmt = stmt.where(ProductBinding.product_id.is_(None))
        elif status == "ml":
            stmt = stmt.where(ProductBinding.confirmed.is_(False))
        elif status == "confirmed":
            stmt = stmt.where(ProductBinding.confirmed.is_(True))
        if q:
            stmt = stmt.where(or_(func.lower(Product.name).like(f"%{q.lower()}%"), Product.sku == q, Product.cod_good == q))
        return list(self.session.scalars(stmt.order_by(Product.id.desc()).limit(limit).offset(offset)))

    def create_manual(self, data: ProductCreate) -> Product:
        last = self.session.scalar(select(func.max(Product.id)).where(Product.id >= MANUAL_ID_START))
        pid = (last or MANUAL_ID_START - 1) + 1
        chars = [{"name": c.name, "value": c.value} for c in data.characteristics]
        categories = {"0": data.category} if data.category else {}
        p = Product(
            id=pid, name=data.name, description=data.description, brand_name=data.brand, status=True,
            currency="RUB", price=data.price, result_price=data.price, unit=data.unit, in_stock=True,
            package_area=data.package_area, quantity_in_package=data.quantity_in_package, categories=categories,
            categories_tree=[{"id": 0, "name": data.category}] if data.category else [],
            specs=nz.extract_specs(chars, data.package_area, data.quantity_in_package, data.name),
            raw={"source": "manual", "name": data.name, "characteristics": chars},
        )
        self.session.add(p)
        self.session.flush()
        rows = nz.characteristic_rows(pid, chars)
        if rows:
            upsert(self.session, ProductCharacteristic, rows, ["product_id", "code"])
        self.session.commit()
        self._candidates.clear()
        return p

    def delete_manual(self, product_id: int) -> bool:
        if product_id < MANUAL_ID_START or self.get(product_id) is None:
            return False
        for model in (ProductBinding, ProductCharacteristic, ProductCategory):
            self.session.execute(delete(model).where(model.product_id == product_id))
        self.session.execute(delete(Product).where(Product.id == product_id))
        self.session.commit()
        self._candidates.clear()
        return True

    def unbound(self, limit: int = 100, after_id: int = -1) -> list[Product]:
        stmt = (
            select(Product)
            .outerjoin(ProductBinding, ProductBinding.product_id == Product.id)
            .where(ProductBinding.product_id.is_(None), Product.status.isnot(False), Product.id > after_id)
            .order_by(Product.id)
            .limit(limit)
        )
        return list(self.session.scalars(stmt))

    def binding_counts(self) -> tuple[int, int, int]:
        total = self.session.scalar(
            select(func.count()).select_from(Product).where(Product.status.isnot(False))
        ) or 0
        manual = self.session.scalar(
            select(func.count()).select_from(ProductBinding).where(ProductBinding.confirmed.is_(True))
        ) or 0
        ml = self.session.scalar(
            select(func.count()).select_from(ProductBinding).where(ProductBinding.confirmed.is_(False))
        ) or 0
        return total, manual, ml

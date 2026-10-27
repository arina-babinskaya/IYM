from collections.abc import Sequence

from typing import Literal

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from app.catalog import normalize as nz
from app.db import upsert
from app.ml.ranker import signals
from app.models import Product, ProductBinding, ProductCategory, ProductCharacteristic
from app.schemas import BindingIn, BindingOut, Characteristic, ProductBrief, ProductCreate, ProductOut, Suggestion
from app.taxonomy import Material, WorkType

MANUAL_ID_START = 9_000_000_000_000
AdminStatus = Literal["unbound", "ml", "confirmed", "all"]


def to_brief(p: Product) -> ProductBrief:
    return ProductBrief(
        id=p.id, sku=p.sku, name=p.name, url_key=p.url_key, picture_url=p.picture_url, brand=p.brand_name,
        unit=p.unit, result_price=p.result_price, currency=p.currency or "RUB", in_stock=p.in_stock,
    )


def has_flags(p: Product, b: ProductBinding, required: Sequence[str]) -> bool:
    flags = b.flags or {}
    found = signals(p, b)
    return all(flags.get(f) or found.get(f, 0) >= 1 for f in required)


class CatalogRepo:
    def __init__(self, session: Session):
        self.session = session

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
        stmt = (
            select(Product, ProductBinding)
            .join(ProductBinding, ProductBinding.product_id == Product.id)
            .where(ProductBinding.material == material.value)
            .where(Product.status.isnot(False), Product.result_price.isnot(None))
            .where(or_(ProductBinding.confirmed.is_(True), ProductBinding.confidence >= min_confidence))
        )
        if in_stock_only:
            stmt = stmt.where(Product.in_stock.isnot(False))
        rows = [(p, b) for p, b in self.session.execute(stmt.limit(limit * 5))]
        if work_type is not None:
            rows = [(p, b) for p, b in rows if work_type.value in (b.work_types or [])]
        if required_flags:
            rows = [(p, b) for p, b in rows if has_flags(p, b, required_flags)]
        return rows[:limit]

    def set_binding(
        self, product_id: int, data: BindingIn, source: str, confidence: float | None, confirmed: bool
    ) -> ProductBinding:
        b = self.binding(product_id) or ProductBinding(product_id=product_id)
        b.material = data.material.value
        b.work_types = [w.value for w in data.work_types]
        b.room_types = [r.value for r in data.room_types]
        b.flags = dict(data.flags)
        b.source, b.confidence, b.confirmed = source, confidence, confirmed
        self.session.add(b)
        self.session.commit()
        return b

    def save_ml_bindings(self, pairs: Sequence[tuple[int, Suggestion]]) -> None:
        rows = [
            {
                "product_id": pid,
                "material": s.material.value,
                "work_types": [w.value for w in s.work_types],
                "room_types": [r.value for r in s.room_types],
                "flags": dict(s.flags),
                "source": "ml",
                "confidence": s.confidence,
                "confirmed": False,
            }
            for pid, s in pairs
        ]
        upsert(self.session, ProductBinding, rows, ["product_id"])
        self.session.commit()

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
        return p

    def delete_manual(self, product_id: int) -> bool:
        if product_id < MANUAL_ID_START or self.get(product_id) is None:
            return False
        for model in (ProductBinding, ProductCharacteristic, ProductCategory):
            self.session.execute(delete(model).where(model.product_id == product_id))
        self.session.execute(delete(Product).where(Product.id == product_id))
        self.session.commit()
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

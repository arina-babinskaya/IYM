from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Sequence

from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.orm import Session

from app.ml.catalog_matching import CatalogMatchResult
from app.models import CatalogCategoryAssignment, Product

CatalogAssignmentStatus = Literal[
    "unassigned", "predicted", "review", "manual", "unbound", "ml", "confirmed", "all"
]


@dataclass(frozen=True)
class CatalogSaveCounts:
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    manual_preserved: int = 0
    needs_review: int = 0


class CatalogMatchingRepo:
    """Persistence isolated from ProductBinding and the renovation candidate repository."""

    def __init__(self, session: Session):
        self.session = session

    def assignment(self, product_id: int) -> CatalogCategoryAssignment | None:
        return self.session.get(CatalogCategoryAssignment, product_id)

    def active_count(self) -> int:
        return self.session.scalar(
            select(func.count()).select_from(Product).where(Product.status.isnot(False))
        ) or 0

    def products_batch(self, limit: int, after_id: int = -1) -> list[Product]:
        return list(self.session.scalars(
            select(Product).where(Product.status.isnot(False), Product.id > after_id)
            .order_by(Product.id).limit(limit)
        ))

    def unassigned_products_batch(self, limit: int, after_id: int = -1) -> list[Product]:
        return list(self.session.scalars(
            select(Product).outerjoin(
                CatalogCategoryAssignment, CatalogCategoryAssignment.product_id == Product.id
            ).where(
                Product.status.isnot(False), Product.id > after_id,
                CatalogCategoryAssignment.product_id.is_(None),
            ).order_by(Product.id).limit(limit)
        ))

    def list_rows(
        self,
        status: CatalogAssignmentStatus = "all",
        category_id: str | None = None,
        q: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[tuple[Product, CatalogCategoryAssignment | None]]:
        stmt = select(Product, CatalogCategoryAssignment).outerjoin(
            CatalogCategoryAssignment, CatalogCategoryAssignment.product_id == Product.id
        ).where(Product.status.isnot(False))
        if status in {"unassigned", "unbound"}:
            stmt = stmt.where(CatalogCategoryAssignment.product_id.is_(None))
        elif status in {"predicted", "ml"}:
            stmt = stmt.where(CatalogCategoryAssignment.source == "ml")
        elif status == "review":
            stmt = stmt.where(CatalogCategoryAssignment.status == "needs_review")
        elif status in {"manual", "confirmed"}:
            stmt = stmt.where(CatalogCategoryAssignment.source == "manual")
        if category_id:
            stmt = stmt.where(CatalogCategoryAssignment.category_id == category_id)
        if q:
            query = q.strip().lower()
            conditions = [func.lower(Product.name).like(f"%{query}%"), Product.sku == q, Product.cod_good == q]
            if q.isdigit():
                conditions.append(cast(Product.id, String) == q)
            stmt = stmt.where(or_(*conditions))
        return list(self.session.execute(stmt.order_by(Product.id.desc()).limit(limit).offset(offset)))

    def stats(self) -> dict[str, int | float]:
        total = self.active_count()
        base = select(func.count()).select_from(CatalogCategoryAssignment).join(Product).where(
            Product.status.isnot(False)
        )
        assigned = self.session.scalar(base) or 0
        ml = self.session.scalar(base.where(CatalogCategoryAssignment.source == "ml")) or 0
        manual = self.session.scalar(base.where(CatalogCategoryAssignment.source == "manual")) or 0
        review = self.session.scalar(base.where(CatalogCategoryAssignment.status == "needs_review")) or 0
        return {
            "products_total": total,
            "assigned": assigned,
            "model_suggestions": ml,
            "manual_confirmed": manual,
            "needs_review": review,
            "unassigned": total - assigned,
            "coverage": round(assigned / total, 4) if total else 0.0,
        }

    @staticmethod
    def _alternatives(result: CatalogMatchResult) -> list[dict[str, str | float]]:
        prediction = result.prediction
        return [
            {"category_id": prediction.category_id, "category_name": prediction.category_name,
             "score": prediction.confidence},
            *[
                {"category_id": item.category_id, "category_name": item.category_name,
                 "score": item.confidence}
                for item in prediction.alternatives
            ],
        ]

    def save_predictions(self, results: Sequence[CatalogMatchResult]) -> CatalogSaveCounts:
        counts = {"inserted": 0, "updated": 0, "unchanged": 0, "manual_preserved": 0, "needs_review": 0}
        product_ids = [int(item.product_id) for item in results if item.product_id is not None]
        existing = {
            item.product_id: item for item in self.session.scalars(
                select(CatalogCategoryAssignment).where(CatalogCategoryAssignment.product_id.in_(product_ids))
            )
        } if product_ids else {}
        for result in results:
            product_id = int(result.product_id) if result.product_id is not None else None
            if product_id is None:
                counts["unchanged"] += 1
                continue
            current = existing.get(product_id)
            if current is not None and current.source == "manual":
                counts["manual_preserved"] += 1
                continue
            prediction = result.prediction
            status = "needs_review" if prediction.needs_review else "predicted"
            alternatives = self._alternatives(result)
            values = (
                prediction.category_id, prediction.confidence, prediction.model,
                result.taxonomy_version, status, alternatives,
            )
            if current is None:
                current = CatalogCategoryAssignment(
                    product_id=product_id, category_id=prediction.category_id,
                    model_score=prediction.confidence, model_version=prediction.model,
                    taxonomy_version=result.taxonomy_version, status=status, source="ml",
                    alternatives=alternatives,
                )
                self.session.add(current)
                counts["inserted"] += 1
            else:
                old = (current.category_id, current.model_score, current.model_version,
                       current.taxonomy_version, current.status, current.alternatives)
                if old == values:
                    counts["unchanged"] += 1
                else:
                    (current.category_id, current.model_score, current.model_version,
                     current.taxonomy_version, current.status, current.alternatives) = values
                    current.source = "ml"
                    counts["updated"] += 1
            if status == "needs_review":
                counts["needs_review"] += 1
        self.session.commit()
        return CatalogSaveCounts(**counts)

    def save_manual(self, product_id: int, category_id: str, taxonomy_version: str) -> CatalogCategoryAssignment:
        current = self.assignment(product_id)
        if current is None:
            current = CatalogCategoryAssignment(product_id=product_id, category_id=category_id)
            self.session.add(current)
            original = None
        else:
            original = current.category_id
        current.category_id = category_id
        current.taxonomy_version = taxonomy_version
        current.status = "confirmed" if original is None or original == category_id else "corrected"
        current.source = "manual"
        # Retain the model score and alternatives as review provenance when confirming/correcting.
        current.model_version = current.model_version or "manual"
        current.alternatives = current.alternatives or []
        self.session.commit()
        return current

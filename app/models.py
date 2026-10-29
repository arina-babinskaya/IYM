from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

Json = JSON(none_as_null=True).with_variant(JSONB(none_as_null=True), "postgresql")
Money = Numeric(14, 2)
Qty = Numeric(14, 4)
Id = BigInteger().with_variant(Integer(), "sqlite")


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=False)
    parent_id: Mapped[int | None] = mapped_column(Id, index=True)
    name: Mapped[str] = mapped_column(String(512))
    path: Mapped[list[Any] | None] = mapped_column(Json)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=False)
    sku: Mapped[str | None] = mapped_column(String(128), index=True)
    cod_good: Mapped[str | None] = mapped_column(String(128), index=True)
    name: Mapped[str] = mapped_column(String(1024))
    description: Mapped[str | None] = mapped_column(Text)
    url_key: Mapped[str | None] = mapped_column(String(1024))
    picture_url: Mapped[str | None] = mapped_column(String(1024))
    brand_name: Mapped[str | None] = mapped_column(String(256))
    status: Mapped[bool | None] = mapped_column(Boolean, index=True)

    currency: Mapped[str | None] = mapped_column(String(8))
    price: Mapped[Decimal | None] = mapped_column(Money)
    result_price: Mapped[Decimal | None] = mapped_column(Money)
    old_price: Mapped[Decimal | None] = mapped_column(Money)

    unit: Mapped[str | None] = mapped_column(String(32))
    quantity_in_package: Mapped[Decimal | None] = mapped_column(Qty)
    package_area: Mapped[Decimal | None] = mapped_column(Qty)
    in_stock: Mapped[bool | None] = mapped_column(Boolean, index=True)
    rating: Mapped[Decimal | None] = mapped_column(Numeric(4, 2))
    recsys_rating: Mapped[float | None]

    categories: Mapped[dict[str, str] | None] = mapped_column(Json)
    categories_tree: Mapped[list[Any] | None] = mapped_column(Json)
    specs: Mapped[dict[str, Any] | None] = mapped_column(Json)
    raw: Mapped[dict[str, Any] | None] = mapped_column(Json)
    last_seen_run: Mapped[int | None] = mapped_column(Integer, index=True)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ProductCategory(Base):
    __tablename__ = "product_categories"

    product_id: Mapped[int] = mapped_column(Id, ForeignKey("products.id", ondelete="CASCADE"), primary_key=True)
    category_id: Mapped[int] = mapped_column(Id, primary_key=True, index=True)


class ProductCharacteristic(Base):
    __tablename__ = "product_characteristics"

    product_id: Mapped[int] = mapped_column(Id, ForeignKey("products.id", ondelete="CASCADE"), primary_key=True)
    code: Mapped[str] = mapped_column(String(256), primary_key=True, index=True)
    name: Mapped[str | None] = mapped_column(String(512))
    value_raw: Mapped[str | None] = mapped_column(Text)
    value_num: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    unit: Mapped[str | None] = mapped_column(String(16))
    value_json: Mapped[Any | None] = mapped_column(Json)


class ProductBinding(Base):
    __tablename__ = "product_bindings"

    product_id: Mapped[int] = mapped_column(Id, ForeignKey("products.id", ondelete="CASCADE"), primary_key=True)
    product_category: Mapped[str | None] = mapped_column(String(64), index=True)
    material: Mapped[str] = mapped_column(String(64), index=True)
    work_types: Mapped[list[str]] = mapped_column(Json, default=list)
    room_types: Mapped[list[str]] = mapped_column(Json, default=list)
    flags: Mapped[dict[str, bool]] = mapped_column(Json, default=dict)
    source: Mapped[str] = mapped_column(String(16))
    confidence: Mapped[float | None]
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class CatalogCategoryAssignment(Base):
    """Independent full-catalog taxonomy assignment; never consumed by renovation ranking."""

    __tablename__ = "catalog_category_assignments"

    product_id: Mapped[int] = mapped_column(
        Id, ForeignKey("products.id", ondelete="CASCADE"), primary_key=True
    )
    category_id: Mapped[str] = mapped_column(String(128), index=True)
    model_score: Mapped[float | None]
    model_version: Mapped[str | None] = mapped_column(String(128))
    taxonomy_version: Mapped[str] = mapped_column(String(128), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    source: Mapped[str] = mapped_column(String(16), index=True)
    alternatives: Mapped[list[dict[str, Any]]] = mapped_column(Json, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class IngestRun(Base):
    __tablename__ = "ingest_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(1024))
    status: Mapped[str] = mapped_column(String(16))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stats: Mapped[dict[str, Any] | None] = mapped_column(Json)
    error: Mapped[str | None] = mapped_column(Text)

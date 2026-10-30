from collections.abc import Iterator, Sequence
from functools import lru_cache
from typing import Any

from sqlalchemy import Engine, create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


@lru_cache
def get_engine() -> Engine:
    url = get_settings().database_url
    kwargs: dict[str, Any] = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs = {"connect_args": {"check_same_thread": False}}
    engine = create_engine(url, **kwargs)
    if url.startswith("sqlite"):
        event.listen(engine, "connect", _sqlite_unicode_lower)
    return engine


def _sqlite_unicode_lower(conn: Any, _: Any) -> None:
    conn.create_function("lower", 1, lambda s: s.lower() if isinstance(s, str) else s, deterministic=True)


@lru_cache
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def get_session() -> Iterator[Session]:
    with get_sessionmaker()() as session:
        yield session


def init_db(engine: Engine | None = None) -> None:
    from app import models

    target = engine or get_engine()
    Base.metadata.create_all(target)
    # Backward-compatible additive migration. Existing bindings and their material values are
    # untouched; the authoritative ML category is populated only by future classification runs.
    columns = {column["name"] for column in inspect(target).get_columns("product_bindings")}
    if "product_category" not in columns:
        with target.begin() as connection:
            connection.execute(text("ALTER TABLE product_bindings ADD COLUMN product_category VARCHAR(64)"))
            connection.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_product_bindings_product_category "
                "ON product_bindings (product_category)"
            ))
    # Existing consultant titles predate automatic naming and must be treated as manual so a
    # later message or edit never overwrites a title chosen by the user.
    if inspect(target).has_table("consultant_chats"):
        chat_columns = {column["name"] for column in inspect(target).get_columns("consultant_chats")}
        if "title_source" not in chat_columns:
            with target.begin() as connection:
                connection.execute(text(
                    "ALTER TABLE consultant_chats ADD COLUMN title_source VARCHAR(16) "
                    "NOT NULL DEFAULT 'manual'"
                ))


def upsert(
    session: Session,
    model: type[Base],
    rows: Sequence[dict[str, Any]],
    index_elements: Sequence[str],
    chunk_size: int = 200,
    update: bool = True,
) -> int:
    if not rows:
        return 0
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    elif dialect == "sqlite":
        from sqlalchemy.dialects.sqlite import insert
    else:
        raise NotImplementedError(f"upsert не поддерживает {dialect}")

    affected = 0
    for start in range(0, len(rows), chunk_size):
        chunk = rows[start : start + chunk_size]
        stmt = insert(model).values(list(chunk))
        update_cols = {
            key: stmt.excluded[key] for key in chunk[0] if key not in index_elements
        } if update else {}
        if update_cols:
            stmt = stmt.on_conflict_do_update(index_elements=list(index_elements), set_=update_cols)
        else:
            stmt = stmt.on_conflict_do_nothing(index_elements=list(index_elements))
        result = session.execute(stmt)
        if result.rowcount is not None and result.rowcount >= 0:
            affected += result.rowcount
    return affected

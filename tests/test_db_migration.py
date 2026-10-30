from sqlalchemy import create_engine, inspect, text

from app.db import init_db


def test_additive_product_category_migration_preserves_confirmed_binding(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'old.sqlite'}")
    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE product_bindings (
                product_id INTEGER PRIMARY KEY,
                material VARCHAR(64) NOT NULL,
                work_types JSON NOT NULL,
                room_types JSON NOT NULL,
                flags JSON NOT NULL,
                source VARCHAR(16) NOT NULL,
                confidence FLOAT,
                confirmed BOOLEAN NOT NULL,
                updated_at DATETIME
            )
        """))
        connection.execute(text("""
            INSERT INTO product_bindings
                (product_id, material, work_types, room_types, flags, source, confidence, confirmed)
            VALUES
                (42, 'paint', '["wall_painting"]', '[]', '{}', 'manual', NULL, 1)
        """))

    init_db(engine)

    assert "product_category" in {column["name"] for column in inspect(engine).get_columns("product_bindings")}
    with engine.connect() as connection:
        row = connection.execute(text("""
            SELECT material, work_types, source, confidence, confirmed, product_category
            FROM product_bindings WHERE product_id = 42
        """)).one()
    assert tuple(row) == ("paint", '["wall_painting"]', "manual", None, 1, None)
    assert "ix_product_bindings_product_category" in {
        index["name"] for index in inspect(engine).get_indexes("product_bindings")
    }
    engine.dispose()


def test_existing_consultant_titles_migrate_as_manual(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy-consultant.sqlite'}")
    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE consultant_chats (
                id VARCHAR(36) PRIMARY KEY, owner_hash VARCHAR(64) NOT NULL,
                title VARCHAR(120) NOT NULL, preference_summary TEXT,
                created_at DATETIME, updated_at DATETIME
            )
        """))
        connection.execute(text("""
            INSERT INTO consultant_chats(id, owner_hash, title)
            VALUES ('legacy', 'owner', 'Название пользователя')
        """))
    init_db(engine)
    assert "title_source" in {
        column["name"] for column in inspect(engine).get_columns("consultant_chats")
    }
    with engine.connect() as connection:
        assert connection.execute(text(
            "SELECT title_source FROM consultant_chats WHERE id='legacy'"
        )).scalar_one() == "manual"
    engine.dispose()

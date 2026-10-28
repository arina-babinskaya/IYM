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

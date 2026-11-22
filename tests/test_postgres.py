"""Integration checks against an isolated schema in the configured PostgreSQL server."""

from decimal import Decimal
from pathlib import Path
import sys
from uuid import uuid4

import pandas as pd
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DataError, IntegrityError


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from load_postgres import (PRODUCTS_PATH, SALES_PATH, database_url, load_database, source_rows)  # noqa: E402


@pytest.fixture
def db_engine():
    admin = create_engine(database_url())
    schema = "test_pipeline_" + uuid4().hex
    with admin.begin() as connection:
        connection.execute(text(f"CREATE SCHEMA {schema}"))
    engine = create_engine(database_url(), connect_args={"options": f"-csearch_path={schema}"})
    try:
        yield engine
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        admin.dispose()


def test_load_is_idempotent_and_matches_sources(db_engine):
    expected = source_rows()
    counts = dict(zip(("products", "customers", "orders", "order_items"), map(len, expected)))
    assert load_database(db_engine) == counts
    assert load_database(db_engine) == counts
    with db_engine.connect() as connection:
        for table, count in counts.items():
            assert connection.scalar(text(f"SELECT COUNT(*) FROM {table}")) == count
        assert connection.scalar(text("SELECT COUNT(*) FROM order_items oi JOIN orders o USING(order_id) JOIN customers c USING(customer_id) JOIN products p USING(product_id)")) == counts["order_items"]
        actual = connection.scalar(text("SELECT SUM(quantity * unit_price) FROM order_items"))
    sales = pd.read_csv(SALES_PATH, dtype=str)
    expected_total = sum((int(row.quantity) * Decimal(row.unit_price) for row in sales.itertuples()), Decimal(0))
    assert actual == expected_total


def test_foreign_keys_reject_orphans(db_engine):
    load_database(db_engine)
    with pytest.raises(IntegrityError):
        with db_engine.begin() as connection:
            connection.execute(text("INSERT INTO order_items VALUES (9223372036854775807, 999999, 1, 1, 1.00)"))


def test_same_product_can_have_distinct_sale_lines(db_engine):
    load_database(db_engine)
    with db_engine.begin() as connection:
        first = connection.execute(text("SELECT order_id, product_id, unit_price FROM order_items LIMIT 1")).one()
        connection.execute(text("""INSERT INTO order_items
            (order_item_id, order_id, product_id, quantity, unit_price)
            VALUES (9223372036854775807, :order_id, :product_id, 1, :unit_price)"""),
            {"order_id": first.order_id, "product_id": first.product_id,
             "unit_price": first.unit_price + Decimal("0.01")})
        assert connection.scalar(text("""SELECT COUNT(*) FROM order_items
            WHERE order_id=:order_id AND product_id=:product_id"""),
            {"order_id": first.order_id, "product_id": first.product_id}) >= 2


def test_failed_load_rolls_back_updates(db_engine, tmp_path):
    load_database(db_engine)
    products = pd.read_parquet(PRODUCTS_PATH)
    original_title = products.loc[0, "title"]
    products.loc[0, "title"] = "Changed in failed load"
    changed_products = tmp_path / "products.parquet"
    products.to_parquet(changed_products, index=False)
    sales = pd.read_csv(SALES_PATH, dtype=str)
    sales.loc[0, "unit_price"] = "999999999999.99"  # exceeds NUMERIC(12, 2)
    changed_sales = tmp_path / "sales.csv"
    sales.to_csv(changed_sales, index=False)
    with pytest.raises(DataError):
        load_database(db_engine, changed_products, changed_sales)
    with db_engine.connect() as connection:
        assert connection.scalar(text("SELECT title FROM products WHERE product_id=:id"),
                                 {"id": int(products.loc[0, "id"])}) == original_title
        assert connection.scalar(text("SELECT COUNT(*) FROM order_items")) == len(sales)

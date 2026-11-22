"""Integration checks for the final verification step."""

from decimal import Decimal
from pathlib import Path
import sys

import pytest
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from load_postgres import load_database, source_rows  # noqa: E402
from run_pipeline import verify_database  # noqa: E402
from test_postgres import db_engine  # noqa: F401, E402


def test_verification_and_rerun(db_engine):
    expected = load_database(db_engine)
    items = source_rows()[3]
    revenue = sum((item["quantity"] * item["unit_price"] for item in items), Decimal(0))
    ids = [item["order_item_id"] for item in items]
    first = verify_database(db_engine, expected, revenue, ids)
    load_database(db_engine)
    second = verify_database(db_engine, expected, revenue, ids)
    assert first == second
    assert first["orphans"] == (0, 0, 0)
    assert first["total_revenue"] == revenue


def test_verification_detects_changed_revenue(db_engine):
    expected = load_database(db_engine)
    items = source_rows()[3]
    revenue = sum((item["quantity"] * item["unit_price"] for item in items), Decimal(0))
    with db_engine.begin() as connection:
        connection.execute(text("UPDATE order_items SET quantity = quantity + 1 WHERE order_item_id = :id"),
                           {"id": items[0]["order_item_id"]})
    with pytest.raises(ValueError, match="revenue differ"):
        verify_database(db_engine, expected, revenue, [item["order_item_id"] for item in items])

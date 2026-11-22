"""Behavior checks for the Stage 2 generator and cleaner."""

from pathlib import Path
import sys

import pandas as pd


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from clean_sales import clean_sales  # noqa: E402
from generate_sales import generate_sales  # noqa: E402


PRODUCTS = pd.DataFrame({"id": [10, 20, 30], "price": [10.0, 20.0, 30.0]})


def row(order, product, quantity=1, price="10.00", customer="1", date="2025-01-02"):
    return {
        "order_id": str(order), "customer_id": customer,
        "customer_name": "Alice", "customer_email": "alice@example.com",
        "order_date": date, "product_id": str(product),
        "quantity": str(quantity), "unit_price": price,
    }


def test_generator_is_reproducible_and_uses_catalog_ids():
    first = generate_sales(PRODUCTS)
    second = generate_sales(PRODUCTS)
    pd.testing.assert_frame_equal(first, second)
    assert 150 <= len(first) <= 200
    assert set(first.loc[first["product_id"].isin(PRODUCTS["id"]), "product_id"]) == {10, 20, 30}
    assert len(set(first["product_id"]) - set(PRODUCTS["id"])) == 1


def test_cleaning_preserves_purchases_and_historical_prices():
    rows = [
        row(1, 10, 2, "8.50"),
        row(1, 10, 2, "8.50"),  # exact duplicate
        row(1, 10, 3, "8.50"),  # legitimate repeat: sum quantity
        row(1, 10, 1, "9.00"),  # distinct historical price: separate line
        row(1, 20, 1, "20.00", customer=None, date="01/02/2025"),
        row(1, 30, 1, "30.00", customer="2"),  # order conflict
        row(2, 20, 0, "20.00"),
        row(3, 20, "many", "20.00"),
        row(4, 20, 1, "free"),
        row(5, 20, 1, "20.00", date="2025-90-01"),
        row(6, 999, 1, "20.00"),
        row(7, 20, 1, "0.00"),
        row(8, 20, 1, "-3.00"),
    ]
    rows[4]["customer_name"] = None
    cleaned, report = clean_sales(pd.DataFrame(rows), PRODUCTS)
    assert len(cleaned) == 3
    assert cleaned.loc[(cleaned.product_id == 10) & (cleaned.unit_price == 8.5), "quantity"].item() == 5
    assert set(cleaned.unit_price) == {8.5, 9.0, 20.0}
    assert cleaned.customer_id.eq(1).all()
    assert cleaned.order_date.eq("2025-01-02").all()
    assert cleaned.customer_name.notna().all()
    assert report["duplicate_rows_removed"] == 1
    assert report["invalid_product_ids"] == 1
    assert report["invalid_dates"] == 1
    assert report["conflicting_order_rows"] == 1
    assert report["duplicate_order_item_rows_consolidated"] == 1
    assert report["rows_removed"] == len(rows) - len(cleaned)


def test_unrecoverable_missing_customer_stays_nullable_and_bad_money_is_removed():
    incomplete = row(2, 10, price="10.00", customer=None)
    incomplete["customer_name"] = None
    incomplete["customer_email"] = None
    cleaned, report = clean_sales(pd.DataFrame([incomplete, row(3, 20, price="oops")]), PRODUCTS)
    assert cleaned.empty
    assert report["missing_values"]["total"] == 3
    assert report["invalid_prices"] == 1

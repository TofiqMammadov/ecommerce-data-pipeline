"""Clean Stage 2 sales data using the Stage 1 product catalog."""

from datetime import datetime
import json
import math
from pathlib import Path
import sys

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
RAW_PATH = ROOT / "data/raw/sales_raw.csv"
PRODUCTS_PATH = ROOT / "data/raw/products.parquet"
CLEAN_PATH = ROOT / "data/processed/sales_clean.csv"
REPORT_PATH = ROOT / "data/processed/sales_quality_report.json"
COLUMNS = (
    "order_id", "customer_id", "customer_name", "customer_email",
    "order_date", "product_id", "quantity", "unit_price",
)


def parse_date(value: object) -> str | None:
    """Accept ISO and US dates, but reject ambiguous or impossible dates."""
    if pd.isna(value):
        return None
    for format_string in ("%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(str(value), format_string).date().isoformat()
        except ValueError:
            continue
    return None


def clean_sales(raw: pd.DataFrame, products: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Return cleaned line items and a report of the input and decisions."""
    missing_columns = set(COLUMNS) - set(raw.columns)
    if missing_columns:
        raise ValueError(f"Sales CSV is missing columns: {sorted(missing_columns)}")
    if not {"id", "price"}.issubset(products.columns):
        raise ValueError("Product catalog must contain id and price")
    if products["id"].isna().any() or products["id"].duplicated().any():
        raise ValueError("Product catalog IDs must be present and unique")
    catalog_prices = pd.to_numeric(products["price"], errors="coerce")
    if catalog_prices.isna().any() or (catalog_prices <= 0).any():
        raise ValueError("Product catalog prices must be positive")

    frame = raw.loc[:, list(COLUMNS)].copy().reset_index(drop=True)
    frame = frame.astype("string")
    for column in COLUMNS:
        frame[column] = frame[column].str.strip().replace("", pd.NA)
    missing_values = {column: int(frame[column].isna().sum()) for column in COLUMNS}
    total_raw = len(frame)
    frame = frame.drop_duplicates().copy()
    duplicates_removed = total_raw - len(frame)
    corrected = set()

    invalid_types = {}
    invalid_numeric = pd.Series(False, index=frame.index)
    numeric = {}
    for column in ("order_id", "customer_id", "product_id", "quantity", "unit_price"):
        converted = pd.to_numeric(frame[column], errors="coerce")
        invalid = frame[column].notna() & (converted.isna() | ~converted.map(
            lambda x: pd.isna(x) or math.isfinite(x)
        ))
        if column != "unit_price":
            invalid |= converted.notna() & (converted % 1 != 0)
        invalid_types[column] = int(invalid.sum())
        invalid_numeric |= invalid
        numeric[column] = converted
        # A decimal-looking integer is valid, but its representation is corrected.
        if column != "unit_price":
            valid = frame[column].notna() & ~invalid
            normalized = converted.loc[valid].astype("int64").astype("string")
            corrected.update(normalized.index[frame.loc[valid, column] != normalized].tolist())

    parsed_dates = frame["order_date"].map(parse_date)
    invalid_dates = parsed_dates.isna()
    corrected.update(frame.index[parsed_dates.notna() & (frame["order_date"] != parsed_dates)].tolist())
    valid_catalog_ids = set(products["id"].astype(int))
    invalid_products = numeric["product_id"].notna() & ~numeric["product_id"].isin(valid_catalog_ids)
    invalid_products |= frame["product_id"].isna() | (frame["product_id"].notna() & numeric["product_id"].isna())
    invalid_quantities = numeric["quantity"].notna() & (numeric["quantity"] <= 0)
    invalid_prices = numeric["unit_price"].notna() & (
        (numeric["unit_price"] <= 0) |
        ((numeric["unit_price"] * 100).round(6) % 1 != 0)
    )
    invalid_prices |= frame["unit_price"].notna() & numeric["unit_price"].isna()
    invalid_ids = pd.Series(False, index=frame.index)
    for column in ("order_id", "customer_id", "product_id"):
        invalid_ids |= numeric[column].notna() & (numeric[column] <= 0)

    # Missing customer IDs can be recovered from another line of the same order.
    required_missing = frame[["order_id", "product_id", "quantity", "unit_price"]].isna().any(axis=1)
    rejected = invalid_numeric | invalid_dates | invalid_products | invalid_quantities | invalid_prices | invalid_ids | required_missing
    frame = frame.loc[~rejected].copy()
    rejected_count = int(rejected.sum())
    for column, values in numeric.items():
        frame[column] = values.loc[frame.index]
    frame["order_date"] = parsed_dates.loc[frame.index]

    # Use the first surviving, known customer on an order as its reference.
    order_customer = frame.dropna(subset=["customer_id"]).drop_duplicates("order_id").set_index("order_id")["customer_id"]
    fill_id = frame["customer_id"].isna() & frame["order_id"].isin(order_customer.index)
    frame.loc[fill_id, "customer_id"] = frame.loc[fill_id, "order_id"].map(order_customer)
    corrected.update(frame.index[fill_id].tolist())
    missing_customer_id = frame["customer_id"].isna()
    rejected_count += int(missing_customer_id.sum())
    frame = frame.loc[~missing_customer_id].copy()

    first_order = frame.drop_duplicates("order_id").set_index("order_id")[["customer_id", "order_date"]]
    expected_customer = frame["order_id"].map(first_order["customer_id"])
    expected_date = frame["order_id"].map(first_order["order_date"])
    conflicting_orders = (frame["customer_id"] != expected_customer) | (frame["order_date"] != expected_date)
    conflicting_count = int(conflicting_orders.sum())
    rejected_count += conflicting_count
    frame = frame.loc[~conflicting_orders].copy()

    current_prices = frame["product_id"].map(products.set_index("id")["price"])
    historical_price_count = int((frame["unit_price"].round(2) != current_prices.round(2)).sum())

    # Fill only from a known row for the same customer; otherwise leave nullable.
    for column in ("customer_name", "customer_email"):
        lookup = frame.dropna(subset=[column]).drop_duplicates("customer_id").set_index("customer_id")[column]
        to_fill = frame[column].isna() & frame["customer_id"].isin(lookup.index)
        frame.loc[to_fill, column] = frame.loc[to_fill, "customer_id"].map(lookup)
        corrected.update(frame.index[to_fill].tolist())

    # Two purchases of the same product at the same price in one order form
    # one line with summed quantity. Different sale prices stay separate.
    item_key = ["order_id", "product_id", "unit_price"]
    repeated = frame.duplicated(item_key, keep=False)
    corrected.update(frame.index[repeated].tolist())
    surviving_indices = set(frame.index)
    item_rows_consolidated = len(frame) - frame[item_key].drop_duplicates().shape[0]
    frame = frame.groupby(item_key, sort=False, as_index=False).agg({
        "customer_id": "first", "customer_name": "first", "customer_email": "first",
        "order_date": "first", "quantity": "sum",
    })
    frame = frame.loc[:, list(COLUMNS)]
    for column in ("order_id", "customer_id", "product_id", "quantity"):
        frame[column] = frame[column].astype("int64")
    frame["unit_price"] = frame["unit_price"].astype("float64")
    frame = frame.sort_values(["order_id", "product_id", "unit_price"]).reset_index(drop=True)

    report = {
        "total_raw_rows": total_raw,
        "duplicate_rows_removed": duplicates_removed,
        "missing_values": {"total": sum(missing_values.values()), "by_column": missing_values},
        "invalid_data_types_found": {"total": sum(invalid_types.values()), "by_column": invalid_types},
        "invalid_dates": int(invalid_dates.sum()),
        "invalid_product_ids": int(invalid_products.sum()),
        "invalid_quantities": int(invalid_quantities.sum()),
        "invalid_prices": int(invalid_prices.sum()),
        "historical_sale_price_rows_retained": historical_price_count,
        "conflicting_order_rows": conflicting_count,
        "duplicate_order_item_rows_consolidated": item_rows_consolidated,
        "rows_corrected": len(corrected & surviving_indices),
        "rejected_rows": rejected_count,
        "rows_removed": total_raw - len(frame),
        "final_cleaned_row_count": len(frame),
    }
    return frame, report


def main() -> None:
    raw = pd.read_csv(RAW_PATH, dtype="string")
    products = pd.read_parquet(PRODUCTS_PATH)
    cleaned, report = clean_sales(raw, products)
    CLEAN_PATH.parent.mkdir(parents=True, exist_ok=True)
    cleaned.to_csv(CLEAN_PATH, index=False, float_format="%.2f")
    REPORT_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"Saved cleaned sales to {CLEAN_PATH}")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

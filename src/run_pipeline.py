"""Run the complete e-commerce ETL and verify the loaded data."""

from decimal import Decimal
import json
import logging
from pathlib import Path
import sys

import pandas as pd
from sqlalchemy import bindparam, create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from clean_sales import CLEAN_PATH, REPORT_PATH, clean_sales
from fetch_products import OUTPUT_PATH as PRODUCTS_PATH, fetch_products, validate_and_select
from generate_sales import OUTPUT_PATH as RAW_SALES_PATH, SEED, generate_sales
from load_postgres import database_url, load_database, source_rows


LOG = logging.getLogger("pipeline")
TABLES = ("products", "customers", "orders", "order_items")


def verify_database(engine: Engine, expected_counts: dict[str, int],
                    expected_revenue: Decimal, item_ids: list[int]) -> dict:
    """Check counts, foreign keys, and the revenue of this run's sale lines."""
    with engine.connect() as connection:
        counts = {table: connection.scalar(text(f"SELECT COUNT(*) FROM {table}")) for table in TABLES}
        orphans = connection.execute(text("""
            SELECT
              (SELECT COUNT(*) FROM orders o LEFT JOIN customers c USING (customer_id)
               WHERE c.customer_id IS NULL),
              (SELECT COUNT(*) FROM order_items i LEFT JOIN orders o USING (order_id)
               WHERE o.order_id IS NULL),
              (SELECT COUNT(*) FROM order_items i LEFT JOIN products p USING (product_id)
               WHERE p.product_id IS NULL)
        """)).one()
        total_revenue = connection.scalar(text(
            "SELECT COALESCE(SUM(quantity * unit_price), 0) FROM order_items"
        ))
        source_result = connection.execute(
            text("""SELECT COUNT(*), COALESCE(SUM(quantity * unit_price), 0)
                    FROM order_items WHERE order_item_id IN :ids""").bindparams(
                bindparam("ids", expanding=True)), {"ids": item_ids}
        ).one()

    if any(counts[table] < expected_counts[table] for table in TABLES):
        raise ValueError(f"Database counts are below source counts: {counts} vs {expected_counts}")
    if any(orphans):
        raise ValueError(f"Foreign key verification failed: orphan counts={tuple(orphans)}")
    if source_result[0] != expected_counts["order_items"] or source_result[1] != expected_revenue:
        raise ValueError("Loaded sale lines or their revenue differ from the cleaned source")
    return {
        "counts": counts,
        "orphans": tuple(orphans),
        "total_revenue": total_revenue,
        "source_revenue": source_result[1],
    }


def run_pipeline() -> dict:
    LOG.info("Stage 1/6: Fetching products from DummyJSON")
    products = validate_and_select(fetch_products())
    PRODUCTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    products.to_parquet(PRODUCTS_PATH, engine="pyarrow", index=False)
    LOG.info("Saved %d products to %s", len(products), PRODUCTS_PATH)

    LOG.info("Stage 2/6: Generating sales with seed %d", SEED)
    raw_sales = generate_sales(products, seed=SEED)
    RAW_SALES_PATH.parent.mkdir(parents=True, exist_ok=True)
    raw_sales.to_csv(RAW_SALES_PATH, index=False)
    LOG.info("Saved %d raw sales rows to %s", len(raw_sales), RAW_SALES_PATH)

    LOG.info("Stage 3/6: Cleaning and validating sales")
    cleaned, report = clean_sales(pd.read_csv(RAW_SALES_PATH, dtype="string"), products)
    if cleaned.empty:
        raise ValueError("Cleaning produced no sale lines; database load stopped")
    CLEAN_PATH.parent.mkdir(parents=True, exist_ok=True)
    cleaned.to_csv(CLEAN_PATH, index=False, float_format="%.2f")
    REPORT_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    LOG.info("Retained %d sale lines; rejected %d rows", len(cleaned), report["rejected_rows"])

    LOG.info("Stage 4/6: Checking PostgreSQL availability")
    engine = create_engine(database_url(), connect_args={"connect_timeout": 5})
    try:
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        except SQLAlchemyError as exc:
            raise RuntimeError("PostgreSQL is unavailable. Start it with 'docker compose up -d --wait' and check .env") from exc

        LOG.info("Stage 5/6: Loading PostgreSQL in one transaction")
        source_counts = load_database(engine)
        LOG.info("Stage 6/6: Verifying counts, foreign keys, and revenue")
        items = source_rows()[3]
        expected_revenue = sum((row["quantity"] * row["unit_price"] for row in items), Decimal("0.00"))
        result = verify_database(engine, source_counts, expected_revenue,
                                 [row["order_item_id"] for row in items])
    finally:
        engine.dispose()

    LOG.info("Pipeline complete")
    print("\nExecution summary")
    print(f"Products fetched: {len(products)}; raw sales rows: {len(raw_sales)}; cleaned sale lines: {len(cleaned)}")
    print("Database rows: " + ", ".join(f"{name}={result['counts'][name]}" for name in TABLES))
    print(f"Foreign key orphan counts (orders/customers, items/orders, items/products): {result['orphans']}")
    print(f"Total database sales revenue: {result['total_revenue']:.2f}")
    print(f"Revenue from this run's sale lines: {result['source_revenue']:.2f}")
    return result


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s", stream=sys.stdout)
    try:
        run_pipeline()
    except (OSError, ValueError, RuntimeError, SQLAlchemyError, pd.errors.ParserError) as exc:
        LOG.error("Pipeline stopped: %s", exc)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()

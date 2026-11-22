"""Load the Stage 1 catalog and Stage 2 cleaned sales into PostgreSQL."""

from datetime import date
from decimal import Decimal
import hashlib
import os
from pathlib import Path

from dotenv import load_dotenv
import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, Engine


ROOT = Path(__file__).resolve().parents[1]
PRODUCTS_PATH = ROOT / "data/raw/products.parquet"
SALES_PATH = ROOT / "data/processed/sales_clean.csv"
SCHEMA_PATH = ROOT / "sql/schema.sql"


def database_url() -> URL:
    load_dotenv(ROOT / ".env")
    required = ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB")
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        raise ValueError(f"Missing database configuration: {', '.join(missing)}")
    return URL.create(
        "postgresql+psycopg",
        username=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        host=os.getenv("POSTGRES_HOST", "127.0.0.1"),
        port=int(os.getenv("POSTGRES_PORT", "5433")),
        database=os.environ["POSTGRES_DB"],
    )


def optional(value):
    return None if pd.isna(value) or value == "" else value


def money(value: object) -> Decimal:
    amount = Decimal(str(value))
    if not amount.is_finite() or amount.as_tuple().exponent < -2:
        raise ValueError(f"Invalid monetary amount: {value!r}")
    return amount


def item_id(order_id: int, product_id: int, unit_price: Decimal) -> int:
    """Stable independent ID for a cleaned sale line, including historical price."""
    key = f"{order_id}:{product_id}:{unit_price:.2f}".encode("ascii")
    return int.from_bytes(hashlib.sha256(key).digest()[:8], "big") & ((1 << 63) - 1) or 1


def source_rows(products_path: Path = PRODUCTS_PATH, sales_path: Path = SALES_PATH):
    products = pd.read_parquet(products_path)
    sales = pd.read_csv(sales_path, dtype=str, keep_default_na=False)
    required_products = {"id", "title", "category", "price", "stock", "brand", "rating"}
    required_sales = {"order_id", "customer_id", "customer_name", "customer_email",
                      "order_date", "product_id", "quantity", "unit_price"}
    if not required_products <= set(products) or not required_sales <= set(sales):
        raise ValueError("Source file is missing required columns")

    product_rows = [{
        "product_id": int(row.id), "title": str(row.title), "category": str(row.category),
        "price": money(row.price), "stock": optional(row.stock),
        "brand": optional(row.brand), "rating": None if pd.isna(row.rating) else Decimal(str(row.rating)),
    } for row in products.itertuples(index=False)]
    for row in product_rows:
        if row["stock"] is not None:
            row["stock"] = int(row["stock"])
    if len({row["product_id"] for row in product_rows}) != len(product_rows):
        raise ValueError("Duplicate product IDs in Parquet")

    customers, orders, items = {}, {}, {}
    product_ids = {row["product_id"] for row in product_rows}
    for row in sales.itertuples(index=False):
        order_id, customer_id, product_id = int(row.order_id), int(row.customer_id), int(row.product_id)
        if product_id not in product_ids:
            raise ValueError(f"Unknown product ID {product_id} in sales CSV")
        customer = {"customer_id": customer_id, "customer_name": optional(row.customer_name),
                    "customer_email": optional(row.customer_email)}
        order = {"order_id": order_id, "customer_id": customer_id,
                 "order_date": date.fromisoformat(row.order_date)}
        for mapping, key, value in ((customers, customer_id, customer), (orders, order_id, order)):
            if key in mapping and mapping[key] != value:
                raise ValueError(f"Conflicting source details for ID {key}")
            mapping[key] = value
        price = money(row.unit_price)
        logical_key = (order_id, product_id, price)
        if logical_key in items:
            raise ValueError(f"Duplicate cleaned sale line: {logical_key}")
        items[logical_key] = {"order_item_id": item_id(*logical_key), "order_id": order_id,
                              "product_id": product_id, "quantity": int(row.quantity),
                              "unit_price": price}
    item_rows = list(items.values())
    if len({row["order_item_id"] for row in item_rows}) != len(item_rows):
        raise ValueError("Generated order item ID collision")
    return product_rows, list(customers.values()), list(orders.values()), item_rows


UPSERTS = (
    """INSERT INTO products (product_id, title, category, price, stock, brand, rating)
       VALUES (:product_id, :title, :category, :price, :stock, :brand, :rating)
       ON CONFLICT (product_id) DO UPDATE SET title=EXCLUDED.title, category=EXCLUDED.category,
       price=EXCLUDED.price, stock=EXCLUDED.stock, brand=EXCLUDED.brand, rating=EXCLUDED.rating""",
    """INSERT INTO customers (customer_id, customer_name, customer_email)
       VALUES (:customer_id, :customer_name, :customer_email)
       ON CONFLICT (customer_id) DO UPDATE SET customer_name=EXCLUDED.customer_name,
       customer_email=EXCLUDED.customer_email""",
    """INSERT INTO orders (order_id, customer_id, order_date)
       VALUES (:order_id, :customer_id, :order_date)
       ON CONFLICT (order_id) DO UPDATE SET customer_id=EXCLUDED.customer_id,
       order_date=EXCLUDED.order_date""",
    """INSERT INTO order_items (order_item_id, order_id, product_id, quantity, unit_price)
       VALUES (:order_item_id, :order_id, :product_id, :quantity, :unit_price)
       ON CONFLICT (order_item_id) DO UPDATE SET order_id=EXCLUDED.order_id,
       product_id=EXCLUDED.product_id, quantity=EXCLUDED.quantity,
       unit_price=EXCLUDED.unit_price""",
)


def load_database(engine: Engine, products_path: Path = PRODUCTS_PATH,
                  sales_path: Path = SALES_PATH, schema_path: Path = SCHEMA_PATH) -> dict[str, int]:
    batches = source_rows(products_path, sales_path)
    with engine.begin() as connection:
        for statement in schema_path.read_text(encoding="utf-8").split(";"):
            if statement.strip():
                connection.execute(text(statement))
        for statement, rows in zip(UPSERTS, batches):
            if rows:
                connection.execute(text(statement), rows)
    return dict(zip(("products", "customers", "orders", "order_items"), map(len, batches)))


def main() -> None:
    engine = create_engine(database_url())
    try:
        counts = load_database(engine)
        print("Loaded source records: " + ", ".join(f"{name}={count}" for name, count in counts.items()))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()

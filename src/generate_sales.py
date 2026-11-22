"""Generate a repeatable, deliberately imperfect sales CSV for Stage 2."""

from pathlib import Path
import random

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
PRODUCTS_PATH = ROOT / "data/raw/products.parquet"
OUTPUT_PATH = ROOT / "data/raw/sales_raw.csv"
SEED = 20261122
COLUMNS = (
    "order_id", "customer_id", "customer_name", "customer_email",
    "order_date", "product_id", "quantity", "unit_price",
)


def generate_sales(products: pd.DataFrame, seed: int = SEED) -> pd.DataFrame:
    """Build 180 valid line items, then add known data quality problems."""
    if not {"id", "price"}.issubset(products.columns) or products.empty:
        raise ValueError("Products must contain id and price columns")
    catalog = products.set_index("id")["price"].to_dict()
    ids = sorted(catalog)
    if len(ids) < 2:
        raise ValueError("At least two products are needed for multi-item orders")

    rng = random.Random(seed)
    rows = []
    for order_number in range(1, 91):
        customer_number = rng.randint(1, 30)
        order_date = pd.Timestamp("2025-01-01") + pd.Timedelta(days=rng.randint(0, 364))
        for product_id in rng.sample(ids, 2):
            # Historical sale prices may differ from today's catalog price.
            multiplier = rng.choice((0.85, 1.0, 1.0, 1.1))
            rows.append({
                "order_id": order_number,
                "customer_id": str(customer_number),
                "customer_name": f"Customer {customer_number}",
                "customer_email": f"customer{customer_number}@example.com",
                "order_date": order_date.strftime("%Y-%m-%d"),
                "product_id": product_id,
                "quantity": rng.randint(1, 4),
                "unit_price": f"{float(catalog[product_id]) * multiplier:.2f}",
            })

    rows.extend((rows[0].copy(), rows[1].copy()))  # exact duplicates
    rows[2]["customer_name"] = None
    rows[3]["customer_email"] = None
    rows[4]["quantity"] = "2.0"  # numeric text that can be converted
    rows[5]["quantity"] = "many"
    rows[6]["unit_price"] = "free"
    rows[7]["order_date"] = "2025-99-99"
    rows[8]["quantity"] = -2
    rows[9]["quantity"] = 0
    rows[10]["product_id"] = max(ids) + 999999
    rows[11]["customer_id"] = None
    rows[16]["customer_id"] = None  # recoverable from another line in this order
    rows[14]["order_date"] = pd.Timestamp(rows[14]["order_date"]).strftime("%m/%d/%Y")
    repeated_item = rows[15].copy()
    repeated_item["quantity"] = 1  # another legitimate purchase of the same item
    rows.append(repeated_item)
    wrong_customer = rows[12].copy()
    wrong_customer["customer_id"] = 999
    rows.append(wrong_customer)
    wrong_date = rows[13].copy()
    wrong_date["order_date"] = "2024-01-01"
    rows.append(wrong_date)
    return pd.DataFrame(rows, columns=COLUMNS)


def main() -> None:
    products = pd.read_parquet(PRODUCTS_PATH)
    sales = generate_sales(products)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    sales.to_csv(OUTPUT_PATH, index=False)
    print(f"Generated {len(sales)} sales rows with seed {SEED}: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()

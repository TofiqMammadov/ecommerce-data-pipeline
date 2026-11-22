"""Fetch 100 DummyJSON products and save selected fields as Parquet."""

from pathlib import Path
import sys

import pandas as pd
import requests


API_URL = "https://dummyjson.com/products"
PRODUCT_COUNT = 100
PAGE_SIZE = 50
TIMEOUT_SECONDS = 15
OUTPUT_PATH = Path(__file__).resolve().parents[1] / "data" / "raw" / "products.parquet"
COLUMNS = ("id", "title", "category", "price", "stock", "brand", "rating")


def fetch_products() -> list[dict]:
    products = []

    with requests.Session() as session:
        while len(products) < PRODUCT_COUNT:
            offset = len(products)
            try:
                response = session.get(
                    API_URL,
                    params={"limit": min(PAGE_SIZE, PRODUCT_COUNT - offset), "skip": offset},
                    timeout=TIMEOUT_SECONDS,
                )
                response.raise_for_status()
                payload = response.json()
            except (requests.RequestException, ValueError) as exc:
                raise RuntimeError(f"Failed to fetch products at offset {offset}: {exc}") from exc

            if not isinstance(payload, dict) or not isinstance(payload.get("products"), list):
                raise ValueError(f"Invalid API response at offset {offset}: missing products list")

            page = payload["products"]
            if not page:
                raise ValueError(f"API returned no products at offset {offset}; need {PRODUCT_COUNT}")
            if len(page) > min(PAGE_SIZE, PRODUCT_COUNT - offset):
                raise ValueError(f"API returned too many products at offset {offset}")
            products.extend(page)

    if len(products) != PRODUCT_COUNT:
        raise ValueError(f"Expected {PRODUCT_COUNT} products, received {len(products)}")
    return products


def validate_and_select(products: list[dict]) -> pd.DataFrame:
    rows = []
    seen_ids = set()

    for index, product in enumerate(products):
        if not isinstance(product, dict):
            raise ValueError(f"Product at position {index} is not an object")

        product_id = product.get("id")
        if isinstance(product_id, bool) or not isinstance(product_id, int) or product_id <= 0:
            raise ValueError(f"Invalid product ID at position {index}: {product_id!r}")
        if product_id in seen_ids:
            raise ValueError(f"Duplicate product ID: {product_id}")
        seen_ids.add(product_id)

        for field in ("title", "category"):
            if not isinstance(product.get(field), str) or not product[field].strip():
                raise ValueError(f"Product {product_id} has invalid {field}")

        price = product.get("price")
        if isinstance(price, bool) or not isinstance(price, (int, float)) or not 0 <= price < float("inf"):
            raise ValueError(f"Product {product_id} has invalid price")

        stock = product.get("stock")
        if stock is not None and (isinstance(stock, bool) or not isinstance(stock, int) or stock < 0):
            raise ValueError(f"Product {product_id} has invalid stock")

        brand = product.get("brand")
        if brand is not None and not isinstance(brand, str):
            raise ValueError(f"Product {product_id} has invalid brand")

        rating = product.get("rating")
        if rating is not None and (
            isinstance(rating, bool)
            or not isinstance(rating, (int, float))
            or not 0 <= rating <= 5
        ):
            raise ValueError(f"Product {product_id} has invalid rating")

        rows.append({field: product.get(field) for field in COLUMNS})

    frame = pd.DataFrame(rows, columns=COLUMNS)
    return frame.astype(
        {
            "id": "int64",
            "title": "string",
            "category": "string",
            "price": "float64",
            "stock": "Int64",
            "brand": "string",
            "rating": "Float64",
        }
    )


def main() -> None:
    frame = validate_and_select(fetch_products())
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(OUTPUT_PATH, engine="pyarrow", index=False)
    print(f"Fetched {len(frame)} products")
    print(f"Saved to {OUTPUT_PATH}")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

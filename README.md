# E-commerce data pipeline

## Stage 1: API to Parquet

Fetch 100 products from the [DummyJSON Products API](https://dummyjson.com/products), select `id`, `title`, `category`, `price`, `stock`, `brand`, and `rating`, and save them to `data/raw/products.parquet`. Missing optional values (`stock`, `brand`, and `rating`) are stored as nulls.

From the project root, with Python 3.12 and the existing virtual environment:

```bash
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python src/fetch_products.py
```

The script prints the fetched count and output location. It exits with an error if the API request fails, the response is invalid, or fewer than 100 distinct products are available.

## Stage 2: synthetic sales and cleaning

Run from the project root after Stage 1 has produced `data/raw/products.parquet`:

```bash
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python src/generate_sales.py
.venv/bin/python src/clean_sales.py
.venv/bin/python -m pytest -q
```

The generator uses seed `20261122`, samples only product IDs from the Parquet file for ordinary sales, and writes 185 rows to `data/raw/sales_raw.csv`. It adds one deliberately unknown product ID plus duplicates, missing customer fields, malformed numbers and dates, non-positive quantities, and conflicting order details. Re-running it against the same product file produces the same CSV.

The cleaner writes `data/processed/sales_clean.csv` and `data/processed/sales_quality_report.json`. It removes exact duplicates and rows with invalid dates, unknown products, invalid identifiers, non-positive or non-integer quantities, and invalid prices. It accepts ISO dates and `MM/DD/YYYY`, then writes ISO dates. A missing customer ID is filled only from another valid line of the same order; missing names or emails are filled from a known row for that customer when available. Unrecoverable customer IDs cause removal; unrecoverable names and emails remain blank for later review.

Each order must have one customer ID and date. A conflicting line is removed, with the first valid line setting the order's values. Repeated lines for the same order, product, and sale price have their quantities summed after exact duplicates are removed. Lines at different sale prices remain separate, preserving legitimate historical prices. Sale prices must be positive and have no more than two decimal places; a difference from today's catalog price is reported and retained.

The JSON report counts raw and final rows, missing values, invalid values, corrections, and removals. `rows_removed` is the raw row count minus the final row count; it includes exact duplicates, rejected rows, and lines consolidated into one order item. `rejected_rows` counts only invalid or conflicting input rows. `rows_corrected` counts surviving input rows changed by date or numeric normalization, customer detail fills, or item consolidation.

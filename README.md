# E-commerce data pipeline

## Stage 1: API to Parquet

Fetch 100 products from the [DummyJSON Products API](https://dummyjson.com/products), select `id`, `title`, `category`, `price`, `stock`, `brand`, and `rating`, and save them to `data/raw/products.parquet`. Missing optional values (`stock`, `brand`, and `rating`) are stored as nulls.

From the project root, with Python 3.12 and the existing virtual environment:

```bash
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python src/fetch_products.py
```

The script prints the fetched count and output location. It exits with an error if the API request fails, the response is invalid, or fewer than 100 distinct products are available.

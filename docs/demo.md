# Stage 4 presentation demo

## Prepare

Use an Apple Silicon Mac with Python 3.12, Docker Desktop, and internet access. From the repository root, create the virtual environment and install dependencies if needed:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` with your own local PostgreSQL password. If `.env` already exists, keep it and confirm its values match the existing Docker volume. Do not show the password on screen or commit `.env`.

## Present the architecture

Show the Mermaid diagram in the README: API → Parquet → seeded sales CSV → cleaning and quality report → transactional PostgreSQL load → verification. Explain that the synthetic input deliberately includes invalid rows, while cleaned sales reference valid catalog products.

## Run the demo

```bash
docker compose up -d --wait
.venv/bin/python src/run_pipeline.py
```

Point out each of the six stage messages, the raw and cleaned row counts, all three zero orphan counts, and revenue. The first run on a fresh database should show table counts equal to the source counts. The exact revenue can change when DummyJSON changes product prices.

Run the same command again:

```bash
.venv/bin/python src/run_pipeline.py
```

Compare the database row counts and revenue. If the API catalog did not change between runs, they should be identical; the loader uses upserts and stable order-item IDs. The pipeline does not delete old data, so a database used for earlier demos may contain additional rows. The runner still verifies the current run's sale lines and revenue.

Show the SQL checks and analysis:

```bash
docker compose exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < sql/verify.sql
docker compose exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < sql/sales_by_product.sql
```

The first query prints table counts, three orphan counts that should all be zero, and total sales revenue. The second ranks products by sales revenue. Then run tests:

```bash
.venv/bin/python -m pytest -q
```

Explain that tests use temporary database schemas and leave application tables intact. The loader transaction rolls back on failure, and re-running it updates matching records instead of duplicating them.

## If the demo fails

- API request failure: check internet access and retry the command.
- PostgreSQL unavailable: check Docker Desktop, run `docker compose up -d --wait`, and verify `.env` host and port.
- Credentials mismatch with an existing Docker volume: use the original database credentials rather than deleting the volume.

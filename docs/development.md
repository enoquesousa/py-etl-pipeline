# Development Guide

## Local Setup

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# Linux / macOS
source .venv/bin/activate

pip install -r requirements.txt         # runtime, tests, ruff, Strawberry, Uvicorn
cp .env.example .env                  # then edit .env with your credentials
```

## Running the Pipeline

```bash
# One-shot, bulk mode (default)
python main.py

# One-shot, upsert mode
$env:LOAD_MODE = "upsert"             # PowerShell
python main.py

# Scheduled (runs immediately, then every 60 minutes)
$env:RUN_SCHEDULED = "true"
python main.py
```

## CSV Input

Set `SALES_CSV_PATH` to point at a CSV file. The extractor normalises column names
(e.g. `Unit Price` → `unit_price`) so header casing doesn't matter.

Supported columns (after normalisation):

| Column | Required | Notes |
|--------|----------|-------|
| `product_name` | Yes | |
| `unit_price` | Yes | |
| `quantity` | No | Defaults to 1 |
| `sold_at` | No | Parsed to UTC datetime |
| `external_id` | No | Used as upsert key |

Example CSV:

```csv
Product Name,Quantity,Unit Price,Sold At,External ID
Laptop,2,1299.99,2026-05-01T10:30:00Z,ext-001
Mouse,5,29.99,2026-05-01T11:00:00Z,ext-002
```

## Lint and format

Uses [Ruff](https://docs.astral.sh/ruff/) (configured in `pyproject.toml`).

```bash
ruff check .
ruff format .
```

Continuous Integration runs `ruff check`, `ruff format --check`, and `pytest` on pushes and pull requests (see `.github/workflows/ci.yml`).

## GraphQL API (optional)

A small read-only schema exposes `health`, `version`, and non-secret ETL runtime hints (`loadBatchSize`, default `LOAD_MODE`, `RUN_SCHEDULED` default). Strawberry and Uvicorn are listed in `requirements.txt` together with the rest of the stack.

Run the ASGI app (from repo root, with `src` on `PYTHONPATH` or after `pip install -e .`):

```bash
uvicorn py_etl_pipeline.graphql_server:app --host 127.0.0.1 --port 8000 --no-proxy-headers
```

Example query:

```graphql
query {
  health
  version
  etl {
    loadBatchSize
    defaultLoadMode
    scheduledDefault
  }
}
```

Post JSON to `http://localhost:8000/graphql` with body `{"query": "query { health }"}`.

GET and POST are supported only at `/graphql`. GraphiQL and WebSockets are
disabled. The body and query string each have a 64 KiB limit before parsing.
The default local mode checks the actual peer and browser authority/origin and
rejects forwarding headers. Do not expose this mode through a proxy, whose
loopback connection would be trusted as a local client.

Set `ETL_GRAPHQL_PUBLIC=1` only when you intend to publish the schema's metadata
to anyone who can reach the listener. This public mode does not authenticate
clients and does not make access decisions from forwarding headers. It never
grants access to sales rows, database credentials, or ETL execution. If deployment
policy requires authenticated monitoring, place the public probe behind an
appropriately configured access-controlled proxy. Keep backend ports private.
The probe does not automatically load `.env`; pass Uvicorn `--env-file` explicitly
when you want file-based settings.

## Tests

```bash
# Default suite — uses in-memory SQLite, no live DB required
pytest

# Verbose with failure summary
pytest -v -ra

# Single module
pytest tests/test_config.py -v
```

### PostgreSQL integration tests

Tests marked `@pytest.mark.pg` require a live Postgres instance. Use a disposable
database: fixtures may create tables, even though test transactions are rolled
back. Opt in with `--run-pg`. For example, in bash:

```bash
# Set a throwaway password without putting its value in the Docker argv.
read -rsp 'Disposable database password: ' POSTGRES_PASSWORD
export POSTGRES_PASSWORD
export POSTGRES_USER=etl POSTGRES_DB=etl_db POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=5433
unset DATABASE_URL
docker run --name etl-pg \
  --env POSTGRES_USER --env POSTGRES_PASSWORD --env POSTGRES_DB \
  -p 127.0.0.1:5433:5432 -d postgres:16

# Wait until PostgreSQL is ready, then use the exported connection fields.
pytest --run-pg
```

Tests do not load a checkout `.env`. Export the test connection settings
explicitly. Diagnostic failures and skipped PG fixtures omit connection values
and raw exceptions. Do not print environment values to debug credentials.

## Migrations (Alembic)

```bash
# Apply all pending migrations
alembic upgrade head

# Generate a new migration after changing models.py
alembic upgrade head
alembic revision --autogenerate -m "describe change"

# Roll back one migration
alembic downgrade -1

```

Select the database through exported connection settings or the checkout-root
`.env`. Avoid putting a DSN containing credentials in `alembic -x url=...` or
other command-line arguments; these can appear in shell history and process
inspection. A full URL remains supported for existing callers.

## Docker Compose

Brings up Postgres 16 + the ETL container. First fill in `POSTGRES_PASSWORD` in
your local `.env` or inject it through the environment; missing or empty values
are rejected:

```bash
docker compose up --build
```

- **`db`**: Postgres on `127.0.0.1:5433` → container `5432` by default. User `postgres` and database `data-py` can be configured; there is no default password.
- **`etl`**: Builds from `Dockerfile`, mounts `./data` read-only, runs in scheduled mode (every 60 minutes).
- The ETL container starts only after Postgres passes its `pg_isready` healthcheck.
- The worker receives separate connection fields and connects to `db:5432`; SQLAlchemy escapes the fields. The host-side `DATABASE_URL` is not forwarded into the container.
- Environment-based secrets remain visible to Docker administrators. Changing `POSTGRES_PASSWORD` does not reset credentials already stored in a persistent Postgres volume; rotate the database account and client settings together.

One-off run against the Compose DB:

```bash
LOAD_MODE=upsert docker compose run --rm -e LOAD_MODE=upsert etl python main.py
```

## Utility Scripts

| Script | Purpose |
|--------|---------|
| `scripts/validate_load.py` | End-to-end smoke test: bulk + upsert against generated CSVs. Uses SQLite by default. |
| `scripts/validate_load.ps1` | PowerShell wrapper; prefer exporting connection settings over passing a secret-bearing `-DatabaseUrl` argument. |
| `scripts/diagnose_db.py` | Tests the configured PostgreSQL connection without printing credentials, DSNs, or raw failures; preserves query/TLS/socket options and never tries a fallback host. |
| `scripts/demo_load.py` | Interactive demo: bulk insert, upsert, logging. Run with `DATABASE_URL=sqlite:///demo.db`. |

Run from the repo root:

```bash
python scripts/validate_load.py
python scripts/diagnose_db.py
python scripts/demo_load.py
```

The connection diagnostic respects all options in the selected URL, including
`connect_timeout` when supplied. It returns 0 on success, 1 on a failed connection
or cleanup, and 2 for invalid configuration or a non-PostgreSQL backend. It no
longer forces a timeout or tries another host.

## Code Conventions

- Modules stay under **300 lines** — split rather than grow.
- Type annotations follow **PEP 484**; SQLAlchemy 2 `Mapped[]` style.
- Database identifiers use **snake_case** (`sales`, `logs`).
- No comments unless the *why* is non-obvious.

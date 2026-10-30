# Configuration Reference

All settings are read from environment variables. Copy `.env.example` to `.env`
and fill in your values — dotenv files with real credentials are excluded from
Git and the Docker build context and must never be committed.

The CLI, utility scripts, and Alembic explicitly load the `.env` at the checkout
root when they start. Exported environment variables take precedence. Library
imports and configuration getters do not load files. An embedding application
can opt in with `load_environment(path)` and a deliberate file path; it does not
search ancestor directories. The normal dotenv interpolation behavior remains
enabled. For literal credentials whose characters would be interpreted by an
environment-file parser, inject them directly through the process environment
or your secret manager.
Alembic callers supplying an explicit `-x url=...` retain that override and skip
dotenv loading; prefer environment injection for URLs that contain secrets.

## Database

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DATABASE_URL` | Yes* | — | Complete URL, used unchanged; PostgreSQL transport/auth options and SQLite URLs are supported |
| `POSTGRES_USER` | Yes* | — | Used only when `DATABASE_URL` is unset |
| `POSTGRES_PASSWORD` | Yes* | — | Used only when `DATABASE_URL` is unset |
| `POSTGRES_DB` | Yes* | — | Used only when `DATABASE_URL` is unset |
| `POSTGRES_HOST` | No | `localhost` | Used only when `DATABASE_URL` is unset |
| `POSTGRES_PORT` | No | `5433` | Used only when `DATABASE_URL` is unset; integer from 1 to 65535 |

\* Either `DATABASE_URL` **or** the full set of `POSTGRES_*` variables is required.

An explicitly supplied URL takes precedence and may use external database
authentication without a password in the URL. Its caller is responsible for
valid URL encoding and TLS options. Do not print it: passwords and query options
can both contain secrets.

The separate fields are preferable when entering a password: SQLAlchemy 2.1+
escapes user, password, and database name without changing spaces into `+`.
The host must describe a hostname or IP address without URL separators; IPv6
is supported. Host and port failures use fixed messages without their values.
`database_url()` still returns a string for the SQLAlchemy/driver consumers.

Compose requires a nonempty `POSTGRES_PASSWORD`. It passes separate fields to
the worker, uses `db:5432` inside its network, and publishes PostgreSQL only on
`127.0.0.1:${POSTGRES_PORT:-5433}`. It intentionally does not pass a host-side
`DATABASE_URL` into the worker. Existing PostgreSQL volumes retain their stored
passwords; changing this environment value does not rotate an initialized
database account. Update the account and clients together.

## Optional GraphQL probe

| Variable | Default | Description |
|----------|---------|-------------|
| `ETL_GRAPHQL_PUBLIC` | `0` | `0`/absent permits only local clients; `1` deliberately publishes non-secret metadata without authentication; other values, including empty, are invalid |

The ASGI probe reads only exported environment values. To load a file for the
server, explicitly use Uvicorn `--env-file`. Its schema exposes health, package
version, normalized load mode, batch size, and a scheduling flag. It does not
expose database URLs or credentials. Local access also checks actual peer,
Host, Origin, and browser fetch metadata; use `--no-proxy-headers`.

## Pipeline behaviour

| Variable | Default | Description |
|----------|---------|-------------|
| `SALES_CSV_PATH` | — | Path to the CSV file to extract. If unset or missing, the pipeline runs with zero rows. |
| `LOAD_MODE` | `bulk` | Loading strategy: `bulk` or `upsert` |
| `LOAD_BATCH_SIZE` | `500` | Rows processed per database batch. Min: 1. |

## Scheduling

| Variable | Default | Description |
|----------|---------|-------------|
| `RUN_SCHEDULED` | — | Set to `true` / `1` / `yes` to run on a repeating schedule instead of once |
| `SCHEDULE_INTERVAL_MINUTES` | `60` | Interval between scheduled runs |

## Retry (tenacity)

| Variable | Default | Description |
|----------|---------|-------------|
| `DB_RETRY_ATTEMPTS` | `10` | Maximum retries on `OperationalError` |
| `DB_RETRY_BASE_DELAY_SECONDS` | `0.5` | Initial backoff delay |
| `DB_RETRY_MAX_DELAY_SECONDS` | `10` | Maximum backoff delay |

## Debugging

| Variable | Default | Description |
|----------|---------|-------------|
| `SQLALCHEMY_ECHO` | — | Set to `true` / `1` / `yes` to print all SQL statements |
| `VALIDATE_FORCE_SQLITE` | — | Forces `scripts/validate_load.py` to use SQLite even when `DATABASE_URL` is set |

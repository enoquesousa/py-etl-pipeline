<div align="center">
<h1>py-etl-pipeline</h1>

<p>Minimal Python ETL: CSV → PostgreSQL with bulk insert, native upsert, audit logging, retries, optional scheduling, Alembic migrations, Docker Compose, and an optional GraphQL health surface.</p>

  <img src="assets/python.png" alt="py-etl-pipeline banner" width="600px">

  <br>

[![CI](https://github.com/enoquesousa/py-etl-pipeline/actions/workflows/ci.yml/badge.svg)](https://github.com/enoquesousa/py-etl-pipeline/actions/workflows/ci.yml)
[![CodeQL](https://github.com/enoquesousa/py-etl-pipeline/actions/workflows/codeql.yml/badge.svg)](https://github.com/enoquesousa/py-etl-pipeline/actions/workflows/codeql.yml)
[![Dependency review](https://img.shields.io/badge/dependency%20review-in%20CI-0085CA?style=flat&logo=githubactions&logoColor=white)](https://github.com/enoquesousa/py-etl-pipeline/actions/workflows/ci.yml)
[![Publish](https://img.shields.io/badge/Publish-release%20%7C%20manual-blue?style=flat&logo=githubactions&logoColor=white)](https://github.com/enoquesousa/py-etl-pipeline/actions/workflows/publish.yml)
[![Python](https://img.shields.io/badge/Python-3.11%2B-blue?style=flat&logo=python&logoColor=white)](https://github.com/enoquesousa/py-etl-pipeline/blob/main/pyproject.toml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=flat)](LICENSE)
[![Last Commit](https://img.shields.io/github/last-commit/enoquesousa/py-etl-pipeline?style=flat)](https://github.com/enoquesousa/py-etl-pipeline/commits)
[![Ruff](https://img.shields.io/badge/Ruff-linting-261230?style=flat&logo=ruff&logoColor=white)](https://github.com/astral-sh/ruff)
[![pytest](https://img.shields.io/badge/tests-pytest-blue?style=flat&logo=pytest&logoColor=white)](https://docs.pytest.org/)
[![CodeFactor](https://www.codefactor.io/repository/github/enoquesousa/py-etl-pipeline/badge)](https://www.codefactor.io/repository/github/enoquesousa/py-etl-pipeline)
[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?style=flat&logo=pre-commit&logoColor=white)](https://github.com/enoquesousa/py-etl-pipeline/blob/main/.pre-commit-config.yaml)

</div>

---

**py-etl-pipeline** is a small, production-minded **ETL** service: **extract** sales rows from CSV (pandas + normalised headers), **transform** with validation and coercion, then **load** into PostgreSQL using either **bulk insert** or **`ON CONFLICT DO UPDATE` upsert**, with **row-level audit logging**, **tenacity** retries for transient DB errors, optional **scheduled** runs, **Alembic** migrations, and **Docker Compose** for Postgres + the worker. An optional **Strawberry GraphQL** ASGI app exposes **health**, **version**, and non-secret runtime hints. Canonical repository: `github.com/enoquesousa/py-etl-pipeline`.

## Demo (quick smoke test)

Create a virtual environment, install dependencies, point at a SQLite file, and run the bundled demo script (no live Postgres required).

**Linux / macOS (bash)**

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

export DATABASE_URL="sqlite:///./demo_smoke.db"
python scripts/demo_load.py
```

**Windows (PowerShell)**

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

$env:DATABASE_URL = "sqlite:///./demo_smoke.db"
python scripts/demo_load.py
```

To exercise the full **CLI entrypoint** against PostgreSQL, copy `.env.example` → `.env`, set a password and the other `POSTGRES_*` fields (or supply a complete `DATABASE_URL`), ensure your CSV path via `SALES_CSV_PATH`, then run `python main.py` (see [docs/development.md](docs/development.md)). CLI entry points explicitly load the checkout-root `.env` without overriding exported variables. Importing the library does not search for or load dotenv files.

## Features

| Area | What you get |
| ---- | -------------- |
| Extract | CSV via **pandas** with automatic header normalisation (e.g. `Unit Price` → `unit_price`). |
| Transform | Type coercion, defaults, and row validation before load. |
| Load | **Bulk insert** or PostgreSQL-native **upsert** with shared chunking/dedup helpers. |
| Audit | Every load batch recorded in a **`logs`** table via `load_logging`. |
| Resilience | **Tenacity** retries with exponential backoff for transient database failures (`retry_db`). |
| Scheduling | Optional recurring runs using the **`schedule`** library (`RUN_SCHEDULED`). |
| Migrations | **Alembic** with autogenerate wired to SQLAlchemy models. |
| Docker | **`docker-compose.yml`** — Postgres 16 plus an ETL image with health-aware startup. |
| GraphQL (optional) | Local **Strawberry** HTTP probe at `/graphql`: `health`, `version`, and non-secret ETL runtime hints; explicit opt-in for public metadata access. |

## Tech stack

| Component | Role |
| --------- | ---- |
| Python 3.11+ | Language and runtime |
| SQLAlchemy 2.1+ | ORM, sessions, schema bootstrap, and connection-field escaping |
| psycopg2 | PostgreSQL driver |
| pandas | CSV extraction |
| tenacity | Retry/backoff for DB operations |
| Alembic | Schema migrations |
| pytest / pytest-cov | Tests and coverage |
| Ruff | Lint + format |
| Strawberry + Starlette + Uvicorn | Optional GraphQL HTTP surface |

## Prerequisites

- Python **3.11+** and `pip`.
- **PostgreSQL** for production-style runs (`main.py`, Compose stack, `--run-pg` tests). **SQLite** is enough for demos and much of the unit suite.

## Installation and usage

### From source (recommended)

```bash
git clone https://github.com/enoquesousa/py-etl-pipeline.git
cd py-etl-pipeline
pip install -r requirements.txt
cp .env.example .env   # then edit credentials and paths
```

### Development install (editable)

```bash
pip install -e .
```

### PyPI

There are **no PyPI install badges** in this README yet because uploads to PyPI run **only on a published GitHub Release** (see `.github/workflows/publish.yml`). The same workflow supports **Run workflow** (manual dispatch): it builds wheels/sdists and uploads **artifacts** for inspection, without publishing. Configure **PyPI trusted publishing** (or a token) for the `pypi` environment for release publishes; then `pip install py-etl-pipeline` works after the first successful publish.

**Dependency review** runs as a **CI job on every pull request** (not on plain pushes to `main`), using `actions/dependency-review-action` alongside lint and tests.

## Quick Start

### One-shot pipeline (bulk)

```bash
python main.py
```

`LOAD_MODE` defaults to **`bulk`**. The pipeline bootstraps missing tables and reads the CSV configured by `SALES_CSV_PATH`.

### Upsert mode

**Linux / macOS**

```bash
export LOAD_MODE=upsert
python main.py
```

**Windows (PowerShell)**

```powershell
$env:LOAD_MODE = "upsert"
python main.py
```

### Scheduled mode

Runs once at startup, then every `SCHEDULE_INTERVAL_MINUTES` (default **60**):

**Linux / macOS**

```bash
export RUN_SCHEDULED=true
python main.py
```

**Windows (PowerShell)**

```powershell
$env:RUN_SCHEDULED = "true"
python main.py
```

### Optional GraphQL probe

```bash
uvicorn py_etl_pipeline.graphql_server:app --host 127.0.0.1 --port 8000 --no-proxy-headers
```

Example body against `http://localhost:8000/graphql`:

```json
{"query": "query { health version }"}
```

Only `/graphql` is served, using GET or POST. The probe does not query the
database, return sales/log records, or run the ETL. By default it accepts only
an actual loopback peer with a local Host and compatible Origin/fetch metadata.
It rejects forwarding headers in local mode; keep `--no-proxy-headers` and do
not publish the local mode through a proxy.

To deliberately publish these metadata fields, set `ETL_GRAPHQL_PUBLIC=1` and
choose the desired bind address. This mode is **unauthenticated public access**:
it does not introduce users, API keys, sessions, or JWTs. Missing/`0` keeps local
mode; any other value is rejected. GraphiQL and WebSockets are disabled. The body
and query string each have a 64 KiB limit before GraphQL parsing. These limits
are not a general query-cost or concurrency quota.

The probe reads the process environment. Use exported variables, or explicitly
pass Uvicorn `--env-file /path/to/file` when needed; the library does not load a
dotenv file on import. See [SECURITY.md](SECURITY.md) for its separate trust
boundary from the ETL worker and PostgreSQL.

## Resilience (automatic retries)

Database-facing entrypoints are wrapped with **`retry_db`** (Tenacity): transient errors are retried with backoff before surfacing. Tune behaviour via the Tenacity configuration in [`src/py_etl_pipeline/retry.py`](src/py_etl_pipeline/retry.py).

## Documentation

| Document | Contents |
| -------- | -------- |
| [LICENSE](LICENSE) | MIT License |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Contribution guidelines |
| [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) | Community standards |
| [SECURITY.md](SECURITY.md) | Vulnerability reporting, database credentials, and HTTP access model |
| [CHANGELOG.md](CHANGELOG.md) | Version history |
| [`codecov.yml`](codecov.yml) | Codecov defaults |
| [`.pre-commit-config.yaml`](.pre-commit-config.yaml) | Local + CI-friendly Ruff hooks |
| [docs/architecture.md](docs/architecture.md) | Components, data flow, schema |
| [docs/configuration.md](docs/configuration.md) | Environment variables |
| [docs/development.md](docs/development.md) | Setup, tests, migrations, Docker, scripts |

## Project layout

| Path | Role |
| ---- | ---- |
| `src/py_etl_pipeline/config.py` | Environment loading and DSN construction |
| `src/py_etl_pipeline/database.py` | Engine, session factory, `init_db` |
| `src/py_etl_pipeline/models.py` | SQLAlchemy models (`Sale`, `LogEntry`, …) |
| `src/py_etl_pipeline/extract.py` | CSV → DataFrame |
| `src/py_etl_pipeline/transform.py` | Validation and coercion |
| `src/py_etl_pipeline/load.py` | Load strategy dispatcher |
| `src/py_etl_pipeline/load_bulk.py` | Bulk insert path |
| `src/py_etl_pipeline/load_upsert.py` | Upsert path (PG-native + safeguards) |
| `src/py_etl_pipeline/load_logging.py` | Audit log helper |
| `src/py_etl_pipeline/load_utils.py` | Chunking, dedup, key checks |
| `src/py_etl_pipeline/pipeline.py` | End-to-end orchestration |
| `src/py_etl_pipeline/retry.py` | Shared retry decorator |
| `src/py_etl_pipeline/graphql_server.py` | Optional Strawberry ASGI app |
| `main.py` | CLI entry: bootstrap + run (scheduled or one-shot) |
| `migrations/` | Alembic environment and revisions |
| `scripts/` | `validate_load`, `diagnose_db`, `demo_load` |
| `tests/` | `pytest` suite (SQLite by default; Postgres behind `--run-pg`) |
| `.github/workflows/` | CI (incl. PR dependency review), CodeQL, PyPI publish |
| `docker-compose.yml` / `Dockerfile` | Local stack and ETL image |

## Tests

```bash
pip install -r requirements.txt
pytest -q
```

PostgreSQL integration tests are opt-in:

```bash
pytest --run-pg
```

### Coverage

Coverage is collected on Python **3.12** in CI and uploaded to **Codecov**.

```bash
pip install -r requirements.txt
pytest --cov=py_etl_pipeline --cov-report=term-missing
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## Changelog

See [CHANGELOG.md](CHANGELOG.md).

## License

[MIT](LICENSE).

<div align="center">

## Author

**Enoque Sousa**

[![LinkedIn](https://img.shields.io/badge/LinkedIn-0077B5?style=flat&logo=linkedin&logoColor=white)](https://www.linkedin.com/in/enoque-sousa-bb89aa168/)
[![GitHub](https://img.shields.io/badge/GitHub-100000?style=flat&logo=github&logoColor=white)](https://github.com/enoquesousa)
[![Portfolio](https://img.shields.io/badge/Portfolio-FF5722?style=flat&logo=target&logoColor=white)](https://enoquesousa.vercel.app)

**[⬆ Back to Top](#py-etl-pipeline)**

Made with ❤️ by [Enoque Sousa](https://github.com/enoquesousa)

**Project status:** Study project

</div>

"""Check the configured PostgreSQL connection without printing credentials."""

from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from py_etl_pipeline.config import database_url, load_environment


def main() -> int:
    load_environment(ROOT / ".env")
    try:
        url = database_url()
        backend = make_url(url).get_backend_name()
    except Exception:
        print("Database configuration is invalid or incomplete.")
        return 2
    if backend != "postgresql":
        print("This diagnostic requires a PostgreSQL connection URL.")
        return 2

    print("PostgreSQL connection configured.")
    try:
        connection_engine = create_engine(url, poolclass=NullPool)
        try:
            with connection_engine.connect():
                pass
        finally:
            connection_engine.dispose()
    except Exception:
        print("PostgreSQL connection check failed.")
        return 1

    print("PostgreSQL connection check succeeded.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Pytest fixtures and CLI options for the ETL test suite."""

from __future__ import annotations

import os
import sys
import warnings
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

# Ensure the src/ directory is on sys.path so `py_etl_pipeline` imports work
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC_PATH = os.path.join(ROOT, "src")
if SRC_PATH not in sys.path:
    sys.path.insert(0, SRC_PATH)

from py_etl_pipeline.models import Base


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register `--run-pg` to opt into integration tests that need a live PostgreSQL."""
    parser.addoption(
        "--run-pg",
        action="store_true",
        default=False,
        help="Run integration tests marked @pytest.mark.pg against a live PostgreSQL.",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip @pytest.mark.pg tests unless --run-pg is supplied."""
    if config.getoption("--run-pg"):
        return
    skip = pytest.mark.skip(reason="needs --run-pg (requires live PostgreSQL)")
    for item in items:
        if "pg" in item.keywords:
            item.add_marker(skip)


@pytest.fixture
def sqlite_engine() -> Iterator[Engine]:
    """Fresh in-memory SQLite engine with the full schema applied."""
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def session(sqlite_engine: Engine) -> Iterator[Session]:
    """Session bound to the in-memory SQLite engine."""
    factory = sessionmaker(bind=sqlite_engine, autoflush=False, autocommit=False, future=True)
    s = factory()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture
def pg_engine() -> Iterator[Engine]:
    """Engine for the PostgreSQL integration tests.

    Reads the URL from `DATABASE_URL` (or `POSTGRES_*`). Skips with a visible
    warning when the URL is missing, points to a non-Postgres backend, or the
    server is unreachable / refuses authentication.
    """
    from py_etl_pipeline.config import database_url

    try:
        url = database_url()
    except ValueError:
        pytest.skip("PostgreSQL configuration is missing or invalid.")

    if not url.startswith(("postgresql://", "postgresql+")):
        pytest.skip("DATABASE_URL is not a PostgreSQL URL.")

    engine = None
    try:
        engine = create_engine(url, future=True, pool_pre_ping=True)
        with engine.connect():
            pass
        Base.metadata.create_all(engine)
    except (SQLAlchemyError, ValueError):
        if engine is not None:
            engine.dispose()
        warnings.warn(
            "Skipping @pytest.mark.pg tests: the PostgreSQL connection or schema setup failed.",
            stacklevel=1,
        )
        pytest.skip("PostgreSQL not reachable; see warning above")

    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def pg_session(pg_engine: Engine) -> Iterator[Session]:
    """Session bound to a real PostgreSQL connection.

    Wraps the test in an outer transaction that is rolled back on teardown,
    so committed rows do not leak between tests.
    """
    connection = pg_engine.connect()
    outer = connection.begin()
    factory = sessionmaker(bind=connection, autoflush=False, autocommit=False, future=True)
    s = factory()
    try:
        yield s
    finally:
        s.close()
        outer.rollback()
        connection.close()

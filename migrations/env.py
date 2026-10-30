from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# Alembic Config object, provides access to values in alembic.ini
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Ensure we can import from src/ when running from repo root
ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from py_etl_pipeline.config import database_url, load_environment  # noqa: E402
from py_etl_pipeline.models import Base  # noqa: E402

target_metadata = Base.metadata


def get_url() -> str:
    # Prefer explicit DATABASE_URL (including when using `alembic -x url=...`)
    x_args = context.get_x_argument(as_dictionary=True)
    if "url" in x_args and x_args["url"]:
        return x_args["url"]
    load_environment(ROOT / ".env")
    return database_url()


def run_migrations_offline() -> None:
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = get_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()


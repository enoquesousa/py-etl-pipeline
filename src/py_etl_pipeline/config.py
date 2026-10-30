"""Explicit environment loading and database connection configuration."""

import os
from ipaddress import IPv6Address

from dotenv import load_dotenv
from sqlalchemy.engine import URL


def load_environment(dotenv_path: str | os.PathLike[str]) -> bool:
    """Load one explicit dotenv file, preserving values already in the environment.

    Importing this module never reads a file. Application entrypoints choose the
    path when starting; library users may call this function explicitly.
    """
    return load_dotenv(dotenv_path=dotenv_path, override=False)


def database_url() -> str:
    """Return an explicit URL unchanged, or safely encode PostgreSQL fields.

    A complete DATABASE_URL may select SQLite or external authentication. Only
    the separate PostgreSQL fields require a user, password and database name.
    The returned string contains credentials and must not be logged.
    """
    url = os.getenv("DATABASE_URL")
    if url:
        return url

    user = os.getenv("POSTGRES_USER", "")
    password = os.getenv("POSTGRES_PASSWORD", "")
    db = os.getenv("POSTGRES_DB", "")

    if not all([user, password, db]):
        raise ValueError("Set DATABASE_URL or POSTGRES_USER, POSTGRES_PASSWORD, and POSTGRES_DB.")

    connection = URL.create(
        "postgresql",
        username=user,
        password=password,
        host=_postgres_host(os.getenv("POSTGRES_HOST", "localhost")),
        port=_postgres_port(os.getenv("POSTGRES_PORT", "5433")),
        database=db,
    )
    return connection.render_as_string(hide_password=False)


def _postgres_port(value: str) -> int:
    message = "POSTGRES_PORT must be an integer from 1 to 65535."
    if not value.isascii() or not value.isdecimal():
        raise ValueError(message)
    try:
        port = int(value)
    except ValueError:
        raise ValueError(message) from None
    if not 1 <= port <= 65535:
        raise ValueError(message)
    return port


def _postgres_host(value: str) -> str:
    message = "POSTGRES_HOST must be a hostname or IP address without URL separators."
    bracketed = value.startswith("[") and value.endswith("]")
    if bracketed:
        value = value[1:-1]
    if bracketed or ":" in value:
        try:
            IPv6Address(value)
        except ValueError:
            raise ValueError(message) from None
    if any(character in value for character in "/?#@[]\\") or any(
        character.isspace() or ord(character) < 32 or ord(character) == 127 for character in value
    ):
        raise ValueError(message)
    return value


def load_batch_size() -> int:
    raw = os.getenv("LOAD_BATCH_SIZE", "500").strip()
    try:
        n = int(raw)
    except ValueError:
        n = 500
    return max(1, n)

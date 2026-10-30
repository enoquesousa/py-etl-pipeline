"""Database URLs and explicit environment loading, without database connections."""

from __future__ import annotations

import importlib
import traceback
from pathlib import Path

import dotenv
import pytest
from sqlalchemy.engine import make_url


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip DB-related env vars so each test starts from a known baseline."""
    for var in (
        "DATABASE_URL",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_HOST",
        "POSTGRES_PORT",
        "POSTGRES_DB",
        "LOAD_BATCH_SIZE",
    ):
        monkeypatch.delenv(var, raising=False)


def _reload_config():
    import py_etl_pipeline.config as config

    return importlib.reload(config)


def test_uses_database_url_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@host:5433/db")
    assert _reload_config().database_url() == "postgresql://u:p@host:5433/db"


def test_builds_from_postgres_vars_with_url_encoding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("POSTGRES_USER", "u@1")
    monkeypatch.setenv("POSTGRES_PASSWORD", "p ss")
    monkeypatch.setenv("POSTGRES_HOST", "h")
    monkeypatch.setenv("POSTGRES_PORT", "6543")
    monkeypatch.setenv("POSTGRES_DB", "db")
    parsed = make_url(_reload_config().database_url())
    assert (parsed.username, parsed.password) == ("u@1", "p ss")
    assert (parsed.host, parsed.port, parsed.database) == ("h", 6543, "db")


def test_uses_defaults_for_host_and_port(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POSTGRES_USER", "u")
    monkeypatch.setenv("POSTGRES_PASSWORD", "p")
    monkeypatch.setenv("POSTGRES_DB", "db")
    assert _reload_config().database_url() == "postgresql://u:p@localhost:5433/db"


def test_raises_when_required_vars_missing() -> None:
    with pytest.raises(ValueError):
        _reload_config().database_url()


@pytest.mark.parametrize(
    "value",
    ["with spaces + plus", "reserved@:/?#%", "literal%40%2F", "usuário-秘密+á"],
)
def test_connection_fields_round_trip_without_creating_url_options(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("POSTGRES_USER", value)
    monkeypatch.setenv("POSTGRES_PASSWORD", value)
    monkeypatch.setenv("POSTGRES_DB", value)
    parsed = make_url(_reload_config().database_url())
    assert parsed.drivername == "postgresql"
    assert parsed.username == value
    assert parsed.password == value
    assert parsed.database == value
    assert parsed.host == "localhost"
    assert parsed.port == 5433
    assert not parsed.query


@pytest.mark.parametrize("host", ["127.0.0.1", "db.internal", "::1", "[2001:db8::1]"])
def test_hosts_round_trip_without_dns_resolution(
    monkeypatch: pytest.MonkeyPatch, host: str
) -> None:
    _set_postgres_parts(monkeypatch)
    monkeypatch.setenv("POSTGRES_HOST", host)
    parsed = make_url(_reload_config().database_url())
    assert parsed.host == host.strip("[]")
    assert parsed.port == 5433


@pytest.mark.parametrize("port", ["1", "65535", "05433"])
def test_explicit_port_boundaries(monkeypatch: pytest.MonkeyPatch, port: str) -> None:
    _set_postgres_parts(monkeypatch)
    monkeypatch.setenv("POSTGRES_PORT", port)
    assert make_url(_reload_config().database_url()).port == int(port)


@pytest.mark.parametrize(
    "port",
    [
        "",
        "0",
        "65536",
        "-1",
        "+5433",
        "54 33",
        "１２３",
        "marker-private-port",
        pytest.param("9" * 5000, id="overlong-number"),
    ],
)
def test_invalid_ports_fail_without_echoing_values(
    monkeypatch: pytest.MonkeyPatch, port: str
) -> None:
    _set_postgres_parts(monkeypatch)
    monkeypatch.setenv("POSTGRES_PORT", port)
    with pytest.raises(ValueError) as caught:
        _reload_config().database_url()
    assert str(caught.value) == "POSTGRES_PORT must be an integer from 1 to 65535."
    rendered = "".join(traceback.format_exception(caught.value))
    assert "marker-private" not in rendered
    assert "Invalid literal" not in rendered


@pytest.mark.parametrize(
    "host",
    [
        "marker-private@host",
        "host/marker-private",
        "host?password=marker-private",
        "host#marker-private",
        "host\\marker-private",
        "host\nmarker-private",
        "[marker-private]",
        "marker-private:5433",
    ],
)
def test_invalid_hosts_fail_without_echoing_values(
    monkeypatch: pytest.MonkeyPatch, host: str
) -> None:
    _set_postgres_parts(monkeypatch)
    monkeypatch.setenv("POSTGRES_HOST", host)
    with pytest.raises(ValueError) as caught:
        _reload_config().database_url()
    assert str(caught.value) == (
        "POSTGRES_HOST must be a hostname or IP address without URL separators."
    )
    assert "marker-private" not in "".join(traceback.format_exception(caught.value))


@pytest.mark.parametrize(
    "url",
    [
        "sqlite:///:memory:",
        "sqlite:///relative+file.db",
        "postgresql://user@/db?host=/run/postgresql&sslmode=verify-full&sslpassword=private-marker",
    ],
)
def test_complete_url_is_unchanged_and_ignores_unused_parts(
    monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("POSTGRES_HOST", "invalid/private-marker")
    monkeypatch.setenv("POSTGRES_PORT", "private-marker")
    assert _reload_config().database_url() == url


@pytest.mark.parametrize("missing", ["POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB"])
def test_separate_fields_still_require_all_credentials(
    monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    _set_postgres_parts(monkeypatch)
    monkeypatch.delenv(missing)
    with pytest.raises(ValueError, match="Set DATABASE_URL or POSTGRES_USER"):
        _reload_config().database_url()


def test_import_does_not_load_dotenv_even_before_pytest_sets_current_test(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_read(*args, **kwargs):
        pytest.fail("Importing configuration must not read dotenv files.")

    with monkeypatch.context() as patch:
        patch.delenv("PYTEST_CURRENT_TEST", raising=False)
        patch.setattr(dotenv, "load_dotenv", unexpected_read)
        config = _reload_config()
        assert config.load_batch_size() == 500
    importlib.reload(config)


def test_explicit_dotenv_loading_preserves_environment_precedence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "chosen.env"
    path.write_text("POSTGRES_USER=file-user\nPOSTGRES_PASSWORD=file-password\n", encoding="utf-8")
    monkeypatch.setenv("POSTGRES_PASSWORD", "environment-password")
    config = _reload_config()
    assert config.load_environment(path) is True
    monkeypatch.setenv("POSTGRES_DB", "db")
    parsed = make_url(config.database_url())
    assert parsed.username == "file-user"
    assert parsed.password == "environment-password"


def test_explicit_dotenv_path_does_not_search_ancestors(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / ".env").write_text("POSTGRES_PASSWORD=ancestor-private-marker\n", encoding="utf-8")
    nested = tmp_path / "nested"
    nested.mkdir()
    monkeypatch.chdir(nested)
    config = _reload_config()
    assert config.load_environment(nested / "missing.env") is False
    with pytest.raises(ValueError, match="Set DATABASE_URL"):
        config.database_url()


def _set_postgres_parts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POSTGRES_USER", "user")
    monkeypatch.setenv("POSTGRES_PASSWORD", "marker-private-password")
    monkeypatch.setenv("POSTGRES_DB", "db")


def test_load_batch_size_defaults_to_500(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LOAD_BATCH_SIZE", raising=False)
    assert _reload_config().load_batch_size() == 500


def test_load_batch_size_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOAD_BATCH_SIZE", "100")
    assert _reload_config().load_batch_size() == 100


def test_load_batch_size_invalid_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOAD_BATCH_SIZE", "not-a-number")
    assert _reload_config().load_batch_size() == 500


def test_load_batch_size_minimum_one(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOAD_BATCH_SIZE", "0")
    assert _reload_config().load_batch_size() == 1

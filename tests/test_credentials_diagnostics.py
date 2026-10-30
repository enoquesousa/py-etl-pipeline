"""Credential-safe diagnostics and explicit startup, using no database connections."""

from __future__ import annotations

import importlib.util
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import alembic
import pytest
from sqlalchemy.exc import OperationalError

import conftest as fixtures
from py_etl_pipeline import config

ROOT = Path(__file__).resolve().parents[1]
SECRET = "synthetic-private-credential-marker"
DSN = (
    f"postgresql://private-user:{SECRET}@private-host:6543/private-db"
    f"?host=/run/postgresql&sslmode=verify-full&sslpassword={SECRET}&connect_timeout=9"
)


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "DATABASE_URL",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_HOST",
        "POSTGRES_PORT",
        "POSTGRES_DB",
    ):
        monkeypatch.delenv(name, raising=False)


def _load_module(relative_path: str):
    path = ROOT / relative_path
    spec = importlib.util.spec_from_file_location(f"probe_{path.stem}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def diagnostic(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(config, "load_environment", Mock(return_value=False))
    module = _load_module("scripts/diagnose_db.py")
    engine = Mock()
    engine.connect.return_value = nullcontext()
    monkeypatch.setattr(module, "create_engine", Mock(return_value=engine))
    return module, engine


def test_diagnostic_preserves_full_connection_options_without_printing_them(
    diagnostic, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module, engine = diagnostic
    monkeypatch.setenv("DATABASE_URL", DSN)
    assert module.main() == 0
    module.load_environment.assert_called_once_with(ROOT / ".env")
    module.create_engine.assert_called_once_with(DSN, poolclass=module.NullPool)
    engine.connect.assert_called_once_with()
    engine.dispose.assert_called_once_with()
    output = capsys.readouterr()
    assert "succeeded" in output.out
    for value in (SECRET, "private-user", "private-host", "private-db", DSN):
        assert value not in output.out + output.err


@pytest.mark.parametrize("stage", ["create", "connect", "dispose"])
def test_diagnostic_errors_never_echo_driver_exceptions(
    diagnostic, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], stage: str
) -> None:
    module, engine = diagnostic
    monkeypatch.setenv("DATABASE_URL", DSN)
    failure = RuntimeError(f"driver exposed {DSN}")
    operation = module.create_engine if stage == "create" else getattr(engine, stage)
    operation.side_effect = failure
    assert module.main() == 1
    output = capsys.readouterr()
    assert "failed" in output.out
    assert SECRET not in output.out + output.err
    if stage != "create":
        engine.dispose.assert_called_once_with()


@pytest.mark.parametrize(
    "url", ["", f"sqlite:///{SECRET}.db", f"postgresql://u:p@host:{SECRET}/db"]
)
def test_diagnostic_rejects_missing_invalid_or_non_postgres_configuration_before_connecting(
    diagnostic, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], url: str
) -> None:
    module, _ = diagnostic
    monkeypatch.setenv("DATABASE_URL", url)
    assert module.main() == 2
    module.create_engine.assert_not_called()
    output = capsys.readouterr()
    assert SECRET not in output.out + output.err


def test_pg_fixture_skip_does_not_echo_an_unsupported_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config, "database_url", lambda: f"sqlite:///{SECRET}.db")
    create_engine = Mock()
    monkeypatch.setattr(fixtures, "create_engine", create_engine)
    fixture = fixtures.pg_engine.__wrapped__()
    with pytest.raises(pytest.skip.Exception) as skipped:
        next(fixture)
    assert SECRET not in str(skipped.value)
    create_engine.assert_not_called()


@pytest.mark.parametrize("stage", ["create", "connect"])
def test_pg_fixture_warnings_do_not_echo_url_or_database_errors(
    monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    monkeypatch.setattr(config, "database_url", lambda: DSN)
    engine = Mock()
    create_engine = Mock(return_value=engine)
    if stage == "create":
        create_engine.side_effect = ValueError(DSN)
    else:
        engine.connect.side_effect = OperationalError(None, None, RuntimeError(DSN))
    monkeypatch.setattr(fixtures, "create_engine", create_engine)
    fixture = fixtures.pg_engine.__wrapped__()
    with pytest.warns(UserWarning) as warnings, pytest.raises(pytest.skip.Exception) as skipped:
        next(fixture)
    assert SECRET not in str(skipped.value)
    assert all(SECRET not in str(warning.message) for warning in warnings)
    if stage == "connect":
        engine.dispose.assert_called_once_with()


@pytest.mark.parametrize("path", ["main.py", "scripts/demo_load.py", "scripts/validate_load.py"])
def test_entrypoints_load_the_checkout_env_only_when_started(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, path: str
) -> None:
    class StopAfterBootstrap(Exception):
        pass

    load = Mock(side_effect=StopAfterBootstrap)
    monkeypatch.setattr(config, "load_environment", load)
    monkeypatch.chdir(tmp_path)
    module = _load_module(path)
    load.assert_not_called()
    with pytest.raises(StopAfterBootstrap):
        module.main()
    load.assert_called_once()
    assert Path(load.call_args.args[0]) == ROOT / ".env"


@pytest.mark.parametrize("explicit_override", [False, True])
def test_migrations_preserve_the_full_url_and_explicit_override(
    monkeypatch: pytest.MonkeyPatch, explicit_override: bool
) -> None:
    load = Mock(return_value=False)
    monkeypatch.setattr(config, "load_environment", load)
    monkeypatch.setenv("DATABASE_URL", DSN)
    context = SimpleNamespace(
        config=SimpleNamespace(config_file_name=None),
        get_x_argument=Mock(return_value={"url": DSN} if explicit_override else {}),
        configure=Mock(),
        begin_transaction=Mock(return_value=nullcontext()),
        run_migrations=Mock(),
        is_offline_mode=Mock(return_value=True),
    )
    monkeypatch.setattr(alembic, "context", context)
    _load_module("migrations/env.py")
    assert context.configure.call_args.kwargs["url"] == DSN
    if explicit_override:
        load.assert_not_called()
    else:
        load.assert_called_once_with(ROOT / ".env")

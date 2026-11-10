import asyncio
import traceback
from unittest.mock import Mock

import pytest
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session
from starlette.applications import Starlette

from app.models import database


def synthetic_target(driver="postgresql"):
    url = URL.create(driver, host="database.invalid", database="mock_fixture")
    return SecretStr(url.render_as_string())


@pytest.fixture
def engine():
    # Fictional, non-routable test target; constructing an engine does not connect.
    value = database.create_database_engine(synthetic_target())
    yield value
    value.dispose()


def test_engine_is_lazy_and_uses_installed_driver(engine):
    assert isinstance(engine, Engine)
    assert engine.dialect.driver == "psycopg2"
    assert engine.echo is False
    assert engine.hide_parameters is True


def test_engine_creation_options(monkeypatch):
    build = Mock(return_value=Mock(spec=Engine))
    monkeypatch.setattr(database, "create_engine", build)
    database.create_database_engine(synthetic_target("postgresql+psycopg2"))
    args, kwargs = build.call_args
    assert args[0].drivername == "postgresql+psycopg2"
    assert kwargs == {"echo": False, "hide_parameters": True, "pool_pre_ping": True}


@pytest.mark.parametrize(
    "value",
    ["synthetic-sensitive-marker", "sqlite://", "postgresql://", synthetic_target("postgresql+psycopg").get_secret_value()],
)
def test_invalid_database_configuration_is_sanitized(value):
    with pytest.raises(database.DatabaseConfigurationError) as captured:
        database.create_database_engine(SecretStr(value))
    assert value not in "".join(traceback.format_exception(captured.value))


def test_plain_text_database_configuration_is_rejected():
    with pytest.raises(database.DatabaseConfigurationError):
        database.create_database_engine("synthetic-sensitive-marker")


def test_engine_construction_failure_is_sanitized(monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("synthetic-sensitive-marker")

    monkeypatch.setattr(database, "create_engine", fail)
    with pytest.raises(database.DatabaseConfigurationError) as captured:
        database.create_database_engine(synthetic_target())
    assert "synthetic-sensitive-marker" not in "".join(traceback.format_exception(captured.value))


def test_session_factory_is_lazy_and_sessions_are_distinct(engine):
    factory = database.create_session_factory(engine)
    with factory() as first, factory() as second:
        assert isinstance(first, Session)
        assert first is not second
        assert first.bind is engine
        assert first.autoflush is False
        assert first.expire_on_commit is False
        assert not first.in_transaction()


@pytest.mark.parametrize("fail", [False, True])
def test_real_session_releases_uncommitted_transaction_without_io(engine, fail):
    dependency = database.get_db(request_for(database.create_session_factory(engine)))
    session = next(dependency)
    session.begin()  # A SQLAlchemy logical transaction; no connection acquired.
    assert session.in_transaction()
    if fail:
        with pytest.raises(RuntimeError, match="fixture failure"):
            dependency.throw(RuntimeError("fixture failure"))
    else:
        with pytest.raises(StopIteration):
            next(dependency)
    assert not session.in_transaction()


def request_for(factory):
    application = Starlette()
    application.state.session_factory = factory
    return Request({"type": "http", "app": application})


def test_unconfigured_session_dependency_fails_closed():
    with pytest.raises(HTTPException) as captured:
        next(database.get_db(request_for(None)))
    assert captured.value.status_code == 503


def test_session_creation_failure_is_sanitized():
    factory = Mock(side_effect=RuntimeError("synthetic-sensitive-marker"))
    with pytest.raises(HTTPException) as captured:
        next(database.get_db(request_for(factory)))
    assert captured.value.status_code == 503
    assert "synthetic-sensitive-marker" not in "".join(traceback.format_exception(captured.value))


def test_success_closes_without_committing():
    session = Mock(spec=Session)
    dependency = database.get_db(request_for(Mock(return_value=session)))
    assert next(dependency) is session
    with pytest.raises(StopIteration):
        next(dependency)
    session.close.assert_called_once_with()
    session.commit.assert_not_called()
    session.rollback.assert_not_called()


@pytest.mark.parametrize("error", [RuntimeError("failure"), GeneratorExit()])
def test_failure_or_cancellation_rolls_back_and_closes(error):
    session = Mock(spec=Session)
    dependency = database.get_db(request_for(Mock(return_value=session)))
    next(dependency)
    with pytest.raises(type(error)):
        dependency.throw(error)
    session.rollback.assert_called_once_with()
    session.close.assert_called_once_with()
    session.commit.assert_not_called()


@pytest.mark.parametrize("rollback_fails,close_fails", [(True, False), (False, True), (True, True)])
@pytest.mark.parametrize("primary_type", [ValueError, HTTPException, GeneratorExit, asyncio.CancelledError])
def test_cleanup_failures_preserve_primary(caplog, rollback_fails, close_fails, primary_type):
    primary = HTTPException(409, "fixture conflict") if primary_type is HTTPException else primary_type()
    session = Mock(spec=Session)
    if rollback_fails:
        session.rollback.side_effect = RuntimeError("synthetic-private-rollback")
    if close_fails:
        session.close.side_effect = RuntimeError("synthetic-private-close")
    dependency = database.get_db(request_for(Mock(return_value=session)))
    next(dependency)
    with pytest.raises(type(primary)) as captured:
        dependency.throw(primary)
    assert captured.value is primary
    rendered = "".join(traceback.format_exception(captured.value)) + caplog.text
    assert "synthetic-private" not in rendered
    assert caplog.records
    assert all(not record.exc_info for record in caplog.records)
    session.rollback.assert_called_once_with()
    session.close.assert_called_once_with()
    session.commit.assert_not_called()


def test_close_failure_after_success_is_sanitized(caplog):
    session = Mock(spec=Session)
    session.close.side_effect = RuntimeError("synthetic-private-close")
    dependency = database.get_db(request_for(Mock(return_value=session)))
    next(dependency)
    with pytest.raises(database.DatabaseSessionCleanupError) as captured:
        next(dependency)
    assert "synthetic-private" not in "".join(traceback.format_exception(captured.value)) + caplog.text
    session.close.assert_called_once_with()
    session.rollback.assert_not_called()
    session.commit.assert_not_called()


def test_request_scoped_sessions_and_failure_cleanup():
    sessions = []

    def factory():
        session = Mock(spec=Session)
        sessions.append(session)
        return session

    # These routes exist solely on this test application, never the shipped app.
    application = FastAPI()
    application.state.session_factory = factory

    @application.get("/fixture")
    def fixture_route(session: Session = Depends(database.get_db)):
        return {"ok": True}

    @application.get("/failure")
    def failure_route(session: Session = Depends(database.get_db)):
        raise HTTPException(status_code=409, detail="fixture conflict")

    with TestClient(application) as client:
        assert client.get("/fixture").status_code == 200
        assert client.get("/fixture").status_code == 200
        assert client.get("/failure").status_code == 409
    assert len(sessions) == 3
    assert sessions[0] is not sessions[1]
    for session in sessions:
        session.close.assert_called_once_with()
        session.commit.assert_not_called()
    sessions[2].rollback.assert_called_once_with()

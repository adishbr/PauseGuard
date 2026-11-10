import importlib

import pytest
from fastapi.testclient import TestClient

from app.config import ConfigurationError, Settings
from app.models.database import Base


@pytest.fixture
def create_app():
    # Import under the offline guard, rather than during test collection.
    from app.main import create_app

    return create_app


def test_creation_and_lifespan_need_no_database(create_app):
    application = create_app(Settings(environment="test"))
    with TestClient(application) as client:
        assert client.get("/api/v2/health").status_code == 200
    assert application.state.session_factory is None
    assert not Base.metadata.tables


def test_module_reload_does_not_connect(monkeypatch):
    monkeypatch.setenv("PAUSEGUARD_ENVIRONMENT", "test")
    monkeypatch.setenv("PAUSEGUARD_MODE", "mock")
    module = importlib.import_module("app.main")
    assert importlib.reload(module).app.state.session_factory is None


def test_applications_do_not_share_dependency_overrides(create_app):
    first = create_app(Settings())
    second = create_app(Settings())
    first.dependency_overrides[object()] = lambda: None
    assert not second.dependency_overrides


def test_only_health_is_exposed_as_a_domain_route(application):
    assert set(application.openapi()["paths"]) == {"/api/v2/health"}
    assert application.debug is False


def test_factory_rejects_invalid_environment(monkeypatch, create_app):
    monkeypatch.setenv("PAUSEGUARD_ENVIRONMENT", "production")
    with pytest.raises(ConfigurationError):
        create_app()


def test_explicit_settings_do_not_load_environment(monkeypatch, create_app):
    monkeypatch.setenv("PAUSEGUARD_ENVIRONMENT", "production")
    assert create_app(Settings(environment="test")).state.settings.environment == "test"

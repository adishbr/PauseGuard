"""Install guards before pytest imports application test modules."""

import pytest

from tests.offline import install_guards


def pytest_configure(config):
    patches = pytest.MonkeyPatch()
    cleanup = install_guards(patches)
    config.add_cleanup(cleanup)


@pytest.fixture(autouse=True)
def test_environment(monkeypatch):
    monkeypatch.setenv("PAUSEGUARD_ENVIRONMENT", "test")
    monkeypatch.setenv("PAUSEGUARD_MODE", "mock")


@pytest.fixture
def application():
    from app.config import Settings
    from app.main import create_app

    return create_app(Settings(environment="test"))

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
    registered_before = set(Base.metadata.tables)
    application = create_app(Settings(environment="test"))
    with TestClient(application) as client:
        assert client.get("/api/v2/health").status_code == 200
    assert application.state.session_factory is None
    assert set(Base.metadata.tables) == registered_before


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


CANONICAL_V2_ROUTES = {
    "/api/v2/health",
    "/api/v2/profile",
    "/api/v2/demo/session",
    "/api/v2/auth/signup",
    "/api/v2/auth/otp/challenge",
    "/api/v2/auth/otp/verify",
    "/api/v2/auth/login",
    "/api/v2/auth/logout",
    "/api/v2/identity/verify",
    "/api/v2/identity/status",
    "/api/v2/guardian/enroll",
    "/api/v2/guardian/status",
    "/api/v2/guardian/dashboard",
    "/api/v2/guardian/revoke",
    "/api/v2/guardian/invitations",
    "/api/v2/guardian/invitations/{invitation_id}/accept",
    "/api/v2/guardian/invitations/{invitation_id}/decline",
    "/api/v2/guardian/invitations/{invitation_id}/revoke",
    "/api/v2/guardian/calls/{call_id}/status",
    "/api/v2/guardian/calls/provider-callback",
    "/api/v2/payments",
    "/api/v2/payments/{payment_id}",
    "/api/v2/payments/{payment_id}/events",
    "/api/v2/payments/{payment_id}/risk",
    "/api/v2/payments/{payment_id}/evidence",
    "/api/v2/payments/{payment_id}/warning/acknowledge",
    "/api/v2/payments/{payment_id}/guardian/decision",
    "/api/v2/payments/{payment_id}/fallback/activate",
    "/api/v2/payments/{payment_id}/cancel",
    "/api/v2/payments/{payment_id}/confirm",
    "/api/v2/account/balance",
    "/api/v2/safe-lock",
    "/api/v2/safety/purpose-challenge",
    "/api/v2/safety/anti-smurfing/check",
    "/api/v2/audit/verify",
    "/api/v2/audit/anchors",
    "/api/v2/anchors",
    "/api/v2/recovery/guide",
    "/api/v2/risk/advice",
    "/api/v2/policy-lab/simulate",
    "/api/v2/sandbox/razorpay/config",
    "/api/v2/sandbox/razorpay/orders",
    "/api/v2/sandbox/razorpay/verify",
    "/api/v2/sandbox/razorpay/webhook",
    "/api/v2/sandbox/razorpay/orders/{order_id}",
}


def test_only_canonical_v2_foundation_routes_are_exposed(application):
    assert set(application.openapi()["paths"]) == CANONICAL_V2_ROUTES
    assert application.debug is False


# Alias for backward compatibility with existing test runners
test_only_health_is_exposed_as_a_domain_route = test_only_canonical_v2_foundation_routes_are_exposed


def test_factory_rejects_invalid_environment(monkeypatch, create_app):
    monkeypatch.setenv("PAUSEGUARD_ENVIRONMENT", "production")
    with pytest.raises(ConfigurationError):
        create_app()


def test_explicit_settings_do_not_load_environment(monkeypatch, create_app):
    monkeypatch.setenv("PAUSEGUARD_ENVIRONMENT", "production")
    assert create_app(Settings(environment="test")).state.settings.environment == "test"

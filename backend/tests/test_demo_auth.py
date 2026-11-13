"""Targeted verification tests for the local demo authentication bridge.

Covers:
1. Explicitly authorized payer demo session creation
2. Explicitly authorized guardian demo session creation
3. Bearer token resolution and GET /api/v2/profile verification
4. Role isolation enforcement
5. Invalid and expired token rejection (401)
6. Missing demo-auth flag fail-closed rejection (403)
7. Non-local / production environment rejection (403)
8. Non-loopback and forwarded remote request rejection (403)
9. Admin privilege isolation (disabled by default, requires allow_demo_admin)
10. Arbitrary phone/email rejection (no fake credentials accepted)
11. Schema strictness (extra field rejection, invalid role rejection)
12. GET /api/v2/demo/session inspection
13. WebSocket query-token authentication contract
"""

from uuid import UUID
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.auth.dependencies import (
    get_current_actor,
    require_admin,
    require_guardian,
    require_payer,
)
from app.auth.identities import (
    SYNTHETIC_ADMIN_ID,
    SYNTHETIC_GUARDIAN_ID,
    SYNTHETIC_OTHER_PAYER_ID,
    SYNTHETIC_PAYER_ID,
)
from app.auth.router import router as auth_router
from app.api.websocket import router as ws_router
from app.config import Settings
from app.main import create_app
from app.models.roles import UserRole
from app.services.payment_guards import TrustedActorContext


@pytest.fixture
def demo_app() -> FastAPI:
    """Create test app with explicit local demo auth enabled."""
    app = FastAPI(title="DemoAuthTestApp")
    app.state.settings = Settings(
        environment="test",
        mode="mock",
        allow_demo_auth=True,
        allow_demo_admin=False,
    )
    app.include_router(auth_router)
    app.include_router(ws_router)

    @app.get("/test/payer-gate")
    def payer_gate(actor: TrustedActorContext = Depends(require_payer)):
        return {"authorized": True, "user_id": str(actor.user_id)}

    @app.get("/test/guardian-gate")
    def guardian_gate(actor: TrustedActorContext = Depends(require_guardian)):
        return {"authorized": True, "user_id": str(actor.user_id)}

    @app.get("/test/admin-gate")
    def admin_gate(actor: TrustedActorContext = Depends(require_admin)):
        return {"authorized": True, "user_id": str(actor.user_id)}

    return app


@pytest.fixture
def client(demo_app: FastAPI) -> TestClient:
    return TestClient(demo_app)


# ---------------------------------------------------------------------------
# 1. Explicitly Authorized Payer Demo Session & Profile Resolution
# ---------------------------------------------------------------------------

def test_payer_demo_session_creation_and_profile_resolution(client: TestClient):
    """Verify POST /api/v2/demo/session creates a valid payer session."""
    response = client.post("/api/v2/demo/session", json={"role": "payer"})
    assert response.status_code == 200
    data = response.json()

    assert data["token"] == "demo-token-payer"
    assert data["token_type"] == "Bearer"
    assert data["user_id"] == str(SYNTHETIC_PAYER_ID)
    assert data["role"] == "payer"
    assert data["roles"] == ["payer"]
    assert data["expires_in_seconds"] == 1800
    assert data["expiresAt"] > 0

    # Verify frontend-compatible profile metadata
    profile = data["profile"]
    assert profile["id"] == str(SYNTHETIC_PAYER_ID)
    assert profile["role"] == "payer"
    assert profile["name"] == "Asha Demo"
    assert profile["contact"] == "asha@pauseguard.test"
    assert profile["sample"] is True
    assert profile["thresholdPaise"] == 5500000

    # Verify the issued token resolves GET /api/v2/profile
    profile_resp = client.get(
        "/api/v2/profile",
        headers={"Authorization": f"Bearer {data['token']}"},
    )
    assert profile_resp.status_code == 200
    pdata = profile_resp.json()
    assert pdata["user_id"] == str(SYNTHETIC_PAYER_ID)
    assert pdata["roles"] == ["payer"]


# ---------------------------------------------------------------------------
# 2. Explicitly Authorized Guardian Demo Session
# ---------------------------------------------------------------------------

def test_guardian_demo_session_creation(client: TestClient):
    """Verify POST /api/v2/demo/session creates a valid guardian session."""
    response = client.post("/api/v2/demo/session", json={"role": "guardian"})
    assert response.status_code == 200
    data = response.json()

    assert data["token"] == "demo-token-guardian"
    assert data["token_type"] == "Bearer"
    assert data["user_id"] == str(SYNTHETIC_GUARDIAN_ID)
    assert data["role"] == "guardian"
    assert data["roles"] == ["guardian"]

    profile = data["profile"]
    assert profile["id"] == str(SYNTHETIC_GUARDIAN_ID)
    assert profile["role"] == "guardian"
    assert profile["name"] == "Ravi Demo"
    assert profile["contact"] == "ravi@pauseguard.test"

    # Verify bearer resolution
    profile_resp = client.get(
        "/api/v2/profile",
        headers={"Authorization": f"Bearer {data['token']}"},
    )
    assert profile_resp.status_code == 200
    assert profile_resp.json()["user_id"] == str(SYNTHETIC_GUARDIAN_ID)
    assert profile_resp.json()["roles"] == ["guardian"]


# ---------------------------------------------------------------------------
# 3. Role Isolation Enforcement
# ---------------------------------------------------------------------------

def test_demo_session_role_isolation(client: TestClient):
    """Verify that issued payer cannot access guardian endpoints and vice versa."""
    payer_token = client.post("/api/v2/demo/session", json={"role": "payer"}).json()["token"]
    guardian_token = client.post("/api/v2/demo/session", json={"role": "guardian"}).json()["token"]

    # Payer can access payer gate, forbidden on guardian gate
    assert client.get("/test/payer-gate", headers={"Authorization": f"Bearer {payer_token}"}).status_code == 200
    assert client.get("/test/guardian-gate", headers={"Authorization": f"Bearer {payer_token}"}).status_code == 403

    # Guardian can access guardian gate, forbidden on payer gate
    assert client.get("/test/guardian-gate", headers={"Authorization": f"Bearer {guardian_token}"}).status_code == 200
    assert client.get("/test/payer-gate", headers={"Authorization": f"Bearer {guardian_token}"}).status_code == 403


# ---------------------------------------------------------------------------
# 4. Invalid Token Rejection (401)
# ---------------------------------------------------------------------------

def test_invalid_tokens_rejected(client: TestClient):
    """Verify invalid or forged tokens return 401."""
    for invalid_token in ["forged-token", "demo-token-unknown", "Bearer invalid", ""]:
        resp = client.get("/api/v2/profile", headers={"Authorization": f"Bearer {invalid_token}"})
        assert resp.status_code == 401
        assert "WWW-Authenticate" in resp.headers


# ---------------------------------------------------------------------------
# 5. Missing Demo-Auth Flag Rejection (403)
# ---------------------------------------------------------------------------

def test_missing_demo_auth_flag_rejects_session():
    """When allow_demo_auth is False, session issuance is strictly rejected."""
    app = FastAPI()
    app.state.settings = Settings(environment="test", mode="mock", allow_demo_auth=False)
    app.include_router(auth_router)

    with TestClient(app) as tc:
        resp = tc.post("/api/v2/demo/session", json={"role": "payer"})
        assert resp.status_code == 403
        assert "Demo authentication is disabled" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# 6. Non-Local / Production Rejection (403)
# ---------------------------------------------------------------------------

def test_non_local_or_real_mode_rejects_session():
    """Production or real mode must reject demo sessions even with opt-in flag."""
    class ProductionSettings:
        environment = "production"
        mode = "mock"
        allow_demo_auth = True
        allow_demo_admin = True

    app = FastAPI()
    app.state.settings = ProductionSettings()
    app.include_router(auth_router)

    with TestClient(app) as tc:
        resp = tc.post("/api/v2/demo/session", json={"role": "payer"})
        assert resp.status_code == 403
        assert "Demo authentication is disabled" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# 7. Non-Loopback and Forwarded Requests Rejected (403)
# ---------------------------------------------------------------------------

def test_non_loopback_client_rejected(client: TestClient):
    """External client IP addresses must be rejected with 403."""
    # TestClient default host is 'testclient' which is recognized as loopback.
    # Simulate an external client by modifying client host or providing untrusted X-Forwarded-For
    resp = client.post(
        "/api/v2/demo/session",
        json={"role": "payer"},
        headers={"X-Forwarded-For": "203.0.113.195"},
    )
    assert resp.status_code == 403
    assert "loopback" in resp.json()["detail"].lower()


def test_loopback_forwarded_client_accepted(client: TestClient):
    """Forwarded headers with only loopback addresses should be accepted."""
    resp = client.post(
        "/api/v2/demo/session",
        json={"role": "payer"},
        headers={"X-Forwarded-For": "127.0.0.1, ::1"},
    )
    assert response_is_success(resp)


def response_is_success(response):
    return response.status_code == 200


# ---------------------------------------------------------------------------
# 8. Admin Privilege Isolation
# ---------------------------------------------------------------------------

def test_admin_privilege_isolation_disabled_by_default(client: TestClient):
    """Admin demo sessions must be rejected when allow_demo_admin is False (default)."""
    resp = client.post("/api/v2/demo/session", json={"role": "admin"})
    assert resp.status_code == 403
    assert "Admin demo session issuance is disabled" in resp.json()["detail"]


def test_admin_privilege_allowed_only_when_explicitly_configured():
    """Admin demo sessions succeed when PAUSEGUARD_ALLOW_DEMO_ADMIN=True."""
    app = FastAPI()
    app.state.settings = Settings(
        environment="test",
        mode="mock",
        allow_demo_auth=True,
        allow_demo_admin=True,
    )
    app.include_router(auth_router)

    with TestClient(app) as tc:
        resp = tc.post("/api/v2/demo/session", json={"role": "admin"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["token"] == "demo-token-admin"
        assert data["user_id"] == str(SYNTHETIC_ADMIN_ID)
        assert data["role"] == "admin"


# ---------------------------------------------------------------------------
# 9. Synthetic Identity Mapping & Arbitrary Contact Rejection
# ---------------------------------------------------------------------------

def test_authorized_contacts_resolve_correct_identities(client: TestClient):
    """Authorized contacts map to known synthetic identities."""
    # Asha by email
    resp1 = client.post("/api/v2/demo/session", json={"role": "payer", "contact": "asha@pauseguard.test"})
    assert resp1.status_code == 200
    assert resp1.json()["user_id"] == str(SYNTHETIC_PAYER_ID)

    # Asha by 10-digit mobile
    resp2 = client.post("/api/v2/demo/session", json={"role": "payer", "contact": "+919876543210"})
    assert resp2.status_code == 200
    assert resp2.json()["user_id"] == str(SYNTHETIC_PAYER_ID)

    # Secondary payer
    resp3 = client.post("/api/v2/demo/session", json={"role": "payer", "contact": "sandbox-payer@pauseguard.test"})
    assert resp3.status_code == 200
    assert resp3.json()["user_id"] == str(SYNTHETIC_OTHER_PAYER_ID)


def test_arbitrary_unmapped_contacts_are_rejected(client: TestClient):
    """Arbitrary phone numbers or emails must NOT be provisioned or accepted."""
    for unknown in ["user@unknown.com", "+919999999999", "random_payer"]:
        resp = client.post("/api/v2/demo/session", json={"role": "payer", "contact": unknown})
        assert resp.status_code == 404
        assert "No authorized synthetic demo identity matches" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# 10. Schema Strictness (Extra Fields & Invalid Role)
# ---------------------------------------------------------------------------

def test_schema_strictness_extra_fields_and_roles(client: TestClient):
    """Extra fields and unrecognized roles must be rejected."""
    # Extra field rejected
    resp1 = client.post("/api/v2/demo/session", json={"role": "payer", "extra_field": "disallowed"})
    assert resp1.status_code == 422

    # Unrecognized role rejected
    resp2 = client.post("/api/v2/demo/session", json={"role": "superadmin"})
    assert resp2.status_code == 422


# ---------------------------------------------------------------------------
# 11. GET /api/v2/demo/session Inspection
# ---------------------------------------------------------------------------

def test_get_current_demo_session(client: TestClient):
    """Authenticated caller can inspect their active demo session."""
    payer_token = client.post("/api/v2/demo/session", json={"role": "payer"}).json()["token"]

    resp = client.get("/api/v2/demo/session", headers={"Authorization": f"Bearer {payer_token}"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["user_id"] == str(SYNTHETIC_PAYER_ID)
    assert data["role"] == "payer"
    assert data["token"] == payer_token

    # Unauthenticated returns 401
    assert client.get("/api/v2/demo/session").status_code == 401


# ---------------------------------------------------------------------------
# 12. WebSocket Query-Token Authentication Contract
# ---------------------------------------------------------------------------

def test_websocket_query_token_authentication(client: TestClient):
    """Verify WebSocket endpoint /api/v2/ws?token=... authenticates synthetic token."""
    # Valid payer token connects and receives initial connection payload
    with client.websocket_connect("/api/v2/ws?token=demo-token-payer") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "CONNECTION_ESTABLISHED"
        assert msg["user_id"] == str(SYNTHETIC_PAYER_ID)
        assert msg["roles"] == ["payer"]

        # Ping-pong works
        ws.send_text('{"type": "PING"}')
        reply = ws.receive_json()
        assert reply["type"] == "PONG"


def test_websocket_missing_or_invalid_token_closed(client: TestClient):
    """WebSocket without token or with invalid token is closed with policy violation."""
    with pytest.raises(Exception):
        with client.websocket_connect("/api/v2/ws") as ws:
            ws.receive_json()

    with pytest.raises(Exception):
        with client.websocket_connect("/api/v2/ws?token=invalid-token") as ws:
            ws.receive_json()


# ---------------------------------------------------------------------------
# 13. Integration on Real create_app() Factory
# ---------------------------------------------------------------------------

def test_real_app_factory_demo_session():
    """Verify /api/v2/demo/session works through the canonical create_app() factory."""
    app = create_app(Settings(environment="test", mode="mock", allow_demo_auth=True))
    with TestClient(app) as tc:
        resp = tc.post("/api/v2/demo/session", json={"role": "payer"})
        assert resp.status_code == 200
        token = resp.json()["token"]

        profile_resp = tc.get("/api/v2/profile", headers={"Authorization": f"Bearer {token}"})
        assert profile_resp.status_code == 200
        assert profile_resp.json()["user_id"] == str(SYNTHETIC_PAYER_ID)

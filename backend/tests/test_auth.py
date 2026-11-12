"""Comprehensive offline test suite for Phase 3A authentication and authorization.

Tests:
1. Bearer token extraction, format validation, and HTTP 401 handling with WWW-Authenticate.
2. Fail-closed demo token gating: disabled by default, requires explicit opt-in.
3. Fail-closed rejection of demo tokens in production and real mode regardless of opt-in.
4. Server-managed synthetic identities, token registry, and authoritative enrollments.
5. Strict prevention of client-side ID spoofing and role escalation.
6. Role authorization dependencies and HTTP 403 enforcement.
7. Resource ownership and cross-account isolation.
8. Authoritative guardian relationship verification and rejection of client-controlled assignments.
9. Guardian execution invariant (guardian cannot execute payments).
10. Privacy-preserving payment view levels (full vs redacted).
11. Registration and behavior of GET /api/v2/profile in the actual app factory.
12. Strict Pydantic schema validation and extra field rejection.
"""

from uuid import UUID, uuid4
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.auth.authorization import (
    assert_guardian_cannot_execute,
    authorize_account_access,
    authorize_payment_view_level,
    authorize_resource_owner,
    verify_guardian_to_payer_relationship,
)
from app.auth.dependencies import (
    get_current_actor,
    require_admin,
    require_analyst,
    require_any_role,
    require_guardian,
    require_payer,
    require_role,
)
from app.auth.exceptions import (
    AuthenticationError,
    AuthorizationError,
    CrossAccountAccessError,
    GuardianAssignmentError,
)
from app.auth.identities import (
    DEMO_TOKEN_REGISTRY,
    SYNTHETIC_ADMIN,
    SYNTHETIC_ADMIN_ID,
    SYNTHETIC_ANALYST,
    SYNTHETIC_ANALYST_ID,
    SYNTHETIC_GUARDIAN,
    SYNTHETIC_GUARDIAN_ENROLLMENTS,
    SYNTHETIC_GUARDIAN_ID,
    SYNTHETIC_OTHER_PAYER,
    SYNTHETIC_OTHER_PAYER_ID,
    SYNTHETIC_PAYER,
    SYNTHETIC_PAYER_ID,
    get_authoritative_guardian_for_payer,
    is_demo_mode_allowed,
    resolve_synthetic_token,
)
from app.auth.router import router as auth_router
from app.auth.schemas import (
    ActorProfileResponse,
    FullPaymentView,
    GuardianDecisionRequest,
    RedactedPaymentView,
)
from app.config import Settings
from app.main import create_app
from app.models.roles import UserRole
from app.services.payment_guards import TrustedActorContext


# ---------------------------------------------------------------------------
# Test Application Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def auth_app() -> FastAPI:
    """FastAPI test app mounting the auth router with explicit demo auth enabled."""
    app = FastAPI(title="AuthTestApp")
    app.state.settings = Settings(environment="test", mode="mock", allow_demo_auth=True)
    app.include_router(auth_router)

    @app.get("/test/payer-only")
    def payer_route(actor: TrustedActorContext = Depends(require_payer)):
        return {"status": "ok", "user_id": str(actor.user_id)}

    @app.get("/test/guardian-only")
    def guardian_route(actor: TrustedActorContext = Depends(require_guardian)):
        return {"status": "ok", "user_id": str(actor.user_id)}

    @app.get("/test/analyst-only")
    def analyst_route(actor: TrustedActorContext = Depends(require_analyst)):
        return {"status": "ok", "user_id": str(actor.user_id)}

    @app.get("/test/admin-only")
    def admin_route(actor: TrustedActorContext = Depends(require_admin)):
        return {"status": "ok", "user_id": str(actor.user_id)}

    @app.get("/test/operator")
    def operator_route(actor: TrustedActorContext = Depends(require_any_role(UserRole.ANALYST, UserRole.ADMIN))):
        return {"status": "ok", "user_id": str(actor.user_id)}

    return app


@pytest.fixture
def client(auth_app: FastAPI) -> TestClient:
    return TestClient(auth_app)


# ---------------------------------------------------------------------------
# Bearer Token Extraction & Authentication Tests (HTTP 401)
# ---------------------------------------------------------------------------

def test_missing_authorization_header_returns_401(client: TestClient):
    response = client.get("/api/v2/profile")
    assert response.status_code == 401
    assert "Bearer" in response.headers.get("WWW-Authenticate", "")
    assert "Missing or malformed Authorization header" in response.json()["detail"]


def test_non_bearer_scheme_returns_401(client: TestClient):
    response = client.get("/api/v2/profile", headers={"Authorization": "Basic dXNlcjpwYXNz"})
    assert response.status_code == 401
    assert "Bearer" in response.headers.get("WWW-Authenticate", "")
    assert "Missing or malformed Authorization header" in response.json()["detail"]


def test_empty_bearer_token_returns_401(client: TestClient):
    response = client.get("/api/v2/profile", headers={"Authorization": "Bearer   "})
    assert response.status_code == 401
    assert "Bearer" in response.headers.get("WWW-Authenticate", "")
    # Depending on whether HTTPBearer parses whitespace as empty string or None
    assert response.status_code == 401


def test_unknown_bearer_token_returns_401(client: TestClient):
    response = client.get("/api/v2/profile", headers={"Authorization": "Bearer unrecognized-token-999"})
    assert response.status_code == 401
    assert "Bearer" in response.headers.get("WWW-Authenticate", "")
    assert "Invalid, expired, or unrecognized" in response.json()["detail"]


# ---------------------------------------------------------------------------
# Fail-Closed Demo Token Gating (Production & Default Security)
# ---------------------------------------------------------------------------

def test_default_configuration_rejects_demo_tokens():
    """Verify default Settings() (allow_demo_auth=False) rejects demo tokens."""
    default_app = FastAPI(title="DefaultSettingsApp")
    default_app.state.settings = Settings()  # allow_demo_auth=False by default
    default_app.include_router(auth_router)

    with TestClient(default_app) as default_client:
        response = default_client.get(
            "/api/v2/profile",
            headers={"Authorization": "Bearer demo-token-payer"},
        )
        assert response.status_code == 401
        assert "WWW-Authenticate" in response.headers
        assert "Demo authentication is disabled in this environment" in response.json()["detail"]


def test_explicit_local_mock_authorization_accepts_demo_tokens():
    """Verify explicit authorization in local/test mock mode allows demo tokens."""
    app = FastAPI()
    app.state.settings = Settings(environment="local", mode="mock", allow_demo_auth=True)
    app.include_router(auth_router)

    with TestClient(app) as test_client:
        response = test_client.get(
            "/api/v2/profile",
            headers={"Authorization": "Bearer demo-token-payer"},
        )
        assert response.status_code == 200
        assert response.json()["user_id"] == str(SYNTHETIC_PAYER_ID)


def test_production_rejects_demo_tokens_regardless_of_opt_in():
    """Production must strictly reject demo tokens even if allow_demo_auth is True."""
    class ProductionSettingsWithOptIn:
        environment = "production"
        mode = "mock"
        allow_demo_auth = True
        enable_demo_auth = True

    assert is_demo_mode_allowed(ProductionSettingsWithOptIn()) is False  # type: ignore

    app = FastAPI()
    app.state.settings = ProductionSettingsWithOptIn()
    app.include_router(auth_router)

    with TestClient(app) as prod_client:
        response = prod_client.get(
            "/api/v2/profile",
            headers={"Authorization": "Bearer demo-token-payer"},
        )
        assert response.status_code == 401
        assert "Demo authentication is disabled in this environment" in response.json()["detail"]


def test_real_mode_rejects_demo_tokens_regardless_of_opt_in():
    """Real mode must strictly reject demo tokens even if allow_demo_auth is True."""
    class RealModeSettingsWithOptIn:
        environment = "local"
        mode = "real"
        allow_demo_auth = True
        enable_demo_auth = True

    assert is_demo_mode_allowed(RealModeSettingsWithOptIn()) is False  # type: ignore

    app = FastAPI()
    app.state.settings = RealModeSettingsWithOptIn()
    app.include_router(auth_router)

    with TestClient(app) as real_client:
        response = real_client.get(
            "/api/v2/profile",
            headers={"Authorization": "Bearer demo-token-payer"},
        )
        assert response.status_code == 401
        assert "Demo authentication is disabled in this environment" in response.json()["detail"]


def test_resolve_synthetic_token_fails_closed_without_opt_in():
    # Default Settings has allow_demo_auth=False
    assert resolve_synthetic_token("demo-token-payer", settings=Settings()) is None
    # Explicit opt-in in test/mock succeeds
    assert resolve_synthetic_token("demo-token-payer", settings=Settings(allow_demo_auth=True)) is not None


# ---------------------------------------------------------------------------
# Synthetic Identities & Demo Token Resolution
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "token,expected_actor",
    [
        ("demo-token-payer", SYNTHETIC_PAYER),
        ("demo_token_payer", SYNTHETIC_PAYER),
        ("demo-token-guardian", SYNTHETIC_GUARDIAN),
        ("demo_token_guardian", SYNTHETIC_GUARDIAN),
        ("demo-token-analyst", SYNTHETIC_ANALYST),
        ("demo_token_analyst", SYNTHETIC_ANALYST),
        ("demo-token-admin", SYNTHETIC_ADMIN),
        ("demo_token_admin", SYNTHETIC_ADMIN),
        ("demo-token-other-payer", SYNTHETIC_OTHER_PAYER),
        ("demo_token_other_payer", SYNTHETIC_OTHER_PAYER),
    ],
)
def test_valid_demo_tokens_resolve_expected_actors(token: str, expected_actor: TrustedActorContext):
    opt_in_settings = Settings(environment="test", mode="mock", allow_demo_auth=True)
    actor = resolve_synthetic_token(token, settings=opt_in_settings)
    assert actor is not None
    assert actor.user_id == expected_actor.user_id
    assert actor.roles == expected_actor.roles


def test_synthetic_user_ids_are_distinct():
    ids = {
        SYNTHETIC_PAYER_ID,
        SYNTHETIC_GUARDIAN_ID,
        SYNTHETIC_ANALYST_ID,
        SYNTHETIC_ADMIN_ID,
        SYNTHETIC_OTHER_PAYER_ID,
    }
    assert len(ids) == 5


def test_resolve_synthetic_token_rejects_non_strings():
    assert resolve_synthetic_token(None) is None  # type: ignore
    assert resolve_synthetic_token(123) is None  # type: ignore


# ---------------------------------------------------------------------------
# Server-Side Authority: Client-Supplied Claims Are Ignored
# ---------------------------------------------------------------------------

def test_client_supplied_headers_and_claims_are_ignored(client: TestClient):
    """Verify that client cannot elevate role by supplying spoofed headers."""
    spoofed_headers = {
        "Authorization": "Bearer demo-token-payer",
        "X-User-Role": "admin",
        "X-Role": "admin",
        "X-Actor-ID": str(SYNTHETIC_ADMIN_ID),
    }
    response = client.get("/test/admin-only", headers=spoofed_headers)
    assert response.status_code == 403
    assert "Forbidden: Operation requires admin role" in response.json()["detail"]


# ---------------------------------------------------------------------------
# Real Application Factory Integration Tests
# ---------------------------------------------------------------------------

def test_profile_endpoint_on_real_application_factory():
    """Verify GET /api/v2/profile works through create_app() with explicit opt-in."""
    # 1. Real app with default settings rejects demo tokens
    default_app = create_app(Settings(environment="test", mode="mock"))
    with TestClient(default_app) as real_client:
        resp = real_client.get(
            "/api/v2/profile",
            headers={"Authorization": "Bearer demo-token-payer"},
        )
        assert resp.status_code == 401
        assert "Demo authentication is disabled in this environment" in resp.json()["detail"]

    # 2. Real app with explicit opt-in accepts demo tokens
    opt_in_app = create_app(Settings(environment="test", mode="mock", allow_demo_auth=True))
    with TestClient(opt_in_app) as opt_in_client:
        unauth_resp = opt_in_client.get("/api/v2/profile")
        assert unauth_resp.status_code == 401
        assert "WWW-Authenticate" in unauth_resp.headers

        payer_resp = opt_in_client.get(
            "/api/v2/profile",
            headers={"Authorization": "Bearer demo-token-payer"},
        )
        assert payer_resp.status_code == 200
        payer_data = payer_resp.json()
        assert payer_data["user_id"] == str(SYNTHETIC_PAYER_ID)
        assert payer_data["roles"] == ["payer"]
        assert payer_data["notification_preference_paise"] is None

        # ID spoofing attempt via query params and headers ignored
        spoofed_resp = opt_in_client.get(
            f"/api/v2/profile?user_id={SYNTHETIC_ADMIN_ID}&role=admin",
            headers={
                "Authorization": "Bearer demo-token-payer",
                "X-User-ID": str(SYNTHETIC_ADMIN_ID),
                "X-Role": "admin",
            },
        )
        assert spoofed_resp.status_code == 200
        assert spoofed_resp.json()["user_id"] == str(SYNTHETIC_PAYER_ID)
        assert spoofed_resp.json()["roles"] == ["payer"]


# ---------------------------------------------------------------------------
# Role Authorization Dependencies (HTTP 403)
# ---------------------------------------------------------------------------

def test_require_role_dependency_matrix(client: TestClient):
    payer_headers = {"Authorization": "Bearer demo-token-payer"}
    guardian_headers = {"Authorization": "Bearer demo-token-guardian"}
    analyst_headers = {"Authorization": "Bearer demo-token-analyst"}
    admin_headers = {"Authorization": "Bearer demo-token-admin"}

    # Payer endpoint
    assert client.get("/test/payer-only", headers=payer_headers).status_code == 200
    assert client.get("/test/payer-only", headers=guardian_headers).status_code == 403
    assert client.get("/test/payer-only", headers=analyst_headers).status_code == 403
    assert client.get("/test/payer-only", headers=admin_headers).status_code == 403

    # Guardian endpoint
    assert client.get("/test/guardian-only", headers=guardian_headers).status_code == 200
    assert client.get("/test/guardian-only", headers=payer_headers).status_code == 403
    assert client.get("/test/guardian-only", headers=analyst_headers).status_code == 403

    # Analyst endpoint
    assert client.get("/test/analyst-only", headers=analyst_headers).status_code == 200
    assert client.get("/test/analyst-only", headers=payer_headers).status_code == 403

    # Admin endpoint
    assert client.get("/test/admin-only", headers=admin_headers).status_code == 200
    assert client.get("/test/admin-only", headers=payer_headers).status_code == 403


def test_require_any_role_dependency(client: TestClient):
    analyst_headers = {"Authorization": "Bearer demo-token-analyst"}
    admin_headers = {"Authorization": "Bearer demo-token-admin"}
    payer_headers = {"Authorization": "Bearer demo-token-payer"}

    assert client.get("/test/operator", headers=analyst_headers).status_code == 200
    assert client.get("/test/operator", headers=admin_headers).status_code == 200
    resp = client.get("/test/operator", headers=payer_headers)
    assert resp.status_code == 403
    assert "Forbidden: Operation requires one of" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Resource Ownership & Cross-Account Access Checks
# ---------------------------------------------------------------------------

def test_authorize_resource_owner_success_and_forbidden():
    owner_id = SYNTHETIC_PAYER_ID
    # Owner accessing own resource -> succeeds
    authorize_resource_owner(SYNTHETIC_PAYER, owner_id)

    # Different user accessing resource -> 403 CrossAccountAccessError
    with pytest.raises(CrossAccountAccessError) as exc_info:
        authorize_resource_owner(SYNTHETIC_OTHER_PAYER, owner_id)
    assert exc_info.value.status_code == 403
    assert "cannot access resource owned by" in exc_info.value.detail


def test_authorize_account_access_success_and_forbidden():
    account_owner_id = SYNTHETIC_PAYER_ID
    # Own account -> succeeds
    authorize_account_access(SYNTHETIC_PAYER, account_owner_id)

    # Foreign account -> 403 CrossAccountAccessError
    with pytest.raises(CrossAccountAccessError) as exc_info:
        authorize_account_access(SYNTHETIC_OTHER_PAYER, account_owner_id)
    assert exc_info.value.status_code == 403
    assert "cannot access account owned by" in exc_info.value.detail


def test_authorize_resource_owner_validates_types():
    with pytest.raises(AuthorizationError):
        authorize_resource_owner("not-an-actor", SYNTHETIC_PAYER_ID)  # type: ignore

    with pytest.raises(AuthorizationError):
        authorize_resource_owner(SYNTHETIC_PAYER, "not-a-uuid")  # type: ignore


# ---------------------------------------------------------------------------
# Authoritative Guardian Relationship Verification & Anti-Spoofing
# ---------------------------------------------------------------------------

def test_authoritative_guardian_lookup():
    assert get_authoritative_guardian_for_payer(SYNTHETIC_PAYER_ID) == SYNTHETIC_GUARDIAN_ID
    assert get_authoritative_guardian_for_payer(uuid4()) is None
    assert get_authoritative_guardian_for_payer("not-a-uuid") is None  # type: ignore


def test_verify_guardian_relationship_authoritative_server_lookup():
    """Verify that when assigned_guardian_id is omitted, it resolves authoritatively from server."""
    verify_guardian_to_payer_relationship(
        SYNTHETIC_GUARDIAN,
        payer_id=SYNTHETIC_PAYER_ID,
    )


def test_verify_guardian_relationship_rejects_spoofed_guardian_id():
    """Verify that an untrusted caller supplying a mismatched assigned_guardian_id is rejected."""
    spoofed_guardian_id = uuid4()
    with pytest.raises(GuardianAssignmentError) as exc_info:
        verify_guardian_to_payer_relationship(
            SYNTHETIC_GUARDIAN,
            assigned_guardian_id=spoofed_guardian_id,
            payer_id=SYNTHETIC_PAYER_ID,
        )
    assert exc_info.value.status_code == 403
    assert "Supplied guardian does not match authoritative server enrollment" in exc_info.value.detail


def test_verify_guardian_relationship_rejects_client_assignment_when_payer_unenrolled():
    """Verify that a client cannot self-authorize by supplying assigned_guardian_id for unenrolled payer."""
    unenrolled_payer_id = uuid4()
    # Even if the caller supplies their own user_id as assigned_guardian_id, it is rejected
    with pytest.raises(GuardianAssignmentError) as exc_info:
        verify_guardian_to_payer_relationship(
            SYNTHETIC_GUARDIAN,
            assigned_guardian_id=SYNTHETIC_GUARDIAN_ID,
            payer_id=unenrolled_payer_id,
        )
    assert exc_info.value.status_code == 403
    assert "Payer has no enrolled guardian on record" in exc_info.value.detail


def test_verify_guardian_relationship_rejects_non_guardian_role():
    with pytest.raises(AuthorizationError) as exc_info:
        verify_guardian_to_payer_relationship(
            SYNTHETIC_PAYER,
            assigned_guardian_id=SYNTHETIC_PAYER_ID,
            payer_id=SYNTHETIC_OTHER_PAYER_ID,
        )
    assert exc_info.value.status_code == 403
    assert "Actor does not hold the guardian role" in exc_info.value.detail


def test_verify_guardian_relationship_payer_cannot_be_own_guardian():
    dual_actor = TrustedActorContext(
        user_id=SYNTHETIC_PAYER_ID,
        roles=frozenset({UserRole.PAYER, UserRole.GUARDIAN}),
    )
    with pytest.raises(GuardianAssignmentError) as exc_info:
        verify_guardian_to_payer_relationship(
            dual_actor,
            assigned_guardian_id=SYNTHETIC_PAYER_ID,
            payer_id=SYNTHETIC_PAYER_ID,
        )
    assert exc_info.value.status_code == 403
    assert "Payer cannot act as guardian for their own transaction" in exc_info.value.detail


def test_verify_guardian_relationship_unassigned_guardian_rejected():
    other_guardian_actor = TrustedActorContext(
        user_id=uuid4(),
        roles=frozenset({UserRole.GUARDIAN}),
    )
    with pytest.raises(GuardianAssignmentError) as exc_info:
        verify_guardian_to_payer_relationship(
            other_guardian_actor,
            payer_id=SYNTHETIC_PAYER_ID,
        )
    assert exc_info.value.status_code == 403
    assert "Actor is not the assigned guardian" in exc_info.value.detail


# ---------------------------------------------------------------------------
# Invariant: Guardian Approval Never Executes Payment
# ---------------------------------------------------------------------------

def test_assert_guardian_cannot_execute_target_state():
    with pytest.raises(AuthorizationError) as exc_info:
        assert_guardian_cannot_execute(target_state="EXECUTED")
    assert "Guardian approval cannot transition payment to EXECUTED" in exc_info.value.detail

    assert_guardian_cannot_execute(target_state="READY_TO_EXECUTE")
    assert_guardian_cannot_execute(target_state="REJECTED")


def test_assert_guardian_cannot_execute_actor_role():
    with pytest.raises(AuthorizationError) as exc_info:
        assert_guardian_cannot_execute(actor=SYNTHETIC_GUARDIAN)
    assert "Guardian role cannot execute payments" in exc_info.value.detail

    assert_guardian_cannot_execute(actor=SYNTHETIC_PAYER)


# ---------------------------------------------------------------------------
# Privacy-Preserving Payment View Levels
# ---------------------------------------------------------------------------

def test_authorize_payment_view_level_with_authoritative_resolution():
    # Payer gets full view
    level = authorize_payment_view_level(
        SYNTHETIC_PAYER,
        payer_id=SYNTHETIC_PAYER_ID,
    )
    assert level == "full"

    # Assigned guardian gets redacted view (resolved automatically from server state)
    level = authorize_payment_view_level(
        SYNTHETIC_GUARDIAN,
        payer_id=SYNTHETIC_PAYER_ID,
    )
    assert level == "redacted"

    # Foreign payer gets forbidden
    with pytest.raises(AuthorizationError):
        authorize_payment_view_level(
            SYNTHETIC_OTHER_PAYER,
            payer_id=SYNTHETIC_PAYER_ID,
        )

    # Unassigned guardian gets forbidden
    unassigned_guardian = TrustedActorContext(
        user_id=uuid4(),
        roles=frozenset({UserRole.GUARDIAN}),
    )
    with pytest.raises(AuthorizationError):
        authorize_payment_view_level(
            unassigned_guardian,
            payer_id=SYNTHETIC_PAYER_ID,
        )


# ---------------------------------------------------------------------------
# Schema Validation & Immutability Tests
# ---------------------------------------------------------------------------

def test_actor_profile_response_schema():
    profile = ActorProfileResponse(
        user_id=SYNTHETIC_PAYER_ID,
        roles=[UserRole.PAYER],
        notification_preference_paise=500000,
    )
    assert profile.user_id == SYNTHETIC_PAYER_ID
    assert profile.roles == [UserRole.PAYER]
    assert profile.notification_preference_paise == 500000

    with pytest.raises(ValidationError):
        profile.notification_preference_paise = 100  # type: ignore

    with pytest.raises(ValidationError):
        ActorProfileResponse(
            user_id=SYNTHETIC_PAYER_ID,
            roles=[UserRole.PAYER],
            extra_field="disallowed",  # type: ignore
        )


def test_redacted_payment_view_schema():
    view = RedactedPaymentView(
        id="pg_01J...",
        status="AWAITING_GUARDIAN",
        tier=3,
        guardian_deadline="2026-11-10T10:00:30+00:00",
        message="A security review is requested for an unusual transaction.",
    )
    assert view.tier == 3
    assert view.status == "AWAITING_GUARDIAN"

    with pytest.raises(ValidationError):
        RedactedPaymentView(
            id="pg_01J...",
            status="AWAITING_GUARDIAN",
            tier=3,
            message="Test",
            amount_paise=5000000,  # type: ignore
        )


def test_full_payment_view_schema():
    view = FullPaymentView(
        id="pg_01J...",
        status="READY_TO_EXECUTE",
        tier=0,
        amount_paise=25000,
        beneficiary_id="trusted_merchant_01",
        purpose="groceries",
        version=1,
    )
    assert view.amount_paise == 25000
    assert view.beneficiary_id == "trusted_merchant_01"


def test_guardian_decision_request_schema():
    decision = GuardianDecisionRequest(approved=True, notes="Verified by phone")
    assert decision.approved is True
    assert decision.notes == "Verified by phone"

    with pytest.raises(ValidationError):
        GuardianDecisionRequest(approved=True, notes="x" * 300)  # max_length is 256

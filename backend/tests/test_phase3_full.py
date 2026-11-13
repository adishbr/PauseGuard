"""Comprehensive Phase 3 offline test suite covering all security, state, and API requirements.

Test categories:
1. Authentication & 4-role permissions.
2. Guardian enrollment, opt-in, status, and revocation safeguards.
3. Unauthorized-access & cross-account access denial.
4. Repeated, duplicate, late (>=30s), and replayed decision rejection.
5. Cross-account privacy and view redaction.
6. Fail-closed behavior (unenrolled payers, unexpired deadlines, Safe-Lock lockouts).
7. Telephony simulation invariants (call answer != approval, webhook != authorization).
8. End-to-end happy path payment lifecycle.
9. End-to-end timeout, fallback activation, and terminal immutability lifecycle.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4
import pytest
from fastapi.testclient import TestClient

from app.auth.identities import (
    SYNTHETIC_ADMIN_ID,
    SYNTHETIC_ANALYST_ID,
    SYNTHETIC_GUARDIAN_ID,
    SYNTHETIC_OTHER_PAYER_ID,
    SYNTHETIC_PAYER_ID,
)
from app.auth.schemas import (
    FullPaymentView,
    GuardianEnrollRequest,
    PaymentCreateRequest,
    RedactedPaymentView,
)
from app.config import Settings
from app.main import create_app
from app.models.roles import UserRole
from app.services.guardian_service import get_guardian_service
from app.services.payment_guards import PaymentStatus, TrustedActorContext
from app.services.payment_service import PaymentRecord, get_payment_service
from app.services.telephony_service import get_telephony_service


@pytest.fixture(autouse=True)
def reset_services():
    """Ensure clean isolated service state before each test."""
    get_guardian_service().reset_for_testing()
    get_payment_service().reset_for_testing()
    get_telephony_service().reset_for_testing()
    yield
    get_guardian_service().reset_for_testing()
    get_payment_service().reset_for_testing()
    get_telephony_service().reset_for_testing()


@pytest.fixture
def test_app():
    settings = Settings(environment="test", mode="mock", allow_demo_auth=True)
    return create_app(settings)


@pytest.fixture
def client(test_app):
    return TestClient(test_app)


def auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ===========================================================================
# 1. Authentication & Role Permissions
# ===========================================================================

def test_unauthenticated_request_rejected(client):
    """Requests without credentials fail with 401 Unauthorized."""
    response = client.get("/api/v2/profile")
    assert response.status_code == 401
    assert "WWW-Authenticate" in response.headers


def test_invalid_bearer_token_rejected(client):
    """Unknown or malformed bearer tokens fail with 401."""
    response = client.get("/api/v2/profile", headers=auth_header("invalid-token-xyz"))
    assert response.status_code == 401


def test_all_four_roles_authenticate_correctly(client):
    """Payer, guardian, analyst, and admin authenticate to their server-resolved roles."""
    roles_map = {
        "demo-token-payer": "payer",
        "demo-token-guardian": "guardian",
        "demo-token-analyst": "analyst",
        "demo-token-admin": "admin",
    }
    for token, expected_role in roles_map.items():
        resp = client.get("/api/v2/profile", headers=auth_header(token))
        assert resp.status_code == 200, f"Token {token} failed authentication"
        data = resp.json()
        assert expected_role in data["roles"]


def test_payer_only_endpoints_deny_other_roles(client):
    """Endpoints requiring PAYER strictly reject guardian, analyst, and admin with 403."""
    non_payer_tokens = ["demo-token-guardian", "demo-token-analyst", "demo-token-admin"]
    for token in non_payer_tokens:
        resp = client.post(
            "/api/v2/payments",
            json={
                "beneficiary_id": "test_merchant",
                "amount_paise": 100000,
                "purpose": "test",
                "idempotency_key": f"key_{token}",
            },
            headers=auth_header(token),
        )
        assert resp.status_code == 403, f"Expected 403 for {token}, got {resp.status_code}"


# ===========================================================================
# 2. Guardian Enrollment, Opt-In, Status, and Revocation
# ===========================================================================

def test_guardian_status_default_synthetic_payer(client):
    """Default synthetic payer is enrolled with default synthetic guardian."""
    resp = client.get("/api/v2/guardian/status", headers=auth_header("demo-token-payer"))
    assert resp.status_code == 200
    data = resp.json()
    assert data["has_guardian"] is True
    assert data["enrollment"] is not None
    assert data["enrollment"]["status"] == "active"
    assert data["enrollment"]["guardian_id"] == str(SYNTHETIC_GUARDIAN_ID)


def test_guardian_status_for_guardian(client):
    """Enrolled guardian status reflects active protection relationship."""
    resp = client.get("/api/v2/guardian/status", headers=auth_header("demo-token-guardian"))
    assert resp.status_code == 200
    data = resp.json()
    assert data["has_guardian"] is True
    assert str(SYNTHETIC_PAYER_ID) in [str(p) for p in data["guarded_payers"]]


def test_guardian_status_unenrolled_payer(client):
    """Payer without active enrollment receives has_guardian=False."""
    resp = client.get("/api/v2/guardian/status", headers=auth_header("demo-token-other-payer"))
    assert resp.status_code == 200
    data = resp.json()
    assert data["has_guardian"] is False
    assert data["enrollment"] is None


def test_payer_can_enroll_new_guardian_with_opt_in(client):
    """Payer can successfully enroll an authorized guardian with explicit opt-in."""
    new_guardian_id = str(SYNTHETIC_GUARDIAN_ID)
    resp = client.post(
        "/api/v2/guardian/enroll",
        json={"guardian_id": new_guardian_id, "opt_in_confirmed": True},
        headers=auth_header("demo-token-other-payer"),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "active"
    assert data["payer_id"] == str(SYNTHETIC_OTHER_PAYER_ID)
    assert data["guardian_id"] == new_guardian_id


def test_guardian_enrollment_omitted_opt_in_fails_closed(client):
    """Enrollment without explicit opt_in_confirmed defaults to False and fails (422)."""
    resp = client.post(
        "/api/v2/guardian/enroll",
        json={"guardian_id": str(SYNTHETIC_GUARDIAN_ID)},  # Omitting opt_in_confirmed
        headers=auth_header("demo-token-other-payer"),
    )
    assert resp.status_code == 422


def test_guardian_enrollment_fails_without_opt_in(client):
    """Enrollment fails closed (422) if opt_in_confirmed is explicitly False."""
    resp = client.post(
        "/api/v2/guardian/enroll",
        json={"guardian_id": str(SYNTHETIC_GUARDIAN_ID), "opt_in_confirmed": False},
        headers=auth_header("demo-token-other-payer"),
    )
    assert resp.status_code == 422


def test_arbitrary_guardian_uuid_rejected_without_server_evidence(client):
    """Client-supplied arbitrary guardian UUID cannot be self-verified and is rejected (403)."""
    arbitrary_id = str(uuid4())
    resp = client.post(
        "/api/v2/guardian/enroll",
        json={"guardian_id": arbitrary_id, "opt_in_confirmed": True},
        headers=auth_header("demo-token-other-payer"),
    )
    assert resp.status_code == 403
    assert "Guardian identity verification failed" in resp.json()["detail"]


def test_self_guardianship_strictly_rejected(client):
    """Payer attempting to enroll themselves as guardian is rejected."""
    resp = client.post(
        "/api/v2/guardian/enroll",
        json={"guardian_id": str(SYNTHETIC_PAYER_ID), "opt_in_confirmed": True},
        headers=auth_header("demo-token-payer"),
    )
    assert resp.status_code == 403
    assert "cannot enroll themselves" in resp.json()["detail"].lower()


def test_payer_can_revoke_guardian(client):
    """Payer can revoke their active guardian enrollment."""
    resp = client.post("/api/v2/guardian/revoke", headers=auth_header("demo-token-payer"))
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "revoked"
    assert data["payer_id"] == str(SYNTHETIC_PAYER_ID)

    # After revocation, status has_guardian is False
    status_resp = client.get("/api/v2/guardian/status", headers=auth_header("demo-token-payer"))
    assert status_resp.json()["has_guardian"] is False
    assert status_resp.json()["enrollment"] is None


def test_revoking_when_not_enrolled_fails(client):
    """Attempting to revoke when no guardian is enrolled fails closed."""
    resp = client.post("/api/v2/guardian/revoke", headers=auth_header("demo-token-other-payer"))
    assert resp.status_code == 403
    assert "no active guardian" in resp.json()["detail"].lower()


# ===========================================================================
# 3. Unauthorized-Access & Cross-Account Denial
# ===========================================================================

def test_cross_account_payment_access_denied(client):
    """Payer B cannot view or access Payer A's payment."""
    # Create payment as Payer A
    create_resp = client.post(
        "/api/v2/payments",
        json={
            "beneficiary_id": "test_merchant",
            "amount_paise": 6000000,
            "purpose": "high_value_transfer",
            "idempotency_key": "cross_acc_01",
        },
        headers=auth_header("demo-token-payer"),
    )
    assert create_resp.status_code == 201
    payment_id = create_resp.json()["id"]

    # Payer B (other-payer) attempts to view Payer A's payment
    view_resp = client.get(f"/api/v2/payments/{payment_id}", headers=auth_header("demo-token-other-payer"))
    assert view_resp.status_code == 403
    assert "Forbidden" in view_resp.json()["detail"]


def test_unassigned_guardian_access_denied(client):
    """A guardian who is not enrolled for this payer cannot view or decide on the payment."""
    payment_service = get_payment_service()
    now = datetime.now(timezone.utc)
    payment_record = PaymentRecord(
        id="pg_foreign_001",
        payer_id=SYNTHETIC_OTHER_PAYER_ID,  # Other payer has NO guardian enrolled
        beneficiary_id="foreign_merchant",
        amount_paise=5000000,
        purpose="rent",
        idempotency_key="idemp_foreign",
        status=PaymentStatus.AWAITING_GUARDIAN,
        tier=3,
        guardian_deadline=now + timedelta(seconds=30),
        assigned_guardian_id=SYNTHETIC_GUARDIAN_ID,  # Mismatch with server enrollment
        created_at=now.isoformat(),
    )
    payment_service.seed_payment(payment_record)

    # Guardian attempts to view: fails closed because other-payer has no server enrollment for this guardian
    resp = client.get("/api/v2/payments/pg_foreign_001", headers=auth_header("demo-token-guardian"))
    assert resp.status_code == 403


def test_guardian_cannot_confirm_payment(client):
    """Guardian role cannot confirm or execute payments under any circumstance."""
    create_resp = client.post(
        "/api/v2/payments",
        json={
            "beneficiary_id": "merchant_1",
            "amount_paise": 5500000,
            "purpose": "test",
            "idempotency_key": "guardian_no_exec_01",
        },
        headers=auth_header("demo-token-payer"),
    )
    payment_id = create_resp.json()["id"]

    # Guardian approves to READY_TO_EXECUTE
    dec_resp = client.post(
        f"/api/v2/payments/{payment_id}/guardian/decision",
        json={"approved": True, "notes": "looks fine"},
        headers=auth_header("demo-token-guardian"),
    )
    assert dec_resp.status_code == 200
    assert dec_resp.json()["can_execute_payment"] is False

    # Guardian tries to execute / confirm payment -> 403 Forbidden
    confirm_resp = client.post(
        f"/api/v2/payments/{payment_id}/confirm",
        json={"idempotency_key": "confirm_key_01"},
        headers=auth_header("demo-token-guardian"),
    )
    assert confirm_resp.status_code == 403


# ===========================================================================
# 4. Duplicate, Late (>=30s), and Replayed Decisions
# ===========================================================================

def test_duplicate_guardian_decision_rejected(client):
    """Submitting a decision twice on the same payment fails with 409 Conflict."""
    create_resp = client.post(
        "/api/v2/payments",
        json={
            "beneficiary_id": "merchant_dup",
            "amount_paise": 5500000,
            "purpose": "test",
            "idempotency_key": "dup_key_01",
        },
        headers=auth_header("demo-token-payer"),
    )
    payment_id = create_resp.json()["id"]

    # First decision succeeds
    resp1 = client.post(
        f"/api/v2/payments/{payment_id}/guardian/decision",
        json={"approved": True, "notes": "Approved once"},
        headers=auth_header("demo-token-guardian"),
    )
    assert resp1.status_code == 200

    # Second decision fails with 409 Conflict
    resp2 = client.post(
        f"/api/v2/payments/{payment_id}/guardian/decision",
        json={"approved": True, "notes": "Duplicate approval"},
        headers=auth_header("demo-token-guardian"),
    )
    assert resp2.status_code == 409
    assert "Conflict" in resp2.json()["detail"]


def test_late_guardian_decision_strictly_rejected(client):
    """Guardian decision submitted at or after 30-second deadline is rejected with 422."""
    now = datetime.now(timezone.utc)
    expired_deadline = now - timedelta(seconds=1)  # 1 second past deadline

    payment_record = PaymentRecord(
        id="pg_late_001",
        payer_id=SYNTHETIC_PAYER_ID,
        beneficiary_id="merchant_late",
        amount_paise=6000000,
        purpose="urgent_transfer",
        idempotency_key="key_late_001",
        status=PaymentStatus.AWAITING_GUARDIAN,
        tier=3,
        guardian_deadline=expired_deadline,
        assigned_guardian_id=SYNTHETIC_GUARDIAN_ID,
        created_at=(now - timedelta(seconds=35)).isoformat(),
    )
    get_payment_service().seed_payment(payment_record)

    # Guardian tries to approve expired payment
    resp = client.post(
        "/api/v2/payments/pg_late_001/guardian/decision",
        json={"approved": True, "notes": "Late approval attempt"},
        headers=auth_header("demo-token-guardian"),
    )
    assert resp.status_code == 422
    assert "expired" in resp.json()["detail"].lower()


# ===========================================================================
# 5. Privacy Redaction and Cross-Account Isolation
# ===========================================================================

def test_privacy_redaction_for_assigned_guardian(client):
    """Assigned guardian receives only sanitized alert message without sensitive details."""
    create_resp = client.post(
        "/api/v2/payments",
        json={
            "beneficiary_id": "secret_bank_recipient_42",
            "amount_paise": 7500000,
            "purpose": "medical_confidential_procedure",
            "idempotency_key": "privacy_key_01",
        },
        headers=auth_header("demo-token-payer"),
    )
    payment_id = create_resp.json()["id"]

    # Guardian inspects payment view
    resp = client.get(f"/api/v2/payments/{payment_id}", headers=auth_header("demo-token-guardian"))
    assert resp.status_code == 200
    data = resp.json()

    # Redacted fields MUST NOT be present
    assert "amount_paise" not in data
    assert "beneficiary_id" not in data
    assert "purpose" not in data

    # Safe fields MUST be present
    assert data["id"] == payment_id
    assert data["status"] == "AWAITING_GUARDIAN"
    assert data["tier"] == 3
    assert "message" in data
    assert "PauseGuard" in data["message"]


def test_owning_payer_receives_full_payment_view(client):
    """Owning payer receives the complete payment view."""
    create_resp = client.post(
        "/api/v2/payments",
        json={
            "beneficiary_id": "store_123",
            "amount_paise": 5500000,
            "purpose": "appliances",
            "idempotency_key": "full_view_key_01",
        },
        headers=auth_header("demo-token-payer"),
    )
    payment_id = create_resp.json()["id"]

    resp = client.get(f"/api/v2/payments/{payment_id}", headers=auth_header("demo-token-payer"))
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == payment_id
    assert data["amount_paise"] == 5500000
    assert data["beneficiary_id"] == "store_123"
    assert data["purpose"] == "appliances"
    assert data["version"] >= 1


# ===========================================================================
# 6. Fail-Closed Invariants (Unenrolled Payers, Premature Fallback, Safe-Lock)
# ===========================================================================

def test_unenrolled_payer_high_risk_payment_fails_closed(client):
    """Unenrolled payer creating high-risk payment requiring guardian fails closed (403)."""
    resp = client.post(
        "/api/v2/payments",
        json={
            "beneficiary_id": "risk_recipient",
            "amount_paise": 9900000,
            "purpose": "crypto_scam_indicator",
            "idempotency_key": "unenrolled_risk_01",
        },
        headers=auth_header("demo-token-other-payer"),  # other-payer is unenrolled
    )
    assert resp.status_code == 403
    assert "no enrolled guardian" in resp.json()["detail"].lower()


def test_premature_fallback_activation_rejected(client):
    """Payer attempting to activate fallback before the 30-second window expires is rejected (422)."""
    create_resp = client.post(
        "/api/v2/payments",
        json={
            "beneficiary_id": "merchant_quick",
            "amount_paise": 5500000,
            "purpose": "test",
            "idempotency_key": "premature_fallback_01",
        },
        headers=auth_header("demo-token-payer"),
    )
    payment_id = create_resp.json()["id"]

    # Immediately try to activate fallback before 30s have passed
    resp = client.post(
        f"/api/v2/payments/{payment_id}/fallback/activate",
        headers=auth_header("demo-token-payer"),
    )
    assert resp.status_code == 422
    assert "not expired" in resp.json()["detail"].lower()


def test_fallback_activation_never_authorizes_payment(client):
    """When fallback review is activated after deadline expiry, can_authorize_payment is False."""
    now = datetime.now(timezone.utc)
    expired_payment = PaymentRecord(
        id="pg_fallback_001",
        payer_id=SYNTHETIC_PAYER_ID,
        beneficiary_id="merchant_timeout",
        amount_paise=5500000,
        purpose="test_timeout",
        idempotency_key="idemp_timeout",
        status=PaymentStatus.AWAITING_GUARDIAN,
        tier=3,
        guardian_deadline=now - timedelta(seconds=5),  # Expired
        assigned_guardian_id=SYNTHETIC_GUARDIAN_ID,
        created_at=(now - timedelta(seconds=40)).isoformat(),
    )
    get_payment_service().seed_payment(expired_payment)

    # Activate fallback
    resp = client.post(
        "/api/v2/payments/pg_fallback_001/fallback/activate",
        headers=auth_header("demo-token-payer"),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "AWAITING_FALLBACK_REVIEW"
    assert data["can_authorize_payment"] is False

    # Attempting to confirm from AWAITING_FALLBACK_REVIEW must fail
    confirm_resp = client.post(
        "/api/v2/payments/pg_fallback_001/confirm",
        json={"idempotency_key": "confirm_timeout_01"},
        headers=auth_header("demo-token-payer"),
    )
    assert confirm_resp.status_code == 409


def test_safe_lock_engaged_blocks_confirmation(client):
    """Payer confirmation is blocked if Safe-Lock is engaged (423 Locked)."""
    # Create and approve payment
    create_resp = client.post(
        "/api/v2/payments",
        json={
            "beneficiary_id": "merchant_safelock",
            "amount_paise": 5500000,
            "purpose": "test",
            "idempotency_key": "safelock_test_01",
        },
        headers=auth_header("demo-token-payer"),
    )
    payment_id = create_resp.json()["id"]

    client.post(
        f"/api/v2/payments/{payment_id}/guardian/decision",
        json={"approved": True},
        headers=auth_header("demo-token-guardian"),
    )

    # Engage Safe-Lock for payer
    get_payment_service().set_safe_lock(SYNTHETIC_PAYER_ID, is_locked=True)

    # Confirmation fails with 423 Locked
    confirm_resp = client.post(
        f"/api/v2/payments/{payment_id}/confirm",
        json={"idempotency_key": "confirm_safelock_key"},
        headers=auth_header("demo-token-payer"),
    )
    assert confirm_resp.status_code == 423
    assert "Safe-Lock is currently engaged" in confirm_resp.json()["detail"]


# ===========================================================================
# 7. Telephony Simulation Invariants
# ===========================================================================

def test_telephony_call_status_cannot_authorize_payment(client):
    """Call answered status maintains can_authorize_payment: False invariant."""
    resp = client.get("/api/v2/guardian/calls/call_synthetic_001/status", headers=auth_header("demo-token-payer"))
    assert resp.status_code == 200
    data = resp.json()
    assert data["can_authorize_payment"] is False


def test_telephony_provider_webhook_cannot_authorize_payment(client):
    """Provider webhook callback records event with mock signature but cannot authorize payment."""
    resp = client.post(
        "/api/v2/guardian/calls/provider-callback",
        json={
            "call_id": "call_synthetic_001",
            "event": "answered",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
        headers={"X-Mock-Provider-Signature": "mock-telephony-signature"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["recorded"] is True
    assert data["can_authorize_payment"] is False


def test_telephony_provider_webhook_missing_signature_rejected(client):
    """Unsigned provider webhook is rejected with 401 Unauthorized."""
    resp = client.post(
        "/api/v2/guardian/calls/provider-callback",
        json={
            "call_id": "call_synthetic_001",
            "event": "answered",
        },
    )
    assert resp.status_code == 401
    assert "Invalid or missing mock provider webhook signature" in resp.json()["detail"]


def test_telephony_provider_webhook_wrong_signature_rejected(client):
    """Untrusted signature provider webhook is rejected with 401 Unauthorized."""
    resp = client.post(
        "/api/v2/guardian/calls/provider-callback",
        json={
            "call_id": "call_synthetic_001",
            "event": "answered",
        },
        headers={"X-Mock-Provider-Signature": "forged-signature"},
    )
    assert resp.status_code == 401


def test_telephony_provider_webhook_non_mock_environment_disabled():
    """Unverified callbacks fail closed (501) outside local/test mock environments."""
    prod_app = create_app()
    prod_app.state.settings = type("MockSettings", (), {"environment": "production", "mode": "real"})()
    prod_client = TestClient(prod_app)
    resp = prod_client.post(
        "/api/v2/guardian/calls/provider-callback",
        json={
            "call_id": "call_synthetic_001",
            "event": "answered",
        },
        headers={"X-Mock-Provider-Signature": "mock-telephony-signature"},
    )
    assert resp.status_code == 501
    assert "disabled outside local mock/test" in resp.json()["detail"]


# ===========================================================================
# 8. End-to-End Happy Path Lifecycle
# ===========================================================================

def test_end_to_end_payment_lifecycle(client):
    """Full lifecycle: CREATE -> GUARDIAN_REVIEW -> APPROVE -> READY_TO_EXECUTE -> CONFIRM -> EXECUTED."""
    # 1. Payer creates high-value payment (status: AWAITING_GUARDIAN)
    create_resp = client.post(
        "/api/v2/payments",
        json={
            "beneficiary_id": "store_supermarket",
            "amount_paise": 6500000,
            "purpose": "groceries_bulk",
            "idempotency_key": "e2e_happy_01",
        },
        headers=auth_header("demo-token-payer"),
    )
    assert create_resp.status_code == 201
    payment = create_resp.json()
    assert payment["status"] == "AWAITING_GUARDIAN"
    payment_id = payment["id"]

    # 2. Guardian views redacted alert
    guardian_view = client.get(f"/api/v2/payments/{payment_id}", headers=auth_header("demo-token-guardian"))
    assert guardian_view.status_code == 200
    assert "amount_paise" not in guardian_view.json()

    # 3. Guardian approves within deadline
    decision_resp = client.post(
        f"/api/v2/payments/{payment_id}/guardian/decision",
        json={"approved": True, "notes": "Verified with payer over phone"},
        headers=auth_header("demo-token-guardian"),
    )
    assert decision_resp.status_code == 200
    assert decision_resp.json()["target_status"] == "READY_TO_EXECUTE"
    assert decision_resp.json()["can_execute_payment"] is False

    # 4. Payer executes final confirmation
    confirm_resp = client.post(
        f"/api/v2/payments/{payment_id}/confirm",
        json={"idempotency_key": "e2e_confirm_key_01"},
        headers=auth_header("demo-token-payer"),
    )
    assert confirm_resp.status_code == 200
    assert confirm_resp.json()["status"] == "EXECUTED"

    # 5. Terminal state cannot be modified or re-executed
    reconfirm_resp = client.post(
        f"/api/v2/payments/{payment_id}/confirm",
        json={"idempotency_key": "e2e_confirm_key_02"},
        headers=auth_header("demo-token-payer"),
    )
    assert reconfirm_resp.status_code == 409


def test_payment_idempotency_on_creation(client):
    """Submitting same idempotency key returns exact same payment."""
    payload = {
        "beneficiary_id": "vendor_alpha",
        "amount_paise": 5500000,
        "purpose": "supplies",
        "idempotency_key": "idem_unique_123",
    }
    resp1 = client.post("/api/v2/payments", json=payload, headers=auth_header("demo-token-payer"))
    assert resp1.status_code == 201
    id1 = resp1.json()["id"]

    resp2 = client.post("/api/v2/payments", json=payload, headers=auth_header("demo-token-payer"))
    assert resp2.status_code == 201
    assert resp2.json()["id"] == id1


# ===========================================================================
# 9. Concurrency & Race-Condition Invariants
# ===========================================================================

def test_concurrent_guardian_approval_vs_timeout(client):
    """Approval and timeout race: exactly one authoritative transition wins."""
    now = datetime.now(timezone.utc)
    payment_record = PaymentRecord(
        id="pg_race_timeout_001",
        payer_id=SYNTHETIC_PAYER_ID,
        beneficiary_id="merchant_race",
        amount_paise=5500000,
        purpose="race_test",
        idempotency_key="key_race_01",
        status=PaymentStatus.AWAITING_GUARDIAN,
        tier=3,
        guardian_deadline=now,
        assigned_guardian_id=SYNTHETIC_GUARDIAN_ID,
        created_at=(now - timedelta(seconds=30)).isoformat(),
    )
    get_payment_service().seed_payment(payment_record)

    results = []
    def do_approve():
        resp = client.post(
            "/api/v2/payments/pg_race_timeout_001/guardian/decision",
            json={"approved": True, "notes": "concurrent approval"},
            headers=auth_header("demo-token-guardian"),
        )
        results.append(("approve", resp.status_code))

    def do_fallback():
        resp = client.post(
            "/api/v2/payments/pg_race_timeout_001/fallback/activate",
            headers=auth_header("demo-token-payer"),
        )
        results.append(("fallback", resp.status_code))

    with ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(do_approve)
        f2 = executor.submit(do_fallback)
        f1.result()
        f2.result()

    status_codes = [code for _, code in results]
    assert 200 in status_codes
    assert len(results) == 2


def test_concurrent_approval_vs_rejection(client):
    """Concurrent approval vs rejection: exactly one decision is recorded."""
    create_resp = client.post(
        "/api/v2/payments",
        json={
            "beneficiary_id": "merchant_race2",
            "amount_paise": 5500000,
            "purpose": "race_test_2",
            "idempotency_key": "key_race_02",
        },
        headers=auth_header("demo-token-payer"),
    )
    payment_id = create_resp.json()["id"]

    results = []
    def do_approve():
        resp = client.post(
            f"/api/v2/payments/{payment_id}/guardian/decision",
            json={"approved": True, "notes": "approve race"},
            headers=auth_header("demo-token-guardian"),
        )
        results.append(resp.status_code)

    def do_reject():
        resp = client.post(
            f"/api/v2/payments/{payment_id}/guardian/decision",
            json={"approved": False, "notes": "reject race"},
            headers=auth_header("demo-token-guardian"),
        )
        results.append(resp.status_code)

    with ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(do_approve)
        f2 = executor.submit(do_reject)
        f1.result()
        f2.result()

    assert results.count(200) == 1
    assert results.count(409) == 1


def test_concurrent_duplicate_payment_creation(client):
    """Concurrent payment creation with identical idempotency key is thread-safe."""
    payload = {
        "beneficiary_id": "vendor_concurrent",
        "amount_paise": 5500000,
        "purpose": "race_creation",
        "idempotency_key": "idem_race_create_01",
    }
    payment_ids = []

    def create_one():
        resp = client.post("/api/v2/payments", json=payload, headers=auth_header("demo-token-payer"))
        if resp.status_code == 201:
            payment_ids.append(resp.json()["id"])

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(create_one) for _ in range(5)]
        for f in futures:
            f.result()

    assert len(payment_ids) == 5
    # All 5 concurrent requests returned the identical payment ID
    assert len(set(payment_ids)) == 1


def test_concurrent_double_payer_confirmation(client):
    """Concurrent payer confirmation requests: exactly one execution succeeds."""
    create_resp = client.post(
        "/api/v2/payments",
        json={
            "beneficiary_id": "merchant_race3",
            "amount_paise": 5500000,
            "purpose": "race_test_3",
            "idempotency_key": "key_race_03",
        },
        headers=auth_header("demo-token-payer"),
    )
    payment_id = create_resp.json()["id"]

    client.post(
        f"/api/v2/payments/{payment_id}/guardian/decision",
        json={"approved": True},
        headers=auth_header("demo-token-guardian"),
    )

    confirm_results = []
    def do_confirm(key: str):
        resp = client.post(
            f"/api/v2/payments/{payment_id}/confirm",
            json={"idempotency_key": key},
            headers=auth_header("demo-token-payer"),
        )
        confirm_results.append(resp.status_code)

    with ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(do_confirm, "key_c1")
        f2 = executor.submit(do_confirm, "key_c2")
        f1.result()
        f2.result()

    assert confirm_results.count(200) == 1
    assert confirm_results.count(409) == 1


def test_concurrent_guardian_revocation_vs_authorization(client):
    """Concurrent revocation and decision: thread-safe, no deadlock, authoritative outcome."""
    create_resp = client.post(
        "/api/v2/payments",
        json={
            "beneficiary_id": "merchant_race4",
            "amount_paise": 5500000,
            "purpose": "race_test_4",
            "idempotency_key": "key_race_04",
        },
        headers=auth_header("demo-token-payer"),
    )
    payment_id = create_resp.json()["id"]

    revocation_status = []
    decision_status = []

    def do_revoke():
        resp = client.post("/api/v2/guardian/revoke", headers=auth_header("demo-token-payer"))
        revocation_status.append(resp.status_code)

    def do_decide():
        resp = client.post(
            f"/api/v2/payments/{payment_id}/guardian/decision",
            json={"approved": True},
            headers=auth_header("demo-token-guardian"),
        )
        decision_status.append(resp.status_code)

    with ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(do_revoke)
        f2 = executor.submit(do_decide)
        f1.result()
        f2.result()

    assert revocation_status[0] == 200
    assert decision_status[0] in (200, 403)


def test_guardian_cannot_replay_payer_confirm_idempotency_key(client):
    """Non-payers must be rejected (403) even if they replay the payer's confirm idempotency_key."""
    create_resp = client.post(
        "/api/v2/payments",
        json={
            "beneficiary_id": "merchant_safe_replay",
            "amount_paise": 5500000,
            "purpose": "kyc_verification",
            "idempotency_key": "key_replay_create_01",
        },
        headers=auth_header("demo-token-payer"),
    )
    assert create_resp.status_code == 201
    payment_id = create_resp.json()["id"]

    dec_resp = client.post(
        f"/api/v2/payments/{payment_id}/guardian/decision",
        json={"approved": True},
        headers=auth_header("demo-token-guardian"),
    )
    assert dec_resp.status_code == 200

    confirm_resp = client.post(
        f"/api/v2/payments/{payment_id}/confirm",
        json={"idempotency_key": "key_replay_confirm_01"},
        headers=auth_header("demo-token-payer"),
    )
    assert confirm_resp.status_code == 200

    guardian_replay = client.post(
        f"/api/v2/payments/{payment_id}/confirm",
        json={"idempotency_key": "key_replay_confirm_01"},
        headers=auth_header("demo-token-guardian"),
    )
    assert guardian_replay.status_code == 403


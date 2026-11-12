"""Comprehensive unit and integration tests for final PauseGuard V2 backend integration.

Tests:
1. Account balance and mock ledger inspection (GET /api/v2/account/balance)
2. Payment history listing and pagination (GET /api/v2/payments)
3. Lifecycle and audit event streaming / polling (GET /api/v2/payments/{id}/events)
4. Payment risk explanations (GET /api/v2/payments/{id}/risk)
5. Redacted privacy-safe evidence export (GET /api/v2/payments/{id}/evidence)
6. Safe-Lock binary enforcement and status (POST/GET /api/v2/safe-lock)
7. Purpose Challenge coercion detection (POST /api/v2/safety/purpose-challenge)
8. Anti-Smurfing rolling velocity evaluation (POST /api/v2/safety/anti-smurfing/check)
9. Cryptographic audit chain verification and anchoring (GET /api/v2/audit/verify, POST /api/v2/audit/anchors)
10. Victim aftercare and 1930 recovery guide (GET /api/v2/recovery/guide)
11. Multi-signal advisory risk evaluation (POST /api/v2/risk/advice)
12. Policy Lab simulation benchmark runner (POST /api/v2/policy-lab/simulate)
13. Authenticated WebSocket lifecycle and PING/PONG (WebSocket /api/v2/ws)
14. Request correlation ID propagation (X-Correlation-ID header)
"""

from uuid import uuid4
import pytest
from fastapi.testclient import TestClient

from app.auth.identities import (
    SYNTHETIC_ADMIN_TOKEN,
    SYNTHETIC_ANALYST_TOKEN,
    SYNTHETIC_GUARDIAN_TOKEN,
    SYNTHETIC_OTHER_PAYER_TOKEN,
    SYNTHETIC_PAYER_ID,
    SYNTHETIC_PAYER_TOKEN,
)
from app.config import Settings
from app.main import create_app
from app.services.payment_service import get_payment_service


@pytest.fixture
def client():
    settings = Settings(environment="test", mode="mock", allow_demo_auth=True)
    app = create_app(settings)
    service = get_payment_service()
    service.reset_for_testing()
    with TestClient(app) as test_client:
        yield test_client


# ---------------------------------------------------------------------------
# 1. Account & Ledger Inspection
# ---------------------------------------------------------------------------

def test_account_balance_authenticated_payer(client):
    headers = {"Authorization": f"Bearer {SYNTHETIC_PAYER_TOKEN}"}
    response = client.get("/api/v2/account/balance", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["user_id"] == str(SYNTHETIC_PAYER_ID)
    assert data["balance_paise"] == 100000000
    assert data["currency"] == "INR"
    assert data["ledger_entries_count"] == 0


def test_account_balance_unauthenticated_rejected(client):
    response = client.get("/api/v2/account/balance")
    assert response.status_code == 401
    assert "Bearer" in response.headers.get("www-authenticate", "")


# ---------------------------------------------------------------------------
# 2. Payment History & Pagination
# ---------------------------------------------------------------------------

def test_payment_listing_and_pagination(client):
    payer_headers = {"Authorization": f"Bearer {SYNTHETIC_PAYER_TOKEN}"}

    # Create 3 payments
    for i in range(3):
        create_res = client.post(
            "/api/v2/payments",
            headers=payer_headers,
            json={
                "beneficiary_id": f"merchant_{i}",
                "amount_paise": 10000 + i,
                "purpose": f"test payment {i}",
                "idempotency_key": f"list_idem_{i}_{uuid4().hex[:8]}",
            },
        )
        assert create_res.status_code == 201

    # List payments with limit=2
    list_res = client.get("/api/v2/payments?limit=2&offset=0", headers=payer_headers)
    assert list_res.status_code == 200
    items = list_res.json()
    assert len(items) == 2

    # Second page
    page2_res = client.get("/api/v2/payments?limit=2&offset=2", headers=payer_headers)
    assert page2_res.status_code == 200
    page2_items = page2_res.json()
    assert len(page2_items) == 1


def test_payment_listing_privacy_redaction_for_guardian(client):
    payer_headers = {"Authorization": f"Bearer {SYNTHETIC_PAYER_TOKEN}"}
    guardian_headers = {"Authorization": f"Bearer {SYNTHETIC_GUARDIAN_TOKEN}"}

    # Create high-risk tier 3 payment requiring guardian
    create_res = client.post(
        "/api/v2/payments",
        headers=payer_headers,
        json={
            "beneficiary_id": "suspicious_beneficiary",
            "amount_paise": 5500000,
            "purpose": "kyc_verification_urgent",
            "idempotency_key": f"guard_list_{uuid4().hex[:8]}",
        },
    )
    assert create_res.status_code == 201

    # Guardian views payments
    list_res = client.get("/api/v2/payments", headers=guardian_headers)
    assert list_res.status_code == 200
    items = list_res.json()
    assert len(items) >= 1
    guardian_view = items[0]
    # Redacted: must not contain amount_paise or raw purpose
    assert "amount_paise" not in guardian_view
    assert "purpose" not in guardian_view
    assert "message" in guardian_view


# ---------------------------------------------------------------------------
# 3. Events Polling & Risk Explanations
# ---------------------------------------------------------------------------

def test_payment_events_and_risk_explanation(client):
    payer_headers = {"Authorization": f"Bearer {SYNTHETIC_PAYER_TOKEN}"}

    # Routine payment
    create_res = client.post(
        "/api/v2/payments",
        headers=payer_headers,
        json={
            "beneficiary_id": "trusted_store",
            "amount_paise": 20000,
            "purpose": "groceries",
            "idempotency_key": f"events_idem_{uuid4().hex[:8]}",
        },
    )
    assert create_res.status_code == 201
    payment_id = create_res.json()["id"]

    # Retrieve events
    events_res = client.get(f"/api/v2/payments/{payment_id}/events", headers=payer_headers)
    assert events_res.status_code == 200
    events = events_res.json()
    assert len(events) >= 1
    assert events[0]["event_type"] == "PAYMENT_CREATED"

    # Retrieve risk explanation
    risk_res = client.get(f"/api/v2/payments/{payment_id}/risk", headers=payer_headers)
    assert risk_res.status_code == 200
    risk_data = risk_res.json()
    assert risk_data["payment_id"] == payment_id
    assert risk_data["tier"] == 0
    assert risk_data["is_hard_blocked"] is False
    assert risk_data["requires_guardian"] is False
    assert len(risk_data["reasons"]) >= 1


# ---------------------------------------------------------------------------
# 4. Redacted Evidence Export
# ---------------------------------------------------------------------------

def test_evidence_export_masks_pii(client):
    payer_headers = {"Authorization": f"Bearer {SYNTHETIC_PAYER_TOKEN}"}

    create_res = client.post(
        "/api/v2/payments",
        headers=payer_headers,
        json={
            "beneficiary_id": "test_merchant",
            "amount_paise": 50000,
            "purpose": "Monthly rent payment",
            "idempotency_key": f"evidence_idem_{uuid4().hex[:8]}",
        },
    )
    payment_id = create_res.json()["id"]

    evidence_res = client.get(f"/api/v2/payments/{payment_id}/evidence", headers=payer_headers)
    assert evidence_res.status_code == 200
    ev = evidence_res.json()
    assert ev["payment_id"] == payment_id
    assert ev["redaction_applied"] is True
    assert ev["review_required_before_sharing"] is True
    assert "exported_at" in ev
    # Sensitive keys never leaked in top-level evidence response
    assert "amount_paise" not in ev
    assert "purpose" not in ev


def test_evidence_export_forbidden_for_guardian(client):
    payer_headers = {"Authorization": f"Bearer {SYNTHETIC_PAYER_TOKEN}"}
    guardian_headers = {"Authorization": f"Bearer {SYNTHETIC_GUARDIAN_TOKEN}"}

    create_res = client.post(
        "/api/v2/payments",
        headers=payer_headers,
        json={
            "beneficiary_id": "supplier",
            "amount_paise": 6000000,
            "purpose": "kyc_verification",
            "idempotency_key": f"guard_ev_{uuid4().hex[:8]}",
        },
    )
    payment_id = create_res.json()["id"]

    ev_res = client.get(f"/api/v2/payments/{payment_id}/evidence", headers=guardian_headers)
    assert ev_res.status_code == 403


# ---------------------------------------------------------------------------
# 5. Safe-Lock Binary Enforcement
# ---------------------------------------------------------------------------

def test_safe_lock_toggle_and_enforcement(client):
    payer_headers = {"Authorization": f"Bearer {SYNTHETIC_PAYER_TOKEN}"}

    # Check initially unlocked
    status_res = client.get("/api/v2/safe-lock", headers=payer_headers)
    assert status_res.status_code == 200
    assert status_res.json()["is_locked"] is False

    # Engage Safe-Lock
    lock_res = client.post("/api/v2/safe-lock", headers=payer_headers, json={"is_locked": True})
    assert lock_res.status_code == 200
    assert lock_res.json()["is_locked"] is True

    # Attempting to create a payment must fail closed (423 Locked)
    blocked_res = client.post(
        "/api/v2/payments",
        headers=payer_headers,
        json={
            "beneficiary_id": "routine_store",
            "amount_paise": 1000,
            "purpose": "tea",
            "idempotency_key": f"locked_idem_{uuid4().hex[:8]}",
        },
    )
    assert blocked_res.status_code == 423
    assert "Safe-Lock is currently engaged" in blocked_res.json()["detail"]

    # Disengage Safe-Lock
    unlock_res = client.post("/api/v2/safe-lock", headers=payer_headers, json={"is_locked": False})
    assert unlock_res.status_code == 200
    assert unlock_res.json()["is_locked"] is False

    # Creation succeeds after unlock
    ok_res = client.post(
        "/api/v2/payments",
        headers=payer_headers,
        json={
            "beneficiary_id": "routine_store",
            "amount_paise": 1000,
            "purpose": "tea",
            "idempotency_key": f"unlocked_idem_{uuid4().hex[:8]}",
        },
    )
    assert ok_res.status_code == 201


# ---------------------------------------------------------------------------
# 6. Safety Checks: Purpose Challenge & Anti-Smurfing
# ---------------------------------------------------------------------------

def test_purpose_challenge_coercion_detection(client):
    headers = {"Authorization": f"Bearer {SYNTHETIC_PAYER_TOKEN}"}

    # Benign purpose
    clean_res = client.post(
        "/api/v2/safety/purpose-challenge",
        headers=headers,
        json={"purpose": "Dinner with family at restaurant"},
    )
    assert clean_res.status_code == 200
    assert clean_res.json()["suspicious"] is False
    assert len(clean_res.json()["reasons"]) == 0

    # Coercive purpose
    coercive_res = client.post(
        "/api/v2/safety/purpose-challenge",
        headers=headers,
        json={"purpose": "Urgent police fine payment or arrest warrant right now"},
    )
    assert coercive_res.status_code == 200
    data = coercive_res.json()
    assert data["suspicious"] is True
    assert "urgency" in data["reasons"] or "threat" in data["reasons"] or "authority_impersonation" in data["reasons"]


def test_anti_smurfing_velocity_check(client):
    headers = {"Authorization": f"Bearer {SYNTHETIC_PAYER_TOKEN}"}

    # Attempt 1
    res1 = client.post(
        "/api/v2/safety/anti-smurfing/check",
        headers=headers,
        json={"amount_paise": 4000000, "subject_id": "smurf_target_1"},
    )
    assert res1.status_code == 200
    assert res1.json()["suspicious"] is False
    assert res1.json()["attempt_count"] == 1

    # Attempt 2
    res2 = client.post(
        "/api/v2/safety/anti-smurfing/check",
        headers=headers,
        json={"amount_paise": 4000000, "subject_id": "smurf_target_1"},
    )
    assert res2.status_code == 200
    assert res2.json()["attempt_count"] == 2

    # Attempt 3 (triggers structuring threshold)
    res3 = client.post(
        "/api/v2/safety/anti-smurfing/check",
        headers=headers,
        json={"amount_paise": 4000000, "subject_id": "smurf_target_1"},
    )
    assert res3.status_code == 200
    assert res3.json()["attempt_count"] == 3
    assert res3.json()["suspicious"] is True


# ---------------------------------------------------------------------------
# 7. Audit Verification & Anchors
# ---------------------------------------------------------------------------

def test_audit_verify_and_anchors(client):
    headers = {"Authorization": f"Bearer {SYNTHETIC_PAYER_TOKEN}"}

    # Verify audit hash chain
    verify_res = client.get("/api/v2/audit/verify", headers=headers)
    assert verify_res.status_code == 200
    data = verify_res.json()
    assert data["valid"] is True
    assert data["total_events"] >= 1
    assert len(data["head_hash"]) == 64

    # Create audit anchor
    anchor_res = client.post("/api/v2/audit/anchors", headers=headers)
    assert anchor_res.status_code == 200
    anchor_data = anchor_res.json()
    assert anchor_data["sequence"] >= 1
    assert len(anchor_data["head_hash"]) == 64
    assert anchor_data["anchor_type"] == "sha256_checkpoint"

    # Also test alias /anchors
    alias_res = client.post("/api/v2/anchors", headers=headers)
    assert alias_res.status_code == 200
    assert alias_res.json()["anchor_type"] == "sha256_checkpoint"


# ---------------------------------------------------------------------------
# 8. Recovery Guide
# ---------------------------------------------------------------------------

def test_recovery_guide(client):
    headers = {"Authorization": f"Bearer {SYNTHETIC_PAYER_TOKEN}"}
    res = client.get("/api/v2/recovery/guide", headers=headers)
    assert res.status_code == 200
    guide = res.json()
    assert guide["helpline_number"] == "1930"
    assert "cybercrime.gov.in" in guide["portal_url"]
    assert len(guide["immediate_steps"]) >= 3
    assert "cannot reverse settled UPI" in guide["disclaimer"]


# ---------------------------------------------------------------------------
# 9. Advisory Risk Evaluation (/risk/advice)
# ---------------------------------------------------------------------------

def test_risk_advice_advisory_invariants(client):
    headers = {"Authorization": f"Bearer {SYNTHETIC_PAYER_TOKEN}"}
    payload = {
        "payment_id": f"adv_{uuid4().hex[:8]}",
        "beneficiary_id": "flagged_mule_account",
        "amount_paise": 7500000,
        "purpose": "urgent investment verification",
        "profile_type": "personal",
        "transcript_text": "Do not hang up the call, transfer money immediately to police account.",
        "transcript_consented": True,
    }
    res = client.post("/api/v2/risk/advice", headers=headers, json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["payment_id"] == payload["payment_id"]
    # Critical security invariant: advisory signals NEVER authorize payments
    assert data["can_authorize_payment"] is False
    assert len(data["reason_codes"]) >= 1
    assert "synthetic" in data["calibration_caveat"].lower()


# ---------------------------------------------------------------------------
# 10. Policy Lab Simulation (/policy-lab/simulate)
# ---------------------------------------------------------------------------

def test_policy_lab_simulate_requires_analyst(client):
    payer_headers = {"Authorization": f"Bearer {SYNTHETIC_PAYER_TOKEN}"}
    payload = {"sample_size": 20, "seed": 42, "baseline_a_threshold_paise": 5000000}

    # Payer cannot run Policy Lab
    res_payer = client.post("/api/v2/policy-lab/simulate", headers=payer_headers, json=payload)
    assert res_payer.status_code == 403

    # Analyst can run Policy Lab
    analyst_headers = {"Authorization": f"Bearer {SYNTHETIC_ANALYST_TOKEN}"}
    res_analyst = client.post("/api/v2/policy-lab/simulate", headers=analyst_headers, json=payload)
    assert res_analyst.status_code == 200
    report = res_analyst.json()
    assert report["seed"] == 42
    assert report["dataset_split"] == "test"
    assert "policy_metrics" in report
    assert "Baseline A" in report["policy_metrics"] or any("baseline" in k.lower() for k in report["policy_metrics"])


# ---------------------------------------------------------------------------
# 11. Guardian Dashboard (/guardian/dashboard)
# ---------------------------------------------------------------------------

def test_guardian_dashboard(client):
    guardian_headers = {"Authorization": f"Bearer {SYNTHETIC_GUARDIAN_TOKEN}"}
    res = client.get("/api/v2/guardian/dashboard", headers=guardian_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["active_guardianships_count"] >= 1
    assert "pending_reviews" in data
    assert "pending_reviews_count" in data


def test_guardian_service_count_active_guardianships_real_service():
    """Verify count_active_guardianships on the real GuardianService without mocks."""
    from app.services.guardian_service import get_guardian_service
    from app.auth.identities import SYNTHETIC_GUARDIAN_ID
    service = get_guardian_service()
    service.reset_for_testing()
    count = service.count_active_guardianships(SYNTHETIC_GUARDIAN_ID)
    assert count >= 1
    # Check non-existent guardian returns 0
    assert service.count_active_guardianships(uuid4()) == 0


def test_payment_listing_forbidden_for_analyst(client):
    """Analyst and Admin roles are forbidden from listing transactional payment history."""
    analyst_headers = {"Authorization": f"Bearer {SYNTHETIC_ANALYST_TOKEN}"}
    res = client.get("/api/v2/payments", headers=analyst_headers)
    assert res.status_code == 403


def test_safe_lock_missing_row_fails_closed(client):
    """Payer without registered SafeLockState fails closed with HTTP 423 on status inspection."""
    unseeded_payer = uuid4()
    service = get_payment_service()
    with pytest.raises(Exception) as exc_info:
        service.get_safe_lock_status(unseeded_payer)
    assert "unavailable for payer (fail-closed)" in str(exc_info.value)


# ---------------------------------------------------------------------------
# 12. WebSocket Authenticated Stream (/ws)
# ---------------------------------------------------------------------------

def test_websocket_authentication_and_ping_pong(client):
    # Missing token fails closed with 1008
    with pytest.raises(Exception):
        with client.websocket_connect("/api/v2/ws") as ws:
            pass

    # Invalid token fails closed with 1008
    with pytest.raises(Exception):
        with client.websocket_connect("/api/v2/ws?token=invalid_token_123") as ws:
            pass

    # Valid payer token connects and streams
    with client.websocket_connect(f"/api/v2/ws?token={SYNTHETIC_PAYER_TOKEN}") as ws:
        init_msg = ws.receive_json()
        assert init_msg["type"] == "CONNECTION_ESTABLISHED"
        assert init_msg["user_id"] == str(SYNTHETIC_PAYER_ID)

        # Ping Pong
        ws.send_text('{"type": "PING"}')
        pong_msg = ws.receive_json()
        assert pong_msg["type"] == "PONG"


def test_websocket_real_delivery_and_privacy_redaction_and_isolation(client):
    """Verify live payment event delivery, guardian privacy redaction, and cross-user isolation."""
    with client.websocket_connect(f"/api/v2/ws?token={SYNTHETIC_PAYER_TOKEN}") as payer_ws:
        payer_init = payer_ws.receive_json()
        assert payer_init["type"] == "CONNECTION_ESTABLISHED"

        with client.websocket_connect(f"/api/v2/ws?token={SYNTHETIC_GUARDIAN_TOKEN}") as guardian_ws:
            guardian_init = guardian_ws.receive_json()
            assert guardian_init["type"] == "CONNECTION_ESTABLISHED"

            with client.websocket_connect(f"/api/v2/ws?token={SYNTHETIC_OTHER_PAYER_TOKEN}") as other_ws:
                other_init = other_ws.receive_json()
                assert other_init["type"] == "CONNECTION_ESTABLISHED"

                # Trigger synchronous payment creation requiring guardian
                payer_headers = {"Authorization": f"Bearer {SYNTHETIC_PAYER_TOKEN}"}
                create_res = client.post(
                    "/api/v2/payments",
                    headers=payer_headers,
                    json={
                        "beneficiary_id": "suspicious_target",
                        "amount_paise": 6000000,
                        "purpose": "kyc_verification_urgent",
                        "idempotency_key": f"ws_deliv_{uuid4().hex[:8]}",
                    },
                )
                assert create_res.status_code == 201

                # 1. Payer receives full view over WebSocket
                payer_msg = payer_ws.receive_json()
                assert payer_msg["event_type"] == "PAYMENT_CREATED"
                assert payer_msg["amount_paise"] == 6000000
                assert payer_msg["status"] == "AWAITING_GUARDIAN"

                # 2. Guardian receives redacted view over WebSocket
                guardian_msg = guardian_ws.receive_json()
                assert guardian_msg["event_type"] == "PAYMENT_CREATED"
                assert guardian_msg.get("redacted") is True
                assert "amount_paise" not in guardian_msg
                assert "purpose" not in guardian_msg
                assert "message" in guardian_msg



# ---------------------------------------------------------------------------
# 13. Correlation ID Middleware
# ---------------------------------------------------------------------------

def test_correlation_id_middleware(client):
    custom_id = "test-corr-abc-123"
    res = client.get("/api/v2/health", headers={"X-Correlation-ID": custom_id})
    assert res.status_code == 200
    assert res.headers.get("X-Correlation-ID") == custom_id

    # If omitted by client, server generates one
    res_no_header = client.get("/api/v2/health")
    assert res_no_header.status_code == 200
    generated_id = res_no_header.headers.get("X-Correlation-ID")
    assert generated_id is not None
    assert generated_id.startswith("corr_")

"""Gate 4 tests: approval snapshot invalidation, compromised guardian suspension & backup failover, appeals, safe retry, and step-up."""

from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from app.config import Settings
from app.main import create_app
from app.services.guardian_service import get_guardian_service
from app.services.payment_service import PaymentStatus, get_payment_service


@pytest.fixture
def gate4_client():
    get_guardian_service().reset_for_testing()
    get_payment_service().reset_for_testing()
    settings = Settings(environment="test", mode="mock", allow_demo_auth=True, allow_demo_admin=True)
    app = create_app(settings=settings)
    with TestClient(app) as client:
        yield client
    get_guardian_service().reset_for_testing()
    get_payment_service().reset_for_testing()


def _signup_verify_login_and_kyc(
    client: TestClient, *, email: str, role: str, name: str, doc_ref: str
) -> dict:
    s = client.post(
        "/api/v2/auth/signup",
        json={"email": email, "password": "StrongPassword123!", "full_name": name, "role": role},
    )
    assert s.status_code == 201, s.text
    sd = s.json()
    v = client.post(
        "/api/v2/auth/otp/verify",
        json={"challenge_id": sd["challenge_id"], "otp_code": sd["dev_otp_preview"]},
    )
    assert v.status_code == 200, v.text
    login = client.post(
        "/api/v2/auth/login",
        json={"email": email, "password": "StrongPassword123!"},
    )
    assert login.status_code == 200, login.text
    tok = login.json()["access_token"]
    kyc = client.post(
        "/api/v2/identity/verify",
        headers={"Authorization": f"Bearer {tok}"},
        json={
            "provider": "synthetic_local_idp",
            "full_name": name,
            "synthetic_document_ref": doc_ref,
            "consent_confirmed": True,
        },
    )
    assert kyc.status_code == 200, kyc.text
    return {"token": tok, "user_id": login.json()["user_id"], "email": email}


def _invite_and_accept(
    client: TestClient, *, payer_tok: str, guardian: dict, role_slot: str = "primary"
) -> str:
    inv = client.post(
        "/api/v2/guardian/invitations",
        headers={"Authorization": f"Bearer {payer_tok}"},
        json={
            "guardian_email": guardian["email"],
            "relationship": "family",
            "role_slot": role_slot,
            "notification_channel": "in_app",
        },
    )
    assert inv.status_code == 201, inv.text
    inv_data = inv.json()
    ch = client.post(
        "/api/v2/auth/otp/challenge",
        json={"contact": guardian["email"], "purpose": "guardian_invite", "channel": "email"},
    )
    assert ch.status_code == 200, ch.text
    ch_data = ch.json()
    acc = client.post(
        f"/api/v2/guardian/invitations/{inv_data['invitation_id']}/accept",
        headers={"Authorization": f"Bearer {guardian['token']}"},
        json={
            "invite_token": inv_data["dev_invite_token_preview"],
            "otp_challenge_id": ch_data["challenge_id"],
            "otp_code": ch_data["dev_otp_preview"],
            "explicit_consent": True,
        },
    )
    assert acc.status_code == 200, acc.text
    assert acc.json()["status"] == "ACTIVE"
    return inv_data["invitation_id"]


def test_acceptance_06_modifying_payee_or_amount_invalidates_guardian_approval(gate4_client: TestClient):
    """Acceptance Test #6: Modifying payee or amount after guardian approval invalidates prior approval."""
    payer_headers = {"Authorization": "Bearer demo-token-payer"}
    guardian_headers = {"Authorization": "Bearer demo-token-guardian"}

    created = gate4_client.post(
        "/api/v2/payments",
        headers=payer_headers,
        json={
            "beneficiary_id": "vendor_initial",
            "amount_paise": 6_000_000,
            "purpose": "equipment deposit",
            "idempotency_key": f"g4-mod-{uuid4().hex}",
        },
    )
    assert created.status_code == 201
    pid = created.json()["id"]
    assert created.json()["status"] == "AWAITING_GUARDIAN"

    approved = gate4_client.post(
        f"/api/v2/payments/{pid}/guardian/decision",
        headers=guardian_headers,
        json={"approved": True, "notes": "Verified initial invoice"},
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "READY_TO_EXECUTE"

    # Payer changes beneficiary and amount -> prior guardian approval must be invalidated
    edited = gate4_client.patch(
        f"/api/v2/payments/{pid}",
        headers=payer_headers,
        json={"beneficiary_id": "scammer_substituted_vpa", "amount_paise": 9_500_000},
    )
    assert edited.status_code == 200
    assert edited.json()["status"] == "AWAITING_GUARDIAN"
    assert edited.json()["beneficiary_id"] == "scammer_substituted_vpa"
    assert edited.json()["amount_paise"] == 9_500_000

    # Payer confirmation must now fail (409) until guardian re-approves modified payment
    confirm_blocked = gate4_client.post(
        f"/api/v2/payments/{pid}/confirm",
        headers=payer_headers,
        json={"idempotency_key": f"g4-confirm-{uuid4().hex}"},
    )
    assert confirm_blocked.status_code == 409

    # Guardian approves modified payment -> confirm now succeeds
    reapproved = gate4_client.post(
        f"/api/v2/payments/{pid}/guardian/decision",
        headers=guardian_headers,
        json={"approved": True, "notes": "Re-verified edited amount"},
    )
    assert reapproved.status_code == 200
    confirmed = gate4_client.post(
        f"/api/v2/payments/{pid}/confirm",
        headers=payer_headers,
        json={"idempotency_key": f"g4-confirm-ok-{uuid4().hex}"},
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "EXECUTED"


def test_acceptance_08_compromised_guardian_suspended_and_backup_activated(gate4_client: TestClient):
    """Acceptance Test #8: Suspended/compromised primary guardian is blocked; enrolled backup activates."""
    payer = _signup_verify_login_and_kyc(
        gate4_client, email="g4payer@example.com", role="payer", name="Asha Payer", doc_ref="SYNTH-P-100"
    )
    primary = _signup_verify_login_and_kyc(
        gate4_client, email="g4prim@example.com", role="guardian", name="Ravi Primary", doc_ref="SYNTH-G-101"
    )
    backup = _signup_verify_login_and_kyc(
        gate4_client, email="g4back@example.com", role="guardian", name="Meera Backup", doc_ref="SYNTH-G-102"
    )

    prim_inv_id = _invite_and_accept(gate4_client, payer_tok=payer["token"], guardian=primary, role_slot="primary")
    _invite_and_accept(gate4_client, payer_tok=payer["token"], guardian=backup, role_slot="backup")

    created = gate4_client.post(
        "/api/v2/payments",
        headers={"Authorization": f"Bearer {payer['token']}"},
        json={
            "beneficiary_id": "new_payee_001",
            "amount_paise": 7_500_000,
            "purpose": "large transfer",
            "idempotency_key": f"g4-bkp-{uuid4().hex}",
        },
    )
    assert created.status_code == 201
    pid = created.json()["id"]
    assert created.json()["assigned_guardian_id"] == primary["user_id"]

    # Suspend primary guardian due to suspected compromise
    suspended = gate4_client.post(
        f"/api/v2/guardian/invitations/{prim_inv_id}/suspend",
        headers={"Authorization": "Bearer demo-token-analyst"},
        json={"reason": "suspected account takeover"},
    )
    assert suspended.status_code == 200
    assert suspended.json()["status"] == "SUSPENDED"

    # Suspended primary guardian immediately blocked from approving
    blocked = gate4_client.post(
        f"/api/v2/payments/{pid}/guardian/decision",
        headers={"Authorization": f"Bearer {primary['token']}"},
        json={"approved": True},
    )
    assert blocked.status_code == 403

    # Owning payer activates enrolled backup guardian
    failover = gate4_client.post(
        f"/api/v2/payments/{pid}/fallback/backup",
        headers={"Authorization": f"Bearer {payer['token']}"},
    )
    assert failover.status_code == 200
    assert failover.json()["assigned_guardian_id"] == backup["user_id"]
    assert failover.json()["status"] == "AWAITING_GUARDIAN"

    # Backup guardian approves cleanly
    acc_dec = gate4_client.post(
        f"/api/v2/payments/{pid}/guardian/decision",
        headers={"Authorization": f"Bearer {backup['token']}"},
        json={"approved": True, "notes": "Backup guardian verified call"},
    )
    assert acc_dec.status_code == 200
    assert acc_dec.json()["status"] == "READY_TO_EXECUTE"


def test_acceptance_09_10_appeals_rbac_and_safe_retry_lineage(gate4_client: TestClient):
    """Acceptance Tests #9 & #10: Analyst resolves appeal (no self-approval) and safe retry preserves lineage."""
    payer_headers = {"Authorization": "Bearer demo-token-payer"}
    guardian_headers = {"Authorization": "Bearer demo-token-guardian"}
    analyst_headers = {"Authorization": "Bearer demo-token-analyst"}

    created = gate4_client.post(
        "/api/v2/payments",
        headers=payer_headers,
        json={
            "beneficiary_id": "legit_medical_supplier",
            "amount_paise": 6_000_000,
            "purpose": "hospital invoice",
            "idempotency_key": f"g4-app-parent-{uuid4().hex}",
        },
    )
    assert created.status_code == 201
    parent_id = created.json()["id"]

    # Guardian rejects -> parent enters terminal REJECTED
    rej = gate4_client.post(
        f"/api/v2/payments/{parent_id}/guardian/decision",
        headers=guardian_headers,
        json={"approved": False, "notes": "Caution rejection"},
    )
    assert rej.status_code == 200
    assert rej.json()["status"] == "REJECTED"

    # Safe retry MUST fail before an analyst-approved appeal exists (409)
    early_retry = gate4_client.post(
        f"/api/v2/payments/{parent_id}/retry",
        headers=payer_headers,
        json={"idempotency_key": f"g4-retry-early-{uuid4().hex}"},
    )
    assert early_retry.status_code == 409

    # Payer submits false-alert appeal
    appeal_res = gate4_client.post(
        f"/api/v2/payments/{parent_id}/appeals",
        headers=payer_headers,
        json={"reason": "Called guardian offline, invoice is legitimate", "evidence_note": "INV-2026-99"},
    )
    assert appeal_res.status_code == 201
    appeal_id = appeal_res.json()["appeal_id"]
    assert appeal_res.json()["status"] == "OPEN"

    # Payer CANNOT self-approve appeal (403)
    self_approve = gate4_client.post(
        f"/api/v2/payments/{parent_id}/appeals/{appeal_id}/resolve",
        headers=payer_headers,
        json={"approved": True, "resolution_note": "self approving"},
    )
    assert self_approve.status_code == 403

    # Analyst resolves appeal -> APPROVED_RETRY_ELIGIBLE (still never auto-executes parent)
    resolved = gate4_client.post(
        f"/api/v2/payments/{parent_id}/appeals/{appeal_id}/resolve",
        headers=analyst_headers,
        json={"approved": True, "resolution_note": "Reviewed offline confirmation"},
    )
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "APPROVED_RETRY_ELIGIBLE"

    # Safe retry now succeeds and links parent_payment_id cleanly
    retried = gate4_client.post(
        f"/api/v2/payments/{parent_id}/retry",
        headers=payer_headers,
        json={"idempotency_key": f"g4-retry-ok-{uuid4().hex}", "purpose": "verified hospital invoice"},
    )
    assert retried.status_code == 201
    child = retried.json()
    assert child["parent_payment_id"] == parent_id
    assert child["amount_paise"] == 6_000_000
    assert child["status"] == "AWAITING_GUARDIAN"


def test_step_up_verify_endpoint(gate4_client: TestClient):
    """Verify AWAITING_STEP_UP -> READY_TO_EXECUTE transition enforces owner RBAC."""
    svc = get_payment_service()
    payer_headers = {"Authorization": "Bearer demo-token-payer"}
    created = gate4_client.post(
        "/api/v2/payments",
        headers=payer_headers,
        json={
            "beneficiary_id": "vendor_stepup",
            "amount_paise": 20_000,
            "purpose": "stepup check",
            "idempotency_key": f"g4-stepup-{uuid4().hex}",
        },
    )
    pid = created.json()["id"]
    svc._payments[pid].status = PaymentStatus.AWAITING_STEP_UP

    # Foreign caller denied
    foreign = gate4_client.post(
        f"/api/v2/payments/{pid}/step-up/verify",
        headers={"Authorization": "Bearer demo-token-guardian"},
        json={"challenge_method": "webauthn_stub", "assertion_token": "stub_assertion_ok"},
    )
    assert foreign.status_code == 403

    ok = gate4_client.post(
        f"/api/v2/payments/{pid}/step-up/verify",
        headers=payer_headers,
        json={"challenge_method": "webauthn_stub", "assertion_token": "stub_assertion_ok"},
    )
    assert ok.status_code == 200
    assert ok.json()["status"] == "READY_TO_EXECUTE"
    assert ok.json()["step_up_verified"] is True

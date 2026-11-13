"""Gate 6 tests: Mock Bank Pre-Execution Adapter, HMAC Webhook Verification & Razorpay Parity."""

import json
from types import SimpleNamespace
from fastapi.testclient import TestClient
import pytest

from app.auth.identities import (
    SYNTHETIC_ADMIN_TOKEN,
    SYNTHETIC_GUARDIAN_TOKEN,
    SYNTHETIC_PAYER_ID,
    SYNTHETIC_PAYER_TOKEN,
)
from app.config import Settings
from app.integrations.bank_adapter import (
    BankAdapterError,
    MockBankRailAdapter,
    RealBankRailStubAdapter,
    compute_bank_webhook_hmac,
    resolve_mock_bank_webhook_secret,
)
from app.integrations.razorpay_sandbox import RazorpaySandboxError, load_sandbox_config
from app.main import create_app
from app.services.guardian_service import get_guardian_service
from app.services.payment_service import get_payment_service


@pytest.fixture
def gate6_client():
    get_guardian_service().reset_for_testing()
    get_payment_service().reset_for_testing()
    app = create_app(
        Settings(
            environment="local",
            mode="mock",
            allow_demo_auth=True,
            allow_demo_admin=True,
        )
    )
    with TestClient(app) as client:
        yield client
    get_guardian_service().reset_for_testing()
    get_payment_service().reset_for_testing()


def test_acceptance_16_mock_bank_preexecution_hmac_webhook_and_replay_protection(gate6_client):
    """Acceptance #16: Bank intents & HMAC settlement webhooks never bypass PauseGuard state machine."""
    # 1. Fail-closed outside local mock mode
    prod = SimpleNamespace(environment="production", mode="real")
    with pytest.raises(BankAdapterError, match="disabled"):
        MockBankRailAdapter().create_intent(
            payment_id="pg_blocked",
            payer_id=SYNTHETIC_PAYER_ID,
            amount_paise=10000,
            rail="MOCK_UPI_NPCI",
            settings=prod,
        )
    with pytest.raises(BankAdapterError):
        RealBankRailStubAdapter().create_intent(payment_id="pg_x")

    # 2. Create high-risk payment (AWAITING_GUARDIAN)
    pay_res = gate6_client.post(
        "/api/v2/payments",
        headers={"Authorization": f"Bearer {SYNTHETIC_PAYER_TOKEN}"},
        json={
            "idempotency_key": "gate6-bank-intent-001",
            "beneficiary_id": "beneficiary_new_bank_acc",
            "amount_paise": 6000000,
            "purpose": "Urgent KYC refund compliance transfer",
        },
    )
    assert pay_res.status_code == 201
    payment_id = pay_res.json()["id"]
    assert pay_res.json()["status"] == "AWAITING_GUARDIAN"

    # Guardian cannot create bank intents (403)
    g_forbidden = gate6_client.post(
        "/api/v2/bank/intents",
        headers={"Authorization": f"Bearer {SYNTHETIC_GUARDIAN_TOKEN}"},
        json={"payment_id": payment_id, "rail": "MOCK_UPI_NPCI"},
    )
    assert g_forbidden.status_code == 403

    # Payer creates pre-execution bank intent (idempotent)
    i_res = gate6_client.post(
        "/api/v2/bank/intents",
        headers={"Authorization": f"Bearer {SYNTHETIC_PAYER_TOKEN}"},
        json={"payment_id": payment_id, "rail": "MOCK_UPI_NPCI"},
    )
    assert i_res.status_code == 201, i_res.text
    intent_id = i_res.json()["intent_id"]
    assert i_res.json()["settlement_status"] == "HOLD_PENDING"
    assert i_res.json()["is_mock"] is True

    # Missing or invalid HMAC webhook signature fails closed (400 / 401)
    webhook_body = json.dumps({
        "event_id": "bnk_evt_001",
        "intent_id": intent_id,
        "settlement_status": "SETTLED",
    }).encode("utf-8")
    no_sig = gate6_client.post(
        "/api/v2/bank/webhooks/settlement",
        content=webhook_body,
        headers={"Content-Type": "application/json"},
    )
    assert no_sig.status_code == 400

    bad_sig = gate6_client.post(
        "/api/v2/bank/webhooks/settlement",
        content=webhook_body,
        headers={
            "Content-Type": "application/json",
            "X-PauseGuard-Bank-Signature": "0" * 64,
        },
    )
    assert bad_sig.status_code == 401

    # Valid HMAC SETTLED webhook before EXECUTED MUST FAIL (409)
    secret = resolve_mock_bank_webhook_secret()
    valid_sig = compute_bank_webhook_hmac(webhook_body, secret)
    premature = gate6_client.post(
        "/api/v2/bank/webhooks/settlement",
        content=webhook_body,
        headers={
            "Content-Type": "application/json",
            "X-PauseGuard-Bank-Signature": valid_sig,
        },
    )
    assert premature.status_code == 409

    # 3. Guardian approval + payer confirm -> EXECUTED
    assert gate6_client.post(
        f"/api/v2/payments/{payment_id}/guardian/decision",
        headers={"Authorization": f"Bearer {SYNTHETIC_GUARDIAN_TOKEN}"},
        json={"approved": True},
    ).status_code == 200
    assert gate6_client.post(
        f"/api/v2/payments/{payment_id}/confirm",
        headers={"Authorization": f"Bearer {SYNTHETIC_PAYER_TOKEN}"},
        json={"idempotency_key": "gate6-confirm-001"},
    ).status_code == 200

    # Now valid HMAC SETTLED webhook succeeds + replay returns duplicate=True
    settled = gate6_client.post(
        "/api/v2/bank/webhooks/settlement",
        content=webhook_body,
        headers={
            "Content-Type": "application/json",
            "X-PauseGuard-Bank-Signature": valid_sig,
        },
    )
    assert settled.status_code == 200, settled.text
    assert settled.json()["accepted"] is True
    assert settled.json()["duplicate"] is False
    assert settled.json()["settlement_status"] == "SETTLED"

    replay = gate6_client.post(
        "/api/v2/bank/webhooks/settlement",
        content=webhook_body,
        headers={
            "Content-Type": "application/json",
            "X-PauseGuard-Bank-Signature": valid_sig,
        },
    )
    assert replay.status_code == 200
    assert replay.json()["duplicate"] is True


def test_acceptance_17_razorpay_test_mode_isolation_and_live_key_rejection(gate6_client):
    """Acceptance #17: Razorpay enforces admin-only RBAC and rejects rzp_live_* keys."""
    with pytest.raises(RazorpaySandboxError, match="Test Mode"):
        load_sandbox_config({
            "PAUSEGUARD_RAZORPAY_TEST_ENABLED": "true",
            "RZP_TEST_KEY_ID": "rzp_live_1234567890",
            "RZP_TEST_KEY_SECRET": "secret_value",
        })

    # Payer cannot access admin-only Razorpay sandbox config
    payer_forbidden = gate6_client.get(
        "/api/v2/sandbox/razorpay/config",
        headers={"Authorization": f"Bearer {SYNTHETIC_PAYER_TOKEN}"},
    )
    assert payer_forbidden.status_code == 403

    # Admin gets explicit disabled state (503) or configured test-mode (200) without secrets
    admin_resp = gate6_client.get(
        "/api/v2/sandbox/razorpay/config",
        headers={"Authorization": f"Bearer {SYNTHETIC_ADMIN_TOKEN}"},
    )
    assert admin_resp.status_code in (200, 503)
    assert "key_secret" not in admin_resp.json()

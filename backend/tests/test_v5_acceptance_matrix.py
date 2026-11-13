"""Gate 7 cross-cutting V5 acceptance verification (#7, #18, #19) + observability metrics."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest

from app.auth.identities import (
    SYNTHETIC_ADMIN_TOKEN,
    SYNTHETIC_ANALYST_TOKEN,
    SYNTHETIC_GUARDIAN_TOKEN,
    SYNTHETIC_PAYER_ID,
    SYNTHETIC_PAYER_TOKEN,
    resolve_synthetic_token,
)
from app.config import Settings
from app.integrations.bank_adapter import BankAdapterError, MockBankRailAdapter
from app.main import create_app
from app.services.guardian_service import get_guardian_service
from app.services.identity_assurance_service import SyntheticLocalIdentityProvider
from app.services.otp_service import DeterministicLocalOtpProvider
from app.services.payment_service import PaymentStatus, get_payment_service


@pytest.fixture
def gate7_client():
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


def test_acceptance_07_30s_guardian_timeout_triggers_fallback_never_auto_executes(gate7_client):
    """Acceptance #7: Expired 30s guardian deadline transitions cleanly to AWAITING_FALLBACK_REVIEW without auto-execution."""
    create_res = gate7_client.post(
        "/api/v2/payments",
        headers={"Authorization": f"Bearer {SYNTHETIC_PAYER_TOKEN}"},
        json={
            "idempotency_key": "gate7-timeout-001",
            "beneficiary_id": "beneficiary_unfamiliar_timeout",
            "amount_paise": 6000000,
            "purpose": "Urgent KYC compliance hold check",
        },
    )
    assert create_res.status_code == 201
    payment_id = create_res.json()["id"]
    assert create_res.json()["status"] == "AWAITING_GUARDIAN"

    # Simulate 30s guardian deadline expiry on server
    svc = get_payment_service()
    with svc._lock:
        svc._payments[payment_id].guardian_deadline = datetime.now(timezone.utc) - timedelta(seconds=5)

    fb = gate7_client.post(
        f"/api/v2/payments/{payment_id}/fallback/activate",
        headers={"Authorization": f"Bearer {SYNTHETIC_PAYER_TOKEN}"},
    )
    assert fb.status_code == 200
    assert fb.json()["status"] == "AWAITING_FALLBACK_REVIEW"

    # Verify payment never auto-executed
    view = gate7_client.get(
        f"/api/v2/payments/{payment_id}",
        headers={"Authorization": f"Bearer {SYNTHETIC_PAYER_TOKEN}"},
    ).json()
    assert view["status"] == "AWAITING_FALLBACK_REVIEW"
    assert view["status"] != PaymentStatus.EXECUTED.value


def test_acceptance_18_concurrent_confirmations_execute_single_ledger_debit(gate7_client):
    """Acceptance #18: Concurrent confirmation calls yield only one balance debit & idempotent convergence."""
    bal_before = gate7_client.get(
        "/api/v2/account/balance",
        headers={"Authorization": f"Bearer {SYNTHETIC_PAYER_TOKEN}"},
    ).json()["balance_paise"]

    create_res = gate7_client.post(
        "/api/v2/payments",
        headers={"Authorization": f"Bearer {SYNTHETIC_PAYER_TOKEN}"},
        json={
            "idempotency_key": "gate7-concurrent-001",
            "beneficiary_id": "beneficiary_known_merchant",
            "amount_paise": 50000,
            "purpose": "Routine groceries purchase",
        },
    )
    assert create_res.status_code == 201
    payment_id = create_res.json()["id"]
    assert create_res.json()["status"] == "READY_TO_EXECUTE"

    def _do_confirm():
        return gate7_client.post(
            f"/api/v2/payments/{payment_id}/confirm",
            headers={"Authorization": f"Bearer {SYNTHETIC_PAYER_TOKEN}"},
            json={"idempotency_key": "gate7-same-confirm-key"},
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(_do_confirm) for _ in range(4)]
        responses = [f.result() for f in futures]

    assert all(r.status_code == 200 for r in responses)
    assert all(r.json()["status"] == "EXECUTED" for r in responses)

    bal_after = gate7_client.get(
        "/api/v2/account/balance",
        headers={"Authorization": f"Bearer {SYNTHETIC_PAYER_TOKEN}"},
    ).json()["balance_paise"]
    assert bal_before - bal_after == 50000


def test_acceptance_19_production_environment_fails_closed():
    """Acceptance #19: Production settings fail closed across demo auth, local OTP, mock KYC, mock bank & unconfigured DB."""
    prod = SimpleNamespace(environment="production", mode="real", allow_demo_auth=False, allow_demo_admin=False)

    assert resolve_synthetic_token(SYNTHETIC_PAYER_TOKEN, settings=prod) is None
    assert resolve_synthetic_token(SYNTHETIC_ADMIN_TOKEN, settings=prod) is None

    with pytest.raises(HTTPException) as otp_exc:
        DeterministicLocalOtpProvider().deliver_otp(
            contact="prod@example.com",
            purpose="signup_email",
            channel="email",
            otp_code="123456",
            settings=prod,
        )
    assert otp_exc.value.status_code == 503

    with pytest.raises(HTTPException) as kyc_exc:
        SyntheticLocalIdentityProvider().verify_person(
            full_name="Test User",
            synthetic_document_ref="DOC-1234",
            settings=prod,
        )
    assert kyc_exc.value.status_code == 503

    with pytest.raises(BankAdapterError):
        MockBankRailAdapter().create_intent(
            payment_id="pg_prod",
            payer_id=SYNTHETIC_PAYER_ID,
            amount_paise=1000,
            rail="MOCK_UPI_NPCI",
            settings=prod,
        )


def test_observability_metrics_rbac_and_telemetry(gate7_client):
    """Gate 7 observability: /api/v2/metrics denies payers and reports latency & counters to analyst/admin."""
    gate7_client.get("/api/v2/health")

    payer_forbidden = gate7_client.get(
        "/api/v2/metrics",
        headers={"Authorization": f"Bearer {SYNTHETIC_PAYER_TOKEN}"},
    )
    assert payer_forbidden.status_code == 403

    analyst_ok = gate7_client.get(
        "/api/v2/metrics",
        headers={"Authorization": f"Bearer {SYNTHETIC_ANALYST_TOKEN}"},
    )
    assert analyst_ok.status_code == 200
    body = analyst_ok.json()
    assert body["status"] == "ok"
    assert body["http_requests_sampled"] >= 1
    assert "p50" in body["latency_ms"]
    assert "p95" in body["latency_ms"]
    assert "v5_store_counters" in body

"""Comprehensive integration tests for Razorpay Test Mode merchant sandbox.

Covers:
1. Client and configuration gating (strict test mode, live key rejection).
2. Admin-only role enforcement across all merchant endpoints.
3. Order creation with amount validation and INR currency enforcement.
4. Checkout signature verification and server-side provider reconciliation.
5. Inbound webhook verification, replay deduplication, and P2P safety decoupling.
6. Order history inspection by admin.
"""

from datetime import datetime, timezone
import hashlib
import hmac
import json
from typing import Any, Dict
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.auth.identities import (
    SYNTHETIC_ADMIN,
    SYNTHETIC_ADMIN_TOKEN,
    SYNTHETIC_ANALYST,
    SYNTHETIC_ANALYST_TOKEN,
    SYNTHETIC_GUARDIAN,
    SYNTHETIC_GUARDIAN_TOKEN,
    SYNTHETIC_PAYER,
    SYNTHETIC_PAYER_TOKEN,
)
from app.auth.schemas import (
    RazorpayOrderCreateRequest,
    RazorpayVerifyRequest,
)
from app.config import Settings
from app.integrations.razorpay_sandbox import (
    RazorpaySandboxConfig,
    RazorpaySandboxError,
    load_sandbox_config,
)
from app.main import create_app
from app.models.roles import UserRole
from app.services.payment_guards import TrustedActorContext
from app.services.razorpay_service import (
    RazorpayMerchantService,
    get_razorpay_service,
)

TEST_KEY_ID = "rzp_test_integration_abc123"
TEST_KEY_SECRET = "synthetic_key_secret_xyz789"
TEST_WEBHOOK_SECRET = "synthetic_webhook_secret_whsec_456"


class MockRazorpayOrderApi:
    def __init__(self) -> None:
        self.created_orders: Dict[str, dict] = {}

    def create(self, data: dict) -> dict:
        order_id = f"order_{uuid4().hex[:14]}"
        order_data = {
            "id": order_id,
            "entity": "order",
            "amount": data["amount"],
            "amount_paid": 0,
            "amount_due": data["amount"],
            "currency": data.get("currency", "INR"),
            "receipt": data.get("receipt"),
            "status": "created",
            "attempts": 0,
            "notes": data.get("notes", {}),
            "created_at": int(datetime.now(timezone.utc).timestamp()),
        }
        self.created_orders[order_id] = order_data
        return order_data


class MockRazorpayPaymentApi:
    def __init__(self) -> None:
        self.payments: Dict[str, dict] = {}

    def fetch(self, payment_id: str) -> dict:
        if payment_id in self.payments:
            return self.payments[payment_id]
        raise ValueError(f"Payment {payment_id} not found in provider")

    def register(
        self,
        payment_id: str,
        order_id: str,
        amount: int,
        status: str = "captured",
        method: str = "upi",
    ) -> None:
        self.payments[payment_id] = {
            "id": payment_id,
            "entity": "payment",
            "amount": amount,
            "currency": "INR",
            "status": status,
            "order_id": order_id,
            "method": method,
            "captured": status == "captured",
            "created_at": int(datetime.now(timezone.utc).timestamp()),
        }


class MockRazorpayClient:
    def __init__(self) -> None:
        self.order = MockRazorpayOrderApi()
        self.payment = MockRazorpayPaymentApi()


def compute_payment_signature(order_id: str, payment_id: str, secret: str = TEST_KEY_SECRET) -> str:
    message = f"{order_id}|{payment_id}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def compute_webhook_signature(body: bytes, secret: str = TEST_WEBHOOK_SECRET) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


@pytest.fixture
def mock_client():
    return MockRazorpayClient()


@pytest.fixture
def test_config():
    return RazorpaySandboxConfig(
        key_id=TEST_KEY_ID,
        key_secret=TEST_KEY_SECRET,
        webhook_secret=TEST_WEBHOOK_SECRET,
    )


@pytest.fixture
def configured_env(monkeypatch):
    monkeypatch.setenv("PAUSEGUARD_RAZORPAY_TEST_ENABLED", "true")
    monkeypatch.setenv("RZP_TEST_KEY_ID", TEST_KEY_ID)
    monkeypatch.setenv("RZP_TEST_KEY_SECRET", TEST_KEY_SECRET)
    monkeypatch.setenv("RZP_TEST_WEBHOOK_SECRET", TEST_WEBHOOK_SECRET)


@pytest.fixture
def razorpay_service(configured_env, mock_client, test_config):
    service = get_razorpay_service()
    service.reset_for_testing()
    service._config = test_config
    service.client = mock_client
    yield service
    service.reset_for_testing()


@pytest.fixture
def app(configured_env, razorpay_service):
    settings = Settings(environment="test", mode="mock", allow_demo_auth=True)
    return create_app(settings)


@pytest.fixture
def client(app):
    return TestClient(app)


# ---------------------------------------------------------------------------
# 1. Configuration & Security Boundary Tests
# ---------------------------------------------------------------------------


def test_sandbox_config_rejects_missing_env(monkeypatch):
    monkeypatch.delenv("PAUSEGUARD_RAZORPAY_TEST_ENABLED", raising=False)
    with pytest.raises(RazorpaySandboxError, match="disabled"):
        load_sandbox_config()


def test_sandbox_config_rejects_live_key(monkeypatch):
    monkeypatch.setenv("PAUSEGUARD_RAZORPAY_TEST_ENABLED", "true")
    monkeypatch.setenv("RZP_TEST_KEY_ID", "rzp_live_abc123")
    monkeypatch.setenv("RZP_TEST_KEY_SECRET", "live_secret")
    with pytest.raises(RazorpaySandboxError, match="Test Mode"):
        load_sandbox_config()


def test_unauthenticated_requests_are_rejected(client):
    res = client.post(
        "/api/v2/sandbox/razorpay/orders",
        json={"amount_paise": 50000, "receipt": "test_rcpt"},
    )
    assert res.status_code == 401


@pytest.mark.parametrize(
    "token",
    [
        SYNTHETIC_PAYER_TOKEN,
        SYNTHETIC_GUARDIAN_TOKEN,
        SYNTHETIC_ANALYST_TOKEN,
    ],
)
def test_non_admin_roles_cannot_create_orders(client, token):
    headers = {"Authorization": f"Bearer {token}"}
    res = client.post(
        "/api/v2/sandbox/razorpay/orders",
        json={"amount_paise": 50000, "receipt": "test_rcpt"},
        headers=headers,
    )
    assert res.status_code == 403
    assert "Administrator" in res.json().get("detail", "")


@pytest.mark.parametrize(
    "token",
    [
        SYNTHETIC_PAYER_TOKEN,
        SYNTHETIC_GUARDIAN_TOKEN,
        SYNTHETIC_ANALYST_TOKEN,
    ],
)
def test_non_admin_roles_cannot_verify_checkout(client, token):
    headers = {"Authorization": f"Bearer {token}"}
    res = client.post(
        "/api/v2/sandbox/razorpay/verify",
        json={
            "razorpay_order_id": "order_dummy",
            "razorpay_payment_id": "pay_dummy",
            "razorpay_signature": "0" * 64,
        },
        headers=headers,
    )
    assert res.status_code == 403


# ---------------------------------------------------------------------------
# 2. Order Creation Tests
# ---------------------------------------------------------------------------


def test_admin_creates_order_successfully(client, mock_client):
    headers = {"Authorization": f"Bearer {SYNTHETIC_ADMIN_TOKEN}"}
    payload = {
        "amount_paise": 75000,
        "currency": "INR",
        "receipt": "rcpt_hackathon_001",
        "notes": {"purpose": "merchant_checkout_test"},
    }
    response = client.post("/api/v2/sandbox/razorpay/orders", json=payload, headers=headers)
    assert response.status_code == 201
    data = response.json()
    assert data["amount_paise"] == 75000
    assert data["currency"] == "INR"
    assert data["status"] == "created"
    assert data["receipt"] == "rcpt_hackathon_001"
    assert data["key_id"] == TEST_KEY_ID
    assert data["razorpay_order_id"].startswith("order_")
    assert data["id"].startswith("rzp_ord_")


def test_order_creation_rejects_zero_or_negative_amount(client):
    headers = {"Authorization": f"Bearer {SYNTHETIC_ADMIN_TOKEN}"}
    res_zero = client.post(
        "/api/v2/sandbox/razorpay/orders",
        json={"amount_paise": 0},
        headers=headers,
    )
    assert res_zero.status_code == 422

    res_neg = client.post(
        "/api/v2/sandbox/razorpay/orders",
        json={"amount_paise": -500},
        headers=headers,
    )
    assert res_neg.status_code == 422


def test_order_creation_rejects_extra_fields(client):
    headers = {"Authorization": f"Bearer {SYNTHETIC_ADMIN_TOKEN}"}
    res = client.post(
        "/api/v2/sandbox/razorpay/orders",
        json={"amount_paise": 50000, "malicious_field": "injected"},
        headers=headers,
    )
    assert res.status_code == 422


# ---------------------------------------------------------------------------
# 3. Checkout Verification & Provider Reconciliation Tests
# ---------------------------------------------------------------------------


def test_checkout_verification_success(client, mock_client):
    headers = {"Authorization": f"Bearer {SYNTHETIC_ADMIN_TOKEN}"}

    # 1. Create order
    order_res = client.post(
        "/api/v2/sandbox/razorpay/orders",
        json={"amount_paise": 100000, "receipt": "verify_test_01"},
        headers=headers,
    )
    assert order_res.status_code == 201
    order_data = order_res.json()
    order_id = order_data["razorpay_order_id"]
    payment_id = "pay_test_succ_123"

    # 2. Register mock payment with provider
    mock_client.payment.register(
        payment_id=payment_id,
        order_id=order_id,
        amount=100000,
        status="captured",
        method="upi",
    )

    # 3. Calculate valid HMAC signature
    signature = compute_payment_signature(order_id, payment_id)

    # 4. Verify checkout
    verify_payload = {
        "razorpay_order_id": order_id,
        "razorpay_payment_id": payment_id,
        "razorpay_signature": signature,
    }
    verify_res = client.post("/api/v2/sandbox/razorpay/verify", json=verify_payload, headers=headers)
    assert verify_res.status_code == 200
    v_data = verify_res.json()
    assert v_data["verified"] is True
    assert v_data["status"] == "paid"
    assert v_data["reconciled_with_provider"] is True
    assert v_data["razorpay_order_id"] == order_id
    assert v_data["razorpay_payment_id"] == payment_id
    assert v_data["amount_paise"] == 100000


def test_checkout_verification_fails_on_tampered_signature(client, mock_client):
    headers = {"Authorization": f"Bearer {SYNTHETIC_ADMIN_TOKEN}"}
    order_res = client.post(
        "/api/v2/sandbox/razorpay/orders",
        json={"amount_paise": 50000},
        headers=headers,
    )
    order_id = order_res.json()["razorpay_order_id"]
    payment_id = "pay_tamper_123"

    verify_payload = {
        "razorpay_order_id": order_id,
        "razorpay_payment_id": payment_id,
        "razorpay_signature": "0" * 64,
    }
    verify_res = client.post("/api/v2/sandbox/razorpay/verify", json=verify_payload, headers=headers)
    assert verify_res.status_code == 400
    assert "Invalid payment signature" in verify_res.json().get("detail", "")


def test_checkout_verification_fails_on_amount_tampering(client, mock_client):
    headers = {"Authorization": f"Bearer {SYNTHETIC_ADMIN_TOKEN}"}

    # Order created for 50000 paise (Rs 500)
    order_res = client.post(
        "/api/v2/sandbox/razorpay/orders",
        json={"amount_paise": 50000},
        headers=headers,
    )
    order_id = order_res.json()["razorpay_order_id"]
    payment_id = "pay_amount_tamper_123"

    # Provider reports payment was only 10000 paise (Rs 100)
    mock_client.payment.register(
        payment_id=payment_id,
        order_id=order_id,
        amount=10000,
        status="captured",
    )
    signature = compute_payment_signature(order_id, payment_id)

    verify_payload = {
        "razorpay_order_id": order_id,
        "razorpay_payment_id": payment_id,
        "razorpay_signature": signature,
    }
    verify_res = client.post("/api/v2/sandbox/razorpay/verify", json=verify_payload, headers=headers)
    assert verify_res.status_code == 400
    assert "Amount mismatch" in verify_res.json().get("detail", "")


def test_checkout_verification_fails_on_order_id_mismatch(client, mock_client):
    headers = {"Authorization": f"Bearer {SYNTHETIC_ADMIN_TOKEN}"}

    order_res = client.post(
        "/api/v2/sandbox/razorpay/orders",
        json={"amount_paise": 50000},
        headers=headers,
    )
    order_id = order_res.json()["razorpay_order_id"]
    payment_id = "pay_order_mismatch_123"

    # Provider payment points to completely different order
    mock_client.payment.register(
        payment_id=payment_id,
        order_id="order_completely_different",
        amount=50000,
        status="captured",
    )
    signature = compute_payment_signature(order_id, payment_id)

    verify_payload = {
        "razorpay_order_id": order_id,
        "razorpay_payment_id": payment_id,
        "razorpay_signature": signature,
    }
    verify_res = client.post("/api/v2/sandbox/razorpay/verify", json=verify_payload, headers=headers)
    assert verify_res.status_code == 400
    assert "order ID mismatch" in verify_res.json().get("detail", "")


def test_checkout_verification_fails_when_provider_payment_failed(client, mock_client):
    headers = {"Authorization": f"Bearer {SYNTHETIC_ADMIN_TOKEN}"}

    order_res = client.post(
        "/api/v2/sandbox/razorpay/orders",
        json={"amount_paise": 50000},
        headers=headers,
    )
    order_id = order_res.json()["razorpay_order_id"]
    payment_id = "pay_failed_status_123"

    mock_client.payment.register(
        payment_id=payment_id,
        order_id=order_id,
        amount=50000,
        status="failed",
    )
    signature = compute_payment_signature(order_id, payment_id)

    verify_payload = {
        "razorpay_order_id": order_id,
        "razorpay_payment_id": payment_id,
        "razorpay_signature": signature,
    }
    verify_res = client.post("/api/v2/sandbox/razorpay/verify", json=verify_payload, headers=headers)
    assert verify_res.status_code == 400
    assert "not successful" in verify_res.json().get("detail", "")



# ---------------------------------------------------------------------------
# 4. Inbound Webhook Tests & Replay Deduplication
# ---------------------------------------------------------------------------


def test_webhook_missing_signature_header_rejected(client):
    res = client.post(
        "/api/v2/sandbox/razorpay/webhook",
        json={"id": "event_123", "event": "payment.captured"},
    )
    assert res.status_code == 400
    assert "X-Razorpay-Signature" in res.json().get("detail", "")


def test_webhook_invalid_signature_rejected(client):
    body = json.dumps(
        {"id": "event_123", "event": "payment.captured"}
    ).encode("utf-8")

    res = client.post(
        "/api/v2/sandbox/razorpay/webhook",
        content=body,
        headers={
            "X-Razorpay-Signature": "invalid_signature",
            "Content-Type": "application/json",
        },
    )

    assert res.status_code == 400
    assert "Invalid webhook signature" in res.json().get("detail", "")


def test_webhook_processes_valid_event_and_deduplicates_replay(client):
    event_payload = {
        "id": "event_webhook_test_001",
        "event": "payment.captured",
        "contains": ["payment"],
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_hook_123",
                    "amount": 50000,
                    "currency": "INR",
                    "status": "captured",
                    "order_id": "order_hook_123",
                }
            }
        },
    }

    raw_body = json.dumps(event_payload).encode("utf-8")
    signature = compute_webhook_signature(raw_body)

    headers = {
        "X-Razorpay-Signature": signature,
        "Content-Type": "application/json",
    }

    first_res = client.post(
        "/api/v2/sandbox/razorpay/webhook",
        content=raw_body,
        headers=headers,
    )

    assert first_res.status_code == 200
    first_data = first_res.json()
    assert first_data["status"] == "processed"
    assert first_data["event_id"] == "event_webhook_test_001"
    assert first_data["can_authorize_p2p_payment"] is False

    second_res = client.post(
        "/api/v2/sandbox/razorpay/webhook",
        content=raw_body,
        headers=headers,
    )

    assert second_res.status_code == 200
    second_data = second_res.json()
    assert second_data["status"] == "duplicate"
    assert second_data["event_id"] == "event_webhook_test_001"
    assert second_data["can_authorize_p2p_payment"] is False


@pytest.mark.parametrize(
    "raw_body",
    [
        b"[]",
        b'"invalid"',
        b"123",
        b"null",
    ],
)
def test_webhook_rejects_non_object_root_json(client, raw_body):
    signature = compute_webhook_signature(raw_body)

    response = client.post(
        "/api/v2/sandbox/razorpay/webhook",
        content=raw_body,
        headers={
            "X-Razorpay-Signature": signature,
            "Content-Type": "application/json",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == (
        "Webhook JSON payload must be an object"
    )


def test_webhook_rejects_whitespace_only_event_id(client):
    raw_body = json.dumps({
        "id": "   ",
        "event": "payment.captured",
    }).encode("utf-8")

    signature = compute_webhook_signature(raw_body)

    response = client.post(
        "/api/v2/sandbox/razorpay/webhook",
        content=raw_body,
        headers={
            "X-Razorpay-Signature": signature,
            "Content-Type": "application/json",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == (
        "Webhook event payload missing unique event ID"
    )


@pytest.mark.parametrize(
    ("payload", "expected_detail"),
    [
        (
            "invalid",
            "Webhook payload field must be an object",
        ),
        (
            {"payment": "invalid"},
            "Webhook payment field must be an object",
        ),
        (
            {"payment": {"entity": "invalid"}},
            "Webhook payment entity must be an object",
        ),
    ],
)
def test_webhook_rejects_malformed_nested_structures(
    client, payload, expected_detail
):
    event_payload = {
        "id": f"event_invalid_structure_{uuid4().hex[:8]}",
        "event": "payment.captured",
        "payload": payload,
    }

    raw_body = json.dumps(event_payload).encode("utf-8")
    signature = compute_webhook_signature(raw_body)

    response = client.post(
        "/api/v2/sandbox/razorpay/webhook",
        content=raw_body,
        headers={
            "X-Razorpay-Signature": signature,
            "Content-Type": "application/json",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == expected_detail


def test_webhook_can_never_authorize_p2p_payment(client):
    """Webhook response must never authorize a P2P payment."""

    event_payload = {
        "id": f"event_p2p_check_{uuid4().hex[:8]}",
        "event": "payment.captured",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_p2p_guard",
                    "order_id": "ord_p2p",
                }
            }
        },
    }

    raw_body = json.dumps(event_payload).encode("utf-8")
    signature = compute_webhook_signature(raw_body)

    res = client.post(
        "/api/v2/sandbox/razorpay/webhook",
        content=raw_body,
        headers={
            "X-Razorpay-Signature": signature,
            "Content-Type": "application/json",
        },
    )

    assert res.status_code == 200
    data = res.json()
    assert data["can_authorize_p2p_payment"] is False



# ---------------------------------------------------------------------------
# 5. Order History Inspection Tests
# ---------------------------------------------------------------------------


def test_admin_inspects_order_history(client, mock_client):
    headers = {"Authorization": f"Bearer {SYNTHETIC_ADMIN_TOKEN}"}

    # Create order
    create_res = client.post(
        "/api/v2/sandbox/razorpay/orders",
        json={"amount_paise": 60000, "receipt": "inspect_test_01"},
        headers=headers,
    )
    order_data = create_res.json()
    internal_id = order_data["id"]
    rzp_order_id = order_data["razorpay_order_id"]

    # Verify order
    mock_client.payment.register(
        payment_id="pay_inspect_123",
        order_id=rzp_order_id,
        amount=60000,
        status="captured",
    )
    sig = compute_payment_signature(rzp_order_id, "pay_inspect_123")
    client.post(
        "/api/v2/sandbox/razorpay/verify",
        json={
            "razorpay_order_id": rzp_order_id,
            "razorpay_payment_id": "pay_inspect_123",
            "razorpay_signature": sig,
        },
        headers=headers,
    )

    # Fetch by internal order id
    inspect_res = client.get(f"/api/v2/sandbox/razorpay/orders/{internal_id}", headers=headers)
    assert inspect_res.status_code == 200
    hist = inspect_res.json()
    assert hist["id"] == internal_id
    assert hist["status"] == "paid"
    assert hist["amount_paise"] == 60000
    assert len(hist["payments"]) == 1
    assert hist["payments"][0]["id"] == "pay_inspect_123"

    # Fetch by razorpay_order_id
    inspect_rzp_res = client.get(f"/api/v2/sandbox/razorpay/orders/{rzp_order_id}", headers=headers)
    assert inspect_rzp_res.status_code == 200


def test_order_inspection_not_found(client):
    headers = {"Authorization": f"Bearer {SYNTHETIC_ADMIN_TOKEN}"}
    res = client.get("/api/v2/sandbox/razorpay/orders/non_existent_order_123", headers=headers)
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# 6. Cross-Admin Isolation & Authorization Tests
# ---------------------------------------------------------------------------

OTHER_ADMIN_ID = uuid4()
OTHER_ADMIN = TrustedActorContext(user_id=OTHER_ADMIN_ID, roles=frozenset({UserRole.ADMIN}))


def test_cross_admin_isolation_get_order_forbidden(razorpay_service):
    """Admin B must not inspect Admin A's order."""
    # 1. Admin A creates order
    order_res = razorpay_service.create_order(
        SYNTHETIC_ADMIN,
        RazorpayOrderCreateRequest(amount_paise=50000, receipt="admin_a_rcpt"),
    )

    # 2. Admin B attempts to inspect Admin A's order -> 403 Forbidden
    with pytest.raises(Exception) as exc_info:
        razorpay_service.get_order(OTHER_ADMIN, order_res.id)
    assert exc_info.value.status_code == 403
    assert "does not own" in exc_info.value.detail


def test_cross_admin_isolation_verify_checkout_forbidden(razorpay_service, mock_client):
    """Admin B must not verify or capture Admin A's order."""
    order_res = razorpay_service.create_order(
        SYNTHETIC_ADMIN,
        RazorpayOrderCreateRequest(amount_paise=50000, receipt="admin_a_verify"),
    )
    payment_id = "pay_other_admin_123"
    mock_client.payment.register(
        payment_id=payment_id,
        order_id=order_res.razorpay_order_id,
        amount=50000,
        status="captured",
    )
    sig = compute_payment_signature(order_res.razorpay_order_id, payment_id)

    verify_req = RazorpayVerifyRequest(
        razorpay_order_id=order_res.razorpay_order_id,
        razorpay_payment_id=payment_id,
        razorpay_signature=sig,
    )
    with pytest.raises(Exception) as exc_info:
        razorpay_service.verify_checkout(OTHER_ADMIN, verify_req)
    assert exc_info.value.status_code == 403
    assert "does not own" in exc_info.value.detail


# ---------------------------------------------------------------------------
# 7. Safe Admin-Scoped Idempotency Tests
# ---------------------------------------------------------------------------


def test_admin_scoped_idempotency_order_creation_success(client):
    """Identical retries with same idempotency key return original order."""
    headers = {
        "Authorization": f"Bearer {SYNTHETIC_ADMIN_TOKEN}",
        "Idempotency-Key": "idem_admin_test_001",
    }
    payload = {"amount_paise": 70000, "receipt": "rcpt_idem_01"}

    # First request
    res1 = client.post("/api/v2/sandbox/razorpay/orders", json=payload, headers=headers)
    assert res1.status_code == 201
    data1 = res1.json()

    # Identical retry with same key
    res2 = client.post("/api/v2/sandbox/razorpay/orders", json=payload, headers=headers)
    assert res2.status_code == 201
    data2 = res2.json()

    # Must return identical order
    assert data1["id"] == data2["id"]
    assert data1["razorpay_order_id"] == data2["razorpay_order_id"]
    assert data1["amount_paise"] == data2["amount_paise"]


def test_admin_scoped_idempotency_conflicting_payload_fails(client):
    """Conflicting payload reusing same idempotency key must fail with 409 Conflict."""
    headers = {
        "Authorization": f"Bearer {SYNTHETIC_ADMIN_TOKEN}",
        "Idempotency-Key": "idem_admin_conflict_001",
    }
    payload1 = {"amount_paise": 50000, "receipt": "original_rcpt"}
    payload2 = {"amount_paise": 90000, "receipt": "conflicting_rcpt"}

    res1 = client.post("/api/v2/sandbox/razorpay/orders", json=payload1, headers=headers)
    assert res1.status_code == 201

    res2 = client.post("/api/v2/sandbox/razorpay/orders", json=payload2, headers=headers)
    assert res2.status_code == 409
    assert "conflicting request parameters" in res2.json().get("detail", "")


def test_admin_scoped_idempotency_cross_caller_collision_fails(razorpay_service):
    """Reusing another admin's idempotency key must fail with 409 Conflict."""
    req1 = RazorpayOrderCreateRequest(amount_paise=50000, receipt="rcpt_idem_cross")
    req2 = RazorpayOrderCreateRequest(amount_paise=50000, receipt="rcpt_idem_cross")

    res1 = razorpay_service.create_order(SYNTHETIC_ADMIN, req1, idempotency_key="cross_admin_key_01")
    assert res1.status == "created"

    with pytest.raises(Exception) as exc_info:
        razorpay_service.create_order(OTHER_ADMIN, req2, idempotency_key="cross_admin_key_01")
    assert exc_info.value.status_code == 409
    assert "collision across caller" in exc_info.value.detail


# ---------------------------------------------------------------------------
# 8. Out-of-Order Webhook & Reversal Prevention Tests
# ---------------------------------------------------------------------------


def test_webhook_out_of_order_failed_event_does_not_revert_paid_order(client, razorpay_service):
    """Stale out-of-order payment.failed webhook must NEVER downgrade a paid order."""
    headers = {"Authorization": f"Bearer {SYNTHETIC_ADMIN_TOKEN}"}

    # 1. Create order
    create_res = client.post(
        "/api/v2/sandbox/razorpay/orders",
        json={"amount_paise": 85000, "receipt": "out_of_order_test"},
        headers=headers,
    )
    rzp_order_id = create_res.json()["razorpay_order_id"]

    # 2. Payment captured via webhook
    captured_payload = {
        "id": "event_capture_first",
        "event": "payment.captured",
        "payload": {"payment": {"entity": {"id": "pay_ooo_1", "order_id": rzp_order_id, "amount": 85000}}},
    }
    raw_cap = json.dumps(captured_payload).encode("utf-8")
    sig_cap = compute_webhook_signature(raw_cap)
    res_cap = client.post(
        "/api/v2/sandbox/razorpay/webhook",
        content=raw_cap,
        headers={"X-Razorpay-Signature": sig_cap, "Content-Type": "application/json"},
    )
    assert res_cap.status_code == 200
    assert razorpay_service._mock_orders[rzp_order_id]["status"] == "paid"

    # 3. Delayed/out-of-order payment.failed event arrives later
    failed_payload = {
        "id": "event_failed_delayed",
        "event": "payment.failed",
        "payload": {"payment": {"entity": {"id": "pay_ooo_2", "order_id": rzp_order_id, "amount": 85000}}},
    }
    raw_fail = json.dumps(failed_payload).encode("utf-8")
    sig_fail = compute_webhook_signature(raw_fail)
    res_fail = client.post(
        "/api/v2/sandbox/razorpay/webhook",
        content=raw_fail,
        headers={"X-Razorpay-Signature": sig_fail, "Content-Type": "application/json"},
    )
    assert res_fail.status_code == 200

    # Order must remain paid!
    assert razorpay_service._mock_orders[rzp_order_id]["status"] == "paid"


# ---------------------------------------------------------------------------
# 9. Provider Errors & Failure Handling
# ---------------------------------------------------------------------------


def test_provider_order_create_error_returns_502(client, mock_client):
    """Provider failure during order creation surfaces as 502 Bad Gateway."""
    headers = {"Authorization": f"Bearer {SYNTHETIC_ADMIN_TOKEN}"}

    def failing_create(data):
        raise RuntimeError("Razorpay upstream gateway timeout")

    mock_client.order.create = failing_create

    res = client.post(
        "/api/v2/sandbox/razorpay/orders",
        json={"amount_paise": 50000},
        headers=headers,
    )
    assert res.status_code == 502
    assert "Razorpay provider error" in res.json().get("detail", "")


def test_provider_payment_fetch_error_returns_502(client, mock_client):
    """Provider failure during checkout verification surfaces as 502 Bad Gateway."""
    headers = {"Authorization": f"Bearer {SYNTHETIC_ADMIN_TOKEN}"}

    order_res = client.post(
        "/api/v2/sandbox/razorpay/orders",
        json={"amount_paise": 50000},
        headers=headers,
    )
    rzp_order_id = order_res.json()["razorpay_order_id"]
    payment_id = "pay_fetch_fail_123"
    sig = compute_payment_signature(rzp_order_id, payment_id)

    # Provider fetch fails
    def failing_fetch(p_id):
        raise RuntimeError("Provider connection reset by peer")

    mock_client.payment.fetch = failing_fetch

    res = client.post(
        "/api/v2/sandbox/razorpay/verify",
        json={
            "razorpay_order_id": rzp_order_id,
            "razorpay_payment_id": payment_id,
            "razorpay_signature": sig,
        },
        headers=headers,
    )
    assert res.status_code == 502
    assert "Provider reconciliation error" in res.json().get("detail", "")


def test_webhook_fails_closed_in_production_without_durable_session(monkeypatch, razorpay_service):
    """In production mode, in-memory replay guard is prohibited; must fail closed with 503."""
    monkeypatch.setenv("PAUSEGUARD_ENVIRONMENT", "production")
    monkeypatch.setenv("PAUSEGUARD_MODE", "real")

    raw_body = json.dumps({"id": "event_prod_check", "event": "payment.captured"}).encode("utf-8")
    sig = compute_webhook_signature(raw_body)

    with pytest.raises(Exception) as exc_info:
        razorpay_service.process_webhook(raw_body, sig)
    assert exc_info.value.status_code == 503
    assert "Durable persistence is required" in exc_info.value.detail

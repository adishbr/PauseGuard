"""Gate 5 tests: WebSocket single-use ticket security, redacted outbox durability, and stub failover."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from fastapi.testclient import TestClient
import pytest
from starlette.websockets import WebSocketDisconnect

from app.auth.identities import (
    SYNTHETIC_GUARDIAN_ID,
    SYNTHETIC_GUARDIAN_TOKEN,
    SYNTHETIC_OTHER_PAYER_TOKEN,
    SYNTHETIC_PAYER_ID,
    SYNTHETIC_PAYER_TOKEN,
)
from app.config import Settings
from app.main import create_app
from app.services.guardian_service import get_guardian_service
from app.services.payment_service import get_payment_service
from app.services.notification_service import (
    InAppOutboxProvider,
    SmsStubProvider,
    WebPushStubProvider,
    sanitize_notification_payload,
)
from app.services.v5_store import get_or_create_v5_mock_store


@pytest.fixture
def gate5_client():
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
        yield client, app
    get_guardian_service().reset_for_testing()
    get_payment_service().reset_for_testing()


def _signup_verified_user(client: TestClient, *, email: str, password: str, full_name: str, persona: str) -> str:
    resp = client.post(
        "/api/v2/auth/signup",
        json={"email": email, "password": password, "full_name": full_name, "role": persona},
    )
    assert resp.status_code == 201, resp.text
    sd = resp.json()
    vf = client.post(
        "/api/v2/auth/otp/verify",
        json={"challenge_id": sd["challenge_id"], "otp_code": sd["dev_otp_preview"]},
    )
    assert vf.status_code == 200, vf.text
    login = client.post(
        "/api/v2/auth/login",
        json={"email": email, "password": password},
    )
    assert login.status_code == 200, login.text
    return login.json()["access_token"]


def test_acceptance_12_ws_single_use_ticket_and_plaintext_token_rejection(gate5_client):
    """Acceptance #12: WebSocket requires single-use ticket; expired/reused/plaintext V5 tokens fail closed."""
    client, app = gate5_client
    token = _signup_verified_user(
        client,
        email="ws-payer@example.test",
        password="StrongPassword!123",
        full_name="Meera Krishnan",
        persona="PAYER",
    )

    # 1. Plaintext pg_v5_* token in WS query is strictly forbidden
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/api/v2/ws?token={token}"):
            pass

    # 2. Issue short-lived single-use ticket via authenticated POST
    ticket_resp = client.post("/api/v2/ws/ticket", headers={"Authorization": f"Bearer {token}"})
    assert ticket_resp.status_code == 200
    body = ticket_resp.json()
    assert body["ticket"].startswith("pg_ws_")
    assert body["single_use"] is True
    assert body["expires_in_seconds"] == 30

    ticket = body["ticket"]

    # 3. Connect once with ticket -> succeeds
    with client.websocket_connect(f"/api/v2/ws?ticket={ticket}") as ws:
        hello = ws.receive_json()
        assert hello["type"] == "CONNECTION_ESTABLISHED"
        ws.send_json({"type": "PING"})
        assert ws.receive_json()["type"] == "PONG"

    # 4. Reusing same ticket -> fails closed (WS_1008)
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/api/v2/ws?ticket={ticket}"):
            pass

    # 5. Expired ticket -> fails closed
    ticket_resp2 = client.post("/api/v2/ws/ticket", headers={"Authorization": f"Bearer {token}"})
    ticket2 = ticket_resp2.json()["ticket"]
    store = get_or_create_v5_mock_store(app.state)
    with store.lock:
        for rec in store.ws_tickets_by_hash.values():
            rec.expires_at = datetime.now(timezone.utc) - timedelta(seconds=5)
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/api/v2/ws?ticket={ticket2}"):
            pass


def test_acceptance_13_outbox_redacted_guardian_notification_on_offline_devices(gate5_client):
    """Acceptance #13: Escalation persists durable redacted guardian outbox without active WS."""
    client, _ = gate5_client

    create_resp = client.post(
        "/api/v2/payments",
        headers={"Authorization": f"Bearer {SYNTHETIC_PAYER_TOKEN}"},
        json={
            "idempotency_key": "gate5-outbox-redaction-001",
            "beneficiary_id": "beneficiary_new_scam_acc",
            "amount_paise": 6500000,
            "purpose": "Urgent KYC refund compliance transfer",
        },
    )
    assert create_resp.status_code == 201
    payment = create_resp.json()
    assert payment["status"] == "AWAITING_GUARDIAN"

    # Guardian fetches outbox -> sees redacted alert WITHOUT amount_paise or beneficiary_id
    guardian_outbox = client.get(
        "/api/v2/notifications/outbox",
        headers={"Authorization": f"Bearer {SYNTHETIC_GUARDIAN_TOKEN}"},
    )
    assert guardian_outbox.status_code == 200
    g_data = guardian_outbox.json()
    assert g_data["total"] >= 1
    matching = [item for item in g_data["items"] if item["payment_id"] == payment["id"]]
    assert matching
    g_item = matching[0]
    assert g_item["recipient_user_id"] == str(SYNTHETIC_GUARDIAN_ID)
    assert g_item["recipient_role"] == "GUARDIAN"
    assert g_item["payload"].get("redacted") is True
    assert "amount_paise" not in g_item["payload"]
    assert "beneficiary_id" not in g_item["payload"]
    assert "beneficiary" not in g_item["payload"]

    # Payer fetches own outbox -> sees full details for own payment
    payer_outbox = client.get(
        "/api/v2/notifications/outbox",
        headers={"Authorization": f"Bearer {SYNTHETIC_PAYER_TOKEN}"},
    )
    assert payer_outbox.status_code == 200
    p_matching = [item for item in payer_outbox.json()["items"] if item["payment_id"] == payment["id"]]
    assert p_matching
    assert p_matching[0]["payload"]["amount_paise"] == 6500000

    # Other payer receives empty outbox (strict isolation)
    other_outbox = client.get(
        "/api/v2/notifications/outbox",
        headers={"Authorization": f"Bearer {SYNTHETIC_OTHER_PAYER_TOKEN}"},
    )
    assert other_outbox.status_code == 200
    assert all(item["payment_id"] != payment["id"] for item in other_outbox.json()["items"])


def test_acceptance_14_notification_providers_and_fail_closed_in_production():
    """Acceptance #14: WebPush/SMS stubs succeed in mock mode and fail closed in production."""
    local_mock = Settings(environment="local", mode="mock", allow_demo_auth=True)
    prod = SimpleNamespace(environment="production", mode="real", allow_demo_auth=False)

    assert sanitize_notification_payload("GUARDIAN", {"amount_paise": 5000, "beneficiary_id": "x"}) == {
        "redacted": True,
        "message": "PauseGuard security review required: Please review this transaction.",
    }

    for provider in (InAppOutboxProvider(), WebPushStubProvider(), SmsStubProvider()):
        res = provider.dispatch(
            recipient_user_id=SYNTHETIC_PAYER_ID,
            recipient_role="PAYER",
            event_type="PAYMENT_ESCALATED",
            payload={"payment_id": "p1"},
            settings=local_mock,
        )
        assert res.status == "SENT"

    for stub in (WebPushStubProvider(), SmsStubProvider()):
        with pytest.raises(RuntimeError, match="forbidden"):
            stub.dispatch(
                recipient_user_id=SYNTHETIC_PAYER_ID,
                recipient_role="PAYER",
                event_type="PAYMENT_ESCALATED",
                payload={"payment_id": "p1"},
                settings=prod,
            )

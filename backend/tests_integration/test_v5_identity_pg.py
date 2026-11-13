"""PostgreSQL integration tests for V5 Gate 2 durable accounts, OTP, identity assurance, and guardian invitations."""

from uuid import uuid4

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def _pg_signup_verify_login(client: TestClient, *, email: str, password: str, full_name: str, role: str) -> tuple[str, dict]:
    signup = client.post(
        "/api/v2/auth/signup",
        json={"email": email, "password": password, "full_name": full_name, "role": role},
    )
    assert signup.status_code == 201, signup.text
    sdata = signup.json()

    ver = client.post(
        "/api/v2/auth/otp/verify",
        json={"challenge_id": sdata["challenge_id"], "otp_code": sdata["dev_otp_preview"]},
    )
    assert ver.status_code == 200, ver.text

    login = client.post("/api/v2/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text
    ldata = login.json()
    return ldata["access_token"], ldata


def test_pg_v5_real_signup_kyc_guardian_invite_and_payment_flow(pg_session_factory):
    app = create_app(
        Settings(environment="test", mode="mock", allow_demo_auth=False, allow_demo_admin=False),
        session_factory=pg_session_factory,
    )
    suffix = uuid4().hex[:8]
    with TestClient(app) as client:
        # 1. Admin signup strictly forbidden
        adm_res = client.post(
            "/api/v2/auth/signup",
            json={"email": f"adm_{suffix}@example.com", "password": "Password!1234", "full_name": "No Admin", "role": "admin"},
        )
        assert adm_res.status_code == 403

        # 2. Payer + Guardian durable signup, OTP, and login persisted in PostgreSQL
        p_tok, _ = _pg_signup_verify_login(
            client,
            email=f"payer_{suffix}@example.com",
            password="Password!1234",
            full_name="PG Payer",
            role="payer",
        )
        g_tok, _ = _pg_signup_verify_login(
            client,
            email=f"guard_{suffix}@example.com",
            password="Password!1234",
            full_name="PG Guardian",
            role="guardian",
        )
        p_hdr = {"Authorization": f"Bearer {p_tok}"}
        g_hdr = {"Authorization": f"Bearer {g_tok}"}

        # 3. Verify distinct synthetic identities in PostgreSQL
        assert client.post(
            "/api/v2/identity/verify",
            headers=p_hdr,
            json={"provider": "synthetic_local_idp", "full_name": "PG Payer", "synthetic_document_ref": f"PG-P-{suffix}", "consent_confirmed": True},
        ).status_code == 200
        assert client.post(
            "/api/v2/identity/verify",
            headers=g_hdr,
            json={"provider": "synthetic_local_idp", "full_name": "PG Guardian", "synthetic_document_ref": f"PG-G-{suffix}", "consent_confirmed": True},
        ).status_code == 200

        # 4. Create, verify OTP, accept invitation -> ACTIVE in PostgreSQL
        inv = client.post(
            "/api/v2/guardian/invitations",
            headers=p_hdr,
            json={"guardian_email": f"guard_{suffix}@example.com", "relationship": "sibling", "role_slot": "primary", "notification_channel": "in_app"},
        )
        assert inv.status_code == 201, inv.text
        inv_data = inv.json()

        otp = client.post(
            "/api/v2/auth/otp/challenge",
            json={"contact": f"guard_{suffix}@example.com", "purpose": "guardian_invite", "channel": "email"},
        )
        assert otp.status_code == 200, otp.text
        otp_data = otp.json()

        acc = client.post(
            f"/api/v2/guardian/invitations/{inv_data['invitation_id']}/accept",
            headers=g_hdr,
            json={
                "invite_token": inv_data["dev_invite_token_preview"],
                "otp_challenge_id": otp_data["challenge_id"],
                "otp_code": otp_data["dev_otp_preview"],
                "explicit_consent": True,
            },
        )
        assert acc.status_code == 200, acc.text
        assert acc.json()["status"] == "ACTIVE"

        # 5. Tier 3 high-risk payment assigns durable PostgreSQL guardian, guardian approves, payer executes
        pay = client.post(
            "/api/v2/payments",
            headers=p_hdr,
            json={
                "amount_paise": 6000000,
                "beneficiary_id": "unknown@upi",
                "purpose": "Urgent KYC unblock immediately",
                "idempotency_key": f"pg-v5-{suffix}",
            },
        )
        assert pay.status_code == 201, pay.text
        pay_data = pay.json()
        assert pay_data["status"] == "AWAITING_GUARDIAN"

        dec = client.post(
            f"/api/v2/payments/{pay_data['id']}/guardian/decision",
            headers=g_hdr,
            json={"approved": True, "notes": "Confirmed in PostgreSQL run"},
        )
        assert dec.status_code == 200, dec.text
        assert dec.json()["status"] == "READY_TO_EXECUTE"

        conf = client.post(
            f"/api/v2/payments/{pay_data['id']}/confirm",
            headers=p_hdr,
            json={"idempotency_key": f"pg-conf-{suffix}"},
        )
        assert conf.status_code == 200, conf.text
        assert conf.json()["status"] == "EXECUTED"

        # 6. Durable NotificationOutbox persisted in PostgreSQL with strict guardian redaction
        outbox_res = client.get("/api/v2/notifications/outbox", headers=g_hdr)
        assert outbox_res.status_code == 200, outbox_res.text
        outbox_items = outbox_res.json()["items"]
        assert len(outbox_items) >= 1
        assert outbox_items[0]["payload"]["redacted"] is True
        assert "amount_paise" not in outbox_items[0]["payload"]
        assert "beneficiary_id" not in outbox_items[0]["payload"]


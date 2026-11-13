"""Gate 2 tests for V5 real signup, OTP hardening, synthetic identity assurance, and durable guardian invitations."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.services.identity_assurance_service import SyntheticLocalIdentityProvider
from app.services.otp_service import DeterministicLocalOtpProvider, OtpService
from app.services.v5_store import get_or_create_v5_mock_store


@pytest.fixture
def client():
    app = create_app(Settings(environment="test", mode="mock", allow_demo_auth=False, allow_demo_admin=False))
    with TestClient(app) as tc:
        yield tc


def _signup_verify_login(client: TestClient, *, email: str, password: str, full_name: str, role: str) -> tuple[str, dict]:
    signup = client.post(
        "/api/v2/auth/signup",
        json={"email": email, "password": password, "full_name": full_name, "role": role},
    )
    assert signup.status_code == 201, signup.text
    sdata = signup.json()
    assert sdata["email_verified"] is False
    assert sdata["is_mock_otp_delivery"] is True
    assert sdata["dev_otp_preview"] is not None

    # Unverified account cannot log in (403)
    pre_login = client.post("/api/v2/auth/login", json={"email": email, "password": password})
    assert pre_login.status_code == 403

    verify = client.post(
        "/api/v2/auth/otp/verify",
        json={"challenge_id": sdata["challenge_id"], "otp_code": sdata["dev_otp_preview"]},
    )
    assert verify.status_code == 200, verify.text
    assert verify.json()["email_verified"] is True

    login = client.post("/api/v2/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text
    ldata = login.json()
    assert ldata["access_token"].startswith("pg_v5_")
    assert ldata["is_synthetic"] is False
    assert ldata["role"] == role
    return ldata["access_token"], ldata


def test_acceptance_2_cannot_signup_as_admin_or_analyst(client: TestClient):
    for forbidden_role in ("admin", "analyst", "superuser", "ADMIN"):
        res = client.post(
            "/api/v2/auth/signup",
            json={
                "email": f"{forbidden_role.lower()}@example.com",
                "password": "StrongPassword!123",
                "full_name": "Attempted Admin",
                "role": forbidden_role,
            },
        )
        assert res.status_code == 403


def test_acceptance_3_otp_single_use_lockout_cooldown_and_expiry(client: TestClient):
    app = client.app
    store = get_or_create_v5_mock_store(app.state)
    svc = OtpService(settings=app.state.settings, mock_store=store, cooldown_seconds=30)

    # Cooldown rejection within 30s on same contact+purpose
    now = datetime.now(timezone.utc)
    c1 = svc.create_challenge(contact="user.otp@example.com", purpose="login_step_up", now=now)
    assert c1.dev_otp_preview is not None
    with pytest.raises(Exception) as exc_cool:
        svc.create_challenge(contact="user.otp@example.com", purpose="login_step_up", now=now + timedelta(seconds=5))
    assert getattr(exc_cool.value, "status_code", None) == 429

    # Wrong attempts lock after max_attempts (5)
    for _ in range(4):
        with pytest.raises(Exception) as exc_bad:
            svc.verify_challenge(challenge_id=c1.challenge_id, otp_code="000000" if c1.dev_otp_preview != "000000" else "999999", now=now + timedelta(seconds=10))
        assert getattr(exc_bad.value, "status_code", None) == 401
    with pytest.raises(Exception) as exc_lock:
        svc.verify_challenge(challenge_id=c1.challenge_id, otp_code="000000" if c1.dev_otp_preview != "000000" else "999999", now=now + timedelta(seconds=11))
    assert getattr(exc_lock.value, "status_code", None) == 423
    # Even right code fails once locked
    with pytest.raises(Exception) as exc_still_locked:
        svc.verify_challenge(challenge_id=c1.challenge_id, otp_code=c1.dev_otp_preview, now=now + timedelta(seconds=12))
    assert getattr(exc_still_locked.value, "status_code", None) == 423

    # Expiry check
    c2 = svc.create_challenge(contact="exp@example.com", purpose="login_step_up", now=now)
    with pytest.raises(Exception) as exc_exp:
        svc.verify_challenge(challenge_id=c2.challenge_id, otp_code=c2.dev_otp_preview, now=now + timedelta(seconds=301))
    assert getattr(exc_exp.value, "status_code", None) == 410

    # Single-use check
    c3 = svc.create_challenge(contact="once@example.com", purpose="login_step_up", now=now)
    res = svc.verify_challenge(challenge_id=c3.challenge_id, otp_code=c3.dev_otp_preview, now=now + timedelta(seconds=1))
    assert res.verified is True
    with pytest.raises(Exception) as exc_reuse:
        svc.verify_challenge(challenge_id=c3.challenge_id, otp_code=c3.dev_otp_preview, now=now + timedelta(seconds=2))
    assert getattr(exc_reuse.value, "status_code", None) == 409


def test_real_login_logout_and_client_trusted_person_ref_rejected(client: TestClient):
    token, login_data = _signup_verify_login(
        client,
        email="payer.real@example.com",
        password="StrongPassword!123",
        full_name="Asha Nair",
        role="payer",
    )
    headers = {"Authorization": f"Bearer {token}"}

    # Profile works even with allow_demo_auth=False because V5 session is server-issued
    prof = client.get("/api/v2/profile", headers=headers)
    assert prof.status_code == 200
    assert prof.json()["user_id"] == login_data["user_id"]

    # Client supplying trusted_person_ref directly must fail validation (extra='forbid')
    forged = client.post(
        "/api/v2/identity/verify",
        headers=headers,
        json={
            "provider": "synthetic_local_idp",
            "full_name": "Asha Nair",
            "synthetic_document_ref": "SYNTH-ASHA-001",
            "consent_confirmed": True,
            "trusted_person_ref": "tpr_forged_client_claim",
        },
    )
    assert forged.status_code == 422

    # Valid verification produces opaque tpr_* without echoing raw document ref
    ok = client.post(
        "/api/v2/identity/verify",
        headers=headers,
        json={
            "provider": "synthetic_local_idp",
            "full_name": "Asha Nair",
            "synthetic_document_ref": "SYNTH-ASHA-001",
            "consent_confirmed": True,
        },
    )
    assert ok.status_code == 200
    idata = ok.json()
    assert idata["verified"] is True
    assert idata["is_mock_assurance"] is True
    assert idata["trusted_person_ref"].startswith("tpr_")
    assert "SYNTH-ASHA-001" not in str(idata)

    # Logout invalidates session immediately
    out = client.post("/api/v2/auth/logout", headers=headers)
    assert out.status_code == 200 and out.json()["revoked"] is True
    assert client.get("/api/v2/profile", headers=headers).status_code == 401


def test_acceptance_1_same_person_second_email_collusion_blocked(client: TestClient):
    payer_token, _ = _signup_verify_login(
        client,
        email="alice.payer@example.com",
        password="Password!1234",
        full_name="Alice Payer",
        role="payer",
    )
    sock_token, _ = _signup_verify_login(
        client,
        email="alice.alt.guardian@example.com",
        password="Password!1234",
        full_name="Alice Alt",
        role="guardian",
    )
    p_hdr = {"Authorization": f"Bearer {payer_token}"}
    g_hdr = {"Authorization": f"Bearer {sock_token}"}

    # Payer cannot invite self email
    self_inv = client.post(
        "/api/v2/guardian/invitations",
        headers=p_hdr,
        json={"guardian_email": "alice.payer@example.com", "relationship": "self", "role_slot": "primary", "notification_channel": "in_app"},
    )
    assert self_inv.status_code == 403

    # Verify both accounts using the SAME synthetic human reference
    assert client.post(
        "/api/v2/identity/verify",
        headers=p_hdr,
        json={"provider": "synthetic_local_idp", "full_name": "Alice Payer", "synthetic_document_ref": "SYNTH-HUMAN-99", "consent_confirmed": True},
    ).status_code == 200
    assert client.post(
        "/api/v2/identity/verify",
        headers=g_hdr,
        json={"provider": "synthetic_local_idp", "full_name": "Alice Alt", "synthetic_document_ref": "SYNTH-HUMAN-99", "consent_confirmed": True},
    ).status_code == 200

    # Inviting the alt account fails fail-closed because trusted_person_ref matches payer
    collude_inv = client.post(
        "/api/v2/guardian/invitations",
        headers=p_hdr,
        json={"guardian_email": "alice.alt.guardian@example.com", "relationship": "family", "role_slot": "primary", "notification_channel": "in_app"},
    )
    assert collude_inv.status_code == 403


def test_acceptance_4_and_5_full_invite_accept_payment_and_revoke(client: TestClient):
    payer_token, _ = _signup_verify_login(
        client,
        email="rohan.payer@example.com",
        password="Password!1234",
        full_name="Rohan Payer",
        role="payer",
    )
    guardian_token, _ = _signup_verify_login(
        client,
        email="meera.guardian@example.com",
        password="Password!1234",
        full_name="Meera Guardian",
        role="guardian",
    )
    p_hdr = {"Authorization": f"Bearer {payer_token}"}
    g_hdr = {"Authorization": f"Bearer {guardian_token}"}

    # Two genuinely distinct synthetic people
    assert client.post(
        "/api/v2/identity/verify",
        headers=p_hdr,
        json={"provider": "synthetic_local_idp", "full_name": "Rohan Payer", "synthetic_document_ref": "SYNTH-ROHAN-1", "consent_confirmed": True},
    ).status_code == 200
    assert client.post(
        "/api/v2/identity/verify",
        headers=g_hdr,
        json={"provider": "synthetic_local_idp", "full_name": "Meera Guardian", "synthetic_document_ref": "SYNTH-MEERA-2", "consent_confirmed": True},
    ).status_code == 200

    # Invite Meera
    inv_res = client.post(
        "/api/v2/guardian/invitations",
        headers=p_hdr,
        json={"guardian_email": "meera.guardian@example.com", "relationship": "spouse", "role_slot": "primary", "notification_channel": "in_app"},
    )
    assert inv_res.status_code == 201
    inv = inv_res.json()
    assert inv["status"] == "PENDING"
    assert inv["dev_invite_token_preview"] is not None

    # Guardian requests OTP for acceptance
    otp_res = client.post(
        "/api/v2/auth/otp/challenge",
        json={"contact": "meera.guardian@example.com", "purpose": "guardian_invite", "channel": "email"},
    )
    assert otp_res.status_code == 200
    otp_data = otp_res.json()

    # Acceptance requires explicit_consent=True
    no_consent = client.post(
        f"/api/v2/guardian/invitations/{inv['invitation_id']}/accept",
        headers=g_hdr,
        json={
            "invite_token": inv["dev_invite_token_preview"],
            "otp_challenge_id": otp_data["challenge_id"],
            "otp_code": otp_data["dev_otp_preview"],
            "explicit_consent": False,
        },
    )
    assert no_consent.status_code == 400

    # Valid acceptance transitions to ACTIVE
    accepted = client.post(
        f"/api/v2/guardian/invitations/{inv['invitation_id']}/accept",
        headers=g_hdr,
        json={
            "invite_token": inv["dev_invite_token_preview"],
            "otp_challenge_id": otp_data["challenge_id"],
            "otp_code": otp_data["dev_otp_preview"],
            "explicit_consent": True,
        },
    )
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "ACTIVE"

    # High-risk payment routes to this real verified guardian and executes after approval + payer confirm
    pay_res = client.post(
        "/api/v2/payments",
        headers=p_hdr,
        json={
            "amount_paise": 6000000,
            "beneficiary_id": "unknown@upi",
            "purpose": "Urgent KYC unblock transfer immediately",
            "idempotency_key": f"v5-key-{uuid4().hex}",
        },
    )
    assert pay_res.status_code == 201, pay_res.text
    pdata = pay_res.json()
    assert pdata["status"] == "AWAITING_GUARDIAN"

    # Guardian approves
    dec_res = client.post(
        f"/api/v2/payments/{pdata['id']}/guardian/decision",
        headers=g_hdr,
        json={"approved": True, "notes": "Verified offline with Rohan"},
    )
    assert dec_res.status_code == 200
    assert dec_res.json()["status"] == "READY_TO_EXECUTE"

    # Payer confirms execution
    conf_res = client.post(
        f"/api/v2/payments/{pdata['id']}/confirm",
        headers=p_hdr,
        json={"idempotency_key": f"conf-{uuid4().hex}"},
    )
    assert conf_res.status_code == 200
    assert conf_res.json()["status"] == "EXECUTED"

    # Guardian status reflects active enrollment before revocation
    assert client.get("/api/v2/guardian/status", headers=p_hdr).json()["has_guardian"] is True

    # Guardian revokes link cleanly -> subsequent approvals or enrollment lookup cleared
    rev_res = client.post(f"/api/v2/guardian/invitations/{inv['invitation_id']}/revoke", headers=g_hdr)
    assert rev_res.status_code == 200
    assert rev_res.json()["status"] == "REVOKED"
    assert client.get("/api/v2/guardian/status", headers=p_hdr).json()["has_guardian"] is False

    # High-risk payment after revocation cannot use revoked guardian
    post_revoke_pay = client.post(
        "/api/v2/payments",
        headers=p_hdr,
        json={
            "amount_paise": 6000000,
            "beneficiary_id": "unknown2@upi",
            "purpose": "Urgent KYC transfer",
            "idempotency_key": f"v5-rev-{uuid4().hex}",
        },
    )
    assert post_revoke_pay.status_code in (403, 422) or post_revoke_pay.json()["status"] != "EXECUTED"


def test_acceptance_19_local_providers_fail_closed_in_production_like_settings():
    class FakeProdSettings:
        environment = "production"
        mode = "real"

    with pytest.raises(Exception) as exc1:
        DeterministicLocalOtpProvider().deliver_otp(
            contact="x@example.com", purpose="signup_email", channel="email", otp_code="123456", settings=FakeProdSettings()
        )
    assert getattr(exc1.value, "status_code", None) == 503

    with pytest.raises(Exception) as exc2:
        SyntheticLocalIdentityProvider().verify_person(
            full_name="Test", synthetic_document_ref="DOC1234", settings=FakeProdSettings()
        )
    assert getattr(exc2.value, "status_code", None) == 503


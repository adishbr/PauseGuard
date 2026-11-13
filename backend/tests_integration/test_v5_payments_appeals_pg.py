"""PostgreSQL integration tests for V5 Gate 4 payment snapshot invalidation, appeals, backup guardian, and safe retry."""

from uuid import uuid4

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def _pg_setup_account(client: TestClient, *, email: str, name: str, role: str, doc_ref: str) -> tuple[str, str]:
    s = client.post(
        "/api/v2/auth/signup",
        json={"email": email, "password": "Password!1234", "full_name": name, "role": role},
    ).json()
    client.post(
        "/api/v2/auth/otp/verify",
        json={"challenge_id": s["challenge_id"], "otp_code": s["dev_otp_preview"]},
    )
    login = client.post(
        "/api/v2/auth/login",
        json={"email": email, "password": "Password!1234"},
    ).json()
    tok = login["access_token"]
    client.post(
        "/api/v2/identity/verify",
        headers={"Authorization": f"Bearer {tok}"},
        json={
            "provider": "synthetic_local_idp",
            "full_name": name,
            "synthetic_document_ref": doc_ref,
            "consent_confirmed": True,
        },
    )
    return tok, login["user_id"]


def test_pg_v5_gate4_snapshot_invalidation_appeals_and_retry(pg_session_factory):
    app = create_app(
        Settings(environment="test", mode="mock", allow_demo_auth=True, allow_demo_admin=True),
        session_factory=pg_session_factory,
    )
    suffix = uuid4().hex[:8]
    with TestClient(app) as client:
        p_tok, _ = _pg_setup_account(
            client, email=f"g4p_{suffix}@example.com", name="Payer PG", role="payer", doc_ref=f"PGP-{suffix}"
        )
        g_tok, _ = _pg_setup_account(
            client, email=f"g4g_{suffix}@example.com", name="Guardian PG", role="guardian", doc_ref=f"PGG-{suffix}"
        )

        # Enroll guardian durably
        inv = client.post(
            "/api/v2/guardian/invitations",
            headers={"Authorization": f"Bearer {p_tok}"},
            json={
                "guardian_email": f"g4g_{suffix}@example.com",
                "relationship": "family",
                "role_slot": "primary",
                "notification_channel": "in_app",
            },
        ).json()
        ch = client.post(
            "/api/v2/auth/otp/challenge",
            json={"contact": f"g4g_{suffix}@example.com", "purpose": "guardian_invite", "channel": "email"},
        ).json()
        acc = client.post(
            f"/api/v2/guardian/invitations/{inv['invitation_id']}/accept",
            headers={"Authorization": f"Bearer {g_tok}"},
            json={
                "invite_token": inv["dev_invite_token_preview"],
                "otp_challenge_id": ch["challenge_id"],
                "otp_code": ch["dev_otp_preview"],
                "explicit_consent": True,
            },
        )
        assert acc.status_code == 200

        # Create payment -> approve -> modify payee -> verify invalidated (409 on confirm) -> reject -> appeal -> retry
        created = client.post(
            "/api/v2/payments",
            headers={"Authorization": f"Bearer {p_tok}"},
            json={
                "beneficiary_id": "vpa_orig",
                "amount_paise": 6_000_000,
                "purpose": "equipment invoice",
                "idempotency_key": f"pg-g4-{suffix}",
            },
        ).json()
        pid = created["id"]

        client.post(
            f"/api/v2/payments/{pid}/guardian/decision",
            headers={"Authorization": f"Bearer {g_tok}"},
            json={"approved": True},
        )
        edited = client.patch(
            f"/api/v2/payments/{pid}",
            headers={"Authorization": f"Bearer {p_tok}"},
            json={"beneficiary_id": "vpa_changed", "amount_paise": 7_500_000},
        )
        assert edited.status_code == 200
        assert edited.json()["status"] == "AWAITING_GUARDIAN"

        # Guardian rejects edited payment -> payer appeals -> analyst approves retry -> retry succeeds
        client.post(
            f"/api/v2/payments/{pid}/guardian/decision",
            headers={"Authorization": f"Bearer {g_tok}"},
            json={"approved": False},
        )
        appeal = client.post(
            f"/api/v2/payments/{pid}/appeals",
            headers={"Authorization": f"Bearer {p_tok}"},
            json={"reason": "Invoice recipient verified"},
        ).json()
        assert client.post(
            f"/api/v2/payments/{pid}/appeals/{appeal['appeal_id']}/resolve",
            headers={"Authorization": f"Bearer {p_tok}"},
            json={"approved": True, "resolution_note": "self"},
        ).status_code == 403

        resolved = client.post(
            f"/api/v2/payments/{pid}/appeals/{appeal['appeal_id']}/resolve",
            headers={"Authorization": "Bearer demo-token-analyst"},
            json={"approved": True, "resolution_note": "Confirmed invoice"},
        )
        assert resolved.status_code == 200
        assert resolved.json()["status"] == "APPROVED_RETRY_ELIGIBLE"

        retried = client.post(
            f"/api/v2/payments/{pid}/retry",
            headers={"Authorization": f"Bearer {p_tok}"},
            json={"idempotency_key": f"pg-g4-retry-{suffix}"},
        )
        assert retried.status_code == 201
        assert retried.json()["parent_payment_id"] == pid

"""V4.1 final closure offline regression tests.

Covers:
1. Savepoint-safe IntegrityError handling in DurablePaymentEngine without session.rollback().
2. DurablePaymentEngine confirm_payment authz-before-idempotency ordering (403 over 409).
3. Post-commit WebSocket broadcast dispatch (strictly after commit, never on rollback,
   correct owning payer_id routing on guardian decisions).
4. Bounded Fraud Advisory integration in POST /api/v2/payments (escalation, fail-closed
   Safe-Lock precedence, exception/timeout degradation without holding DB locks).
5. Policy Lab endpoint RBAC and synthetic benchmark contract.
"""

import hashlib
from datetime import datetime, timedelta, timezone
from time import sleep
from unittest.mock import MagicMock, Mock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.identities import (
    SYNTHETIC_GUARDIAN_ID,
    SYNTHETIC_OTHER_PAYER_ID,
    SYNTHETIC_PAYER_ID,
)
from app.auth.schemas import GuardianDecisionRequest, PaymentConfirmRequest, PaymentCreateRequest
from app.config import Settings
from app.main import create_app
from app.models.idempotency import IdempotencyRecord
from app.models.payment import Payment
from app.models.roles import UserRole
from app.models.safe_lock import SafeLockState
from app.services.durable_payment_engine import DurablePaymentEngine, GuardianLateDecisionOutcome
from app.services.payment_guards import PaymentStatus, TrustedActorContext
from app.services.payment_service import get_payment_service
from intelligence.advisory.types import AdvisoryResponse
from intelligence.schemas.risk_signals import (
    BehavioralSignal,
    CalculationMethod,
    DataOrigin,
    EvaluationStatus,
    MuleGraphSignal,
    RegistrySignal,
    RiskSignals,
    SignalProvenance,
    SourceCategory,
    SuggestedCautionLevel,
    TranscriptCoercionSignal,
    VelocitySignal,
)


@pytest.fixture(autouse=True)
def reset_mock_service():
    service = get_payment_service()
    service.reset_for_testing()
    yield
    service.reset_for_testing()


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_durable_confirm_payment_integrity_error_uses_savepoint_not_rollback():
    """confirm_payment handles concurrent IntegrityError via begin_nested() without outer rollback()."""
    from app.models.account import MockAccount

    session = Mock(spec=Session)
    savepoint = MagicMock()
    session.begin_nested.return_value = savepoint

    payment = Payment(
        id="pg_conf_race_001",
        payer_id=SYNTHETIC_PAYER_ID,
        beneficiary_id="vendor_conf_race",
        amount_paise=50_000,
        purpose="confirm race",
        status=PaymentStatus.READY_TO_EXECUTE.value,
        tier=0,
        idempotency_key="idem_create_conf_race",
        version=1,
    )
    safe_lock = SafeLockState(payer_id=SYNTHETIC_PAYER_ID, is_locked=False, version=1)
    account = MockAccount(id=uuid4(), owner_id=SYNTHETIC_PAYER_ID, balance_paise=1_000_000, version=1)

    req = PaymentConfirmRequest(idempotency_key="confirm_race_idem_001")
    req_hash = hashlib.sha256(f"{SYNTHETIC_PAYER_ID}:{payment.id}:{req.idempotency_key}".encode()).hexdigest()
    existing_idem = IdempotencyRecord(
        key=req.idempotency_key,
        caller_id=SYNTHETIC_PAYER_ID,
        endpoint=f"/api/v2/payments/{payment.id}/confirm",
        request_hash=req_hash,
        response_status=200,
        response_body={
            "payment_id": payment.id,
            "status": PaymentStatus.EXECUTED.value,
            "amount_paise": payment.amount_paise,
            "confirmed_at": datetime.now(timezone.utc).isoformat(),
        },
    )

    session.scalars.return_value.one_or_none.side_effect = [
        payment,        # initial payment lookup
        None,           # initial idempotency lookup
        safe_lock,      # Safe-Lock check
        account,        # account lookup
        existing_idem,  # idempotency recovery lookup after savepoint IntegrityError
    ]
    session.flush.side_effect = IntegrityError("dup", params={}, orig=Exception("unique violation"))

    engine = DurablePaymentEngine(session)
    actor = TrustedActorContext(SYNTHETIC_PAYER_ID, frozenset({UserRole.PAYER}))
    res = engine.confirm_payment(actor, payment.id, req)

    assert res.payment_id == payment.id
    assert res.status == PaymentStatus.EXECUTED.value
    session.begin_nested.assert_called_once_with()
    savepoint.__enter__.assert_called_once()
    savepoint.__exit__.assert_called_once()
    session.rollback.assert_not_called()


def test_durable_confirm_payment_enforces_authz_before_idempotency():
    """Non-owning payer guessing an existing confirm idempotency_key receives 403 Forbidden, not 409."""
    session = Mock(spec=Session)
    payment = Payment(
        id="pg_authz_order_001",
        payer_id=SYNTHETIC_PAYER_ID,
        beneficiary_id="vendor_authz_probe",
        amount_paise=40_000,
        purpose="authz ordering check",
        status=PaymentStatus.EXECUTED.value,
        tier=0,
        idempotency_key="idem_create_probe_001",
        version=2,
    )
    session.scalars.return_value.one_or_none.return_value = payment

    engine = DurablePaymentEngine(session)
    other_actor = TrustedActorContext(SYNTHETIC_OTHER_PAYER_ID, frozenset({UserRole.PAYER}))

    with pytest.raises(HTTPException) as exc_info:
        engine.confirm_payment(
            other_actor,
            payment.id,
            PaymentConfirmRequest(idempotency_key="shared_confirm_probe_001"),
        )
    assert exc_info.value.status_code == 403
    # Ownership failed before idempotency_record_for_update query ran
    assert session.scalars.call_count == 1


def test_post_commit_websocket_dispatch_order_and_rollback_suppression():
    """WebSocket notifications dispatch strictly after commit and never when commit fails."""
    call_order: list[str] = []

    created_payment = Payment(
        id="pg_ws_order_001",
        payer_id=SYNTHETIC_PAYER_ID,
        beneficiary_id="vendor_ws_order",
        amount_paise=6_000_000,
        purpose="urgent transfer",
        status=PaymentStatus.AWAITING_GUARDIAN.value,
        tier=3,
        risk_score=75,
        idempotency_key="idem_ws_order_001",
        assigned_guardian_id=SYNTHETIC_GUARDIAN_ID,
        guardian_deadline=datetime.now(timezone.utc) + timedelta(seconds=30),
        version=1,
    )

    def _make_mock_session(*, fail_commit: bool = False):
        session = Mock(spec=Session)
        session.begin_nested.return_value = MagicMock()

        def _commit():
            if fail_commit:
                raise RuntimeError("db commit failed")
            call_order.append("commit")

        session.commit.side_effect = _commit
        session.rollback.side_effect = lambda: call_order.append("rollback")

        def _scalars(stmt):
            sql = str(stmt).lower()
            res = Mock()
            if "safe_lock" in sql:
                res.one_or_none.return_value = SafeLockState(payer_id=SYNTHETIC_PAYER_ID, is_locked=False)
            elif "from payments" in sql and "idempotency_records" not in sql:
                res.one_or_none.return_value = created_payment
            else:
                res.one_or_none.return_value = None
            return res

        session.scalars.side_effect = _scalars

        def _query(model):
            q = Mock()
            if model is Payment:
                q.filter.return_value.one_or_none.side_effect = lambda: (
                    created_payment if "PAYMENT_CREATED" in "".join(call_order) else None
                )
            else:
                q.filter.return_value.one_or_none.return_value = None
            q.order_by.return_value.first.return_value = None
            return q

        session.query.side_effect = _query
        return session

    settings = Settings(environment="test", mode="mock", allow_demo_auth=True)
    app = create_app(settings, session_factory=lambda: _make_mock_session(fail_commit=False))
    client = TestClient(app)

    def _record_broadcast(**kwargs):
        call_order.append(f"broadcast:{kwargs.get('event_type')}:{kwargs.get('payer_id')}")

    with patch("app.api.payments.broadcast_event_sync", side_effect=_record_broadcast):
        # 1. Create payment -> commit MUST precede broadcast
        res = client.post(
            "/api/v2/payments",
            headers=_headers("demo-token-payer"),
            json={
                "beneficiary_id": "vendor_ws_order",
                "amount_paise": 6_000_000,
                "purpose": "urgent transfer",
                "idempotency_key": "idem_ws_order_001",
            },
        )
        assert res.status_code == 201
        assert call_order == ["commit", f"broadcast:PAYMENT_CREATED:{SYNTHETIC_PAYER_ID}"]

        call_order.clear()
        created_payment.id = res.json()["id"]

        # 2. Guardian approval -> routes GUARDIAN_DECISION to owning payer_id strictly after commit
        with patch.object(
            DurablePaymentEngine,
            "get_payment_payer_id",
            return_value=SYNTHETIC_PAYER_ID,
        ):
            dec = client.post(
                f"/api/v2/payments/{created_payment.id}/guardian/decision",
                headers=_headers("demo-token-guardian"),
                json={"approved": True, "notes": "Verified ok"},
            )
            assert dec.status_code == 200
            assert call_order == ["commit", f"broadcast:GUARDIAN_DECISION:{SYNTHETIC_PAYER_ID}"]

    # 3. Failed commit triggers rollback and suppresses broadcast completely
    call_order.clear()
    failing_app = create_app(settings, session_factory=lambda: _make_mock_session(fail_commit=True))
    failing_client = TestClient(failing_app)
    broadcast_spy = Mock()
    with patch("app.api.payments.broadcast_event_sync", broadcast_spy):
        with pytest.raises(RuntimeError, match="db commit failed"):
            failing_client.post(
                "/api/v2/payments",
                headers=_headers("demo-token-payer"),
                json={
                    "beneficiary_id": "vendor_ws_fail_commit",
                    "amount_paise": 20_000,
                    "purpose": "should fail commit",
                    "idempotency_key": "idem_ws_fail_commit_001",
                },
            )
    assert "rollback" in call_order
    broadcast_spy.assert_not_called()


def test_late_guardian_decision_409_commits_fallback_without_approval_broadcast():
    """Late guardian decision returns HTTP 409 and suppresses GUARDIAN_DECISION WS broadcast."""
    settings = Settings(environment="test", mode="mock", allow_demo_auth=True)
    session = Mock(spec=Session)
    session.begin_nested.return_value = MagicMock()
    expired_payment = Payment(
        id="pg_expired_ws_001",
        payer_id=SYNTHETIC_PAYER_ID,
        beneficiary_id="vendor_expired_ws",
        amount_paise=6_000_000,
        purpose="expired deadline ws check",
        status=PaymentStatus.AWAITING_GUARDIAN.value,
        tier=3,
        risk_score=75,
        idempotency_key="idem_expired_ws_001",
        assigned_guardian_id=SYNTHETIC_GUARDIAN_ID,
        guardian_deadline=datetime.now(timezone.utc) - timedelta(seconds=10),
        version=1,
    )
    session.scalars.return_value.one_or_none.side_effect = [expired_payment, None]
    session.query.return_value.order_by.return_value.first.return_value = None

    app = create_app(settings, session_factory=lambda: session)
    client = TestClient(app)
    broadcast_spy = Mock()

    with patch("app.api.payments.broadcast_event_sync", broadcast_spy):
        res = client.post(
            f"/api/v2/payments/{expired_payment.id}/guardian/decision",
            headers=_headers("demo-token-guardian"),
            json={"approved": True, "notes": "Too late"},
        )
        assert res.status_code == 409
        assert res.json()["status"] == PaymentStatus.AWAITING_FALLBACK_REVIEW.value

    session.commit.assert_called_once()
    broadcast_spy.assert_not_called()


def test_create_payment_bounded_advisory_integration_and_degradation():
    """POST /api/v2/payments integrates bounded advisory evaluation without overriding Safe-Lock."""
    settings = Settings(environment="test", mode="mock", allow_demo_auth=True)
    app = create_app(settings)
    client = TestClient(app)

    prov = SignalProvenance(
        source_category=SourceCategory.TRUSTED_SOURCE,
        data_origin=DataOrigin.SYNTHETIC_FIXTURE,
        calculation_method=CalculationMethod.HEURISTIC_RULE_ENGINE,
        is_synthetic=True,
    )

    def _make_high_risk_response(req):
        signals = RiskSignals(
            generated_at=datetime.now(timezone.utc),
            evaluation_latency_ms=1.0,
            evaluation_status=EvaluationStatus.COMPLETE,
            suggested_caution_level=SuggestedCautionLevel.CRITICAL,
            payment_id=req.payment_id,
            payer_id=req.payer_id,
            beneficiary_id=req.beneficiary_id,
            amount_paise=req.amount_paise,
            advisory_score=92,
            reason_codes=("RC_ADVISORY_SCORE_CRITICAL",),
            behavioral=BehavioralSignal(status="unavailable", provenance=prov),
            velocity=VelocitySignal(status="unavailable", provenance=prov),
            registry=RegistrySignal(check_status="performed", is_listed_high_risk=False, provenance=prov),
            mule_graph=MuleGraphSignal(
                status="evaluated",
                hop_distance_to_flagged_mule=1,
                cluster_risk_score=90,
                provenance=prov,
            ),
            transcript=TranscriptCoercionSignal(status="absent", provenance=prov),
        )
        return AdvisoryResponse(risk_signals=signals, evaluator_timings_ms={}, warnings=())

    # 1. Critical advisory signal escalates a small ₹500 transfer to Tier 3 AWAITING_GUARDIAN (never executes)
    with patch("app.api.payments.evaluate_advisory", side_effect=_make_high_risk_response):
        esc = client.post(
            "/api/v2/payments",
            headers=_headers("demo-token-payer"),
            json={
                "beneficiary_id": "new_vendor_advisory",
                "amount_paise": 50_000,
                "purpose": "normal gift",
                "idempotency_key": "idem_adv_esc_001",
            },
        )
        assert esc.status_code == 201
        data = esc.json()
        assert data["tier"] == 3
        assert data["status"] == PaymentStatus.AWAITING_GUARDIAN.value

    # 2. Evaluator timeout degrades safely to deterministic baseline without blocking request
    def _slow_eval(_req):
        sleep(0.15)
        raise TimeoutError("simulated timeout")

    with patch("app.api.payments._ADVISORY_TIMEOUT_SECONDS", 0.02):
        with patch("app.api.payments.evaluate_advisory", side_effect=_slow_eval):
            degraded = client.post(
                "/api/v2/payments",
                headers=_headers("demo-token-payer"),
                json={
                    "beneficiary_id": "normal_vendor",
                    "amount_paise": 25_000,
                    "purpose": "groceries",
                    "idempotency_key": "idem_adv_timeout_001",
                },
            )
            assert degraded.status_code == 201
            assert degraded.json()["status"] == PaymentStatus.READY_TO_EXECUTE.value

    # 3. Engage Safe-Lock: even low-risk advisory cannot override Safe-Lock 423
    sl = client.post(
        "/api/v2/safe-lock",
        headers=_headers("demo-token-payer"),
        json={"is_locked": True},
    )
    assert sl.status_code == 200
    blocked = client.post(
        "/api/v2/payments",
        headers=_headers("demo-token-payer"),
        json={
            "beneficiary_id": "normal_vendor",
            "amount_paise": 10_000,
            "purpose": "groceries",
            "idempotency_key": "idem_adv_sl_001",
        },
    )
    assert blocked.status_code == 423


def test_policy_lab_simulation_rbac_and_benchmark_contract():
    """POST /api/v2/policy-lab/simulate enforces analyst/admin RBAC and returns valid comparison."""
    settings = Settings(environment="test", mode="mock", allow_demo_auth=True)
    app = create_app(settings)
    client = TestClient(app)

    # Payer is forbidden
    payer_res = client.post(
        "/api/v2/policy-lab/simulate",
        headers=_headers("demo-token-payer"),
        json={"seed": 42, "sample_size": 12},
    )
    assert payer_res.status_code == 403

    # Analyst succeeds
    analyst_res = client.post(
        "/api/v2/policy-lab/simulate",
        headers=_headers("demo-token-analyst"),
        json={"seed": 42, "sample_size": 12},
    )
    assert analyst_res.status_code == 200
    body = analyst_res.json()
    assert body["dataset_split"] == "test"
    assert body["is_synthetic"] is True
    assert "policy_metrics" in body and isinstance(body["policy_metrics"], dict)
    assert len(body["policy_metrics"]) >= 3

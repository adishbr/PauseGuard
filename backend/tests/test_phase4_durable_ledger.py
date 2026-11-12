"""Comprehensive Phase 4A offline test suite for durable payment and ledger engine.

Tests:
1. Database-backed idempotency & deduplication.
2. Safe terminal-state transition enforcement (EXECUTED, REJECTED, CANCELLED, EXPIRED, FAILED).
3. Atomic mock ledger debit & balance conservation.
4. Insufficient mock balance rejection (HTTP 400).
5. Safe-Lock rechecked live at confirmation (HTTP 423).
6. Payment cancellation vs execution.
7. Guardian approval vs timeout race and immutability.
8. Transaction rollback & failure resilience.
9. Cryptographic audit event chaining.
10. Multi-threaded concurrency safeguards (no double debit).
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, Mock, patch
from uuid import UUID, uuid4

import hashlib
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.orm.exc import StaleDataError

from app.auth.identities import (
    SYNTHETIC_ADMIN_ID,
    SYNTHETIC_ANALYST_ID,
    SYNTHETIC_GUARDIAN_ID,
    SYNTHETIC_OTHER_PAYER_ID,
    SYNTHETIC_PAYER_ID,
)
from app.auth.schemas import (
    GuardianDecisionRequest,
    PaymentConfirmRequest,
    PaymentCreateRequest,
)
from app.config import Settings
from app.main import create_app
from app.models.account import MockAccount
from app.models.audit import AuditEvent
from app.models.idempotency import IdempotencyRecord
from app.models.ledger import LedgerEntry
from app.models.metadata import metadata
from app.models.payment import GuardianDecision, Payment
from app.models.roles import UserRole
from app.models.safe_lock import SafeLockState
from app.models.user import RoleBinding, SyntheticUser
from app.services.durable_payment_engine import DurablePaymentEngine
from app.services.payment_guards import PaymentStatus, TrustedActorContext
from app.services.payment_service import get_payment_service
from app.services.transactions import TransactionScopeError, transaction_scope


@pytest.fixture(autouse=True)
def reset_service_state():
    service = get_payment_service()
    service.reset_for_testing()
    yield
    service.reset_for_testing()


@pytest.fixture
def app():
    settings = Settings(environment="test", mode="mock", allow_demo_auth=True)
    return create_app(settings)


@pytest.fixture
def client(app):
    return TestClient(app)


def auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ===========================================================================
# 1. API-Level Mock Ledger, Balance & Idempotency Tests
# ===========================================================================

def test_atomic_mock_ledger_debit_and_balance_conservation(client):
    """Payer confirming payment executes an atomic mock ledger debit, conserving balance."""
    service = get_payment_service()
    initial_balance = service.get_account_balance(SYNTHETIC_PAYER_ID)
    amount_paise = 2500000  # ₹25,000 (Tier 0)

    create_resp = client.post(
        "/api/v2/payments",
        json={
            "beneficiary_id": "vendor_store_01",
            "amount_paise": amount_paise,
            "purpose": "office supplies",
            "idempotency_key": "idem_ledger_001",
        },
        headers=auth_header("demo-token-payer"),
    )
    assert create_resp.status_code == 201
    payment_id = create_resp.json()["id"]
    assert create_resp.json()["status"] == "READY_TO_EXECUTE"

    # Confirm payment
    confirm_resp = client.post(
        f"/api/v2/payments/{payment_id}/confirm",
        json={"idempotency_key": "confirm_key_001"},
        headers=auth_header("demo-token-payer"),
    )
    assert confirm_resp.status_code == 200
    assert confirm_resp.json()["status"] == "EXECUTED"

    # Verify balance was debited by exactly amount_paise
    final_balance = service.get_account_balance(SYNTHETIC_PAYER_ID)
    assert final_balance == initial_balance - amount_paise

    # Verify immutable ledger entry
    entries = service.get_ledger_entries(payment_id)
    assert len(entries) == 1
    entry = entries[0]
    assert entry["payment_id"] == payment_id
    assert entry["amount_paise"] == amount_paise
    assert entry["entry_type"] == "DEBIT"
    assert entry["idempotency_key"] == f"debit_{payment_id}_confirm_key_001"


def test_insufficient_mock_balance_rejects_confirmation_without_debit(client):
    """If payer has insufficient mock funds, confirmation fails with 400 and no debit occurs."""
    service = get_payment_service()
    # Set low balance
    service.set_account_balance(SYNTHETIC_PAYER_ID, 500000)  # ₹5,000

    create_resp = client.post(
        "/api/v2/payments",
        json={
            "beneficiary_id": "vendor_store_02",
            "amount_paise": 1000000,  # ₹10,000 > ₹5,000 balance
            "purpose": "expensive gadget",
            "idempotency_key": "idem_balance_001",
        },
        headers=auth_header("demo-token-payer"),
    )
    assert create_resp.status_code == 201
    payment_id = create_resp.json()["id"]

    confirm_resp = client.post(
        f"/api/v2/payments/{payment_id}/confirm",
        json={"idempotency_key": "confirm_balance_001"},
        headers=auth_header("demo-token-payer"),
    )
    assert confirm_resp.status_code == 400
    assert "Insufficient mock account balance" in confirm_resp.json()["detail"]

    # Balance remains completely untouched
    assert service.get_account_balance(SYNTHETIC_PAYER_ID) == 500000
    assert len(service.get_ledger_entries(payment_id)) == 0


def test_duplicate_confirmation_retries_prevent_double_debit(client):
    """Duplicate confirmation requests with identical idempotency key return cached result without double debit."""
    service = get_payment_service()
    initial_balance = service.get_account_balance(SYNTHETIC_PAYER_ID)
    amount_paise = 1500000  # ₹15,000

    create_resp = client.post(
        "/api/v2/payments",
        json={
            "beneficiary_id": "vendor_store_03",
            "amount_paise": amount_paise,
            "purpose": "consulting services",
            "idempotency_key": "idem_retry_001",
        },
        headers=auth_header("demo-token-payer"),
    )
    payment_id = create_resp.json()["id"]

    # First confirmation
    resp1 = client.post(
        f"/api/v2/payments/{payment_id}/confirm",
        json={"idempotency_key": "confirm_retry_key_001"},
        headers=auth_header("demo-token-payer"),
    )
    assert resp1.status_code == 200

    # Retry confirmation with identical idempotency key
    resp2 = client.post(
        f"/api/v2/payments/{payment_id}/confirm",
        json={"idempotency_key": "confirm_retry_key_001"},
        headers=auth_header("demo-token-payer"),
    )
    assert resp2.status_code == 200
    assert resp2.json()["confirmed_at"] == resp1.json()["confirmed_at"]

    # Exactly ONE debit occurred in the ledger
    assert service.get_account_balance(SYNTHETIC_PAYER_ID) == initial_balance - amount_paise
    assert len(service.get_ledger_entries(payment_id)) == 1


def test_concurrent_confirmations_prevent_double_debit(client):
    """Multi-threaded concurrent confirmation attempts: exactly one debit succeeds."""
    service = get_payment_service()
    initial_balance = service.get_account_balance(SYNTHETIC_PAYER_ID)
    amount_paise = 3000000  # ₹30,000

    create_resp = client.post(
        "/api/v2/payments",
        json={
            "beneficiary_id": "vendor_concurrent_01",
            "amount_paise": amount_paise,
            "purpose": "concurrent test",
            "idempotency_key": "idem_conc_001",
        },
        headers=auth_header("demo-token-payer"),
    )
    payment_id = create_resp.json()["id"]

    results = []
    def confirm_attempt(key: str):
        resp = client.post(
            f"/api/v2/payments/{payment_id}/confirm",
            json={"idempotency_key": key},
            headers=auth_header("demo-token-payer"),
        )
        results.append(resp.status_code)

    # 4 concurrent threads attempting confirmation with different keys
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(confirm_attempt, f"key_conc_{i}") for i in range(4)]
        for f in futures:
            f.result()

    assert results.count(200) == 1
    assert results.count(409) == 3
    # Balance was debited exactly once
    assert service.get_account_balance(SYNTHETIC_PAYER_ID) == initial_balance - amount_paise
    assert len(service.get_ledger_entries(payment_id)) == 1


def test_safe_lock_rechecked_at_confirmation_blocks_execution(client):
    """Safe-Lock rechecked live at confirmation rejects transition with 423 Locked and no debit."""
    service = get_payment_service()
    initial_balance = service.get_account_balance(SYNTHETIC_PAYER_ID)

    create_resp = client.post(
        "/api/v2/payments",
        json={
            "beneficiary_id": "merchant_safelock_01",
            "amount_paise": 2000000,
            "purpose": "safe lock check",
            "idempotency_key": "idem_lock_001",
        },
        headers=auth_header("demo-token-payer"),
    )
    payment_id = create_resp.json()["id"]

    # Engage Safe-Lock before confirmation
    service.set_safe_lock(SYNTHETIC_PAYER_ID, is_locked=True)

    confirm_resp = client.post(
        f"/api/v2/payments/{payment_id}/confirm",
        json={"idempotency_key": "confirm_lock_001"},
        headers=auth_header("demo-token-payer"),
    )
    assert confirm_resp.status_code == 423
    assert "Safe-Lock is currently engaged" in confirm_resp.json()["detail"]

    # Balance preserved, no ledger entry
    assert service.get_account_balance(SYNTHETIC_PAYER_ID) == initial_balance
    assert len(service.get_ledger_entries(payment_id)) == 0


def test_payment_cancellation_vs_execution(client):
    """Payer can cancel non-terminal payment; cancelled payment cannot be confirmed or re-executed."""
    service = get_payment_service()
    initial_balance = service.get_account_balance(SYNTHETIC_PAYER_ID)

    create_resp = client.post(
        "/api/v2/payments",
        json={
            "beneficiary_id": "vendor_cancel_01",
            "amount_paise": 1800000,
            "purpose": "cancellation test",
            "idempotency_key": "idem_cancel_001",
        },
        headers=auth_header("demo-token-payer"),
    )
    payment_id = create_resp.json()["id"]

    # Cancel payment
    cancel_resp = client.post(
        f"/api/v2/payments/{payment_id}/cancel",
        headers=auth_header("demo-token-payer"),
    )
    assert cancel_resp.status_code == 200
    assert cancel_resp.json()["status"] == "CANCELLED"

    # Confirmation of cancelled payment fails with 409 Conflict
    confirm_resp = client.post(
        f"/api/v2/payments/{payment_id}/confirm",
        json={"idempotency_key": "confirm_cancelled_001"},
        headers=auth_header("demo-token-payer"),
    )
    assert confirm_resp.status_code == 409

    # Zero debit occurred
    assert service.get_account_balance(SYNTHETIC_PAYER_ID) == initial_balance
    assert len(service.get_ledger_entries(payment_id)) == 0


def test_terminal_state_immutability(client):
    """Terminal state EXECUTED cannot be modified by decisions, cancellations, or confirmations."""
    create_resp = client.post(
        "/api/v2/payments",
        json={
            "beneficiary_id": "vendor_term_01",
            "amount_paise": 1000000,
            "purpose": "terminal immutability",
            "idempotency_key": "idem_term_001",
        },
        headers=auth_header("demo-token-payer"),
    )
    payment_id = create_resp.json()["id"]

    # Confirm to EXECUTED
    client.post(
        f"/api/v2/payments/{payment_id}/confirm",
        json={"idempotency_key": "confirm_term_001"},
        headers=auth_header("demo-token-payer"),
    )

    # Attempting cancellation on EXECUTED fails with 409
    cancel_resp = client.post(
        f"/api/v2/payments/{payment_id}/cancel",
        headers=auth_header("demo-token-payer"),
    )
    assert cancel_resp.status_code == 409

    # Attempting guardian decision on EXECUTED fails with 409
    decision_resp = client.post(
        f"/api/v2/payments/{payment_id}/guardian/decision",
        json={"approved": True},
        headers=auth_header("demo-token-guardian"),
    )
    assert decision_resp.status_code == 409

    # Attempting second confirmation with different key fails with 409
    second_confirm_resp = client.post(
        f"/api/v2/payments/{payment_id}/confirm",
        json={"idempotency_key": "different_confirm_key"},
        headers=auth_header("demo-token-payer"),
    )
    assert second_confirm_resp.status_code == 409


# ===========================================================================
# 2. Durable Database Engine & Session Level Tests
# ===========================================================================

def test_durable_engine_audit_event_hash_chain():
    """DurablePaymentEngine computes SHA-256 hash chains across consecutive audit events."""
    session = Mock(spec=Session)
    events_added = []
    session.add.side_effect = lambda entity: events_added.append(entity)
    session.query.return_value.order_by.return_value.first.return_value = None

    engine = DurablePaymentEngine(session)
    actor = TrustedActorContext(SYNTHETIC_PAYER_ID, frozenset({UserRole.PAYER}))

    # First event
    ev1 = engine._append_audit_event("PAYMENT_CREATED", actor, payment_id="pg_001", payload={"test": 1})
    assert ev1.prev_hash == "0" * 64
    assert len(ev1.event_hash) == 64

    # Second event linked to first
    session.query.return_value.order_by.return_value.first.return_value = ev1
    ev2 = engine._append_audit_event("PAYMENT_EXECUTED", actor, payment_id="pg_001", payload={"test": 2})
    assert ev2.prev_hash == ev1.event_hash
    assert ev2.event_hash != ev1.event_hash


def test_durable_engine_confirm_payment_atomic_flow():
    """DurablePaymentEngine confirm_payment locks rows, checks balance, debits, and adds ledger entry."""
    session = Mock(spec=Session)
    payment = Payment(
        id="pg_flow_001",
        payer_id=SYNTHETIC_PAYER_ID,
        beneficiary_id="vendor_flow",
        amount_paise=5000000,
        purpose="test",
        status="READY_TO_EXECUTE",
        tier=0,
        idempotency_key="create_flow_key",
        version=1,
    )
    account = MockAccount(
        id=uuid4(),
        owner_id=SYNTHETIC_PAYER_ID,
        balance_paise=10000000,  # ₹100,000
        version=1,
    )
    safe_lock = SafeLockState(
        payer_id=SYNTHETIC_PAYER_ID,
        is_locked=False,
        version=1,
    )

    added_objects = []
    session.add.side_effect = lambda obj: added_objects.append(obj)

    # Mock scalars responses for:
    # 1. idempotency_record_for_update -> None
    # 2. payment_for_update -> payment
    # 3. safe_lock_for_payer_for_update -> safe_lock
    # 4. payer_account_for_update -> account
    session.scalars.return_value.one_or_none.side_effect = [
        None,        # idempotency check
        payment,     # payment row
        safe_lock,   # safe lock
        account,     # account row
    ]

    engine = DurablePaymentEngine(session)
    actor = TrustedActorContext(SYNTHETIC_PAYER_ID, frozenset({UserRole.PAYER}))
    req = PaymentConfirmRequest(idempotency_key="confirm_flow_001")

    res = engine.confirm_payment(actor, payment.id, req)

    assert res.status == "EXECUTED"
    assert payment.status == "EXECUTED"
    assert payment.version == 2
    assert account.balance_paise == 5000000  # Debited 10M -> 5M
    assert account.version == 2

    # Check added ledger entry, idempotency record, and audit event
    ledger_entries = [o for o in added_objects if isinstance(o, LedgerEntry)]
    assert len(ledger_entries) == 1
    assert ledger_entries[0].amount_paise == 5000000
    assert ledger_entries[0].entry_type == "DEBIT"

    idem_records = [o for o in added_objects if isinstance(o, IdempotencyRecord)]
    assert len(idem_records) == 1
    assert idem_records[0].key == "confirm_flow_001"

    audit_events = [o for o in added_objects if isinstance(o, AuditEvent)]
    assert len(audit_events) == 1
    assert audit_events[0].event_type == "PAYMENT_EXECUTED"


def test_durable_engine_confirm_payment_rollback_on_insufficient_balance():
    """If account has insufficient balance, exception is raised before any mutation."""
    session = Mock(spec=Session)
    payment = Payment(
        id="pg_insuf_001",
        payer_id=SYNTHETIC_PAYER_ID,
        beneficiary_id="vendor_flow",
        amount_paise=5000000,
        purpose="test",
        status="READY_TO_EXECUTE",
        tier=0,
        idempotency_key="key_insuf",
        version=1,
    )
    account = MockAccount(
        id=uuid4(),
        owner_id=SYNTHETIC_PAYER_ID,
        balance_paise=1000000,  # ₹10,000 < ₹50,000 required
        version=1,
    )
    safe_lock = SafeLockState(payer_id=SYNTHETIC_PAYER_ID, is_locked=False, version=1)

    session.scalars.return_value.one_or_none.side_effect = [
        None, payment, safe_lock, account,
    ]

    engine = DurablePaymentEngine(session)
    actor = TrustedActorContext(SYNTHETIC_PAYER_ID, frozenset({UserRole.PAYER}))
    req = PaymentConfirmRequest(idempotency_key="confirm_insuf_001")

    with pytest.raises(Exception) as exc_info:
        engine.confirm_payment(actor, payment.id, req)
    assert "Insufficient mock account balance" in str(exc_info.value)

    # Balance remains untouched
    assert account.balance_paise == 1000000
    assert payment.status == "READY_TO_EXECUTE"


# ===========================================================================
# 4. Phase 4 Comprehensive Deterministic Policy & Warning Tests
# ===========================================================================

def test_warning_acknowledgment_flow(client):
    """Payment with coercive purpose triggers Tier 1 AWAITING_WARNING; payer can acknowledge to READY_TO_EXECUTE."""
    create_resp = client.post(
        "/api/v2/payments",
        json={
            "beneficiary_id": "vendor_store_warning",
            "amount_paise": 1500000,  # ₹15,000 (< ₹50k, but urgent coercion)
            "purpose": "urgent emergency money needed right now",
            "idempotency_key": "idem_warn_001",
        },
        headers=auth_header("demo-token-payer"),
    )
    assert create_resp.status_code == 201
    data = create_resp.json()
    assert data["status"] == "AWAITING_WARNING"
    assert data["tier"] == 1
    payment_id = data["id"]

    # Non-payer role cannot acknowledge warning -> 403 Forbidden
    non_payer_ack = client.post(
        f"/api/v2/payments/{payment_id}/warning/acknowledge",
        headers=auth_header("demo-token-guardian"),
    )
    assert non_payer_ack.status_code == 403

    # Owning payer acknowledges warning
    ack_resp = client.post(
        f"/api/v2/payments/{payment_id}/warning/acknowledge",
        headers=auth_header("demo-token-payer"),
    )
    assert ack_resp.status_code == 200
    ack_data = ack_resp.json()
    assert ack_data["status"] == "READY_TO_EXECUTE"
    assert ack_data["can_execute_payment"] is False

    # Acknowledging again fails with 409 Conflict (not in AWAITING_WARNING)
    dup_ack = client.post(
        f"/api/v2/payments/{payment_id}/warning/acknowledge",
        headers=auth_header("demo-token-payer"),
    )
    assert dup_ack.status_code == 409

    # Now payer can confirm payment to EXECUTED
    confirm_resp = client.post(
        f"/api/v2/payments/{payment_id}/confirm",
        json={"idempotency_key": "confirm_warn_001"},
        headers=auth_header("demo-token-payer"),
    )
    assert confirm_resp.status_code == 200
    assert confirm_resp.json()["status"] == "EXECUTED"


def test_profile_aware_risk_policy_evaluations():
    """Verify deterministic policy engine behavior across personal, business, and fraud registry cases."""
    from app.services.policy_engine import evaluate_payment_policy, RiskTier
    from intelligence.schemas.risk_signals import AccountProfileType

    payer_id = uuid4()

    # 1. Normal personal transaction: ₹1,000 -> Tier 0
    t0_res = evaluate_payment_policy(
        payer_id=payer_id,
        amount_paise=100000,
        beneficiary_id="vendor_groceries",
        purpose="groceries",
        profile_type=AccountProfileType.PERSONAL,
    )
    assert t0_res.tier == RiskTier.TIER_0
    assert t0_res.target_status == "READY_TO_EXECUTE"

    # 2. High-value personal transaction: ₹55,000 -> Tier 3
    t3_res = evaluate_payment_policy(
        payer_id=payer_id,
        amount_paise=5500000,
        beneficiary_id="vendor_electronics",
        purpose="laptop purchase",
        profile_type=AccountProfileType.PERSONAL,
    )
    assert t3_res.tier == RiskTier.TIER_3
    assert t3_res.requires_guardian is True
    assert "RC_LARGE_AMOUNT_DEVIATION" in t3_res.reason_codes

    # 3. Commercial transaction: ₹50,000 to new supplier -> Tier 0 (ordinary baseline)
    biz_res = evaluate_payment_policy(
        payer_id=payer_id,
        amount_paise=5000000,
        beneficiary_id="supplier_metals",
        purpose="raw material shipment",
        profile_type=AccountProfileType.SMALL_BUSINESS,
    )
    assert biz_res.tier == RiskTier.TIER_0
    assert biz_res.target_status == "READY_TO_EXECUTE"

    # 4. Known fraud registry hit -> Hard block / REJECTED
    fraud_res = evaluate_payment_policy(
        payer_id=payer_id,
        amount_paise=100000,
        beneficiary_id="flagged_mule_01",
        purpose="services",
    )
    assert fraud_res.is_hard_blocked is True
    assert fraud_res.target_status == "REJECTED"
    assert "RC_CONFIRMED_FRAUD_REGISTRY" in fraud_res.reason_codes


def test_durable_engine_warning_acknowledgment_offline():
    """DurablePaymentEngine directly transitions AWAITING_WARNING to READY_TO_EXECUTE with audit logging."""
    session = Mock(spec=Session)
    payment = Payment(
        id="pg_warn_engine_001",
        payer_id=SYNTHETIC_PAYER_ID,
        beneficiary_id="vendor_warn",
        amount_paise=1000000,
        purpose="test warning",
        status="AWAITING_WARNING",
        tier=1,
        idempotency_key="key_warn",
        version=1,
    )
    session.scalars.return_value.one_or_none.return_value = payment
    session.query.return_value.order_by.return_value.first.return_value = None

    added_objects = []
    session.add.side_effect = lambda obj: added_objects.append(obj)

    engine = DurablePaymentEngine(session)
    actor = TrustedActorContext(SYNTHETIC_PAYER_ID, frozenset({UserRole.PAYER}))

    resp = engine.acknowledge_warning(actor, payment.id)

    assert resp.status == "READY_TO_EXECUTE"
    assert payment.status == "READY_TO_EXECUTE"
    assert payment.version == 2
    assert resp.can_execute_payment is False

    audit_events = [o for o in added_objects if isinstance(o, AuditEvent)]
    assert len(audit_events) == 1
    assert audit_events[0].event_type == "WARNING_ACKNOWLEDGED"


def test_double_entry_ledger_funds_conservation_p2p(client):
    """Internal P2P transfer between registered users records BOTH debit and credit ledger entries and conserves total funds."""
    service = get_payment_service()
    payer_id = SYNTHETIC_PAYER_ID
    payee_id = SYNTHETIC_OTHER_PAYER_ID

    # Initial balances
    initial_payer_balance = 50000000  # ₹500,000
    initial_payee_balance = 10000000  # ₹100,000
    service.set_account_balance(payer_id, initial_payer_balance)
    service.set_account_balance(payee_id, initial_payee_balance)

    transfer_amount = 2000000  # ₹20,000

    create_resp = client.post(
        "/api/v2/payments",
        json={
            "beneficiary_id": str(payee_id),
            "amount_paise": transfer_amount,
            "purpose": "reimbursement for lunch",
            "idempotency_key": "idem_p2p_001",
        },
        headers=auth_header("demo-token-payer"),
    )
    assert create_resp.status_code == 201
    payment_id = create_resp.json()["id"]

    # Confirm payment
    confirm_resp = client.post(
        f"/api/v2/payments/{payment_id}/confirm",
        json={"idempotency_key": "confirm_p2p_001"},
        headers=auth_header("demo-token-payer"),
    )
    assert confirm_resp.status_code == 200
    assert confirm_resp.json()["status"] == "EXECUTED"

    # Verify both accounts updated
    final_payer_balance = service.get_account_balance(payer_id)
    final_payee_balance = service.get_account_balance(payee_id)

    assert final_payer_balance == initial_payer_balance - transfer_amount
    assert final_payee_balance == initial_payee_balance + transfer_amount

    # Invariant: Total mock funds conserved exactly
    assert final_payer_balance + final_payee_balance == initial_payer_balance + initial_payee_balance

    # Verify 2 ledger entries: one DEBIT and one CREDIT
    entries = service.get_ledger_entries(payment_id)
    assert len(entries) == 2
    types = {e["entry_type"] for e in entries}
    assert types == {"DEBIT", "CREDIT"}
    for e in entries:
        assert e["amount_paise"] == transfer_amount


def _mock_scalars_with_safe_lock(user_id=SYNTHETIC_PAYER_ID, is_locked=False):
    def _scalars(stmt):
        res = Mock()
        sql_str = str(stmt).lower()
        if "safe_lock" in sql_str:
            res.one_or_none.return_value = SafeLockState(payer_id=user_id, is_locked=is_locked)
        else:
            res.one_or_none.return_value = None
        return res
    return _scalars


def test_fastapi_uses_durable_engine_when_session_factory_provided():
    """FastAPI routes to DurablePaymentEngine and commits session when session_factory is present."""
    mock_session = Mock(spec=Session)
    mock_session.scalars.side_effect = _mock_scalars_with_safe_lock()
    mock_session.query.return_value.filter.return_value.one_or_none.return_value = None
    mock_session.query.return_value.order_by.return_value.first.return_value = None

    mock_factory = Mock(return_value=mock_session)

    settings = Settings(environment="test", mode="mock", allow_demo_auth=True)
    custom_app = create_app(settings, session_factory=mock_factory)
    custom_client = TestClient(custom_app)

    resp = custom_client.post(
        "/api/v2/payments",
        json={
            "beneficiary_id": "vendor_durable_check",
            "amount_paise": 1000000,
            "purpose": "durable injection check",
            "idempotency_key": "idem_durable_inject_001",
        },
        headers=auth_header("demo-token-payer"),
    )
    assert resp.status_code == 201

    # Verify mock_factory was called to create a DB session
    assert mock_factory.call_count == 1
    # Verify session was committed
    assert mock_session.commit.call_count >= 1
    # Verify session was closed
    assert mock_session.close.call_count == 1


def test_idempotency_conflicting_payload_fails_in_durable_engine():
    """DurablePaymentEngine rejects reused idempotency key with conflicting payload (HTTP 409)."""
    session = Mock(spec=Session)
    # Existing idempotency record with hash of different payload
    existing_record = IdempotencyRecord(
        key="reused_key_001",
        caller_id=SYNTHETIC_PAYER_ID,
        endpoint="/api/v2/payments",
        request_hash="different_request_hash_value",
        response_status=201,
        response_body={},
    )
    session.scalars.return_value.one_or_none.return_value = existing_record

    engine = DurablePaymentEngine(session)
    actor = TrustedActorContext(SYNTHETIC_PAYER_ID, frozenset({UserRole.PAYER}))
    req = PaymentCreateRequest(
        beneficiary_id="vendor_conflicting",
        amount_paise=1000000,
        purpose="conflict test",
        idempotency_key="reused_key_001",
    )

    with pytest.raises(Exception) as exc_info:
        engine.create_payment(actor, req)
    assert "mismatched request parameters" in str(exc_info.value)


def test_payment_and_audit_insertion_ordering_and_referential_integrity():
    """Verify Payment row is flushed before dependent AuditEvent and IdempotencyRecord."""
    session = Mock(spec=Session)
    call_log = []

    def mock_add(obj):
        call_log.append(("add", type(obj).__name__, getattr(obj, "id", None)))

    def mock_flush():
        call_log.append(("flush", None, None))

    session.add.side_effect = mock_add
    session.flush.side_effect = mock_flush
    session.scalars.side_effect = _mock_scalars_with_safe_lock()
    session.query.return_value.filter.return_value.one_or_none.return_value = None
    session.query.return_value.order_by.return_value.first.return_value = None

    engine = DurablePaymentEngine(session)
    actor = TrustedActorContext(SYNTHETIC_PAYER_ID, frozenset({UserRole.PAYER}))
    req = PaymentCreateRequest(
        beneficiary_id="vendor_order_01",
        amount_paise=50_000,
        purpose="ordering verification",
        idempotency_key="idem_order_offline_001",
    )

    view = engine.create_payment(actor, req)

    # Verify exact call order:
    # 1. add Payment
    # 2. flush Payment (so foreign key target exists in current transaction)
    # 3. add IdempotencyRecord
    # 4. add AuditEvent
    # 5. flush AuditEvent / IdempotencyRecord
    add_payment_idx = next(i for i, c in enumerate(call_log) if c[0] == "add" and c[1] == "Payment")
    first_flush_idx = next(i for i, c in enumerate(call_log) if c[0] == "flush")
    add_audit_idx = next(i for i, c in enumerate(call_log) if c[0] == "add" and c[1] == "AuditEvent")

    assert add_payment_idx < first_flush_idx < add_audit_idx
    assert view.id.startswith("pg_")
    assert view.status == "READY_TO_EXECUTE"


def test_rollback_when_audit_persistence_fails():
    """If audit event persistence fails, the entire transaction rolls back atomically without commit."""
    session = Mock(spec=Session)
    session.in_transaction.return_value = False
    session.scalars.side_effect = _mock_scalars_with_safe_lock()
    session.query.return_value.filter.return_value.one_or_none.return_value = None
    session.query.return_value.order_by.return_value.first.return_value = None

    engine = DurablePaymentEngine(session)
    actor = TrustedActorContext(SYNTHETIC_PAYER_ID, frozenset({UserRole.PAYER}))
    fail_key = "idem_fail_offline_001"
    req = PaymentCreateRequest(
        beneficiary_id="vendor_fail_01",
        amount_paise=75_000,
        purpose="failure atomicity check",
        idempotency_key=fail_key,
    )

    with patch.object(engine, "_append_audit_event", side_effect=RuntimeError("Simulated audit disk failure")):
        with pytest.raises(RuntimeError):
            with transaction_scope(session):
                engine.create_payment(actor, req)

    # Verify commit was never called and rollback was executed
    assert session.commit.call_count == 0
    assert session.rollback.call_count >= 1


def test_idempotent_retry_after_rollback_succeeds():
    """Client can retry with the same idempotency key after a rolled-back failed creation."""
    actor = TrustedActorContext(SYNTHETIC_PAYER_ID, frozenset({UserRole.PAYER}))
    retry_key = "idem_retry_offline_001"
    req = PaymentCreateRequest(
        beneficiary_id="vendor_retry_01",
        amount_paise=90_000,
        purpose="retry check",
        idempotency_key=retry_key,
    )

    # First attempt: session1 fails during audit persistence and rolls back
    session1 = Mock(spec=Session)
    session1.in_transaction.return_value = False
    session1.scalars.side_effect = _mock_scalars_with_safe_lock()
    session1.query.return_value.filter.return_value.one_or_none.return_value = None
    session1.query.return_value.order_by.return_value.first.return_value = None
    engine1 = DurablePaymentEngine(session1)

    with patch.object(engine1, "_append_audit_event", side_effect=RuntimeError("Simulated transient failure")):
        with pytest.raises(RuntimeError):
            with transaction_scope(session1):
                engine1.create_payment(actor, req)

    assert session1.commit.call_count == 0
    assert session1.rollback.call_count >= 1

    # Second attempt: retry with a fresh session succeeds and commits
    session2 = Mock(spec=Session)
    session2.in_transaction.return_value = False
    session2.scalars.side_effect = _mock_scalars_with_safe_lock()
    session2.query.return_value.filter.return_value.one_or_none.return_value = None
    session2.query.return_value.order_by.return_value.first.return_value = None
    engine2 = DurablePaymentEngine(session2)

    with transaction_scope(session2):
        view = engine2.create_payment(actor, req)

    assert view.id.startswith("pg_")
    assert view.status == "READY_TO_EXECUTE"
    assert session2.commit.call_count == 1


def test_optimistic_concurrency_version_conflict_offline():
    """StaleDataError is raised when concurrent sessions modify the same payment record."""
    session = Mock(spec=Session)
    session.in_transaction.return_value = False
    payment = Payment(
        id="pg_conc_001",
        payer_id=SYNTHETIC_PAYER_ID,
        beneficiary_id="vendor_conc",
        amount_paise=100_000,
        purpose="concurrency check",
        status="READY_TO_EXECUTE",
        tier=0,
        idempotency_key="create_conc_key",
        version=1,
    )
    # Simulate a stale version collision on update: commit raises StaleDataError
    session.scalars.return_value.one_or_none.return_value = payment
    session.commit.side_effect = StaleDataError("UPDATE statement on table 'payments' expected to update 1 row(s); 0 were matched.")

    engine = DurablePaymentEngine(session)
    actor = TrustedActorContext(SYNTHETIC_PAYER_ID, frozenset({UserRole.PAYER}))

    with pytest.raises(TransactionScopeError) as exc_info:
        with transaction_scope(session):
            engine.cancel_payment(actor, payment.id)

    assert "Transaction commit failed" in str(exc_info.value)
    assert session.rollback.call_count >= 1


def test_safe_lock_missing_record_fails_closed_on_payment_creation():
    """Missing SafeLockState record in DurablePaymentEngine fails closed with HTTP 423."""
    session = Mock(spec=Session)
    # scalars returns None for both idempotency and safe-lock
    session.scalars.return_value.one_or_none.return_value = None
    session.query.return_value.filter.return_value.one_or_none.return_value = None

    engine = DurablePaymentEngine(session)
    actor = TrustedActorContext(SYNTHETIC_PAYER_ID, frozenset({UserRole.PAYER}))
    req = PaymentCreateRequest(
        beneficiary_id="vendor_safe_lock_test",
        amount_paise=10_000,
        purpose="safe-lock missing check",
        idempotency_key="idem_safe_missing_001",
    )

    with pytest.raises(HTTPException) as exc_info:
        engine.create_payment(actor, req)

    assert exc_info.value.status_code == 423
    assert "Safe-Lock state is unavailable" in exc_info.value.detail


def test_safe_lock_missing_record_fails_closed_on_payment_confirmation():
    """Missing SafeLockState record in DurablePaymentEngine confirm_payment fails closed with HTTP 423."""
    session = Mock(spec=Session)
    payment = Payment(
        id="pg_safe_confirm_001",
        payer_id=SYNTHETIC_PAYER_ID,
        beneficiary_id="vendor_safe_confirm",
        amount_paise=10_000,
        purpose="safe-lock confirm check",
        status="READY_TO_EXECUTE",
        tier=0,
        idempotency_key="idem_safe_conf_001",
        version=1,
    )

    def _scalars(stmt):
        sql = str(stmt).lower()
        res = Mock()
        if "payments" in sql:
            res.one_or_none.return_value = payment
        elif "safe_lock" in sql:
            # Missing Safe-Lock row
            res.one_or_none.return_value = None
        else:
            res.one_or_none.return_value = None
        return res

    session.scalars.side_effect = _scalars
    engine = DurablePaymentEngine(session)
    actor = TrustedActorContext(SYNTHETIC_PAYER_ID, frozenset({UserRole.PAYER}))
    req = PaymentConfirmRequest(idempotency_key="idem_conf_safe_001")

    with pytest.raises(HTTPException) as exc_info:
        engine.confirm_payment(actor, payment.id, req)

    assert exc_info.value.status_code == 423
    assert "Safe-Lock record missing" in exc_info.value.detail


def test_unverified_guardian_decision_fails_closed():
    """Unverified guardian fails closed in verify_guardian_to_payer_relationship."""
    from app.auth.authorization import verify_guardian_to_payer_relationship
    from app.auth.exceptions import GuardianAssignmentError
    from app.services.guardian_service import get_guardian_service

    svc = get_guardian_service()
    unverified_guardian_id = uuid4()
    payer_id = SYNTHETIC_PAYER_ID

    # Payer is enrolled with SYNTHETIC_GUARDIAN_ID by default
    # If the guardian verification check returns False, it must raise GuardianAssignmentError
    with patch.object(svc, "is_guardian_verified", return_value=False):
        actor = TrustedActorContext(SYNTHETIC_GUARDIAN_ID, frozenset({UserRole.GUARDIAN}))
        with pytest.raises(GuardianAssignmentError) as exc_info:
            verify_guardian_to_payer_relationship(actor, payer_id=payer_id)

        assert "server-verified identity" in str(exc_info.value)


def test_create_payment_concurrent_integrity_error_handled_safely():
    """DurablePaymentEngine handles concurrent IntegrityError gracefully, returning existing payment view."""
    from sqlalchemy.exc import IntegrityError

    session = Mock(spec=Session)
    session.scalars.side_effect = _mock_scalars_with_safe_lock()
    session.query.return_value.filter.return_value.one_or_none.return_value = None
    session.query.return_value.order_by.return_value.first.return_value = None

    # First flush (payment insert) triggers an IntegrityError simulation
    existing_view_data = {
        "id": "pg_concurrent_idem_001",
        "beneficiary_id": "vendor_conc_race",
        "amount_paise": 50000,
        "purpose": "race check",
        "status": "READY_TO_EXECUTE",
        "tier": 0,
        "guardian_deadline": None,
        "assigned_guardian_id": None,
        "version": 1,
    }
    req = PaymentCreateRequest(
        beneficiary_id="vendor_conc_race",
        amount_paise=50000,
        purpose="race check",
        idempotency_key="idem_conc_race_001",
    )
    expected_hash = hashlib.sha256(
        f"{SYNTHETIC_PAYER_ID}:{req.beneficiary_id}:{req.amount_paise}:{req.purpose}".encode()
    ).hexdigest()

    committed_idem = IdempotencyRecord(
        key=req.idempotency_key,
        caller_id=SYNTHETIC_PAYER_ID,
        endpoint="/api/v2/payments",
        request_hash=expected_hash,
        response_status=201,
        response_body=existing_view_data,
    )

    call_phase = "before_race"

    def mock_flush():
        nonlocal call_phase
        call_phase = "after_race"
        raise IntegrityError("duplicate key", params={}, orig=Exception("unique constraint violated"))

    session.flush.side_effect = mock_flush

    def _scalars_race(stmt):
        sql = str(stmt).lower()
        res = Mock()
        if "idempotency_records" in sql:
            if call_phase == "before_race":
                res.one_or_none.return_value = None
            else:
                res.one_or_none.return_value = committed_idem
        elif "safe_lock" in sql:
            res.one_or_none.return_value = SafeLockState(payer_id=SYNTHETIC_PAYER_ID, is_locked=False)
        else:
            res.one_or_none.return_value = None
        return res

    session.scalars.side_effect = _scalars_race

    engine = DurablePaymentEngine(session)
    actor = TrustedActorContext(SYNTHETIC_PAYER_ID, frozenset({UserRole.PAYER}))

    view = engine.create_payment(actor, req)
    assert view.id == "pg_concurrent_idem_001"
    assert session.rollback.call_count >= 1


def test_durable_mode_guard_fails_closed_in_production_without_session_factory():
    """In-memory mock service is strictly prohibited in production; get_payment_engine raises HTTP 503."""
    from app.api.payments import get_payment_engine

    request_mock = Mock()
    request_mock.app.state.session_factory = None
    request_mock.app.state.settings = Mock(
        environment="production",
        mode="mock",
        allow_demo_auth=False,
    )

    gen = get_payment_engine(request_mock)
    with pytest.raises(HTTPException) as exc_info:
        next(gen)

    assert exc_info.value.status_code == 503
    assert "Durable persistence is required" in exc_info.value.detail


def test_advisory_signals_escalate_risk_tier_without_overriding_hard_blocks():
    """Advisory RiskSignals escalate tier to Tier 3 on high risk, but CANNOT bypass Safe-Lock or fraud registry."""
    from app.services.policy_engine import evaluate_payment_policy, RiskTier
    from intelligence.schemas.risk_signals import (
        RiskSignals,
        EvaluationStatus,
        SuggestedCautionLevel,
        BehavioralSignal,
        VelocitySignal,
        RegistrySignal,
        MuleGraphSignal,
        TranscriptCoercionSignal,
        SignalProvenance,
        SourceCategory,
        DataOrigin,
        CalculationMethod,
    )

    now = datetime.now(timezone.utc)
    prov = SignalProvenance(
        source_category=SourceCategory.TRUSTED_SOURCE,
        data_origin=DataOrigin.SYNTHETIC_FIXTURE,
        calculation_method=CalculationMethod.HEURISTIC_RULE_ENGINE,
        is_synthetic=True,
    )

    high_risk_advisory = RiskSignals(
        generated_at=now,
        evaluation_latency_ms=12.5,
        evaluation_status=EvaluationStatus.COMPLETE,
        suggested_caution_level=SuggestedCautionLevel.HIGH,
        payment_id="pg_advisory_001",
        payer_id=str(SYNTHETIC_PAYER_ID),
        beneficiary_id="vendor_advisory_test",
        amount_paise=100000,  # ₹1,000 (ordinarily Tier 0)
        advisory_score=85,     # Critical advisory score >= 80 -> escalates to Tier 3
        reason_codes=("RC_MULE_CLUSTER_HIGH_RISK",),
        behavioral=BehavioralSignal(status="unavailable", provenance=prov),
        velocity=VelocitySignal(status="unavailable", provenance=prov),
        registry=RegistrySignal(check_status="bypassed_in_lab", provenance=prov),
        mule_graph=MuleGraphSignal(
            status="evaluated",
            cluster_risk_score=90,
            hop_distance_to_flagged_mule=1,
            provenance=prov,
        ),
        transcript=TranscriptCoercionSignal(status="absent", provenance=prov),
    )

    # 1. Low amount payment with critical advisory score escalates to Tier 3
    res_escalated = evaluate_payment_policy(
        payer_id=SYNTHETIC_PAYER_ID,
        amount_paise=100000,
        beneficiary_id="vendor_advisory_test",
        purpose="low amount payment",
        advisory_signals=high_risk_advisory,
    )
    assert res_escalated.tier == RiskTier.TIER_3
    assert res_escalated.requires_guardian is True
    assert "RC_ADVISORY_SCORE_CRITICAL" in res_escalated.reason_codes

    # 2. Even with low advisory score, Safe-Lock ALWAYS takes priority (Priority 1 hard block)
    res_safelock = evaluate_payment_policy(
        payer_id=SYNTHETIC_PAYER_ID,
        amount_paise=100000,
        beneficiary_id="vendor_advisory_test",
        purpose="low amount payment",
        is_safe_locked=True,
        advisory_signals=high_risk_advisory,
    )
    assert res_safelock.is_hard_blocked is True
    assert res_safelock.target_status == "REJECTED"
    assert "RC_SAFE_LOCK_ENGAGED" in res_safelock.reason_codes

    # 3. Low advisory score CANNOT downgrade a high-amount payment (> ₹50,000)
    low_risk_advisory = RiskSignals(
        generated_at=now,
        evaluation_latency_ms=5.0,
        evaluation_status=EvaluationStatus.COMPLETE,
        suggested_caution_level=SuggestedCautionLevel.LOW,
        payment_id="pg_advisory_002",
        payer_id=str(SYNTHETIC_PAYER_ID),
        beneficiary_id="vendor_advisory_test",
        amount_paise=6000000,
        advisory_score=5,  # Low AI score claims low risk
        reason_codes=(),
        behavioral=BehavioralSignal(status="unavailable", provenance=prov),
        velocity=VelocitySignal(status="unavailable", provenance=prov),
        registry=RegistrySignal(check_status="bypassed_in_lab", provenance=prov),
        mule_graph=MuleGraphSignal(status="unavailable", provenance=prov),
        transcript=TranscriptCoercionSignal(status="absent", provenance=prov),
    )
    res_high_amount = evaluate_payment_policy(
        payer_id=SYNTHETIC_PAYER_ID,
        amount_paise=6000000,
        beneficiary_id="vendor_advisory_test",
        purpose="large payment",
        advisory_signals=low_risk_advisory,
    )
    # Must remain Tier 3 due to amount deviation; low advisory score cannot downgrade!
    assert res_high_amount.tier == RiskTier.TIER_3
    assert res_high_amount.requires_guardian is True
    assert "RC_LARGE_AMOUNT_DEVIATION" in res_high_amount.reason_codes







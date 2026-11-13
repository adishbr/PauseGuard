"""Phase 4 PostgreSQL integration tests for durable payment & ledger engine.

These tests require an authorized disposable PostgreSQL instance.
DO NOT execute without explicit authorization and disposable credentials.

Run with:
    $env:PAUSEGUARD_POSTGRES_TEST_AUTHORIZED = "true"
    $env:PAUSEGUARD_POSTGRES_TEST_URL = "postgresql+psycopg2://pauseguard_test_runner@127.0.0.1:5432/pauseguard_test_phase4"
    $env:PAUSEGUARD_POSTGRES_TEST_PASSWORD = ...
    python -m pytest backend/tests_integration/test_payment_ledger_integration.py -v
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import threading
import time
from uuid import UUID, uuid4

from fastapi import HTTPException
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.orm.exc import StaleDataError

from app.auth.identities import SYNTHETIC_GUARDIAN_ID, SYNTHETIC_PAYER_ID
from app.auth.schemas import (
    GuardianDecisionRequest,
    PaymentConfirmRequest,
    PaymentCreateRequest,
)
from app.models.account import MockAccount
from app.models.audit import AuditEvent
from app.models.idempotency import IdempotencyRecord
from app.models.ledger import LedgerEntry
from app.models.payment import (
    GuardianDecision,
    Payment,
)
from app.models.safe_lock import SafeLockState
from app.models.user import RoleBinding, SyntheticUser, UserRole
from app.services.durable_payment_engine import DurablePaymentEngine
from app.services.foundation_queries import (
    ledger_entries_for_payment,
    payer_account_for_update,
    payment_for_update,
    safe_lock_for_payer_for_update,
)
from app.services.payment_guards import PaymentStatus, TrustedActorContext
from app.services.transactions import transaction_scope


def _seed_test_payer(
    session: Session,
    user_id: UUID,
    initial_balance: int = 100_000_000,
    is_locked: bool = False,
) -> SyntheticUser:
    """Helper to seed a test payer with role binding, mock account, and Safe-Lock row."""
    user = SyntheticUser(id=user_id)
    session.add(user)
    session.flush()

    role = RoleBinding(
        user_id=user_id,
        role=UserRole.PAYER.value,
    )
    account = MockAccount(
        owner_id=user_id,
        balance_paise=initial_balance,
        version=1,
    )
    safe_lock = SafeLockState(
        payer_id=user_id,
        is_locked=is_locked,
        version=1,
    )
    session.add_all([role, account, safe_lock])
    session.commit()
    return user


def _seed_test_guardian(
    session: Session,
    guardian_id: UUID,
) -> SyntheticUser:
    """Helper to seed a test guardian with role binding."""
    user = SyntheticUser(id=guardian_id)
    session.add(user)
    session.flush()

    role = RoleBinding(
        user_id=guardian_id,
        role=UserRole.GUARDIAN.value,
    )
    session.add(role)
    session.commit()
    return user


class TestDurablePaymentPersistence:
    """Verify durable payment record lifecycle and optimistic concurrency in PostgreSQL."""

    def test_payment_creation_persists_to_postgresql(self, pg_session: Session) -> None:
        payer_id = uuid4()
        _seed_test_payer(pg_session, payer_id, initial_balance=50_000_000)

        actor = TrustedActorContext(
            user_id=payer_id,
            roles=frozenset({UserRole.PAYER}),
        )
        engine = DurablePaymentEngine(pg_session)
        req = PaymentCreateRequest(
            beneficiary_id="vendor_pg_01",
            amount_paise=2_500_000,
            purpose="office supplies",
            idempotency_key=f"idem_pg_{uuid4().hex[:8]}",
        )

        with transaction_scope(pg_session):
            view = engine.create_payment(actor, req)

        assert view.id.startswith("pg_")
        assert view.status == PaymentStatus.READY_TO_EXECUTE.value

        # Verify persisted row in PostgreSQL
        persisted = pg_session.query(Payment).filter(Payment.id == view.id).one()
        assert persisted.payer_id == payer_id
        assert persisted.amount_paise == 2_500_000
        assert persisted.version == 1

    def test_optimistic_locking_detects_concurrent_modifications(
        self, pg_session_factory: sessionmaker[Session]
    ) -> None:
        payer_id = uuid4()
        with pg_session_factory() as session:
            _seed_test_payer(session, payer_id)
            engine = DurablePaymentEngine(session)
            actor = TrustedActorContext(
                user_id=payer_id,
                roles=frozenset({UserRole.PAYER}),
            )
            req = PaymentCreateRequest(
                beneficiary_id="vendor_pg_02",
                amount_paise=1_000_000,
                purpose="concurrent test",
                idempotency_key=f"idem_conc_{uuid4().hex[:8]}",
            )
            view = engine.create_payment(actor, req)
            session.commit()
            payment_id = view.id

        # Two distinct sessions load the same payment row
        with pg_session_factory() as session1, pg_session_factory() as session2:
            p1 = session1.query(Payment).filter(Payment.id == payment_id).one()
            p2 = session2.query(Payment).filter(Payment.id == payment_id).one()

            # Session 1 updates and commits
            p1.status = PaymentStatus.CANCELLED.value
            session1.commit()

            # Session 2 tries to update with stale version
            p2.status = PaymentStatus.REJECTED.value
            with pytest.raises(StaleDataError):
                session2.commit()


class TestGuardianDecisionPersistence:
    """Verify persistent guardian decisions and anti-replay in PostgreSQL."""

    def test_guardian_decision_recorded_and_persisted(self, pg_session: Session) -> None:
        payer_id = SYNTHETIC_PAYER_ID
        guardian_id = SYNTHETIC_GUARDIAN_ID
        _seed_test_payer(pg_session, payer_id)
        _seed_test_guardian(pg_session, guardian_id)

        now = datetime.now(timezone.utc)
        payment_id = f"pg_{uuid4().hex[:16]}"
        payment = Payment(
            id=payment_id,
            payer_id=payer_id,
            beneficiary_id="vendor_high_risk",
            amount_paise=7_500_000,
            purpose="equipment",
            status=PaymentStatus.AWAITING_GUARDIAN.value,
            tier=3,
            risk_score=90,
            reason_codes=["RC_LARGE_AMOUNT_DEVIATION"],
            idempotency_key=f"idem_guard_{uuid4().hex[:8]}",
            assigned_guardian_id=guardian_id,
            guardian_deadline=now + timedelta(seconds=30),
            version=1,
        )
        pg_session.add(payment)
        pg_session.commit()

        actor = TrustedActorContext(
            user_id=guardian_id,
            roles=frozenset({UserRole.GUARDIAN}),
        )
        engine = DurablePaymentEngine(pg_session)
        dec_req = GuardianDecisionRequest(approved=True, notes="Approved for equipment purchase")

        with transaction_scope(pg_session):
            resp = engine.record_guardian_decision(actor, payment_id, dec_req)

        assert resp.status == PaymentStatus.READY_TO_EXECUTE.value
        assert resp.can_execute_payment is False

        # Verify decision row
        dec_row = pg_session.query(GuardianDecision).filter(GuardianDecision.payment_id == payment_id).one()
        assert dec_row.approved is True
        assert dec_row.guardian_id == guardian_id


class TestAtomicMockLedgerDebit:
    """Verify atomic balance debit, ledger write, and balance conservation in PostgreSQL."""

    def test_confirmation_executes_atomic_debit_and_ledger_entry(self, pg_session: Session) -> None:
        payer_id = uuid4()
        initial_balance = 20_000_000  # ₹200,000
        payment_amount = 5_000_000   # ₹50,000
        _seed_test_payer(pg_session, payer_id, initial_balance=initial_balance)

        payment_id = f"pg_{uuid4().hex[:16]}"
        payment = Payment(
            id=payment_id,
            payer_id=payer_id,
            beneficiary_id="vendor_ledger_01",
            amount_paise=payment_amount,
            purpose="bulk materials",
            status=PaymentStatus.READY_TO_EXECUTE.value,
            tier=0,
            risk_score=10,
            idempotency_key=f"idem_exec_{uuid4().hex[:8]}",
            version=1,
        )
        pg_session.add(payment)
        pg_session.commit()

        actor = TrustedActorContext(
            user_id=payer_id,
            roles=frozenset({UserRole.PAYER}),
        )
        engine = DurablePaymentEngine(pg_session)
        confirm_key = f"confirm_{uuid4().hex[:8]}"
        confirm_req = PaymentConfirmRequest(idempotency_key=confirm_key)

        with transaction_scope(pg_session):
            confirm_resp = engine.confirm_payment(actor, payment_id, confirm_req)

        assert confirm_resp.status == PaymentStatus.EXECUTED.value

        # Verify balance conservation: initial - debit == final
        account = pg_session.query(MockAccount).filter(MockAccount.owner_id == payer_id).one()
        assert account.balance_paise == initial_balance - payment_amount

        # Verify immutable ledger entry
        entries = pg_session.scalars(ledger_entries_for_payment(payment_id)).all()
        assert len(entries) == 1
        assert entries[0].entry_type == "DEBIT"
        assert entries[0].amount_paise == payment_amount
        assert entries[0].account_id == account.id

    def test_p2p_double_entry_debit_credit_conservation_in_postgresql(self, pg_session: Session) -> None:
        """P2P payment between registered users records both DEBIT and CREDIT entries, conserving total funds."""
        payer_id = uuid4()
        payee_id = uuid4()
        initial_payer_balance = 30_000_000   # ₹300,000
        initial_payee_balance = 10_000_000   # ₹100,000
        transfer_amount = 5_000_000          # ₹50,000

        _seed_test_payer(pg_session, payer_id, initial_balance=initial_payer_balance)
        _seed_test_payer(pg_session, payee_id, initial_balance=initial_payee_balance)

        payment_id = f"pg_{uuid4().hex[:16]}"
        payment = Payment(
            id=payment_id,
            payer_id=payer_id,
            beneficiary_id=str(payee_id),
            amount_paise=transfer_amount,
            purpose="contract payment",
            status=PaymentStatus.READY_TO_EXECUTE.value,
            tier=0,
            risk_score=10,
            idempotency_key=f"idem_p2p_pg_{uuid4().hex[:8]}",
            version=1,
        )
        pg_session.add(payment)
        pg_session.commit()

        actor = TrustedActorContext(
            user_id=payer_id,
            roles=frozenset({UserRole.PAYER}),
        )
        engine = DurablePaymentEngine(pg_session)
        confirm_req = PaymentConfirmRequest(idempotency_key=f"confirm_p2p_pg_{uuid4().hex[:8]}")

        with transaction_scope(pg_session):
            confirm_resp = engine.confirm_payment(actor, payment_id, confirm_req)

        assert confirm_resp.status == PaymentStatus.EXECUTED.value

        # Verify funds conservation across both accounts
        payer_acc = pg_session.query(MockAccount).filter(MockAccount.owner_id == payer_id).one()
        payee_acc = pg_session.query(MockAccount).filter(MockAccount.owner_id == payee_id).one()

        assert payer_acc.balance_paise == initial_payer_balance - transfer_amount
        assert payee_acc.balance_paise == initial_payee_balance + transfer_amount
        assert payer_acc.balance_paise + payee_acc.balance_paise == initial_payer_balance + initial_payee_balance

        # Verify 2 immutable ledger entries: DEBIT and CREDIT
        entries = pg_session.scalars(ledger_entries_for_payment(payment_id)).all()
        assert len(entries) == 2
        entry_types = {e.entry_type for e in entries}
        assert entry_types == {"DEBIT", "CREDIT"}

    def test_postgresql_check_constraint_rejects_negative_balance(self, pg_session: Session) -> None:
        payer_id = uuid4()
        _seed_test_payer(pg_session, payer_id, initial_balance=1_000_000)

        # Attempt to set negative balance directly to test check constraint ck_accounts_balance_non_negative
        account = pg_session.query(MockAccount).filter(MockAccount.owner_id == payer_id).one()
        account.balance_paise = -500

        with pytest.raises(IntegrityError):
            pg_session.commit()
        pg_session.rollback()


class TestSafeLockAndTerminalImmutability:
    """Verify live Safe-Lock recheck and terminal status immutability in PostgreSQL."""

    def test_engaged_safe_lock_blocks_execution_in_postgresql(self, pg_session: Session) -> None:
        payer_id = uuid4()
        _seed_test_payer(pg_session, payer_id, initial_balance=20_000_000, is_locked=True)

        payment_id = f"pg_{uuid4().hex[:16]}"
        payment = Payment(
            id=payment_id,
            payer_id=payer_id,
            beneficiary_id="vendor_safelock_01",
            amount_paise=1_000_000,
            purpose="test",
            status=PaymentStatus.READY_TO_EXECUTE.value,
            tier=0,
            risk_score=10,
            idempotency_key=f"idem_sl_{uuid4().hex[:8]}",
            version=1,
        )
        pg_session.add(payment)
        pg_session.commit()

        actor = TrustedActorContext(
            user_id=payer_id,
            roles=frozenset({UserRole.PAYER}),
        )
        engine = DurablePaymentEngine(pg_session)
        confirm_req = PaymentConfirmRequest(idempotency_key=f"confirm_sl_{uuid4().hex[:8]}")

        with pytest.raises(Exception) as exc_info:
            with transaction_scope(pg_session):
                engine.confirm_payment(actor, payment_id, confirm_req)

        assert "Safe-Lock is engaged" in str(exc_info.value)

        # Confirm account was NOT debited
        account = pg_session.query(MockAccount).filter(MockAccount.owner_id == payer_id).one()
        assert account.balance_paise == 20_000_000


class TestWarningAcknowledgmentPersistence:
    """Verify durable warning acknowledgment state transition in PostgreSQL."""

    def test_warning_acknowledged_and_persisted(self, pg_session: Session) -> None:
        payer_id = uuid4()
        _seed_test_payer(pg_session, payer_id)

        payment_id = f"pg_{uuid4().hex[:16]}"
        payment = Payment(
            id=payment_id,
            payer_id=payer_id,
            beneficiary_id="vendor_warn_pg",
            amount_paise=1_000_000,
            purpose="urgent emergency transfer",
            status=PaymentStatus.AWAITING_WARNING.value,
            tier=1,
            risk_score=50,
            reason_codes=["RC_SUSPICIOUS_PURPOSE_COERCION_WARNING"],
            idempotency_key=f"idem_warn_pg_{uuid4().hex[:8]}",
            version=1,
        )
        pg_session.add(payment)
        pg_session.commit()

        actor = TrustedActorContext(
            user_id=payer_id,
            roles=frozenset({UserRole.PAYER}),
        )
        engine = DurablePaymentEngine(pg_session)

        with transaction_scope(pg_session):
            ack_resp = engine.acknowledge_warning(actor, payment_id)

        assert ack_resp.status == PaymentStatus.READY_TO_EXECUTE.value
        assert ack_resp.can_execute_payment is False

        # Verify persisted state and version increment
        persisted = pg_session.query(Payment).filter(Payment.id == payment_id).one()
        assert persisted.status == PaymentStatus.READY_TO_EXECUTE.value
        assert persisted.version == 2


class TestSecurityHardeningPersistence:
    """Verify Phase 4 security hardening: advisory xact locking, Safe-Lock fail-closed, and concurrent idempotency."""

    def test_concurrent_audit_writes_hash_chain_continuity_with_advisory_lock(
        self,
        pg_session_factory: sessionmaker[Session],
    ) -> None:
        """PostgreSQL advisory xact lock serializes concurrent audit writes, preserving an unbroken hash chain."""
        with pg_session_factory() as session:
            payer_id = uuid4()
            _seed_test_payer(session, payer_id)

        actor = TrustedActorContext(
            user_id=payer_id,
            roles=frozenset({UserRole.PAYER}),
        )

        num_threads = 5
        errors = []

        def worker(idx: int) -> None:
            try:
                session = pg_session_factory()
                try:
                    engine = DurablePaymentEngine(session)
                    req = PaymentCreateRequest(
                        beneficiary_id="vendor_audit_conc",
                        amount_paise=10_000 + idx,
                        purpose=f"conc audit {idx}",
                        idempotency_key=f"idem_audit_conc_{idx}_{uuid4().hex[:8]}",
                    )
                    with transaction_scope(session):
                        engine.create_payment(actor, req)
                finally:
                    session.close()
            except Exception as e:
                errors.append(e)

        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            list(executor.map(worker, range(num_threads)))

        assert len(errors) == 0, f"Concurrent audit worker errors: {errors}"

        # Verify cryptographic chain continuity
        with pg_session_factory() as session:
            events = (
                session.query(AuditEvent)
                .order_by(AuditEvent.created_at.asc(), AuditEvent.id.asc())
                .all()
            )
            assert len(events) >= num_threads

            # Verify unbroken hash chain
            for i in range(1, len(events)):
                assert events[i].prev_hash == events[i - 1].event_hash, (
                    f"Hash chain broken at event {i}: "
                    f"prev_hash {events[i].prev_hash} != {events[i - 1].event_hash}"
                )

    def test_concurrent_payment_creation_duplicate_idempotency_handling(
        self,
        pg_session_factory: sessionmaker[Session],
    ) -> None:
        """Concurrent payment creations with the same idempotency key are handled safely without unhandled DB errors."""
        with pg_session_factory() as session:
            payer_id = uuid4()
            _seed_test_payer(session, payer_id)

        actor = TrustedActorContext(
            user_id=payer_id,
            roles=frozenset({UserRole.PAYER}),
        )

        shared_key = f"shared_race_{uuid4().hex[:8]}"
        req = PaymentCreateRequest(
            beneficiary_id="vendor_race",
            amount_paise=25000,
            purpose="concurrent idempotency test",
            idempotency_key=shared_key,
        )

        num_threads = 4
        results = []
        errors = []

        def worker(_: int) -> None:
            session = pg_session_factory()
            try:
                engine = DurablePaymentEngine(session)
                with transaction_scope(session):
                    view = engine.create_payment(actor, req)
                    results.append(view)
            except HTTPException as http_exc:
                results.append(http_exc)
            except Exception as exc:
                errors.append(exc)
            finally:
                session.close()

        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            list(executor.map(worker, range(num_threads)))

        # Must have zero unhandled database or server exceptions
        assert len(errors) == 0, f"Unexpected unhandled exceptions during race: {errors}"
        assert len(results) == num_threads

        # Verify exactly one payment row with this idempotency key was persisted
        with pg_session_factory() as session:
            payments = session.query(Payment).filter(Payment.idempotency_key == shared_key).all()
            assert len(payments) == 1
            persisted_id = payments[0].id

            # All successful views must reference this exact payment ID
            for res in results:
                if not isinstance(res, HTTPException):
                    assert res.id == persisted_id

    def test_safe_lock_missing_fails_closed_in_postgresql(
        self,
        pg_session: Session,
    ) -> None:
        """Missing SafeLockState in PostgreSQL fails closed with HTTP 423 on creation and confirmation."""
        payer_id = uuid4()
        # Seed user and account, but NO safe-lock row
        user = SyntheticUser(id=payer_id)
        role = RoleBinding(user_id=payer_id, role=UserRole.PAYER.value)
        account = MockAccount(owner_id=payer_id, balance_paise=50_000_000, version=1)
        pg_session.add_all([user, role, account])
        pg_session.commit()

        actor = TrustedActorContext(
            user_id=payer_id,
            roles=frozenset({UserRole.PAYER}),
        )
        engine = DurablePaymentEngine(pg_session)
        create_req = PaymentCreateRequest(
            beneficiary_id="vendor_no_sl",
            amount_paise=10000,
            purpose="testing missing safe lock",
            idempotency_key=f"idem_no_sl_{uuid4().hex[:8]}",
        )

        # 1. Payment creation fails closed
        with pytest.raises(HTTPException) as exc_info:
            with transaction_scope(pg_session):
                engine.create_payment(actor, create_req)
        assert exc_info.value.status_code == 423
        assert "Safe-Lock state is unavailable" in exc_info.value.detail

        # 2. Payment confirmation fails closed
        payment_id = f"pg_{uuid4().hex[:16]}"
        payment = Payment(
            id=payment_id,
            payer_id=payer_id,
            beneficiary_id="vendor_no_sl",
            amount_paise=10000,
            purpose="testing missing safe lock confirm",
            status=PaymentStatus.READY_TO_EXECUTE.value,
            tier=0,
            idempotency_key=f"idem_sl_conf_{uuid4().hex[:8]}",
            version=1,
        )
        pg_session.add(payment)
        pg_session.commit()

        confirm_req = PaymentConfirmRequest(idempotency_key=f"conf_no_sl_{uuid4().hex[:8]}")
        with pytest.raises(HTTPException) as exc_info2:
            with transaction_scope(pg_session):
                engine.confirm_payment(actor, payment_id, confirm_req)
        assert exc_info2.value.status_code == 423
        assert "Safe-Lock record missing" in exc_info2.value.detail

def test_concurrent_cancellation_and_confirmation_are_serialized(
    pg_session_factory: sessionmaker[Session],
) -> None:
    """Concurrent cancellation and confirmation must produce one valid outcome."""
    payer_id = uuid4()
    initial_balance = 20_000_000
    payment_amount = 5_000_000
    payment_id = f"pg_{uuid4().hex[:16]}"

    with pg_session_factory() as session:
        _seed_test_payer(session, payer_id, initial_balance=initial_balance)
        payment = Payment(
            id=payment_id,
            payer_id=payer_id,
            beneficiary_id="vendor_cancel_race",
            amount_paise=payment_amount,
            purpose="synthetic cancellation race test",
            status=PaymentStatus.READY_TO_EXECUTE.value,
            tier=0,
            risk_score=10,
            idempotency_key=f"idem_race_{uuid4().hex[:8]}",
            version=1,
        )
        session.add(payment)
        session.commit()

    actor = TrustedActorContext(
        user_id=payer_id,
        roles=frozenset({UserRole.PAYER}),
    )
    start_barrier = threading.Barrier(2)

    def attempt(operation: str) -> tuple[str, int | None]:
        with pg_session_factory() as session:
            engine = DurablePaymentEngine(session)
            start_barrier.wait(timeout=10)

            try:
                with transaction_scope(session):
                    if operation == "cancel":
                        response = engine.cancel_payment(actor, payment_id)
                    else:
                        response = engine.confirm_payment(
                            actor,
                            payment_id,
                            PaymentConfirmRequest(
                                idempotency_key=f"confirm_race_{uuid4().hex[:12]}"
                            ),
                        )
                return response.status, None
            except HTTPException as exc:
                return "CONFLICT", exc.status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        cancel_future = executor.submit(attempt, "cancel")
        confirm_future = executor.submit(attempt, "confirm")
        cancel_result = cancel_future.result(timeout=30)
        confirm_result = confirm_future.result(timeout=30)

    results = [cancel_result, confirm_result]
    successful = [result for result in results if result[1] is None]
    rejected = [result for result in results if result[1] is not None]

    assert len(successful) == 1
    assert len(rejected) == 1
    assert rejected[0][1] == 409

    with pg_session_factory() as session:
        final_payment = session.get(Payment, payment_id)
        account = (
            session.query(MockAccount)
            .filter(MockAccount.owner_id == payer_id)
            .one()
        )
        ledger_entries = session.scalars(
            ledger_entries_for_payment(payment_id)
        ).all()

        assert final_payment is not None

        if final_payment.status == PaymentStatus.CANCELLED.value:
            assert account.balance_paise == initial_balance
            assert len(ledger_entries) == 0

        elif final_payment.status == PaymentStatus.EXECUTED.value:
            assert account.balance_paise == initial_balance - payment_amount
            assert len(ledger_entries) == 1
            assert ledger_entries[0].entry_type == "DEBIT"
            assert ledger_entries[0].amount_paise == payment_amount

        else:
            pytest.fail(
                f"Unexpected final payment state: {final_payment.status}"
            )
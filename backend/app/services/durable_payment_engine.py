"""Durable transaction and ledger engine for Phase 4 V2 payments.

Enforces:
1. Row-level locking (SELECT ... FOR UPDATE) and optimistic concurrency.
2. Atomic mock ledger debit with non-negative balance checks.
3. Database-backed idempotency key deduplication.
4. Cryptographically linked audit events committed atomically in transaction.
5. Rechecked Safe-Lock live before mock ledger execution.
6. Irreversible terminal states (EXECUTED, REJECTED, CANCELLED, EXPIRED, FAILED).
7. Strict role boundaries: Guardians cannot execute payments.
"""

from contextlib import nullcontext
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
from typing import Dict, List, Optional, Union
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from intelligence.schemas.risk_signals import RiskSignals

from app.auth.authorization import (
    assert_guardian_cannot_execute,
    authorize_payment_view_level,
    verify_guardian_to_payer_relationship,
)
from app.auth.exceptions import (
    AuthorizationError,
    GuardianAssignmentError,
)
from app.auth.identities import get_authoritative_guardian_for_payer
from app.auth.schemas import (
    FullPaymentView,
    GuardianDecisionRequest,
    PaymentConfirmRequest,
    PaymentConfirmResponse,
    PaymentCreateRequest,
    PaymentDecisionResponse,
    PaymentFallbackResponse,
    PaymentWarningAckResponse,
    RedactedPaymentView,
)
from app.models.account import MockAccount
from app.models.audit import AuditEvent
from app.models.idempotency import IdempotencyRecord
from app.models.ledger import LedgerEntry
from app.models.payment import (
    CANONICAL_PAYMENT_STATUSES,
    GuardianDecision,
    Payment,
)
from app.models.roles import UserRole
from app.models.safe_lock import SafeLockState
from app.services.foundation_queries import (
    guardian_decision_for_update,
    idempotency_record_for_update,
    payer_account_for_update,
    payment_for_update,
    safe_lock_for_payer_for_update,
)
from app.services.payment_guards import (
    PaymentGuardError,
    PaymentStatus,
    TrustedActorContext,
    is_topologically_allowed,
)
from app.services.policy_engine import evaluate_payment_policy
from app.services.transactions import transaction_scope

GENESIS_HASH = "0" * 64
HIGH_RISK_THRESHOLD_PAISE = 5000000  # ₹50,000
AUDIT_CHAIN_ADVISORY_LOCK_ID = 74920491823


@dataclass(frozen=True)
class GuardianLateDecisionOutcome:
    """Sentinel outcome returned when guardian decision arrives after deadline.

    The API route converts this to HTTP 409 without triggering transaction rollback,
    allowing the get_payment_engine dependency to commit state and audit atomically.
    """

    payment_id: str
    status: str


def _compute_hash(prev_hash: str, event_type: str, payment_id: Optional[str], actor_id: UUID, payload: dict) -> str:
    content = f"{prev_hash}|{event_type}|{payment_id or ''}|{actor_id}|{json.dumps(payload, sort_keys=True)}"
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _savepoint_scope(session: Session):
    """Enter a SQL savepoint when supported by session; fall back for bare Mock sessions."""
    sp = session.begin_nested()
    if callable(getattr(sp, "__enter__", None)) and callable(getattr(sp, "__exit__", None)):
        return sp
    return nullcontext()


class DurablePaymentEngine:
    """ACID-compliant transactional payment and ledger engine."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def _allocate_audit_append_seq(self, last_event: Optional[AuditEvent]) -> int:
        bind = getattr(self.session, "bind", None)
        dialect_name = getattr(getattr(bind, "dialect", None), "name", None)
        if dialect_name == "postgresql":
            return int(self.session.execute(text("SELECT nextval('audit_events_append_seq')")).scalar_one())
        last_seq = getattr(last_event, "append_seq", None)
        return (last_seq + 1) if isinstance(last_seq, int) and last_seq >= 1 else 1

    def _append_audit_event(
        self,
        event_type: str,
        actor: TrustedActorContext,
        payment_id: Optional[str] = None,
        payload: Optional[dict] = None,
    ) -> AuditEvent:
        payload_data = payload or {}

        # Concurrency protection: serialize global audit writes across concurrent transactions in PostgreSQL
        # Lock MUST be acquired before allocating append_seq or querying the current chain tail.
        bind = getattr(self.session, "bind", None)
        if bind is not None and getattr(getattr(bind, "dialect", None), "name", None) == "postgresql":
            self.session.execute(
                text("SELECT pg_advisory_xact_lock(:lock_id)"),
                {"lock_id": AUDIT_CHAIN_ADVISORY_LOCK_ID},
            )

        # Get latest event for hash chaining using authoritative monotonic append_seq (never created_at/UUID)
        last_event = (
            self.session.query(AuditEvent)
            .order_by(AuditEvent.append_seq.desc())
            .first()
        )
        next_seq = self._allocate_audit_append_seq(last_event)
        prev_hash = last_event.event_hash if last_event else GENESIS_HASH
        actor_role = next(iter(actor.roles)).value if actor.roles else "unknown"
        event_hash = _compute_hash(prev_hash, event_type, payment_id, actor.user_id, payload_data)

        audit_entry = AuditEvent(
            append_seq=next_seq,
            payment_id=payment_id,
            event_type=event_type,
            actor_id=actor.user_id,
            actor_role=actor_role,
            prev_hash=prev_hash,
            event_hash=event_hash,
            payload_json=payload_data,
        )
        self.session.add(audit_entry)
        self.session.flush()
        return audit_entry

    def create_payment(
        self,
        actor: TrustedActorContext,
        request: PaymentCreateRequest,
        advisory_signals: Optional[RiskSignals] = None,
    ) -> FullPaymentView:
        """Create a new payment with database-backed idempotency and risk intervention tier."""
        if UserRole.PAYER not in actor.roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only authenticated payers can initiate payments",
            )

        endpoint = "/api/v2/payments"
        request_hash = hashlib.sha256(
            f"{actor.user_id}:{request.beneficiary_id}:{request.amount_paise}:{request.purpose}".encode()
        ).hexdigest()

        # Check existing idempotency record
        existing_idem = self.session.scalars(idempotency_record_for_update(request.idempotency_key)).one_or_none()
        if existing_idem:
            if existing_idem.caller_id != actor.user_id or existing_idem.endpoint != endpoint:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Idempotency key collision across caller or endpoint",
                )
            if existing_idem.request_hash != request_hash:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Idempotency key reused with mismatched request parameters",
                )
            return FullPaymentView.model_validate(existing_idem.response_body)

        # Check existing payment table for same key
        existing_payment = self.session.query(Payment).filter(
            Payment.idempotency_key == request.idempotency_key
        ).one_or_none()
        if existing_payment:
            if existing_payment.payer_id != actor.user_id:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Idempotency key already assigned to another payer",
                )
            return self._build_full_view(existing_payment)

        now = datetime.now(timezone.utc)
        payment_id = f"pg_{uuid4().hex[:16]}"

        # Recheck Safe-Lock state for payer; fail closed (HTTP 423) if unavailable or engaged
        safe_lock_row = self.session.scalars(safe_lock_for_payer_for_update(actor.user_id)).one_or_none()
        if safe_lock_row is None:
            raise HTTPException(
                status_code=status.HTTP_423_LOCKED,
                detail="Authoritative Safe-Lock state is unavailable for payer; payment rejected (fail-closed)",
            )
        if safe_lock_row.is_locked:
            raise HTTPException(
                status_code=status.HTTP_423_LOCKED,
                detail="Safe-Lock is currently engaged for payer; payment rejected",
            )
        is_safe_locked = False

        # Evaluate deterministic policy
        policy_res = evaluate_payment_policy(
            payer_id=actor.user_id,
            amount_paise=request.amount_paise,
            beneficiary_id=request.beneficiary_id,
            purpose=request.purpose,
            is_safe_locked=is_safe_locked,
            advisory_signals=advisory_signals,
        )

        assigned_guardian_id = None
        guardian_deadline = None

        if policy_res.is_hard_blocked:
            tier = policy_res.tier
            initial_status = policy_res.target_status
        elif policy_res.requires_guardian:
            tier = policy_res.tier
            authoritative_guardian = self._resolve_authoritative_guardian(actor.user_id)
            if authoritative_guardian is not None:
                initial_status = PaymentStatus.AWAITING_GUARDIAN.value
                assigned_guardian_id = authoritative_guardian
                guardian_deadline = now + timedelta(seconds=30)
            else:
                initial_status = PaymentStatus.AWAITING_FALLBACK_REVIEW.value
        elif policy_res.requires_warning_ack:
            tier = policy_res.tier
            initial_status = PaymentStatus.AWAITING_WARNING.value
        else:
            tier = policy_res.tier
            initial_status = PaymentStatus.READY_TO_EXECUTE.value

        payment = Payment(
            id=payment_id,
            payer_id=actor.user_id,
            beneficiary_id=request.beneficiary_id,
            amount_paise=request.amount_paise,
            purpose=request.purpose,
            status=initial_status,
            tier=tier,
            risk_score=policy_res.risk_score,
            reason_codes=list(policy_res.reason_codes),
            idempotency_key=request.idempotency_key,
            assigned_guardian_id=assigned_guardian_id,
            guardian_deadline=guardian_deadline,
            version=1,
        )

        try:
            with _savepoint_scope(self.session):
                self.session.add(payment)
                self.session.flush()

                # Build view
                view = self._build_full_view(payment)

                # Record idempotency record
                idem_record = IdempotencyRecord(
                    key=request.idempotency_key,
                    caller_id=actor.user_id,
                    endpoint=endpoint,
                    request_hash=request_hash,
                    response_status=201,
                    response_body=view.model_dump(),
                )
                self.session.add(idem_record)

                # Audit event
                self._append_audit_event(
                    event_type="PAYMENT_CREATED",
                    actor=actor,
                    payment_id=payment_id,
                    payload={
                        "amount_paise": request.amount_paise,
                        "tier": tier,
                        "status": initial_status,
                    },
                )
                self.session.flush()
            return view
        except IntegrityError:
            # Savepoint rolled back automatically without disturbing outer transaction_scope
            existing_idem = self.session.scalars(idempotency_record_for_update(request.idempotency_key)).one_or_none()
            if existing_idem:
                if existing_idem.caller_id != actor.user_id or existing_idem.endpoint != endpoint:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Idempotency key collision across caller or endpoint",
                    )
                if existing_idem.request_hash != request_hash:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Idempotency key reused with mismatched request parameters",
                    )
                return FullPaymentView.model_validate(existing_idem.response_body)

            existing_payment = self.session.query(Payment).filter(
                Payment.idempotency_key == request.idempotency_key
            ).one_or_none()
            if existing_payment:
                if existing_payment.payer_id != actor.user_id:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Idempotency key already assigned to another payer",
                    )
                return self._build_full_view(existing_payment)

            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Concurrent payment creation collision or constraint violation",
            )

    def get_payment(
        self,
        actor: TrustedActorContext,
        payment_id: str,
    ) -> Union[FullPaymentView, RedactedPaymentView]:
        """Retrieve payment with strict privacy level authorization."""
        payment = self.session.query(Payment).filter(Payment.id == payment_id).one_or_none()
        if not payment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Payment {payment_id} not found",
            )

        level = authorize_payment_view_level(
            actor=actor,
            payer_id=payment.payer_id,
            assigned_guardian_id=payment.assigned_guardian_id,
        )

        if level.upper() == "FULL":
            return self._build_full_view(payment)
        elif level.upper() == "REDACTED":
            return RedactedPaymentView(
                id=payment.id,
                status=payment.status,
                tier=payment.tier,
                guardian_deadline=payment.guardian_deadline.isoformat() if payment.guardian_deadline else None,
                message="PauseGuard security review required: Please review this transaction.",
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Caller is neither owning payer nor assigned guardian for this transaction",
            )

    def record_guardian_decision(
        self,
        actor: TrustedActorContext,
        payment_id: str,
        request: GuardianDecisionRequest,
    ) -> Union[PaymentDecisionResponse, GuardianLateDecisionOutcome]:
        """Record authenticated guardian decision with row-level locking and deadline enforcement."""
        payment = self.session.scalars(payment_for_update(payment_id)).one_or_none()
        if not payment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Payment {payment_id} not found",
            )

        self._authorize_guardian_decision_actor(
            actor=actor,
            payer_id=payment.payer_id,
            assigned_guardian_id=payment.assigned_guardian_id,
        )

        # Check existing decision record
        existing_decision = self.session.scalars(guardian_decision_for_update(payment_id)).one_or_none()
        if existing_decision:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Guardian decision has already been recorded for this payment",
            )

        # Terminal state check
        if payment.status in (
            PaymentStatus.EXECUTED.value,
            PaymentStatus.REJECTED.value,
            PaymentStatus.CANCELLED.value,
            PaymentStatus.EXPIRED.value,
            PaymentStatus.FAILED.value,
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Cannot record decision on terminal payment in state {payment.status}",
            )

        if payment.status != PaymentStatus.AWAITING_GUARDIAN.value:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Payment is in status {payment.status}, not AWAITING_GUARDIAN",
            )

        now = datetime.now(timezone.utc)
        if payment.guardian_deadline and now >= payment.guardian_deadline:
            payment.status = PaymentStatus.AWAITING_FALLBACK_REVIEW.value
            payment.version += 1
            self._append_audit_event(
                event_type="GUARDIAN_DEADLINE_EXPIRED",
                actor=actor,
                payment_id=payment.id,
                payload={"deadline": payment.guardian_deadline.isoformat()},
            )
            return GuardianLateDecisionOutcome(
                payment_id=payment.id,
                status=payment.status,
            )

        target_status = (
            PaymentStatus.READY_TO_EXECUTE.value if request.approved else PaymentStatus.REJECTED.value
        )
        assert_guardian_cannot_execute(target_state=target_status)

        payment.status = target_status
        payment.version += 1

        decision_record = GuardianDecision(
            payment_id=payment.id,
            guardian_id=actor.user_id,
            approved=request.approved,
            notes=request.notes,
            target_status=target_status,
        )
        self.session.add(decision_record)

        self._append_audit_event(
            event_type="GUARDIAN_DECISION_RECORDED",
            actor=actor,
            payment_id=payment.id,
            payload={"approved": request.approved, "target_status": target_status},
        )

        return PaymentDecisionResponse(
            payment_id=payment.id,
            status=payment.status,
            decision="APPROVED" if request.approved else "REJECTED",
            target_status=target_status,
            recorded_at=now.isoformat(),
            can_execute_payment=False,
        )

    def activate_fallback_review(
        self,
        actor: TrustedActorContext,
        payment_id: str,
    ) -> PaymentFallbackResponse:
        """Payer-initiated transition to fallback review after 30s deadline has elapsed."""
        payment = self.session.scalars(payment_for_update(payment_id)).one_or_none()
        if not payment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Payment {payment_id} not found",
            )

        if payment.payer_id != actor.user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the owning payer can activate fallback review",
            )

        if payment.status != PaymentStatus.AWAITING_GUARDIAN.value:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Cannot activate fallback review from state {payment.status}",
            )

        now = datetime.now(timezone.utc)
        if payment.guardian_deadline and now < payment.guardian_deadline:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Guardian review window has not expired yet",
            )

        payment.status = PaymentStatus.AWAITING_FALLBACK_REVIEW.value
        payment.version += 1

        self._append_audit_event(
            event_type="FALLBACK_REVIEW_ACTIVATED",
            actor=actor,
            payment_id=payment.id,
        )

        return PaymentFallbackResponse(
            payment_id=payment.id,
            status=PaymentStatus.AWAITING_FALLBACK_REVIEW.value,
            deadline_exceeded_at=now.isoformat(),
            can_authorize_payment=False,
        )

    def confirm_payment(
        self,
        actor: TrustedActorContext,
        payment_id: str,
        request: PaymentConfirmRequest,
    ) -> PaymentConfirmResponse:
        """Atomically debit mock account balance, write ledger entry, and transition to EXECUTED."""
        assert_guardian_cannot_execute(actor=actor)
        if UserRole.PAYER not in actor.roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only authenticated payers can confirm payments",
            )

        endpoint = f"/api/v2/payments/{payment_id}/confirm"
        request_hash = hashlib.sha256(f"{actor.user_id}:{payment_id}:{request.idempotency_key}".encode()).hexdigest()

        # Authorize owning payer before idempotency replay so non-payers receive 403/404 instead of probing keys
        payment = self.session.scalars(payment_for_update(payment_id)).one_or_none()
        if not payment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Payment {payment_id} not found",
            )

        if payment.payer_id != actor.user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the owning payer can confirm and execute a payment",
            )

        # Idempotency check
        existing_idem = self.session.scalars(idempotency_record_for_update(request.idempotency_key)).one_or_none()
        if existing_idem:
            if existing_idem.caller_id != actor.user_id or existing_idem.endpoint != endpoint:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Idempotency key collision across caller or endpoint",
                )
            if existing_idem.request_hash != request_hash:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Idempotency key reused with mismatched confirmation parameters",
                )
            return PaymentConfirmResponse.model_validate(existing_idem.response_body)

        if payment.status == PaymentStatus.EXECUTED.value:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Payment has already been executed",
            )

        if payment.status != PaymentStatus.READY_TO_EXECUTE.value:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Cannot confirm payment in status {payment.status}",
            )

        # Recheck Safe-Lock live; fail closed if missing or locked
        safe_lock = self.session.scalars(safe_lock_for_payer_for_update(payment.payer_id)).one_or_none()
        if safe_lock is None:
            raise HTTPException(
                status_code=status.HTTP_423_LOCKED,
                detail="Authoritative Safe-Lock record missing for payer; payment confirmation blocked (fail-closed)",
            )
        if safe_lock.is_locked:
            raise HTTPException(
                status_code=status.HTTP_423_LOCKED,
                detail="Safe-Lock is engaged; payment confirmation blocked",
            )

        # Lock payer mock account row
        account = self.session.scalars(payer_account_for_update(payment.payer_id)).one_or_none()
        if not account:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Payer account not found",
            )

        if account.balance_paise < payment.amount_paise:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Insufficient mock account balance for payment execution",
            )

        try:
            with _savepoint_scope(self.session):
                # Atomic balance debit
                account.balance_paise -= payment.amount_paise
                account.version += 1

                # Record immutable ledger entry
                debit_idempotency_key = f"debit_{payment.id}_{request.idempotency_key}"
                ledger_entry = LedgerEntry(
                    payment_id=payment.id,
                    account_id=account.id,
                    amount_paise=payment.amount_paise,
                    entry_type="DEBIT",
                    idempotency_key=debit_idempotency_key,
                )
                self.session.add(ledger_entry)

                # In double-entry P2P flows: if beneficiary is a registered user with an account, credit them
                beneficiary_uuid = None
                try:
                    beneficiary_uuid = UUID(payment.beneficiary_id)
                except (ValueError, TypeError, AttributeError):
                    pass

                if beneficiary_uuid is not None:
                    beneficiary_account = self.session.scalars(payer_account_for_update(beneficiary_uuid)).one_or_none()
                    if beneficiary_account:
                        beneficiary_account.balance_paise += payment.amount_paise
                        beneficiary_account.version += 1
                        credit_idempotency_key = f"credit_{payment.id}_{request.idempotency_key}"
                        credit_entry = LedgerEntry(
                            payment_id=payment.id,
                            account_id=beneficiary_account.id,
                            amount_paise=payment.amount_paise,
                            entry_type="CREDIT",
                            idempotency_key=credit_idempotency_key,
                        )
                        self.session.add(credit_entry)

                now = datetime.now(timezone.utc)
                payment.status = PaymentStatus.EXECUTED.value
                payment.version += 1

                response = PaymentConfirmResponse(
                    payment_id=payment.id,
                    status=payment.status,
                    amount_paise=payment.amount_paise,
                    confirmed_at=now.isoformat(),
                )

                # Save idempotency record
                idem_record = IdempotencyRecord(
                    key=request.idempotency_key,
                    caller_id=actor.user_id,
                    endpoint=endpoint,
                    request_hash=request_hash,
                    response_status=200,
                    response_body=response.model_dump(),
                )
                self.session.add(idem_record)

                self._append_audit_event(
                    event_type="PAYMENT_EXECUTED",
                    actor=actor,
                    payment_id=payment.id,
                    payload={
                        "amount_paise": payment.amount_paise,
                        "account_id": str(account.id),
                        "new_balance_paise": account.balance_paise,
                    },
                )
                self.session.flush()
            return response
        except IntegrityError:
            # Savepoint rolled back automatically without disturbing outer transaction_scope
            existing_idem = self.session.scalars(idempotency_record_for_update(request.idempotency_key)).one_or_none()
            if existing_idem:
                if existing_idem.caller_id != actor.user_id or existing_idem.endpoint != endpoint:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Idempotency key collision across caller or endpoint",
                    )
                if existing_idem.request_hash != request_hash:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Idempotency key reused with mismatched confirmation parameters",
                    )
                return PaymentConfirmResponse.model_validate(existing_idem.response_body)
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Concurrent payment confirmation conflict or double execution attempt",
            )

    def cancel_payment(
        self,
        actor: TrustedActorContext,
        payment_id: str,
    ) -> PaymentConfirmResponse:
        """Cancel an eligible non-terminal payment."""
        payment = self.session.scalars(payment_for_update(payment_id)).one_or_none()
        if not payment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Payment {payment_id} not found",
            )

        if payment.payer_id != actor.user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the owning payer can cancel a payment",
            )

        if payment.status in (
            PaymentStatus.EXECUTED.value,
            PaymentStatus.REJECTED.value,
            PaymentStatus.CANCELLED.value,
            PaymentStatus.EXPIRED.value,
            PaymentStatus.FAILED.value,
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Cannot cancel terminal payment in state {payment.status}",
            )

        now = datetime.now(timezone.utc)
        payment.status = PaymentStatus.CANCELLED.value
        payment.version += 1

        self._append_audit_event(
            event_type="PAYMENT_CANCELLED",
            actor=actor,
            payment_id=payment.id,
        )

        return PaymentConfirmResponse(
            payment_id=payment.id,
            status=payment.status,
            amount_paise=payment.amount_paise,
            confirmed_at=now.isoformat(),
        )

    def acknowledge_warning(
        self,
        actor: TrustedActorContext,
        payment_id: str,
    ) -> PaymentWarningAckResponse:
        """Acknowledge high-risk or threshold warning by the owning payer."""
        payment = self.session.scalars(payment_for_update(payment_id)).one_or_none()
        if not payment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Payment {payment_id} not found",
            )
        if payment.payer_id != actor.user_id or UserRole.PAYER not in actor.roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the owning payer can acknowledge a payment warning",
            )
        if payment.status != PaymentStatus.AWAITING_WARNING.value:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Payment is in status {payment.status}, cannot acknowledge warning",
            )

        now = datetime.now(timezone.utc)
        payment.status = PaymentStatus.READY_TO_EXECUTE.value
        payment.version += 1

        self._append_audit_event(
            event_type="WARNING_ACKNOWLEDGED",
            actor=actor,
            payment_id=payment.id,
        )

        return PaymentWarningAckResponse(
            payment_id=payment.id,
            status=payment.status,
            acknowledged_at=now.isoformat(),
            can_execute_payment=False,
        )

    # Method aliases for unified service interface
    get_payment_view = get_payment
    submit_guardian_decision = record_guardian_decision
    activate_fallback = activate_fallback_review

    def get_payment_payer_id(self, payment_id: str) -> Optional[UUID]:
        """Resolve owning payer UUID for post-commit WebSocket notification routing."""
        payment = self.session.query(Payment).filter(Payment.id == payment_id).one_or_none()
        return payment.payer_id if payment is not None else None

    def _build_full_view(self, payment: Payment) -> FullPaymentView:
        return FullPaymentView(
            id=payment.id,
            status=payment.status,
            tier=payment.tier,
            amount_paise=payment.amount_paise,
            beneficiary_id=payment.beneficiary_id,
            purpose=payment.purpose,
            guardian_deadline=payment.guardian_deadline.isoformat() if payment.guardian_deadline else None,
            assigned_guardian_id=str(payment.assigned_guardian_id) if payment.assigned_guardian_id else None,
            version=payment.version,
        )

    def _build_redacted_view(self, payment: Payment) -> RedactedPaymentView:
        return RedactedPaymentView(
            id=payment.id,
            status=payment.status,
            tier=payment.tier,
            guardian_deadline=payment.guardian_deadline.isoformat() if payment.guardian_deadline else None,
            message="PauseGuard security review required: Please review this transaction.",
        )

    def list_payments(
        self,
        actor: TrustedActorContext,
        limit: int = 20,
        offset: int = 0,
    ) -> list[Union[FullPaymentView, RedactedPaymentView]]:
        """List payments accessible to the actor with strict role-based privacy redaction."""
        limit = min(max(1, limit), 100)
        offset = max(0, offset)

        if UserRole.PAYER in actor.roles:
            payments = (
                self.session.query(Payment)
                .filter(Payment.payer_id == actor.user_id)
                .order_by(Payment.created_at.desc())
                .offset(offset)
                .limit(limit)
                .all()
            )
            return [self._build_full_view(p) for p in payments]

        if UserRole.GUARDIAN in actor.roles:
            payments = (
                self.session.query(Payment)
                .filter(Payment.assigned_guardian_id == actor.user_id)
                .order_by(Payment.created_at.desc())
                .offset(offset)
                .limit(limit)
                .all()
            )
            return [self._build_redacted_view(p) for p in payments]

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Caller does not have payment history access permissions",
        )

    def get_account_balance_info(self, user_id: UUID) -> tuple[int, int]:
        """Return (balance_paise, ledger_entries_count) for the specified account owner."""
        account = self.session.query(MockAccount).filter(MockAccount.owner_id == user_id).one_or_none()
        if not account:
            return 0, 0
        entries_count = self.session.query(LedgerEntry).filter(LedgerEntry.account_id == account.id).count()
        return account.balance_paise, entries_count

    def get_payment_events(
        self,
        actor: TrustedActorContext,
        payment_id: str,
    ) -> list[dict]:
        """Return ordered audit events for a payment with role-based redaction."""
        payment = self.session.query(Payment).filter(Payment.id == payment_id).one_or_none()
        if not payment:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment not found")

        level = authorize_payment_view_level(
            actor=actor,
            payer_id=payment.payer_id,
            assigned_guardian_id=payment.assigned_guardian_id,
        )

        events = (
            self.session.query(AuditEvent)
            .filter(AuditEvent.payment_id == payment_id)
            .order_by(AuditEvent.append_seq.asc(), AuditEvent.created_at.asc())
            .all()
        )

        if level.upper() == "FULL":
            return [
                {
                    "id": str(e.id),
                    "append_seq": e.append_seq,
                    "event_type": e.event_type,
                    "payment_id": e.payment_id,
                    "actor_id": str(e.actor_id),
                    "actor_role": e.actor_role,
                    "prev_hash": e.prev_hash,
                    "event_hash": e.event_hash,
                    "payload": e.payload_json,
                    "created_at": e.created_at.isoformat() if e.created_at else None,
                }
                for e in events
            ]
        else:
            return [
                {
                    "event_type": e.event_type,
                    "payment_id": e.payment_id,
                    "status": payment.status,
                    "created_at": e.created_at.isoformat() if e.created_at else None,
                    "redacted": True,
                }
                for e in events
            ]

    def get_guardian_pending_reviews(self, guardian_id: UUID) -> list[RedactedPaymentView]:
        """Return all active payments awaiting review assigned to this guardian."""
        now = datetime.now(timezone.utc)
        payments = (
            self.session.query(Payment)
            .filter(
                Payment.assigned_guardian_id == guardian_id,
                Payment.status == PaymentStatus.AWAITING_GUARDIAN.value,
            )
            .order_by(Payment.created_at.desc())
            .all()
        )
        # Filter for non-expired deadlines
        valid_payments = [
            p for p in payments
            if p.guardian_deadline is None or (
                p.guardian_deadline.replace(tzinfo=timezone.utc)
                if p.guardian_deadline.tzinfo is None
                else p.guardian_deadline
            ) > now
        ]
        return [self._build_redacted_view(p) for p in valid_payments]

    def toggle_safe_lock(self, payer_id: UUID, is_locked: bool) -> tuple[bool, int, str]:
        """Atomically toggle Safe-Lock state for a payer."""
        safe_lock = self.session.scalars(safe_lock_for_payer_for_update(payer_id)).one_or_none()
        now = datetime.now(timezone.utc)
        if safe_lock is None:
            safe_lock = SafeLockState(
                payer_id=payer_id,
                is_locked=is_locked,
                version=1,
            )
            self.session.add(safe_lock)
        else:
            safe_lock.is_locked = is_locked
            safe_lock.version += 1
        self.session.flush()
        updated_at = safe_lock.updated_at.isoformat() if safe_lock.updated_at else now.isoformat()
        return safe_lock.is_locked, safe_lock.version, updated_at

    def get_safe_lock_status(self, payer_id: UUID) -> tuple[bool, int, Optional[str]]:
        """Return current Safe-Lock state for a payer."""
        safe_lock = self.session.query(SafeLockState).filter(SafeLockState.payer_id == payer_id).one_or_none()
        if safe_lock is None:
            raise HTTPException(
                status_code=status.HTTP_423_LOCKED,
                detail="Authoritative Safe-Lock state is unavailable for payer (fail-closed)",
            )
        updated_at = safe_lock.updated_at.isoformat() if safe_lock.updated_at else None
        return safe_lock.is_locked, safe_lock.version, updated_at

    def verify_audit_chain(self) -> tuple[bool, int, str]:
        """Verify the integrity of the database audit hash chain in authoritative append order."""
        events = self.session.query(AuditEvent).order_by(AuditEvent.append_seq.asc()).all()
        if not events:
            return True, 0, GENESIS_HASH
        prev_hash = GENESIS_HASH
        seen_seqs: set[int] = set()
        for event in events:
            if not isinstance(event.append_seq, int) or event.append_seq <= 0 or event.append_seq in seen_seqs:
                return False, len(events), event.event_hash
            seen_seqs.add(event.append_seq)
            if event.prev_hash != prev_hash:
                return False, len(events), event.prev_hash or ""
            expected_hash = _compute_hash(
                prev_hash,
                event.event_type,
                event.payment_id,
                event.actor_id,
                event.payload_json if event.payload_json is not None else {},
            )
            if event.event_hash != expected_hash:
                return False, len(events), event.event_hash
            prev_hash = event.event_hash
        return True, len(events), events[-1].event_hash

    def _resolve_authoritative_guardian(self, payer_id: UUID) -> Optional[UUID]:
        """Resolve an active durable V5 GuardianInvitation first, falling back to V4.1 enrollments."""
        from app.models.identity import GuardianInvitation

        rows = (
            self.session.query(GuardianInvitation)
            .filter(
                GuardianInvitation.payer_id == payer_id,
                GuardianInvitation.status == "ACTIVE",
                GuardianInvitation.guardian_user_id.isnot(None),
            )
            .all()
        )
        if isinstance(rows, list) and rows:
            primary = next((r for r in rows if r.role_slot == "primary"), None)
            chosen = primary or rows[0]
            return chosen.guardian_user_id
        return get_authoritative_guardian_for_payer(payer_id)

    def _authorize_guardian_decision_actor(
        self,
        *,
        actor: TrustedActorContext,
        payer_id: UUID,
        assigned_guardian_id: Optional[UUID],
    ) -> None:
        """Authorize a guardian decision against either durable V5 invitations or V4.1 enrollment."""
        from app.auth.exceptions import AuthorizationError, GuardianAssignmentError
        from app.models.identity import GuardianInvitation, IdentityAssurance

        if UserRole.GUARDIAN not in actor.roles:
            raise AuthorizationError("Forbidden: Actor does not hold the guardian role")
        if actor.user_id == payer_id:
            raise GuardianAssignmentError("Forbidden: Payer cannot act as guardian for their own transaction")

        now = datetime.now(timezone.utc)
        active_invites = (
            self.session.query(GuardianInvitation)
            .filter(
                GuardianInvitation.payer_id == payer_id,
                GuardianInvitation.status == "ACTIVE",
            )
            .all()
        )
        if isinstance(active_invites, list) and active_invites:
            matching = next((inv for inv in active_invites if inv.guardian_user_id == actor.user_id), None)
            if matching is None:
                raise GuardianAssignmentError(
                    "Forbidden: Actor is not an active enrolled guardian for this payer"
                )
            if assigned_guardian_id is not None and assigned_guardian_id != actor.user_id:
                raise GuardianAssignmentError(
                    "Forbidden: Supplied guardian does not match authoritative server enrollment"
                )
            assurance = (
                self.session.query(IdentityAssurance)
                .filter(
                    IdentityAssurance.user_id == actor.user_id,
                    IdentityAssurance.revoked.is_(False),
                    IdentityAssurance.expires_at > now,
                )
                .first()
            )
            if assurance is None:
                raise GuardianAssignmentError(
                    "Forbidden: Assigned guardian lacks authoritative server-verified identity assurance"
                )
            return

        verify_guardian_to_payer_relationship(
            actor=actor,
            payer_id=payer_id,
            assigned_guardian_id=assigned_guardian_id,
        )



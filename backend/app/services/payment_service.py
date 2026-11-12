"""Thread-safe in-memory V2 payment lifecycle prototype for hackathon demonstration.

ARCHITECTURAL LIMITATIONS & PHASE SCOPE:
- NON-DURABLE PROTOTYPE: All payment records and state machine transitions are
  maintained in-memory within the active application process. State is NOT persisted
  to durable storage and will not survive process restarts.
- NO REAL SETTLEMENT: Payment execution (status=EXECUTED) represents an in-memory
  mock simulation only. No actual banking network, UPI rails, or persistent ledger
  debits/credits are executed. Durable ledger persistence is deferred to Phase 4.
- CONCURRENCY MODEL: Concurrency protection is provided by threading.Lock for
  synchronous FastAPI endpoints running in worker threads. It guarantees that
  concurrent requests within the single application process transition payment
  state safely and idempotently.

SECURITY INVARIANTS:
1. Payer-only creation & confirmation: Only authenticated owning payers can create
   or confirm execution of payments.
2. Guardian approval NEVER executes payments: A guardian decision can at most
   transition a payment to READY_TO_EXECUTE or REJECTED.
3. Fail-closed 30-second deadline: Guardian decisions after deadline expiry are
   strictly rejected (>= 30s).
4. Fallback review activation: Can ONLY be activated after deadline expiry; fallback
   transition NEVER authorizes payment execution.
5. Anti-replay and idempotency: Duplicate decisions or replayed transitions are rejected.
6. Privacy redaction: Guardians receive only sanitized notifications without sensitive
   financial details (amounts, recipient accounts, or raw purpose).
7. Safe-Lock binary enforcement: Final execution fails closed if Safe-Lock is engaged or missing.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum
import threading
from typing import Dict, Optional, Union
from uuid import UUID, uuid4

from fastapi import HTTPException, status

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
    RedactedPaymentView,
)
from app.models.roles import UserRole
from app.services.payment_guards import (
    PaymentGuardError,
    PaymentStatus,
    TrustedActorContext,
    guardian_approval_target,
    guardian_timeout_target,
    require_payer_confirmation_preconditions,
)


def _build_alert(case_id: str) -> dict:
    """Generate localized, privacy-safe notification alert for a guardian."""
    from safety.guardian_alerts.guardian_alert import build_guardian_alert
    return build_guardian_alert(case_id=case_id)


@dataclass
class PaymentRecord:
    id: str
    payer_id: UUID
    beneficiary_id: str
    amount_paise: int
    purpose: str
    idempotency_key: str
    status: PaymentStatus
    tier: int
    guardian_deadline: Optional[datetime]
    assigned_guardian_id: Optional[UUID]
    created_at: str
    version: int = 1
    decision_recorded_at: Optional[str] = None
    decision_notes: Optional[str] = None
    fallback_activated_at: Optional[str] = None
    confirmed_at: Optional[str] = None


class PaymentService:
    """Thread-safe in-memory repository and state transition orchestrator for V2 payments."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._payments: Dict[str, PaymentRecord] = {}
        self._idempotency_index: Dict[tuple[UUID, str], str] = {}
        self._safe_lock_states: Dict[UUID, bool] = {}

    def reset_for_testing(self) -> None:
        """Reset repository state for isolated test execution."""
        with self._lock:
            self._payments.clear()
            self._idempotency_index.clear()
            self._safe_lock_states.clear()

    def set_safe_lock(self, payer_id: UUID, is_locked: bool) -> None:
        """Set Safe-Lock state for a payer."""
        with self._lock:
            self._safe_lock_states[payer_id] = is_locked

    def get_safe_lock(self, payer_id: UUID) -> Optional[bool]:
        """Get Safe-Lock state for a payer. Defaults to False (unlocked) if registered."""
        with self._lock:
            return self._safe_lock_states.get(payer_id, False)

    def seed_payment(self, record: PaymentRecord) -> None:
        """Seed a specific payment record for testing."""
        with self._lock:
            self._payments[record.id] = record
            self._idempotency_index[(record.payer_id, record.idempotency_key)] = record.id

    def create_payment(
        self,
        actor: TrustedActorContext,
        request: PaymentCreateRequest,
        server_now: Optional[datetime] = None,
        tier: int = 3,
    ) -> FullPaymentView:
        """Create a new risk-evaluated mock payment."""
        if not isinstance(actor, TrustedActorContext) or UserRole.PAYER not in actor.roles:
            raise AuthorizationError("Only authenticated payers can create payments")

        now = server_now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        with self._lock:
            # Check idempotency
            key = (actor.user_id, request.idempotency_key)
            if key in self._idempotency_index:
                existing_id = self._idempotency_index[key]
                existing = self._payments[existing_id]
                return FullPaymentView(
                    id=existing.id,
                    status=existing.status.value,
                    tier=existing.tier,
                    amount_paise=existing.amount_paise,
                    beneficiary_id=existing.beneficiary_id,
                    purpose=existing.purpose,
                    guardian_deadline=existing.guardian_deadline.isoformat() if existing.guardian_deadline else None,
                    assigned_guardian_id=str(existing.assigned_guardian_id) if existing.assigned_guardian_id else None,
                    version=existing.version,
                )

            # Evaluate risk tier and guardian requirement
            assigned_guardian: Optional[UUID] = None
            deadline: Optional[datetime] = None

            if tier == 3 or request.amount_paise >= 5_000_000:
                # High risk / Tier 3 requires enrolled guardian review
                authoritative_guardian = get_authoritative_guardian_for_payer(actor.user_id)
                if authoritative_guardian is None:
                    # Fail-closed: Payer has no enrolled guardian
                    raise GuardianAssignmentError(
                        "Payment requires guardian review, but payer has no enrolled guardian on record"
                    )
                assigned_guardian = authoritative_guardian
                deadline = now + timedelta(seconds=30)
                init_status = PaymentStatus.AWAITING_GUARDIAN
                effective_tier = 3
            else:
                effective_tier = tier
                init_status = PaymentStatus.READY_TO_EXECUTE

            payment_id = f"pg_{uuid4().hex[:16]}"
            record = PaymentRecord(
                id=payment_id,
                payer_id=actor.user_id,
                beneficiary_id=request.beneficiary_id,
                amount_paise=request.amount_paise,
                purpose=request.purpose,
                idempotency_key=request.idempotency_key,
                status=init_status,
                tier=effective_tier,
                guardian_deadline=deadline,
                assigned_guardian_id=assigned_guardian,
                created_at=now.isoformat(),
                version=1,
            )

            self._payments[payment_id] = record
            self._idempotency_index[key] = payment_id

            return FullPaymentView(
                id=record.id,
                status=record.status.value,
                tier=record.tier,
                amount_paise=record.amount_paise,
                beneficiary_id=record.beneficiary_id,
                purpose=record.purpose,
                guardian_deadline=record.guardian_deadline.isoformat() if record.guardian_deadline else None,
                assigned_guardian_id=str(record.assigned_guardian_id) if record.assigned_guardian_id else None,
                version=record.version,
            )

    def get_payment_view(
        self,
        actor: TrustedActorContext,
        payment_id: str,
    ) -> Union[FullPaymentView, RedactedPaymentView]:
        """Retrieve a payment view based on the caller's server-authorized access level."""
        with self._lock:
            record = self._payments.get(payment_id)
            if record is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment not found")

        view_level = authorize_payment_view_level(
            actor,
            payer_id=record.payer_id,
            assigned_guardian_id=record.assigned_guardian_id,
        )

        if view_level == "full":
            return FullPaymentView(
                id=record.id,
                status=record.status.value,
                tier=record.tier,
                amount_paise=record.amount_paise,
                beneficiary_id=record.beneficiary_id,
                purpose=record.purpose,
                guardian_deadline=record.guardian_deadline.isoformat() if record.guardian_deadline else None,
                assigned_guardian_id=str(record.assigned_guardian_id) if record.assigned_guardian_id else None,
                version=record.version,
            )

        if view_level == "redacted":
            alert_info = _build_alert(case_id=record.id)
            return RedactedPaymentView(
                id=record.id,
                status=record.status.value,
                tier=record.tier,
                guardian_deadline=record.guardian_deadline.isoformat() if record.guardian_deadline else None,
                message=alert_info["message"],
            )

        raise AuthorizationError("Unauthorized to view payment")

    def submit_guardian_decision(
        self,
        actor: TrustedActorContext,
        payment_id: str,
        request: GuardianDecisionRequest,
        server_now: Optional[datetime] = None,
    ) -> PaymentDecisionResponse:
        """Submit an authenticated guardian decision for a payment awaiting review."""
        with self._lock:
            record = self._payments.get(payment_id)
            if record is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment not found")

            # Verify guardian relationship
            verify_guardian_to_payer_relationship(
                actor,
                assigned_guardian_id=record.assigned_guardian_id,
                payer_id=record.payer_id,
            )

            # Reject duplicate/replayed decisions
            if record.status != PaymentStatus.AWAITING_GUARDIAN:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Conflict: Payment is in status {record.status.value}, not AWAITING_GUARDIAN. Decision cannot be recorded.",
                )

            now = server_now or datetime.now(timezone.utc)
            if now.tzinfo is None:
                now = now.replace(tzinfo=timezone.utc)

            # Check 30s deadline expiry
            if record.guardian_deadline is not None and now >= record.guardian_deadline:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail="Guardian decision window has expired (>= 30 seconds)",
                )

            if request.approved:
                try:
                    target_status = guardian_approval_target(
                        status=record.status,
                        actor=actor,
                        assigned_guardian_id=record.assigned_guardian_id,
                        guardian_deadline=record.guardian_deadline,  # type: ignore[arg-type]
                        server_now=now,
                        hard_policy_allows=True,
                    )
                except PaymentGuardError as e:
                    raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(e))

                assert_guardian_cannot_execute(target_state=target_status.value)
                record.status = target_status
                decision_label = "APPROVED"
            else:
                record.status = PaymentStatus.REJECTED
                decision_label = "REJECTED"

            record.version += 1
            record.decision_recorded_at = now.isoformat()
            record.decision_notes = request.notes

            return PaymentDecisionResponse(
                payment_id=record.id,
                status=record.status.value,
                decision=decision_label,
                target_status=record.status.value,
                recorded_at=now.isoformat(),
                can_execute_payment=False,
            )

    def activate_fallback(
        self,
        actor: TrustedActorContext,
        payment_id: str,
        server_now: Optional[datetime] = None,
    ) -> PaymentFallbackResponse:
        """Activate fallback review after guardian deadline expiry."""
        with self._lock:
            record = self._payments.get(payment_id)
            if record is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment not found")

            # Only owning payer can activate fallback
            if actor.user_id != record.payer_id or UserRole.PAYER not in actor.roles:
                raise AuthorizationError("Only the owning payer can activate fallback review")

            if record.status != PaymentStatus.AWAITING_GUARDIAN:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Conflict: Payment is in status {record.status.value}, cannot activate fallback",
                )

            now = server_now or datetime.now(timezone.utc)
            if now.tzinfo is None:
                now = now.replace(tzinfo=timezone.utc)

            try:
                target_status = guardian_timeout_target(
                    status=record.status,
                    guardian_deadline=record.guardian_deadline,  # type: ignore[arg-type]
                    server_now=now,
                )
            except PaymentGuardError as e:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=f"Guardian deadline has not expired yet: {e}",
                )

            record.status = target_status
            record.version += 1
            record.fallback_activated_at = now.isoformat()

            return PaymentFallbackResponse(
                payment_id=record.id,
                status=record.status.value,
                deadline_exceeded_at=now.isoformat(),
                can_authorize_payment=False,
            )

    def confirm_payment(
        self,
        actor: TrustedActorContext,
        payment_id: str,
        request: PaymentConfirmRequest,
    ) -> PaymentConfirmResponse:
        """Confirm final payment execution by the authenticated owning payer."""
        with self._lock:
            record = self._payments.get(payment_id)
            if record is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment not found")

            # Check owning payer
            if actor.user_id != record.payer_id or UserRole.PAYER not in actor.roles:
                raise AuthorizationError("Forbidden: Only the authenticated owning payer can execute payment")

            # Check Safe-Lock
            safe_lock_locked = self._safe_lock_states.get(record.payer_id, False)
            if safe_lock_locked:
                raise HTTPException(
                    status_code=status.HTTP_423_LOCKED,
                    detail="Payment rejected: Safe-Lock is currently engaged",
                )

            try:
                require_payer_confirmation_preconditions(
                    status=record.status,
                    actor=actor,
                    payer_id=record.payer_id,
                    safe_lock_is_locked=safe_lock_locked,
                    hard_policy_allows=True,
                )
            except PaymentGuardError as e:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))

            now_str = datetime.now(timezone.utc).isoformat()
            record.status = PaymentStatus.EXECUTED
            record.version += 1
            record.confirmed_at = now_str

            return PaymentConfirmResponse(
                payment_id=record.id,
                status=record.status.value,
                amount_paise=record.amount_paise,
                confirmed_at=now_str,
            )


_default_payment_service: Optional[PaymentService] = None


def get_payment_service() -> PaymentService:
    """Retrieve or initialize the global PaymentService singleton."""
    global _default_payment_service
    if _default_payment_service is None:
        _default_payment_service = PaymentService()
    return _default_payment_service

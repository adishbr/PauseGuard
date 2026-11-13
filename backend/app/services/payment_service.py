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
from typing import Any, Dict, Optional, Union
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
from app.auth.identities import (
    SYNTHETIC_OTHER_PAYER_ID,
    SYNTHETIC_PAYER_ID,
    get_authoritative_guardian_for_payer,
)
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
from app.models.roles import UserRole
from app.services.payment_guards import (
    PaymentGuardError,
    PaymentStatus,
    TrustedActorContext,
    guardian_approval_target,
    guardian_timeout_target,
    require_payer_confirmation_preconditions,
)
from app.services.policy_engine import evaluate_payment_policy


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


DEFAULT_MOCK_BALANCE_PAISE = 100000000  # ₹1,000,000 default mock balance


class PaymentService:
    """Thread-safe in-memory repository and state transition orchestrator for V2 payments."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._payments: Dict[str, PaymentRecord] = {}
        self._idempotency_index: Dict[tuple[UUID, str], str] = {}
        self._safe_lock_states: Dict[UUID, bool] = {
            SYNTHETIC_PAYER_ID: False,
            SYNTHETIC_OTHER_PAYER_ID: False,
        }
        self._accounts: Dict[UUID, int] = {}
        self._ledger_entries: list[dict] = []
        self._confirm_idempotency_map: Dict[tuple[str, str], PaymentConfirmResponse] = {}

    def reset_for_testing(self) -> None:
        """Reset repository state for isolated test execution."""
        with self._lock:
            self._payments.clear()
            self._idempotency_index.clear()
            self._safe_lock_states.clear()
            self._safe_lock_states[SYNTHETIC_PAYER_ID] = False
            self._safe_lock_states[SYNTHETIC_OTHER_PAYER_ID] = False
            self._accounts.clear()
            self._ledger_entries.clear()
            self._confirm_idempotency_map.clear()

    def ensure_user_initialized(
        self,
        user_id: UUID,
        *,
        balance_paise: int = DEFAULT_MOCK_BALANCE_PAISE,
    ) -> None:
        """Initialize mock account balance and Safe-Lock state for a newly signed-up V5 user."""
        with self._lock:
            if user_id not in self._accounts:
                self._accounts[user_id] = balance_paise
            if user_id not in self._safe_lock_states:
                self._safe_lock_states[user_id] = False

    def get_account_balance(self, user_id: UUID) -> int:
        """Retrieve current mock account balance in paise."""
        with self._lock:
            if user_id not in self._accounts:
                self._accounts[user_id] = DEFAULT_MOCK_BALANCE_PAISE
            return self._accounts[user_id]

    def set_account_balance(self, user_id: UUID, balance_paise: int) -> None:
        """Set mock account balance in paise for testing."""
        with self._lock:
            if balance_paise < 0:
                raise ValueError("Account balance cannot be negative")
            self._accounts[user_id] = balance_paise

    def get_ledger_entries(self, payment_id: Optional[str] = None) -> list[dict]:
        """Retrieve immutable mock ledger entries."""
        with self._lock:
            if payment_id:
                return [e for e in self._ledger_entries if e["payment_id"] == payment_id]
            return list(self._ledger_entries)

    def set_safe_lock(self, payer_id: UUID, is_locked: bool) -> None:
        """Set Safe-Lock state for a payer."""
        with self._lock:
            self._safe_lock_states[payer_id] = is_locked

    def get_safe_lock(self, payer_id: UUID) -> Optional[bool]:
        """Get Safe-Lock state for a payer. None if not registered."""
        with self._lock:
            return self._safe_lock_states.get(payer_id)

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
        tier: Optional[int] = None,
        advisory_signals: Optional[Any] = None,
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

            # Evaluate risk policy deterministically; fail closed if Safe-Lock state is unavailable
            safe_lock_state = self._safe_lock_states.get(actor.user_id)
            if safe_lock_state is None:
                raise HTTPException(
                    status_code=status.HTTP_423_LOCKED,
                    detail="Authoritative Safe-Lock state is unavailable for payer; payment rejected (fail-closed)",
                )
            if safe_lock_state is True:
                raise HTTPException(
                    status_code=status.HTTP_423_LOCKED,
                    detail="Payment rejected: Safe-Lock is currently engaged",
                )
            safe_lock_locked = False
            policy_res = evaluate_payment_policy(
                payer_id=actor.user_id,
                amount_paise=request.amount_paise,
                beneficiary_id=request.beneficiary_id,
                purpose=request.purpose,
                is_safe_locked=safe_lock_locked,
                advisory_signals=advisory_signals,
            )

            if tier is not None:
                effective_tier = tier
                requires_guardian = (effective_tier == 3)
                requires_warning_ack = (effective_tier == 1)
            else:
                effective_tier = policy_res.tier
                requires_guardian = policy_res.requires_guardian
                requires_warning_ack = policy_res.requires_warning_ack

            assigned_guardian: Optional[UUID] = None
            deadline: Optional[datetime] = None

            if policy_res.is_hard_blocked:
                init_status = PaymentStatus.REJECTED
            elif requires_guardian:
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
            elif requires_warning_ack:
                init_status = PaymentStatus.AWAITING_WARNING
            else:
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

            # Check owning payer before idempotency replay so non-payers cannot probe/replay receipts
            if actor.user_id != record.payer_id or UserRole.PAYER not in actor.roles:
                raise AuthorizationError("Forbidden: Only the authenticated owning payer can execute payment")

            # Check confirmation idempotency
            cached_confirm = self._confirm_idempotency_map.get((payment_id, request.idempotency_key))
            if cached_confirm is not None:
                return cached_confirm

            # Reject if already terminal
            if record.status == PaymentStatus.EXECUTED:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Payment has already been executed",
                )

            # Check Safe-Lock; fail closed if state is unavailable or locked
            safe_lock_state = self._safe_lock_states.get(record.payer_id)
            if safe_lock_state is None:
                raise HTTPException(
                    status_code=status.HTTP_423_LOCKED,
                    detail="Authoritative Safe-Lock state is unavailable for payer; payment confirmation rejected (fail-closed)",
                )
            if safe_lock_state is True:
                raise HTTPException(
                    status_code=status.HTTP_423_LOCKED,
                    detail="Payment rejected: Safe-Lock is currently engaged",
                )
            safe_lock_locked = False

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

            # Mock account balance check
            balance = self._accounts.get(record.payer_id, DEFAULT_MOCK_BALANCE_PAISE)
            if balance < record.amount_paise:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Insufficient mock account balance for payment execution",
                )

            # Atomic mock balance debit
            self._accounts[record.payer_id] = balance - record.amount_paise

            now_str = datetime.now(timezone.utc).isoformat()

            # Record immutable mock ledger entry
            ledger_entry = {
                "id": str(uuid4()),
                "payment_id": record.id,
                "account_id": str(record.payer_id),
                "amount_paise": record.amount_paise,
                "entry_type": "DEBIT",
                "idempotency_key": f"debit_{record.id}_{request.idempotency_key}",
                "created_at": now_str,
            }
            self._ledger_entries.append(ledger_entry)

            # In double-entry P2P flows: if beneficiary is a registered user with an account, credit them
            beneficiary_uuid = None
            try:
                beneficiary_uuid = UUID(record.beneficiary_id)
            except (ValueError, TypeError, AttributeError):
                pass

            if beneficiary_uuid is not None:
                ben_balance = self._accounts.get(beneficiary_uuid, DEFAULT_MOCK_BALANCE_PAISE)
                self._accounts[beneficiary_uuid] = ben_balance + record.amount_paise
                credit_entry = {
                    "id": str(uuid4()),
                    "payment_id": record.id,
                    "account_id": str(beneficiary_uuid),
                    "amount_paise": record.amount_paise,
                    "entry_type": "CREDIT",
                    "idempotency_key": f"credit_{record.id}_{request.idempotency_key}",
                    "created_at": now_str,
                }
                self._ledger_entries.append(credit_entry)

            record.status = PaymentStatus.EXECUTED
            record.version += 1
            record.confirmed_at = now_str

            response = PaymentConfirmResponse(
                payment_id=record.id,
                status=record.status.value,
                amount_paise=record.amount_paise,
                confirmed_at=now_str,
            )
            self._confirm_idempotency_map[(payment_id, request.idempotency_key)] = response
            return response

    def cancel_payment(
        self,
        actor: TrustedActorContext,
        payment_id: str,
    ) -> PaymentConfirmResponse:
        """Cancel an eligible non-terminal payment by the authenticated owning payer."""
        with self._lock:
            record = self._payments.get(payment_id)
            if record is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment not found")

            if actor.user_id != record.payer_id or UserRole.PAYER not in actor.roles:
                raise AuthorizationError("Forbidden: Only the authenticated owning payer can cancel a payment")

            if record.status in (
                PaymentStatus.EXECUTED,
                PaymentStatus.REJECTED,
                PaymentStatus.CANCELLED,
                PaymentStatus.EXPIRED,
                PaymentStatus.FAILED,
            ):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Cannot cancel terminal payment in state {record.status.value}",
                )

            now_str = datetime.now(timezone.utc).isoformat()
            record.status = PaymentStatus.CANCELLED
            record.version += 1

            return PaymentConfirmResponse(
                payment_id=record.id,
                status=record.status.value,
                amount_paise=record.amount_paise,
                confirmed_at=now_str,
            )

    def acknowledge_warning(
        self,
        actor: TrustedActorContext,
        payment_id: str,
    ) -> PaymentWarningAckResponse:
        """Acknowledge high-risk or threshold warning by the owning payer."""
        with self._lock:
            record = self._payments.get(payment_id)
            if record is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment not found")

            if actor.user_id != record.payer_id or UserRole.PAYER not in actor.roles:
                raise AuthorizationError("Only the owning payer can acknowledge a payment warning")

            if record.status != PaymentStatus.AWAITING_WARNING:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Payment is in status {record.status.value}, cannot acknowledge warning",
                )

            now_str = datetime.now(timezone.utc).isoformat()
            record.status = PaymentStatus.READY_TO_EXECUTE
            record.version += 1

            return PaymentWarningAckResponse(
                payment_id=record.id,
                status=record.status.value,
                acknowledged_at=now_str,
                can_execute_payment=False,
            )

    def _build_redacted_view(self, record: PaymentRecord) -> RedactedPaymentView:
        alert_info = _build_alert(case_id=record.id)
        return RedactedPaymentView(
            id=record.id,
            status=record.status.value,
            tier=record.tier,
            guardian_deadline=record.guardian_deadline.isoformat() if record.guardian_deadline else None,
            message=alert_info["message"],
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

        with self._lock:
            if UserRole.PAYER in actor.roles:
                records = [r for r in self._payments.values() if r.payer_id == actor.user_id]
                records.sort(key=lambda r: r.created_at, reverse=True)
                page = records[offset : offset + limit]
                return [
                    FullPaymentView(
                        id=r.id,
                        status=r.status.value,
                        tier=r.tier,
                        amount_paise=r.amount_paise,
                        beneficiary_id=r.beneficiary_id,
                        purpose=r.purpose,
                        guardian_deadline=r.guardian_deadline.isoformat() if r.guardian_deadline else None,
                        assigned_guardian_id=str(r.assigned_guardian_id) if r.assigned_guardian_id else None,
                        version=r.version,
                    )
                    for r in page
                ]

            if UserRole.GUARDIAN in actor.roles:
                records = [r for r in self._payments.values() if r.assigned_guardian_id == actor.user_id]
                records.sort(key=lambda r: r.created_at, reverse=True)
                page = records[offset : offset + limit]
                return [self._build_redacted_view(r) for r in page]

            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Forbidden: Caller does not have payment history access permissions",
            )

    def get_account_balance_info(self, user_id: UUID) -> tuple[int, int]:
        """Retrieve balance in paise and number of ledger entries for a user."""
        with self._lock:
            if user_id not in self._accounts:
                self._accounts[user_id] = DEFAULT_MOCK_BALANCE_PAISE
            balance = self._accounts[user_id]
            ledger_count = len([e for e in self._ledger_entries if e["account_id"] == str(user_id)])
            return balance, ledger_count

    def get_payment_events(
        self,
        actor: TrustedActorContext,
        payment_id: str,
    ) -> list[dict]:
        """Retrieve audit/lifecycle events for a payment."""
        with self._lock:
            record = self._payments.get(payment_id)
            if record is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment not found")

        view_level = authorize_payment_view_level(
            actor,
            payer_id=record.payer_id,
            assigned_guardian_id=record.assigned_guardian_id,
        )

        with self._lock:
            events = [
                {
                    "event_type": "PAYMENT_CREATED",
                    "payment_id": record.id,
                    "status": record.status.value,
                    "timestamp": record.created_at,
                }
            ]
            if record.decision_recorded_at:
                events.append({
                    "event_type": "GUARDIAN_DECISION",
                    "payment_id": record.id,
                    "status": record.status.value,
                    "timestamp": record.decision_recorded_at,
                })
            if record.fallback_activated_at:
                events.append({
                    "event_type": "FALLBACK_ACTIVATED",
                    "payment_id": record.id,
                    "status": record.status.value,
                    "timestamp": record.fallback_activated_at,
                })
            if record.confirmed_at:
                events.append({
                    "event_type": "PAYMENT_CONFIRMED",
                    "payment_id": record.id,
                    "status": record.status.value,
                    "timestamp": record.confirmed_at,
                })

            if view_level == "redacted":
                for ev in events:
                    ev.pop("amount_paise", None)
                    ev.pop("purpose", None)
            return events

    def get_guardian_pending_reviews(
        self,
        guardian_id: UUID,
    ) -> list[RedactedPaymentView]:
        """Retrieve active pending reviews assigned to a guardian."""
        with self._lock:
            pending: list[RedactedPaymentView] = []
            for record in self._payments.values():
                if (
                    record.assigned_guardian_id == guardian_id
                    and record.status == PaymentStatus.AWAITING_GUARDIAN
                ):
                    pending.append(self._build_redacted_view(record))
            return pending

    def toggle_safe_lock(
        self,
        payer_id: UUID,
        is_locked: bool,
    ) -> tuple[bool, int, str]:
        """Toggle Safe-Lock state for a payer."""
        with self._lock:
            self._safe_lock_states[payer_id] = is_locked
            now_str = datetime.now(timezone.utc).isoformat()
            return is_locked, 1, now_str

    def get_safe_lock_status(
        self,
        payer_id: UUID,
    ) -> tuple[bool, int, Optional[str]]:
        """Retrieve Safe-Lock status for a payer."""
        with self._lock:
            locked = self._safe_lock_states.get(payer_id)
            if locked is None:
                raise HTTPException(
                    status_code=status.HTTP_423_LOCKED,
                    detail="Authoritative Safe-Lock state is unavailable for payer (fail-closed)",
                )
            return locked, 1, datetime.now(timezone.utc).isoformat()

    def verify_audit_chain(self) -> tuple[bool, int, str]:
        """Verify mock audit hash chain."""
        with self._lock:
            if not hasattr(self, "_audit_chain") or not self._audit_chain.records:
                from safety.audit.audit_chain import AuditChain
                self._audit_chain = AuditChain()
                self._audit_chain.append("SYSTEM_START", {"status": "initialized"})
            valid = self._audit_chain.verify()
            return valid, len(self._audit_chain.records), self._audit_chain.records[-1].record_hash

    def get_payment_payer_id(self, payment_id: str) -> Optional[UUID]:
        """Resolve the owning payer UUID for internal event routing."""
        with self._lock:
            record = self._payments.get(payment_id)
            return record.payer_id if record is not None else None

    def get_audit_chain(self):
        """Retrieve mock audit chain for anchoring."""
        with self._lock:
            if not hasattr(self, "_audit_chain") or not self._audit_chain.records:
                from safety.audit.audit_chain import AuditChain
                self._audit_chain = AuditChain()
                self._audit_chain.append("SYSTEM_START", {"status": "initialized"})
            return self._audit_chain




_default_payment_service: Optional[PaymentService] = None


def get_payment_service() -> PaymentService:
    """Retrieve or initialize the global PaymentService singleton."""
    global _default_payment_service
    if _default_payment_service is None:
        _default_payment_service = PaymentService()
    return _default_payment_service

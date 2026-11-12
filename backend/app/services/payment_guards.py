"""Pure V2 topology and necessary guards, NOT a payment authorization service.

Inputs must be fresh trusted server state. Enrollment, anti-replay, evidence,
transaction binding and serialization still require a separately reviewed service.
No function mutates a payment, account or session.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from uuid import UUID

from app.models.roles import UserRole


class PaymentStatus(StrEnum):
    CREATED = "CREATED"
    AWAITING_WARNING = "AWAITING_WARNING"
    AWAITING_STEP_UP = "AWAITING_STEP_UP"
    AWAITING_GUARDIAN = "AWAITING_GUARDIAN"
    AWAITING_FALLBACK_REVIEW = "AWAITING_FALLBACK_REVIEW"
    READY_TO_EXECUTE = "READY_TO_EXECUTE"
    EXECUTED = "EXECUTED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    FAILED = "FAILED"


S = PaymentStatus
TRANSITION_TOPOLOGY = MappingProxyType({
    S.CREATED: frozenset({S.AWAITING_WARNING, S.AWAITING_STEP_UP, S.AWAITING_GUARDIAN,
                          S.AWAITING_FALLBACK_REVIEW, S.READY_TO_EXECUTE, S.REJECTED}),
    S.AWAITING_WARNING: frozenset({S.READY_TO_EXECUTE, S.CANCELLED}),
    S.AWAITING_STEP_UP: frozenset({S.READY_TO_EXECUTE, S.CANCELLED, S.EXPIRED, S.REJECTED}),
    S.AWAITING_GUARDIAN: frozenset({S.READY_TO_EXECUTE, S.REJECTED, S.CANCELLED,
                                    S.AWAITING_FALLBACK_REVIEW}),
    S.AWAITING_FALLBACK_REVIEW: frozenset({S.READY_TO_EXECUTE, S.REJECTED, S.CANCELLED, S.EXPIRED}),
    S.READY_TO_EXECUTE: frozenset({S.EXECUTED, S.CANCELLED, S.REJECTED, S.EXPIRED, S.FAILED}),
    **{terminal: frozenset() for terminal in (S.EXECUTED, S.REJECTED, S.CANCELLED, S.EXPIRED, S.FAILED)},
})


class PaymentGuardError(ValueError):
    """A necessary precondition failed; messages are not canonical reason codes."""


@dataclass(frozen=True)
class TrustedActorContext:
    """Server identity plus persisted grants AFTER authentication, never request data.

    Construction is not authentication. No API dependency currently creates this.
    """

    user_id: UUID
    roles: frozenset[UserRole]

    def __post_init__(self) -> None:
        if not isinstance(self.user_id, UUID) or not isinstance(self.roles, frozenset):
            raise PaymentGuardError("Trusted server actor context is required.")
        if any(not isinstance(role, UserRole) for role in self.roles):
            raise PaymentGuardError("Persisted server roles are required.")


def is_topologically_allowed(source: PaymentStatus, target: PaymentStatus) -> bool:
    """Check adjacency ONLY; an allowed edge never proves its preconditions."""
    return (isinstance(source, PaymentStatus) and isinstance(target, PaymentStatus)
            and target in TRANSITION_TOPOLOGY[source])


def _require_actor(actor: TrustedActorContext, owner_id: UUID | None, role: UserRole) -> None:
    if (not isinstance(actor, TrustedActorContext) or not isinstance(owner_id, UUID)
            or actor.user_id != owner_id or role not in actor.roles):
        raise PaymentGuardError("Required server actor binding is unavailable.")


def _aware(value: datetime) -> bool:
    return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None


def guardian_approval_target(
    *, status: PaymentStatus, actor: TrustedActorContext, assigned_guardian_id: UUID | None,
    guardian_deadline: datetime, server_now: datetime, hard_policy_allows: bool | None,
) -> PaymentStatus:
    """Necessary approval checks; caller must verify enrollment and bound anti-replay.

    Deadline comes from committed server state, now from the server clock. At the
    exact deadline approval fails even if the fallback worker has not run.
    """
    _require_actor(actor, assigned_guardian_id, UserRole.GUARDIAN)
    if not isinstance(status, PaymentStatus) or status is not S.AWAITING_GUARDIAN:
        raise PaymentGuardError("Payment is not awaiting guardian review.")
    if not _aware(guardian_deadline) or not _aware(server_now) or server_now >= guardian_deadline:
        raise PaymentGuardError("Guardian approval window is unavailable or expired.")
    if hard_policy_allows is not True:
        raise PaymentGuardError("Independent hard policy does not permit approval.")
    return S.READY_TO_EXECUTE


def require_payer_confirmation_preconditions(
    *, status: PaymentStatus, actor: TrustedActorContext, payer_id: UUID,
    safe_lock_is_locked: bool | None, hard_policy_allows: bool | None,
) -> None:
    """Necessary final checks, not execution permission; recheck within atomic work.

    Missing Safe-Lock fails closed. Amount/category/advice cannot weaken the binary
    lock. Passing this check never substitutes for durable idempotency or ledger.
    """
    _require_actor(actor, payer_id, UserRole.PAYER)
    if not isinstance(status, PaymentStatus) or status is not S.READY_TO_EXECUTE:
        raise PaymentGuardError("Payment is not ready for payer confirmation.")
    if safe_lock_is_locked is not False or hard_policy_allows is not True:
        raise PaymentGuardError("Fresh Safe-Lock and hard policy must permit confirmation.")


def guardian_timeout_target(
    *, status: PaymentStatus, guardian_deadline: datetime, server_now: datetime,
) -> PaymentStatus:
    """Necessary timeout checks against committed deadline; never releases payment.

    Caller still needs actor/service authorization and atomic state/version update
    so a concurrent guardian decision and timeout cannot both win.
    """
    if not isinstance(status, PaymentStatus) or status is not S.AWAITING_GUARDIAN:
        raise PaymentGuardError("Payment is not awaiting guardian review.")
    if not _aware(guardian_deadline) or not _aware(server_now) or server_now < guardian_deadline:
        raise PaymentGuardError("Guardian deadline is unavailable or not reached.")
    return S.AWAITING_FALLBACK_REVIEW

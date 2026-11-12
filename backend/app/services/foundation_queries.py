"""Parameterized ORM statements only; caller owns transaction and authorization.

Use fresh server identity, never request actor/owner IDs. Locks require a live
PostgreSQL transaction; offline compilation proves no concurrency guarantees.
Role grants alone do not establish guardian assignment or authentication.
Read and refresh all required locked rows before mutation on a clean session:
populate_existing replaces cached attributes and can discard pending changes.
"""

from uuid import UUID

from sqlalchemy import Select, select

from app.models.account import MockAccount
from app.models.audit import AuditEvent
from app.models.idempotency import IdempotencyRecord
from app.models.ledger import LedgerEntry
from app.models.payment import GuardianDecision, Payment
from app.models.safe_lock import SafeLockState
from app.models.user import RoleBinding
from app.services.payment_guards import TrustedActorContext


def role_bindings_for_update(actor: TrustedActorContext) -> Select:
    return (select(RoleBinding).where(RoleBinding.user_id == actor.user_id)
            .with_for_update().execution_options(populate_existing=True))


def owned_account_for_update(actor: TrustedActorContext, account_id: UUID) -> Select:
    return select(MockAccount).where(
        MockAccount.id == account_id, MockAccount.owner_id == actor.user_id,
    ).with_for_update().execution_options(populate_existing=True)


def payer_account_for_update(payer_id: UUID) -> Select:
    return select(MockAccount).where(
        MockAccount.owner_id == payer_id,
    ).with_for_update().execution_options(populate_existing=True)


def safe_lock_for_update(actor: TrustedActorContext) -> Select:
    # A missing row must remain unknown, never default to unlocked. FOR UPDATE
    # cannot lock an absent row; provisioning/lock order remains a future decision.
    return (select(SafeLockState).where(SafeLockState.payer_id == actor.user_id)
            .with_for_update().execution_options(populate_existing=True))


def safe_lock_for_payer_for_update(payer_id: UUID) -> Select:
    return (select(SafeLockState).where(SafeLockState.payer_id == payer_id)
            .with_for_update().execution_options(populate_existing=True))


def payment_for_update(payment_id: str) -> Select:
    return (select(Payment).where(Payment.id == payment_id)
            .with_for_update().execution_options(populate_existing=True))


def guardian_decision_for_update(payment_id: str) -> Select:
    return (select(GuardianDecision).where(GuardianDecision.payment_id == payment_id)
            .with_for_update().execution_options(populate_existing=True))


def idempotency_record_for_update(key: str) -> Select:
    return (select(IdempotencyRecord).where(IdempotencyRecord.key == key)
            .with_for_update().execution_options(populate_existing=True))


def ledger_entries_for_payment(payment_id: str) -> Select:
    return select(LedgerEntry).where(LedgerEntry.payment_id == payment_id).order_by(LedgerEntry.created_at)


def audit_events_for_payment(payment_id: str) -> Select:
    return select(AuditEvent).where(AuditEvent.payment_id == payment_id).order_by(AuditEvent.created_at)

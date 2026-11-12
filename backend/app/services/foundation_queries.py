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


def safe_lock_for_update(actor: TrustedActorContext) -> Select:
    # A missing row must remain unknown, never default to unlocked. FOR UPDATE
    # cannot lock an absent row; provisioning/lock order remains a future decision.
    return (select(SafeLockState).where(SafeLockState.payer_id == actor.user_id)
            .with_for_update().execution_options(populate_existing=True))

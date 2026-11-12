"""Explicit offline model registration, separate from application startup."""

from app.models.account import MockAccount
from app.models.audit import AuditEvent
from app.models.database import Base
from app.models.idempotency import IdempotencyRecord
from app.models.ledger import LedgerEntry
from app.models.payment import GuardianDecision, Payment
from app.models.safe_lock import SafeLockState
from app.models.user import RoleBinding, SyntheticUser, UserRole

metadata = Base.metadata

__all__ = [
    "AuditEvent",
    "GuardianDecision",
    "IdempotencyRecord",
    "LedgerEntry",
    "MockAccount",
    "Payment",
    "RoleBinding",
    "SafeLockState",
    "SyntheticUser",
    "UserRole",
    "metadata",
]

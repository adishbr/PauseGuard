"""Explicit offline model registration, separate from application startup."""

from app.models.account import MockAccount
from app.models.audit import AuditEvent
from app.models.database import Base
from app.models.idempotency import IdempotencyRecord
from app.models.identity import (
    GuardianInvitation,
    IdentityAssurance,
    OtpChallenge,
    UserAccount,
    UserSession,
)
from app.models.ledger import LedgerEntry
from app.models.payment import GuardianDecision, Payment, PaymentAppeal
from app.models.razorpay import RazorpayOrder, RazorpayPayment, RazorpayWebhookEvent
from app.models.safe_lock import SafeLockState
from app.models.user import RoleBinding, SyntheticUser, UserRole

metadata = Base.metadata

__all__ = [
    "AuditEvent",
    "GuardianDecision",
    "GuardianInvitation",
    "IdempotencyRecord",
    "IdentityAssurance",
    "LedgerEntry",
    "MockAccount",
    "OtpChallenge",
    "Payment",
    "PaymentAppeal",
    "RazorpayOrder",
    "RazorpayPayment",
    "RazorpayWebhookEvent",
    "RoleBinding",
    "SafeLockState",
    "SyntheticUser",
    "UserAccount",
    "UserRole",
    "UserSession",
    "metadata",
]

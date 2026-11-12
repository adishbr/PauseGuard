"""Durable payment and guardian decision ORM models for V2 transactions."""

from datetime import datetime
from typing import TYPE_CHECKING, List, Optional
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.models.database import Base
from app.models.user import SyntheticUser

if TYPE_CHECKING:
    from app.models.audit import AuditEvent
    from app.models.ledger import LedgerEntry

CANONICAL_PAYMENT_STATUSES = (
    "CREATED",
    "AWAITING_WARNING",
    "AWAITING_STEP_UP",
    "AWAITING_GUARDIAN",
    "AWAITING_FALLBACK_REVIEW",
    "READY_TO_EXECUTE",
    "EXECUTED",
    "REJECTED",
    "CANCELLED",
    "EXPIRED",
    "FAILED",
)

STATUS_CHECK_SQL = ", ".join(f"'{s}'" for s in CANONICAL_PAYMENT_STATUSES)


class Payment(Base):
    """Persistent payment record adhering to canonical V2 state machine topology."""

    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint("amount_paise > 0", name="ck_payments_positive_amount"),
        CheckConstraint("version > 0", name="ck_payments_positive_version"),
        CheckConstraint("tier >= 0 AND tier <= 3", name="ck_payments_tier_range"),
        CheckConstraint(f"status IN ({STATUS_CHECK_SQL})", name="ck_payments_status"),
        Index("ix_payments_payer_id", "payer_id"),
        Index("ix_payments_status", "status"),
        Index("ix_payments_idempotency_key", "idempotency_key", unique=True),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    payer_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", name="fk_payments_payer", ondelete="RESTRICT"),
        nullable=False,
    )
    beneficiary_id: Mapped[str] = mapped_column(String(128), nullable=False)
    amount_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    purpose: Mapped[str] = mapped_column(String(256), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="CREATED", server_default="CREATED"
    )
    tier: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    risk_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    reason_codes: Mapped[list] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False, default=list
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    assigned_guardian_id: Mapped[Optional[UUID]] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", name="fk_payments_guardian", ondelete="RESTRICT"),
        nullable=True,
    )
    guardian_deadline: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    payer: Mapped[SyntheticUser] = relationship(foreign_keys=[payer_id], lazy="raise")
    guardian: Mapped[Optional[SyntheticUser]] = relationship(
        foreign_keys=[assigned_guardian_id], lazy="raise"
    )
    decision: Mapped[Optional["GuardianDecision"]] = relationship(
        back_populates="payment", lazy="raise", uselist=False
    )
    ledger_entries: Mapped[List["LedgerEntry"]] = relationship(
        back_populates="payment", lazy="raise"
    )
    audit_events: Mapped[List["AuditEvent"]] = relationship(
        back_populates="payment", lazy="raise"
    )

    __mapper_args__ = {"version_id_col": version}


class GuardianDecision(Base):
    """Immutable persistent record of an authenticated guardian's decision."""

    __tablename__ = "guardian_decisions"
    __table_args__ = (
        UniqueConstraint("payment_id", name="uq_guardian_decisions_payment"),
        Index("ix_guardian_decisions_guardian_id", "guardian_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    payment_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("payments.id", name="fk_guardian_decisions_payment", ondelete="RESTRICT"),
        nullable=False,
    )
    guardian_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", name="fk_guardian_decisions_guardian", ondelete="RESTRICT"),
        nullable=False,
    )
    approved: Mapped[bool] = mapped_column(Boolean, nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    target_status: Mapped[str] = mapped_column(String(32), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    payment: Mapped[Payment] = relationship(back_populates="decision", lazy="raise")
    guardian: Mapped[SyntheticUser] = relationship(foreign_keys=[guardian_id], lazy="raise")

"""Immutable double-entry mock ledger ORM model."""

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.account import MockAccount
from app.models.database import Base

if TYPE_CHECKING:
    from app.models.payment import Payment


class LedgerEntry(Base):
    """Immutable record of an atomic mock balance debit or credit."""

    __tablename__ = "ledger_entries"
    __table_args__ = (
        CheckConstraint("amount_paise > 0", name="ck_ledger_entries_positive_amount"),
        CheckConstraint("entry_type IN ('DEBIT', 'CREDIT')", name="ck_ledger_entries_type"),
        UniqueConstraint("idempotency_key", name="uq_ledger_entries_idempotency_key"),
        Index("ix_ledger_entries_payment_id", "payment_id"),
        Index("ix_ledger_entries_account_id", "account_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    payment_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("payments.id", name="fk_ledger_entries_payment", ondelete="RESTRICT"),
        nullable=False,
    )
    account_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("accounts.id", name="fk_ledger_entries_account", ondelete="RESTRICT"),
        nullable=False,
    )
    amount_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    entry_type: Mapped[str] = mapped_column(String(16), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    payment: Mapped["Payment"] = relationship(back_populates="ledger_entries", lazy="raise")
    account: Mapped[MockAccount] = relationship(lazy="raise")

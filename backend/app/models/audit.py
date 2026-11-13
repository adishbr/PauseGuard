"""Persistent audit log ORM model with cryptographic chain linkage."""

from datetime import datetime
from typing import TYPE_CHECKING, Optional
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Sequence,
    String,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.models.database import Base

if TYPE_CHECKING:
    from app.models.payment import Payment

AUDIT_EVENTS_APPEND_SEQ = Sequence(
    "audit_events_append_seq",
    start=1,
    increment=1,
    metadata=Base.metadata,
)


class AuditEvent(Base):
    """Immutable audit record committed atomically with payment transitions."""

    __tablename__ = "audit_events"
    __table_args__ = (
        CheckConstraint("append_seq > 0", name="ck_audit_events_positive_append_seq"),
        Index("ix_audit_events_append_seq", "append_seq", unique=True),
        Index("ix_audit_events_payment_id", "payment_id"),
        Index("ix_audit_events_actor_id", "actor_id"),
        Index("ix_audit_events_event_type", "event_type"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    append_seq: Mapped[int] = mapped_column(BigInteger, nullable=False)
    payment_id: Mapped[Optional[str]] = mapped_column(
        String(64),
        ForeignKey("payments.id", name="fk_audit_events_payment", ondelete="RESTRICT"),
        nullable=True,
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    actor_role: Mapped[str] = mapped_column(String(32), nullable=False)
    prev_hash: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    event_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    payload_json: Mapped[Optional[dict]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    payment: Mapped[Optional["Payment"]] = relationship(
        back_populates="audit_events", lazy="raise"
    )


"""Durable notification outbox ORM model for cross-device / offline delivery."""

from datetime import datetime
from typing import Any, Optional
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    PrimaryKeyConstraint,
    String,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.database import Base

NOTIFICATION_STATUS_VALUES = ("PENDING", "SENT", "DELIVERED", "FAILED")
NOTIFICATION_CHANNEL_VALUES = ("IN_APP", "WEB_PUSH", "SMS_STUB")


class NotificationOutbox(Base):
    """Durable outbox record for guardian and payer security notifications.

    SECURITY INVARIANT:
    Guardian outbox payloads NEVER store sensitive payment amounts or beneficiary IDs.
    """

    __tablename__ = "notification_outbox"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_notification_outbox"),
        CheckConstraint(
            "status IN ('PENDING', 'SENT', 'DELIVERED', 'FAILED')",
            name="ck_notification_outbox_status",
        ),
        CheckConstraint(
            "channel IN ('IN_APP', 'WEB_PUSH', 'SMS_STUB')",
            name="ck_notification_outbox_channel",
        ),
        CheckConstraint("attempts >= 0", name="ck_notification_outbox_attempts"),
        Index("ix_notification_outbox_recipient_user_id", "recipient_user_id"),
        Index("ix_notification_outbox_payment_id", "payment_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, default=uuid4)
    payment_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    recipient_user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", name="fk_notification_outbox_recipient", ondelete="RESTRICT"),
        nullable=False,
    )
    recipient_role: Mapped[str] = mapped_column(String(32), nullable=False)
    channel: Mapped[str] = mapped_column(
        String(32), nullable=False, default="IN_APP", server_default="IN_APP"
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="SENT", server_default="SENT"
    )
    delivery_provider: Mapped[str] = mapped_column(
        String(64), nullable=False, default="in_app_outbox", server_default="in_app_outbox"
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    last_error: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    delivered_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

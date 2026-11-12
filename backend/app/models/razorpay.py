"""SQLAlchemy models for Razorpay Test Mode merchant sandbox orders and webhooks."""

from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, String, Uuid
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.database import Base


class RazorpayOrder(Base):
    """Internal record of a Razorpay Test Mode merchant order."""

    __tablename__ = "razorpay_orders"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    razorpay_order_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    admin_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", name="fk_razorpay_orders_admin", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    amount_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), server_default="INR", nullable=False)
    status: Mapped[str] = mapped_column(String(32), server_default="created", nullable=False, index=True)
    receipt: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    notes_json: Mapped[dict | None] = mapped_column(
        sa.JSON().with_variant(postgresql.JSONB, "postgresql"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=sa.func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
        nullable=False,
    )

    payments: Mapped[list["RazorpayPayment"]] = relationship(
        "RazorpayPayment",
        back_populates="order",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        CheckConstraint("amount_paise > 0", name="ck_razorpay_orders_positive_amount"),
        CheckConstraint(
            "status IN ('created', 'attempted', 'paid', 'failed', 'cancelled')",
            name="ck_razorpay_orders_status",
        ),
    )


class RazorpayPayment(Base):
    """Internal record of a verified or captured Razorpay Test Mode payment."""

    __tablename__ = "razorpay_payments"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # pay_...
    order_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("razorpay_orders.id", name="fk_razorpay_payments_order", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    razorpay_order_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    amount_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), server_default="INR", nullable=False)
    status: Mapped[str] = mapped_column(String(32), server_default="authorized", nullable=False, index=True)
    method: Mapped[str | None] = mapped_column(String(32), nullable=True)
    signature: Mapped[str | None] = mapped_column(String(128), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_description: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=sa.func.now(),
        nullable=False,
    )

    order: Mapped["RazorpayOrder"] = relationship("RazorpayOrder", back_populates="payments")

    __table_args__ = (
        CheckConstraint("amount_paise > 0", name="ck_razorpay_payments_positive_amount"),
        CheckConstraint(
            "status IN ('authorized', 'captured', 'failed', 'refunded')",
            name="ck_razorpay_payments_status",
        ),
    )


class RazorpayWebhookEvent(Base):
    """Immutable audit record and replay barrier for inbound Razorpay webhook events."""

    __tablename__ = "razorpay_webhook_events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # event_...
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    entity_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    payload_json: Mapped[dict] = mapped_column(
        sa.JSON().with_variant(postgresql.JSONB, "postgresql"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(32), server_default="processed", nullable=False)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=sa.func.now(),
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('processed', 'duplicate', 'ignored', 'failed')",
            name="ck_razorpay_webhook_events_status",
        ),
    )


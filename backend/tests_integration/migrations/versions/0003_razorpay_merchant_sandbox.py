"""Razorpay Test Mode merchant sandbox orders, payments, and webhook replay protection.

Revision ID: 0003_razorpay_merchant_sandbox
Revises: 0002_durable_payment_ledger

Creates tables:
- razorpay_orders
- razorpay_payments
- razorpay_webhook_events
"""

from alembic import op
import sqlalchemy as sa

revision = "0003_razorpay_merchant_sandbox"
down_revision = "0002_durable_payment_ledger"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "razorpay_orders",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("razorpay_order_id", sa.String(length=64), nullable=False),
        sa.Column("admin_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("amount_paise", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), server_default="INR", nullable=False),
        sa.Column("status", sa.String(length=32), server_default="created", nullable=False),
        sa.Column("receipt", sa.String(length=128), nullable=True),
        sa.Column("notes_json", sa.JSON().with_variant(sa.dialects.postgresql.JSONB, "postgresql"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["admin_id"], ["users.id"], name="fk_razorpay_orders_admin", ondelete="RESTRICT"),
        sa.CheckConstraint("amount_paise > 0", name="ck_razorpay_orders_positive_amount"),
        sa.CheckConstraint(
            "status IN ('created', 'attempted', 'paid', 'failed', 'cancelled')",
            name="ck_razorpay_orders_status",
        ),
    )
    op.create_index("ix_razorpay_orders_razorpay_order_id", "razorpay_orders", ["razorpay_order_id"], unique=True)
    op.create_index("ix_razorpay_orders_admin_id", "razorpay_orders", ["admin_id"], unique=False)
    op.create_index("ix_razorpay_orders_status", "razorpay_orders", ["status"], unique=False)
    op.create_index("ix_razorpay_orders_receipt", "razorpay_orders", ["receipt"], unique=False)

    op.create_table(
        "razorpay_payments",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("order_id", sa.String(length=64), nullable=False),
        sa.Column("razorpay_order_id", sa.String(length=64), nullable=False),
        sa.Column("amount_paise", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), server_default="INR", nullable=False),
        sa.Column("status", sa.String(length=32), server_default="authorized", nullable=False),
        sa.Column("method", sa.String(length=32), nullable=True),
        sa.Column("signature", sa.String(length=128), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["order_id"], ["razorpay_orders.id"], name="fk_razorpay_payments_order", ondelete="RESTRICT"),
        sa.CheckConstraint("amount_paise > 0", name="ck_razorpay_payments_positive_amount"),
        sa.CheckConstraint(
            "status IN ('authorized', 'captured', 'failed', 'refunded')",
            name="ck_razorpay_payments_status",
        ),
    )
    op.create_index("ix_razorpay_payments_order_id", "razorpay_payments", ["order_id"], unique=False)
    op.create_index("ix_razorpay_payments_razorpay_order_id", "razorpay_payments", ["razorpay_order_id"], unique=False)
    op.create_index("ix_razorpay_payments_status", "razorpay_payments", ["status"], unique=False)

    op.create_table(
        "razorpay_webhook_events",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("entity_id", sa.String(length=64), nullable=True),
        sa.Column("payload_json", sa.JSON().with_variant(sa.dialects.postgresql.JSONB, "postgresql"), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="processed", nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "status IN ('processed', 'duplicate', 'ignored', 'failed')",
            name="ck_razorpay_webhook_events_status",
        ),
    )
    op.create_index("ix_razorpay_webhook_events_event_type", "razorpay_webhook_events", ["event_type"], unique=False)
    op.create_index("ix_razorpay_webhook_events_entity_id", "razorpay_webhook_events", ["entity_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_razorpay_webhook_events_entity_id", table_name="razorpay_webhook_events")
    op.drop_index("ix_razorpay_webhook_events_event_type", table_name="razorpay_webhook_events")
    op.drop_table("razorpay_webhook_events")

    op.drop_index("ix_razorpay_payments_status", table_name="razorpay_payments")
    op.drop_index("ix_razorpay_payments_razorpay_order_id", table_name="razorpay_payments")
    op.drop_index("ix_razorpay_payments_order_id", table_name="razorpay_payments")
    op.drop_table("razorpay_payments")

    op.drop_index("ix_razorpay_orders_receipt", table_name="razorpay_orders")
    op.drop_index("ix_razorpay_orders_status", table_name="razorpay_orders")
    op.drop_index("ix_razorpay_orders_admin_id", table_name="razorpay_orders")
    op.drop_index("ix_razorpay_orders_razorpay_order_id", table_name="razorpay_orders")
    op.drop_table("razorpay_orders")


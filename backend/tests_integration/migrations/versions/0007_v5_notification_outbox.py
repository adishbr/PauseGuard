"""V5 durable notification outbox table for cross-device guardian and payer alerts.

Revision ID: 0007_v5_notification_outbox
Revises: 0006_v5_appeals_retry_stepup

Creates table:
- notification_outbox
"""

from alembic import op
import sqlalchemy as sa

revision = "0007_v5_notification_outbox"
down_revision = "0006_v5_appeals_retry_stepup"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notification_outbox",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("payment_id", sa.String(length=64), nullable=True),
        sa.Column("recipient_user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("recipient_role", sa.String(length=32), nullable=False),
        sa.Column("channel", sa.String(length=32), server_default="IN_APP", nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="SENT", nullable=False),
        sa.Column("delivery_provider", sa.String(length=64), server_default="in_app_outbox", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="1", nullable=False),
        sa.Column("last_error", sa.String(length=256), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_notification_outbox"),
        sa.ForeignKeyConstraint(
            ["recipient_user_id"],
            ["users.id"],
            name="fk_notification_outbox_recipient",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'SENT', 'DELIVERED', 'FAILED')",
            name="ck_notification_outbox_status",
        ),
        sa.CheckConstraint(
            "channel IN ('IN_APP', 'WEB_PUSH', 'SMS_STUB')",
            name="ck_notification_outbox_channel",
        ),
        sa.CheckConstraint("attempts >= 0", name="ck_notification_outbox_attempts"),
    )
    op.create_index(
        "ix_notification_outbox_recipient_user_id",
        "notification_outbox",
        ["recipient_user_id"],
        unique=False,
    )
    op.create_index(
        "ix_notification_outbox_payment_id",
        "notification_outbox",
        ["payment_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_notification_outbox_payment_id", table_name="notification_outbox")
    op.drop_index("ix_notification_outbox_recipient_user_id", table_name="notification_outbox")
    op.drop_table("notification_outbox")

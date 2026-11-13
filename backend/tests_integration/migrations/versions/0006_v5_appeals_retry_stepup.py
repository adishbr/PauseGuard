"""V5 payment integrity snapshot, retry lineage, step-up, and appeals.

Revision ID: 0006_v5_appeals_retry_stepup
Revises: 0005_v5_identity_otp_enrollment

Extends payments and creates table:
- payment_appeals
"""

from alembic import op
import sqlalchemy as sa

revision = "0006_v5_appeals_retry_stepup"
down_revision = "0005_v5_identity_otp_enrollment"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("payments", sa.Column("approved_beneficiary_id", sa.String(length=128), nullable=True))
    op.add_column("payments", sa.Column("approved_amount_paise", sa.BigInteger(), nullable=True))
    op.add_column("payments", sa.Column("approval_snapshot_hash", sa.String(length=128), nullable=True))
    op.add_column("payments", sa.Column("parent_payment_id", sa.String(length=64), nullable=True))
    op.add_column("payments", sa.Column("step_up_verified_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_payments_parent_payment_id", "payments", ["parent_payment_id"], unique=False)

    op.create_table(
        "payment_appeals",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("payment_id", sa.String(length=64), nullable=False),
        sa.Column("payer_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="OPEN", nullable=False),
        sa.Column("reason", sa.String(length=512), nullable=False),
        sa.Column("evidence_note", sa.String(length=512), nullable=True),
        sa.Column("resolved_by_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("resolution_note", sa.String(length=512), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_payment_appeals"),
        sa.ForeignKeyConstraint(["payment_id"], ["payments.id"], name="fk_payment_appeals_payment", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["payer_id"], ["users.id"], name="fk_payment_appeals_payer", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["resolved_by_id"], ["users.id"], name="fk_payment_appeals_resolver", ondelete="RESTRICT"),
        sa.CheckConstraint("status IN ('OPEN', 'APPROVED_RETRY_ELIGIBLE', 'REJECTED')", name="ck_payment_appeals_status"),
    )
    op.create_index("ix_payment_appeals_payment_id", "payment_appeals", ["payment_id"], unique=False)
    op.create_index("ix_payment_appeals_status", "payment_appeals", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_payment_appeals_status", table_name="payment_appeals")
    op.drop_index("ix_payment_appeals_payment_id", table_name="payment_appeals")
    op.drop_table("payment_appeals")
    op.drop_index("ix_payments_parent_payment_id", table_name="payments")
    op.drop_column("payments", "step_up_verified_at")
    op.drop_column("payments", "parent_payment_id")
    op.drop_column("payments", "approval_snapshot_hash")
    op.drop_column("payments", "approved_amount_paise")
    op.drop_column("payments", "approved_beneficiary_id")

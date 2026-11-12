"""Durable payment records, guardian decisions, and atomic mock ledger foundation.

Revision ID: 0002_durable_payment_ledger
Revises: 0001_offline_foundation

Creates tables:
- payments
- guardian_decisions
- ledger_entries
- audit_events
- idempotency_records
"""

from alembic import op
import sqlalchemy as sa

revision = "0002_durable_payment_ledger"
down_revision = "0001_offline_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "payments",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("payer_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("beneficiary_id", sa.String(length=128), nullable=False),
        sa.Column("amount_paise", sa.BigInteger(), nullable=False),
        sa.Column("purpose", sa.String(length=256), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="CREATED", nullable=False),
        sa.Column("tier", sa.Integer(), server_default="0", nullable=False),
        sa.Column("risk_score", sa.Integer(), server_default="0", nullable=False),
        sa.Column("reason_codes", sa.JSON().with_variant(sa.dialects.postgresql.JSONB, "postgresql"), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("assigned_guardian_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("guardian_deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["payer_id"], ["users.id"], name="fk_payments_payer", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["assigned_guardian_id"], ["users.id"], name="fk_payments_guardian", ondelete="RESTRICT"),
        sa.CheckConstraint("amount_paise > 0", name="ck_payments_positive_amount"),
        sa.CheckConstraint("version > 0", name="ck_payments_positive_version"),
        sa.CheckConstraint("tier >= 0 AND tier <= 3", name="ck_payments_tier_range"),
        sa.CheckConstraint(
            "status IN ('CREATED', 'AWAITING_WARNING', 'AWAITING_STEP_UP', 'AWAITING_GUARDIAN', "
            "'AWAITING_FALLBACK_REVIEW', 'READY_TO_EXECUTE', 'EXECUTED', 'REJECTED', 'CANCELLED', 'EXPIRED', 'FAILED')",
            name="ck_payments_status",
        ),
    )
    op.create_index("ix_payments_payer_id", "payments", ["payer_id"], unique=False)
    op.create_index("ix_payments_status", "payments", ["status"], unique=False)
    op.create_index("ix_payments_idempotency_key", "payments", ["idempotency_key"], unique=True)

    op.create_table(
        "guardian_decisions",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("payment_id", sa.String(length=64), nullable=False),
        sa.Column("guardian_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("approved", sa.Boolean(), nullable=False),
        sa.Column("notes", sa.String(length=256), nullable=True),
        sa.Column("target_status", sa.String(length=32), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["payment_id"], ["payments.id"], name="fk_guardian_decisions_payment", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["guardian_id"], ["users.id"], name="fk_guardian_decisions_guardian", ondelete="RESTRICT"),
        sa.UniqueConstraint("payment_id", name="uq_guardian_decisions_payment"),
    )
    op.create_index("ix_guardian_decisions_guardian_id", "guardian_decisions", ["guardian_id"], unique=False)

    op.create_table(
        "ledger_entries",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("payment_id", sa.String(length=64), nullable=False),
        sa.Column("account_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("amount_paise", sa.BigInteger(), nullable=False),
        sa.Column("entry_type", sa.String(length=16), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["payment_id"], ["payments.id"], name="fk_ledger_entries_payment", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], name="fk_ledger_entries_account", ondelete="RESTRICT"),
        sa.CheckConstraint("amount_paise > 0", name="ck_ledger_entries_positive_amount"),
        sa.CheckConstraint("entry_type IN ('DEBIT', 'CREDIT')", name="ck_ledger_entries_type"),
        sa.UniqueConstraint("idempotency_key", name="uq_ledger_entries_idempotency_key"),
    )
    op.create_index("ix_ledger_entries_payment_id", "ledger_entries", ["payment_id"], unique=False)
    op.create_index("ix_ledger_entries_account_id", "ledger_entries", ["account_id"], unique=False)

    op.create_table(
        "audit_events",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("payment_id", sa.String(length=64), nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("actor_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("actor_role", sa.String(length=32), nullable=False),
        sa.Column("prev_hash", sa.String(length=128), nullable=True),
        sa.Column("event_hash", sa.String(length=128), nullable=False),
        sa.Column("payload_json", sa.JSON().with_variant(sa.dialects.postgresql.JSONB, "postgresql"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["payment_id"], ["payments.id"], name="fk_audit_events_payment", ondelete="RESTRICT"),
    )
    op.create_index("ix_audit_events_payment_id", "audit_events", ["payment_id"], unique=False)
    op.create_index("ix_audit_events_actor_id", "audit_events", ["actor_id"], unique=False)
    op.create_index("ix_audit_events_event_type", "audit_events", ["event_type"], unique=False)

    op.create_table(
        "idempotency_records",
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("caller_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("endpoint", sa.String(length=128), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=False),
        sa.Column("response_body", sa.JSON().with_variant(sa.dialects.postgresql.JSONB, "postgresql"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )
    op.create_index("ix_idempotency_records_caller_endpoint", "idempotency_records", ["caller_id", "endpoint"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_idempotency_records_caller_endpoint", table_name="idempotency_records")
    op.drop_table("idempotency_records")
    op.drop_index("ix_audit_events_event_type", table_name="audit_events")
    op.drop_index("ix_audit_events_actor_id", table_name="audit_events")
    op.drop_index("ix_audit_events_payment_id", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_index("ix_ledger_entries_account_id", table_name="ledger_entries")
    op.drop_index("ix_ledger_entries_payment_id", table_name="ledger_entries")
    op.drop_table("ledger_entries")
    op.drop_index("ix_guardian_decisions_guardian_id", table_name="guardian_decisions")
    op.drop_table("guardian_decisions")
    op.drop_index("ix_payments_idempotency_key", table_name="payments")
    op.drop_index("ix_payments_status", table_name="payments")
    op.drop_index("ix_payments_payer_id", table_name="payments")
    op.drop_table("payments")

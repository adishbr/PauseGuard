"""Frozen Phase 2A schema; no payment, ledger, seed or authentication operations.

Revision ID: 0001_offline_foundation
Revises: None

UUID generation, update timestamps and optimistic increments remain ORM behavior;
this revision intentionally adds no database triggers or funding defaults.
"""

from alembic import op
import sqlalchemy as sa

revision = "0001_offline_foundation"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "role_bindings",
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(length=8), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "role", name="pk_role_bindings"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_role_bindings_user", ondelete="RESTRICT"),
        sa.CheckConstraint("role IN ('payer', 'guardian', 'analyst', 'admin')", name="ck_role_bindings_role"),
    )
    op.create_table(
        "accounts",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("owner_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("balance_paise", sa.BigInteger(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], name="fk_accounts_owner", ondelete="RESTRICT"),
        sa.CheckConstraint("balance_paise >= 0", name="ck_accounts_nonnegative_balance"),
        sa.CheckConstraint("version > 0", name="ck_accounts_positive_version"),
    )
    op.create_index("ix_accounts_owner_id", "accounts", ["owner_id"], unique=False)
    op.create_table(
        "safe_lock_states",
        sa.Column("payer_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("is_locked", sa.Boolean(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("payer_id"),
        sa.ForeignKeyConstraint(["payer_id"], ["users.id"], name="fk_safe_lock_states_payer", ondelete="RESTRICT"),
        sa.CheckConstraint("version > 0", name="ck_safe_lock_states_positive_version"),
    )


def downgrade() -> None:
    op.drop_table("safe_lock_states")
    op.drop_index("ix_accounts_owner_id", table_name="accounts")
    op.drop_table("accounts")
    op.drop_table("role_bindings")
    op.drop_table("users")

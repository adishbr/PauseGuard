"""V5 durable user accounts, identity assurances, OTP challenges, sessions, and guardian invitations.

Revision ID: 0005_v5_identity_otp_enrollment
Revises: 0004_audit_append_sequence

Creates tables:
- user_accounts
- identity_assurances
- otp_challenges
- user_sessions
- guardian_invitations
"""

from alembic import op
import sqlalchemy as sa

revision = "0005_v5_identity_otp_enrollment"
down_revision = "0004_audit_append_sequence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_accounts",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("full_name", sa.String(length=120), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("password_hash", sa.String(length=512), nullable=False),
        sa.Column("email_verified", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("is_synthetic", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_user_accounts"),
        sa.ForeignKeyConstraint(["id"], ["users.id"], name="fk_user_accounts_user", ondelete="RESTRICT"),
        sa.CheckConstraint("role IN ('payer', 'guardian', 'analyst', 'admin')", name="ck_user_accounts_role"),
    )
    op.create_index("ix_user_accounts_email", "user_accounts", ["email"], unique=True)
    op.create_index("ix_user_accounts_role", "user_accounts", ["role"], unique=False)

    op.create_table(
        "identity_assurances",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("trusted_person_ref", sa.String(length=128), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("assurance_level", sa.String(length=64), nullable=False),
        sa.Column("provider_evidence_ref", sa.String(length=128), nullable=False),
        sa.Column("is_mock_assurance", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("revoked", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_identity_assurances"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_identity_assurances_user", ondelete="RESTRICT"),
    )
    op.create_index("ix_identity_assurances_user_id", "identity_assurances", ["user_id"], unique=False)
    op.create_index("ix_identity_assurances_trusted_person_ref", "identity_assurances", ["trusted_person_ref"], unique=False)

    op.create_table(
        "otp_challenges",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("contact", sa.String(length=255), nullable=False),
        sa.Column("purpose", sa.String(length=64), nullable=False),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("otp_salt", sa.String(length=64), nullable=False),
        sa.Column("otp_hash", sa.String(length=128), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default="5", nullable=False),
        sa.Column("status", sa.String(length=32), server_default="PENDING", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_otp_challenges"),
        sa.CheckConstraint("attempts >= 0", name="ck_otp_challenges_attempts_non_negative"),
        sa.CheckConstraint("max_attempts > 0", name="ck_otp_challenges_max_attempts_positive"),
        sa.CheckConstraint("status IN ('PENDING', 'VERIFIED', 'LOCKED', 'EXPIRED')", name="ck_otp_challenges_status"),
    )
    op.create_index("ix_otp_challenges_contact_purpose", "otp_challenges", ["contact", "purpose"], unique=False)

    op.create_table(
        "user_sessions",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("auth_method", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_user_sessions"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_user_sessions_user", ondelete="RESTRICT"),
    )
    op.create_index("ix_user_sessions_token_hash", "user_sessions", ["token_hash"], unique=True)
    op.create_index("ix_user_sessions_user_id", "user_sessions", ["user_id"], unique=False)

    op.create_table(
        "guardian_invitations",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("payer_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("guardian_user_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("guardian_email", sa.String(length=255), nullable=False),
        sa.Column("relationship_label", sa.String(length=64), nullable=False),
        sa.Column("role_slot", sa.String(length=16), server_default="primary", nullable=False),
        sa.Column("notification_channel", sa.String(length=32), nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="PENDING", nullable=False),
        sa.Column("payer_trusted_person_ref", sa.String(length=128), nullable=True),
        sa.Column("guardian_trusted_person_ref", sa.String(length=128), nullable=True),
        sa.Column("consent_confirmed", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_guardian_invitations"),
        sa.ForeignKeyConstraint(["payer_id"], ["users.id"], name="fk_guardian_invitations_payer", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["guardian_user_id"], ["users.id"], name="fk_guardian_invitations_guardian", ondelete="RESTRICT"),
        sa.CheckConstraint("role_slot IN ('primary', 'backup')", name="ck_guardian_invitations_role_slot"),
        sa.CheckConstraint(
            "status IN ('PENDING', 'CONTACT_VERIFIED', 'IDENTITY_VERIFIED', 'CONSENTED', 'ACTIVE', 'DECLINED', 'REVOKED', 'EXPIRED', 'SUSPENDED')",
            name="ck_guardian_invitations_status",
        ),
    )
    op.create_index("ix_guardian_invitations_token_hash", "guardian_invitations", ["token_hash"], unique=True)
    op.create_index("ix_guardian_invitations_payer_id", "guardian_invitations", ["payer_id"], unique=False)
    op.create_index("ix_guardian_invitations_guardian_email", "guardian_invitations", ["guardian_email"], unique=False)
    op.create_index("ix_guardian_invitations_status", "guardian_invitations", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_guardian_invitations_status", table_name="guardian_invitations")
    op.drop_index("ix_guardian_invitations_guardian_email", table_name="guardian_invitations")
    op.drop_index("ix_guardian_invitations_payer_id", table_name="guardian_invitations")
    op.drop_index("ix_guardian_invitations_token_hash", table_name="guardian_invitations")
    op.drop_table("guardian_invitations")

    op.drop_index("ix_user_sessions_user_id", table_name="user_sessions")
    op.drop_index("ix_user_sessions_token_hash", table_name="user_sessions")
    op.drop_table("user_sessions")

    op.drop_index("ix_otp_challenges_contact_purpose", table_name="otp_challenges")
    op.drop_table("otp_challenges")

    op.drop_index("ix_identity_assurances_trusted_person_ref", table_name="identity_assurances")
    op.drop_index("ix_identity_assurances_user_id", table_name="identity_assurances")
    op.drop_table("identity_assurances")

    op.drop_index("ix_user_accounts_role", table_name="user_accounts")
    op.drop_index("ix_user_accounts_email", table_name="user_accounts")
    op.drop_table("user_accounts")


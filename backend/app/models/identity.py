"""V5 durable identity, OTP challenge, session, and guardian invitation ORM models.

SECURITY INVARIANTS:
- Plaintext passwords, plaintext OTPs, raw national ID numbers, and raw bearer/invite
  tokens are NEVER stored in these tables. Only salted scrypt hashes, HMAC digests,
  SHA-256 token digests, and opaque server-issued trusted_person_ref tokens are persisted.
- Every foreign key to users.id enforces ondelete='RESTRICT'.
- All timestamps are timezone-aware (TIMESTAMP WITH TIME ZONE).
"""

from datetime import datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.database import Base

GUARDIAN_INVITATION_STATUSES: tuple[str, ...] = (
    "PENDING",
    "CONTACT_VERIFIED",
    "IDENTITY_VERIFIED",
    "CONSENTED",
    "ACTIVE",
    "DECLINED",
    "REVOKED",
    "EXPIRED",
    "SUSPENDED",
)

OTP_CHALLENGE_STATUSES: tuple[str, ...] = (
    "PENDING",
    "VERIFIED",
    "LOCKED",
    "EXPIRED",
)


class UserAccount(Base):
    """Durable email+password account linked 1:1 with authoritative users.id."""

    __tablename__ = "user_accounts"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_user_accounts"),
        ForeignKeyConstraint(["id"], ["users.id"], name="fk_user_accounts_user", ondelete="RESTRICT"),
        CheckConstraint(
            "role IN ('payer', 'guardian', 'analyst', 'admin')",
            name="ck_user_accounts_role",
        ),
        Index("ix_user_accounts_email", "email", unique=True),
        Index("ix_user_accounts_role", "role", unique=False),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, default=uuid4)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    email_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=sa.false()
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=sa.true()
    )
    is_synthetic: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=sa.false()
    )
    email_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class IdentityAssurance(Base):
    """Server-issued opaque identity assurance linking a user to trusted_person_ref."""

    __tablename__ = "identity_assurances"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_identity_assurances"),
        ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_identity_assurances_user", ondelete="RESTRICT"
        ),
        Index("ix_identity_assurances_user_id", "user_id", unique=False),
        Index("ix_identity_assurances_trusted_person_ref", "trusted_person_ref", unique=False),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    trusted_person_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    assurance_level: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_evidence_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    is_mock_assurance: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=sa.true()
    )
    revoked: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=sa.false()
    )
    verified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class OtpChallenge(Base):
    """Salted HMAC-hashed one-time verification challenge with lockout and TTL."""

    __tablename__ = "otp_challenges"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_otp_challenges"),
        CheckConstraint("attempts >= 0", name="ck_otp_challenges_attempts_non_negative"),
        CheckConstraint("max_attempts > 0", name="ck_otp_challenges_max_attempts_positive"),
        CheckConstraint(
            "status IN ('PENDING', 'VERIFIED', 'LOCKED', 'EXPIRED')",
            name="ck_otp_challenges_status",
        ),
        Index("ix_otp_challenges_contact_purpose", "contact", "purpose", unique=False),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, default=uuid4)
    contact: Mapped[str] = mapped_column(String(255), nullable=False)
    purpose: Mapped[str] = mapped_column(String(64), nullable=False)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    otp_salt: Mapped[str] = mapped_column(String(64), nullable=False)
    otp_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="5")
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="PENDING")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class UserSession(Base):
    """Durable bearer session storing strictly SHA-256 token digests."""

    __tablename__ = "user_sessions"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_user_sessions"),
        ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_user_sessions_user", ondelete="RESTRICT"
        ),
        Index("ix_user_sessions_token_hash", "token_hash", unique=True),
        Index("ix_user_sessions_user_id", "user_id", unique=False),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    auth_method: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class GuardianInvitation(Base):
    """Durable payer->guardian invitation and independent consent/collusion state machine."""

    __tablename__ = "guardian_invitations"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_guardian_invitations"),
        ForeignKeyConstraint(
            ["payer_id"], ["users.id"], name="fk_guardian_invitations_payer", ondelete="RESTRICT"
        ),
        ForeignKeyConstraint(
            ["guardian_user_id"],
            ["users.id"],
            name="fk_guardian_invitations_guardian",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "role_slot IN ('primary', 'backup')",
            name="ck_guardian_invitations_role_slot",
        ),
        CheckConstraint(
            "status IN ('PENDING', 'CONTACT_VERIFIED', 'IDENTITY_VERIFIED', 'CONSENTED', "
            "'ACTIVE', 'DECLINED', 'REVOKED', 'EXPIRED', 'SUSPENDED')",
            name="ck_guardian_invitations_status",
        ),
        Index("ix_guardian_invitations_token_hash", "token_hash", unique=True),
        Index("ix_guardian_invitations_payer_id", "payer_id", unique=False),
        Index("ix_guardian_invitations_guardian_email", "guardian_email", unique=False),
        Index("ix_guardian_invitations_status", "status", unique=False),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, default=uuid4)
    payer_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    guardian_user_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    guardian_email: Mapped[str] = mapped_column(String(255), nullable=False)
    relationship_label: Mapped[str] = mapped_column(String(64), nullable=False)
    role_slot: Mapped[str] = mapped_column(String(16), nullable=False, server_default="primary")
    notification_channel: Mapped[str] = mapped_column(String(32), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="PENDING")
    payer_trusted_person_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    guardian_trusted_person_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    consent_confirmed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=sa.false()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


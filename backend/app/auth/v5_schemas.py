"""Typed Pydantic V5 schemas for real account authentication, OTP, identity assurance, and guardian invitations."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SignupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    email: str = Field(..., min_length=5, max_length=255)
    password: str = Field(..., min_length=8, max_length=128)
    full_name: str = Field(..., min_length=2, max_length=120)
    role: str = Field(..., description="Allowed public roles: payer or guardian (privileged roles rejected)")


class SignupResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    user_id: UUID
    email: str
    full_name: str
    role: str
    email_verified: bool
    requires_otp_verification: bool
    challenge_id: UUID
    otp_expires_at: datetime
    is_mock_otp_delivery: bool
    dev_otp_preview: str | None = None
    message: str


class OtpChallengeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    contact: str = Field(..., min_length=3, max_length=255)
    purpose: Literal["signup_email", "login_step_up", "guardian_invite"] = "signup_email"
    channel: Literal["email", "sms_stub"] = "email"


class OtpChallengeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    challenge_id: UUID
    contact: str
    purpose: str
    channel: str
    expires_at: datetime
    is_mock_delivery: bool
    provider_name: str
    dev_otp_preview: str | None = None


class OtpVerifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    challenge_id: UUID
    otp_code: str = Field(..., min_length=4, max_length=12)


class OtpVerifyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    challenge_id: UUID
    contact: str
    purpose: str
    verified: bool
    email_verified: bool
    verified_at: datetime


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    email: str = Field(..., min_length=5, max_length=255)
    password: str = Field(..., min_length=1, max_length=128)


class LoginResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    user_id: UUID
    email: str
    full_name: str
    role: str
    identity_verified: bool
    is_synthetic: bool = False


class LogoutResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    revoked: bool
    message: str


class IdentityVerifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str = Field("synthetic_local_idp")
    full_name: str = Field(..., min_length=2, max_length=120)
    synthetic_document_ref: str = Field(..., min_length=4, max_length=64)
    consent_confirmed: bool = Field(False)


class IdentityAssuranceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    verified: bool
    assurance_id: UUID | None = None
    user_id: UUID
    trusted_person_ref: str | None = None
    provider: str | None = None
    assurance_level: str | None = None
    is_mock_assurance: bool = True
    revoked: bool = False
    verified_at: datetime | None = None
    expires_at: datetime | None = None


class GuardianInvitationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    guardian_email: str = Field(..., min_length=5, max_length=255)
    relationship: str = Field("family", min_length=1, max_length=64)
    role_slot: Literal["primary", "backup"] = "primary"
    notification_channel: Literal["in_app", "email", "push", "sms"] = "in_app"


class GuardianInvitationView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    invitation_id: UUID
    payer_id: UUID
    guardian_user_id: UUID | None = None
    guardian_email: str
    relationship: str
    role_slot: str
    notification_channel: str
    status: str
    consent_confirmed: bool
    expires_at: datetime
    accepted_at: datetime | None = None
    revoked_at: datetime | None = None
    created_at: datetime
    is_mock_invite_delivery: bool = True
    dev_invite_token_preview: str | None = None


class GuardianInvitationListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    sent: list[GuardianInvitationView] = Field(default_factory=list)
    received: list[GuardianInvitationView] = Field(default_factory=list)


class GuardianInvitationAcceptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    invite_token: str = Field(..., min_length=8, max_length=256)
    otp_challenge_id: UUID
    otp_code: str = Field(..., min_length=4, max_length=12)
    explicit_consent: bool = Field(False)


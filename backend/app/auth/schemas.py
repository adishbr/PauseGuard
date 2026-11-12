"""Typed request and response schemas for authentication and profile."""

from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field

from app.models.roles import UserRole


class ActorProfileResponse(BaseModel):
    """Server-resolved profile of the authenticated actor."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    user_id: UUID = Field(..., description="Server-assigned unique user identifier")
    roles: list[UserRole] = Field(..., description="Active server-persisted roles for this user")
    notification_preference_paise: int | None = Field(
        None,
        ge=0,
        description="User notification threshold in paise (does not override hard security policy)",
    )


class RedactedPaymentView(BaseModel):
    """Privacy-preserving payment view for assigned guardians."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(..., description="Payment identifier reference")
    status: str = Field(..., description="Current payment state machine status")
    tier: int = Field(..., ge=0, le=3, description="Risk intervention tier")
    guardian_deadline: str | None = Field(None, description="UTC deadline for guardian response")
    message: str = Field(..., description="Sanitized notification message without sensitive details")


class FullPaymentView(BaseModel):
    """Full payment view accessible only to the owning payer."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    status: str
    tier: int
    amount_paise: int = Field(..., ge=0)
    beneficiary_id: str
    purpose: str
    guardian_deadline: str | None = None
    version: int = Field(..., gt=0)


class GuardianDecisionRequest(BaseModel):
    """Decision submitted by an assigned guardian."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    approved: bool = Field(..., description="Whether the guardian approves proceeding to READY_TO_EXECUTE")
    notes: str | None = Field(None, max_length=256, description="Optional brief notes")


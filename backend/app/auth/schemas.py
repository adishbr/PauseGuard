"""Typed request and response schemas for Phase 3 authentication, guardian, and payments."""

from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field

from app.models.roles import UserRole


# ---------------------------------------------------------------------------
# Profile & Actor Schemas
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Guardian Enrollment & Revocation Schemas
# ---------------------------------------------------------------------------

class GuardianEnrollRequest(BaseModel):
    """Request submitted by a payer to enroll an authorized guardian."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    guardian_id: UUID = Field(..., description="Unique user identifier of the eligible guardian")
    relationship: str = Field("family", min_length=1, max_length=64, description="Relationship category")
    notification_channel: str = Field("in_app", min_length=1, max_length=32, description="Preferred notification channel")
    opt_in_confirmed: bool = Field(False, description="Explicit informed consent opt-in confirmation; must be affirmatively True")


class GuardianEnrollResponse(BaseModel):
    """Authoritative server record of an active guardian enrollment."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    enrollment_id: str = Field(..., description="Unique server-generated enrollment record ID")
    payer_id: UUID = Field(..., description="Owning payer user identifier")
    guardian_id: UUID = Field(..., description="Enrolled guardian user identifier")
    relationship: str = Field(..., description="Relationship description")
    notification_channel: str = Field(..., description="Configured notification channel")
    status: str = Field("active", description="Enrollment status: active or revoked")
    enrolled_at: str = Field(..., description="UTC ISO 8601 timestamp of enrollment")


class GuardianRevokeResponse(BaseModel):
    """Response confirming revocation of a guardian enrollment."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    enrollment_id: str = Field(...)
    payer_id: UUID = Field(...)
    guardian_id: UUID = Field(...)
    status: str = Field("revoked")
    revoked_at: str = Field(...)


class GuardianStatusResponse(BaseModel):
    """Current guardian enrollment summary for an authenticated actor."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    has_guardian: bool = Field(..., description="Whether the caller has an active enrolled guardian")
    enrollment: GuardianEnrollResponse | None = Field(None, description="Active enrollment details if payer")
    guarded_payers: list[UUID] = Field(default_factory=list, description="List of payer IDs this guardian guards")


# ---------------------------------------------------------------------------
# Payment Views & Lifecycle Schemas
# ---------------------------------------------------------------------------

class RedactedPaymentView(BaseModel):
    """Privacy-preserving payment view for assigned guardians."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(..., description="Payment identifier reference")
    status: str = Field(..., description="Current payment state machine status")
    tier: int = Field(..., ge=0, le=3, description="Risk intervention tier")
    guardian_deadline: str | None = Field(None, description="UTC deadline for guardian response")
    message: str = Field(..., description="Sanitized notification message without sensitive financial details")


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
    assigned_guardian_id: str | None = None
    version: int = Field(..., gt=0)


class PaymentCreateRequest(BaseModel):
    """Payer request to create a risk-evaluated mock payment."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    beneficiary_id: str = Field(..., min_length=1, max_length=128)
    amount_paise: int = Field(..., gt=0, description="Amount in integer paise")
    purpose: str = Field(..., min_length=1, max_length=128)
    idempotency_key: str = Field(..., min_length=1, max_length=128)


class GuardianDecisionRequest(BaseModel):
    """Decision submitted by an assigned guardian."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    approved: bool = Field(..., description="Whether the guardian approves proceeding to READY_TO_EXECUTE")
    notes: str | None = Field(None, max_length=256, description="Optional brief notes")


class PaymentDecisionResponse(BaseModel):
    """Confirmation of recorded guardian decision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    payment_id: str
    status: str
    decision: str
    target_status: str
    recorded_at: str
    can_execute_payment: bool = Field(False, description="Invariant: guardian decision cannot execute payments")


class PaymentFallbackResponse(BaseModel):
    """Confirmation of transition to fallback review upon deadline expiry."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    payment_id: str
    status: str = Field("AWAITING_FALLBACK_REVIEW")
    deadline_exceeded_at: str
    can_authorize_payment: bool = Field(False, description="Invariant: fallback transition cannot authorize payment")


class PaymentWarningAckResponse(BaseModel):
    """Response confirming payer acknowledgment of a risk or threshold warning."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    payment_id: str
    status: str = Field("READY_TO_EXECUTE")
    acknowledged_at: str
    can_execute_payment: bool = Field(False, description="Invariant: warning acknowledgment does not execute payment")


class PaymentConfirmRequest(BaseModel):
    """Final confirmation request submitted by the owning payer."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    idempotency_key: str = Field(..., min_length=1, max_length=128)


class PaymentConfirmResponse(BaseModel):
    """Confirmation of atomic payment execution."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    payment_id: str
    status: str = Field("EXECUTED")
    amount_paise: int
    confirmed_at: str


# ---------------------------------------------------------------------------
# Telephony & Call Simulation Schemas
# ---------------------------------------------------------------------------

class CallStatusResponse(BaseModel):
    """Status of an in-app simulated guardian phone call."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    call_id: str
    payment_id: str
    guardian_id: UUID
    status: str
    answered: bool
    can_authorize_payment: bool = Field(False, description="Invariant: call answer is not payment approval")


class CallCallbackRequest(BaseModel):
    """Webhook payload from telephony call provider."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    call_id: str
    event: str = Field(..., description="Call event: answered, completed, failed")
    timestamp: str | None = None


class CallCallbackResponse(BaseModel):
    """Acknowledgment of telephony provider webhook event."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    call_id: str
    status: str
    recorded: bool = True
    can_authorize_payment: bool = Field(False, description="Invariant: webhook cannot authorize payment")

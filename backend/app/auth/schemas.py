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


# ---------------------------------------------------------------------------
# Account & Ledger Schemas
# ---------------------------------------------------------------------------

class AccountBalanceResponse(BaseModel):
    """Current mock account balance and ledger summary."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    user_id: UUID
    balance_paise: int = Field(..., ge=0)
    currency: str = Field("INR")
    ledger_entries_count: int = Field(0, ge=0)


# ---------------------------------------------------------------------------
# Safe-Lock Schemas
# ---------------------------------------------------------------------------

class SafeLockToggleRequest(BaseModel):
    """Request to engage or disengage Safe-Lock."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    is_locked: bool = Field(..., description="True to engage Safe-Lock; False to unlock")


class SafeLockStatusResponse(BaseModel):
    """Current binary Safe-Lock state for a payer."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    payer_id: UUID
    is_locked: bool
    version: int = Field(1, ge=1)
    updated_at: str | None = None


# ---------------------------------------------------------------------------
# Safety & Anti-Fraud Schemas
# ---------------------------------------------------------------------------

class PurposeChallengeRequest(BaseModel):
    """Request to evaluate payment purpose text for coercion cues."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    purpose: str = Field(..., min_length=1, max_length=256)


class PurposeChallengeResponse(BaseModel):
    """Assessment of payment purpose text."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    suspicious: bool
    reasons: list[str] = Field(default_factory=list)


class AntiSmurfingCheckRequest(BaseModel):
    """Request to check rapid velocity or structuring attempts."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    amount_paise: int = Field(..., gt=0)
    subject_id: str | None = None


class AntiSmurfingCheckResponse(BaseModel):
    """Rolling velocity smurfing assessment."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    suspicious: bool
    attempt_count: int = Field(..., ge=0)
    total_amount_paise: int = Field(..., ge=0)
    reasons: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Audit Verification & Anchors Schemas
# ---------------------------------------------------------------------------

class AuditVerificationResponse(BaseModel):
    """Integrity verification of the cryptographic audit hash chain."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    valid: bool
    total_events: int = Field(..., ge=0)
    head_hash: str
    verified_at: str


class AuditAnchorResponse(BaseModel):
    """Exported audit anchor receipt for external checkpointing."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    sequence: int = Field(..., gt=0)
    head_hash: str
    created_at: str
    anchor_type: str = Field("sha256_checkpoint")


# ---------------------------------------------------------------------------
# Evidence & Recovery Schemas
# ---------------------------------------------------------------------------

class EvidenceExportResponse(BaseModel):
    """Privacy-minimizing redacted evidence export."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    payment_id: str
    event_type: str
    timestamp: str
    risk_level: str
    risk_indicators: list[str] = Field(default_factory=list)
    policy_version: str = Field("2.0.0")
    redaction_applied: bool = True
    review_required_before_sharing: bool = True
    exported_at: str


class RecoveryGuideResponse(BaseModel):
    """Official victim aftercare and reporting guidance."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    helpline_number: str = Field("1930", description="National Cyber Crime Reporting Helpline")
    portal_url: str = Field("https://cybercrime.gov.in")
    immediate_steps: list[str]
    disclaimer: str = Field(
        "PauseGuard mock rail prototype cannot reverse settled UPI transfers. "
        "Report fraudulent transactions immediately to your bank and the national cybercrime portal."
    )


# ---------------------------------------------------------------------------
# Risk Advice & Policy Lab Schemas
# ---------------------------------------------------------------------------

class RiskAdviceRequest(BaseModel):
    """Request to compute structured advisory risk signals."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    payment_id: str = Field(..., min_length=1)
    beneficiary_id: str = Field(..., min_length=1)
    amount_paise: int = Field(..., gt=0)
    purpose: str = Field(..., min_length=1)
    profile_type: str = Field("personal")
    transcript_text: str | None = None
    transcript_consented: bool = False


class RiskAdviceResponse(BaseModel):
    """Structured advisory risk signals returned by intelligence engine."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    payment_id: str
    advisory_score: int | None = None
    suggested_caution_level: str | None = None
    reason_codes: list[str] = Field(default_factory=list)
    can_authorize_payment: bool = Field(False, description="Security invariant: advisory signals cannot authorize payment")
    evaluation_status: str
    calibration_caveat: str


class PolicyLabSimulateRequest(BaseModel):
    """Request to execute Policy Lab simulation benchmark."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    sample_size: int = Field(60, ge=10, le=500)
    seed: int = Field(42, ge=0)
    baseline_a_threshold_paise: int = Field(5000000, gt=0)


class GuardianDashboardResponse(BaseModel):
    """Dashboard view for an enrolled guardian."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    guardian_id: UUID
    active_guardianships_count: int = Field(..., ge=0)
    pending_reviews_count: int = Field(..., ge=0)
    pending_reviews: list[RedactedPaymentView] = Field(default_factory=list)


class PaymentRiskExplanationResponse(BaseModel):
    """Risk evaluation explanation for a payment."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    payment_id: str
    tier: int
    is_hard_blocked: bool
    requires_guardian: bool
    requires_warning_ack: bool
    reasons: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Razorpay Test Mode Merchant Sandbox Schemas
# ---------------------------------------------------------------------------

class RazorpayOrderCreateRequest(BaseModel):
    """Request to create an isolated Razorpay Test Mode merchant order."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    amount_paise: int = Field(..., gt=0, description="Order amount in paise (strictly positive integer)")
    currency: str = Field("INR", pattern="^INR$", description="Order currency, strictly INR")
    receipt: str | None = Field(None, max_length=128, description="Optional merchant receipt identifier")
    notes: dict[str, str] | None = Field(None, description="Optional merchant key-value notes")
    idempotency_key: str | None = Field(None, max_length=128, description="Optional client idempotency key")


class RazorpayOrderResponse(BaseModel):
    """Internal order details and Razorpay Test Mode order reference."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    razorpay_order_id: str
    amount_paise: int
    currency: str = Field("INR")
    status: str
    receipt: str | None = None
    key_id: str = Field(..., description="Public Test Mode key ID for Razorpay Checkout SDK")
    created_at: str


class RazorpayVerifyRequest(BaseModel):
    """Client-submitted payment verification payload from Razorpay Checkout handler."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    razorpay_order_id: str = Field(..., min_length=1)
    razorpay_payment_id: str = Field(..., min_length=1)
    razorpay_signature: str = Field(..., min_length=64, max_length=64)


class RazorpayVerifyResponse(BaseModel):
    """Server-reconciled verification response for Razorpay Test Mode payment."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    verified: bool
    status: str
    order_id: str
    razorpay_order_id: str
    razorpay_payment_id: str
    amount_paise: int
    currency: str = Field("INR")
    reconciled_with_provider: bool
    verified_at: str


class RazorpayWebhookResponse(BaseModel):
    """Acknowledgment of processed or deduplicated Razorpay webhook event."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: str
    event_id: str
    event_type: str
    message: str
    can_authorize_p2p_payment: bool = Field(False, description="Invariant: merchant webhooks cannot authorize P2P payments")


# ---------------------------------------------------------------------------
# Local Demo Authentication Bridge Schemas
# ---------------------------------------------------------------------------

class DemoSessionRequest(BaseModel):
    """Validated request to establish a local synthetic demo session."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    role: UserRole = Field(..., description="Requested demo role (payer, guardian, analyst, admin)")
    contact: str | None = Field(None, max_length=128, description="Optional synthetic demo contact matching authorized identities")
    sample: bool | None = Field(None, description="Optional flag for standard sample demo identity")
    identity_tag: str | None = Field(None, max_length=64, description="Optional synthetic identity identifier (primary, other)")


class DemoSessionProfile(BaseModel):
    """Synthetic demo profile metadata compatible with frontend expectations."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    id: str = Field(..., description="Demo profile ID")
    role: str = Field(..., description="Demo role name")
    name: str = Field(..., description="Synthetic display name")
    contact: str = Field(..., description="Synthetic contact identifier")
    sample: bool = Field(True, description="Always True for synthetic demo identities")
    category: str = Field("personal", description="Account category")
    language: str = Field("en", description="Default UI language")
    large_text: bool = Field(False, serialization_alias="largeText", description="Accessibility preference")
    organization: str = Field("", description="Optional organization name")
    recurring_supplier: str = Field("", serialization_alias="recurringSupplier", description="Supplier alias")
    threshold_paise: int | None = Field(None, serialization_alias="thresholdPaise", description="Alert threshold in paise")
    notifications: bool = Field(True, description="Notification preference")
    quiet_start: str = Field("", serialization_alias="quietStart", description="Quiet hours start")
    quiet_end: str = Field("", serialization_alias="quietEnd", description="Quiet hours end")
    call_consent: bool = Field(False, serialization_alias="callConsent", description="Simulated call consent")
    safe_lock: bool = Field(False, serialization_alias="safeLock", description="Safe-Lock status")


class DemoSessionResponse(BaseModel):
    """Structured response confirming local demo session token issuance."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    token: str = Field(..., description="Issued synthetic bearer token for Authorization header")
    token_type: str = Field("Bearer", description="Token scheme")
    expires_in_seconds: int = Field(1800, description="Session lifespan in seconds (30m)")
    expires_at: int = Field(..., serialization_alias="expiresAt", description="Epoch millisecond expiration timestamp")
    user_id: UUID = Field(..., description="Server-assigned synthetic user UUID")
    role: UserRole = Field(..., description="Primary server-resolved role")
    roles: list[UserRole] = Field(..., description="Active server-persisted roles")
    profile: DemoSessionProfile = Field(..., description="Synthetic demo profile metadata")

"""FastAPI router for Safe-Lock, safety evaluations, audit verification, and recovery assist.

Endpoints:
- POST /safe-lock: Engage or disengage binary Safe-Lock for authenticated payer.
- GET  /safe-lock: Retrieve current Safe-Lock state for authenticated payer.
- POST /safety/purpose-challenge: Analyze payment purpose text for coercion patterns.
- POST /safety/anti-smurfing/check: Check rolling payment frequency/structuring indicators.
- GET  /audit/verify: Verify cryptographic SHA-256 audit chain integrity.
- POST /audit/anchors (and /anchors): Export an audit chain checkpoint anchor receipt.
- GET  /recovery/guide: Official aftercare and cybercrime reporting instructions.
"""

from datetime import datetime, timezone
from typing import Annotated, Any, Optional
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException, status

from app.api.payments import get_payment_engine
from app.auth.dependencies import get_current_actor
from app.auth.schemas import (
    AntiSmurfingCheckRequest,
    AntiSmurfingCheckResponse,
    AuditAnchorResponse,
    AuditVerificationResponse,
    PurposeChallengeRequest,
    PurposeChallengeResponse,
    RecoveryGuideResponse,
    SafeLockStatusResponse,
    SafeLockToggleRequest,
)
from app.models.roles import UserRole
from app.services.payment_guards import TrustedActorContext
from safety.anti_smurfing.rolling_detector import RollingSmurfingDetector
from safety.audit.external_anchor import create_anchor
from safety.purpose_challenge.purpose_challenge import assess_purpose

# Dedicated routers for clean mounting in main app
safe_lock_router = APIRouter(prefix="/api/v2/safe-lock", tags=["safe-lock"])
safety_router = APIRouter(prefix="/api/v2/safety", tags=["safety"])
audit_router = APIRouter(prefix="/api/v2/audit", tags=["audit"])
anchors_router = APIRouter(prefix="/api/v2/anchors", tags=["anchors"])
recovery_router = APIRouter(prefix="/api/v2/recovery", tags=["recovery"])

_global_smurfing_detector = RollingSmurfingDetector(
    window_seconds=600,
    minimum_attempts=3,
    amount_threshold_paise=10000000,
)


# ---------------------------------------------------------------------------
# Safe-Lock Endpoints
# ---------------------------------------------------------------------------

@safe_lock_router.post("", response_model=SafeLockStatusResponse, status_code=status.HTTP_200_OK)
def toggle_safe_lock(
    actor: Annotated[TrustedActorContext, Depends(get_current_actor)],
    request: SafeLockToggleRequest,
    engine: Annotated[Any, Depends(get_payment_engine)],
) -> SafeLockStatusResponse:
    """Engage or disengage Safe-Lock for the authenticated payer."""
    if UserRole.PAYER not in actor.roles and UserRole.ADMIN not in actor.roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Only authenticated payers can configure Safe-Lock",
        )
    is_locked, version, updated_at = engine.toggle_safe_lock(actor.user_id, request.is_locked)
    return SafeLockStatusResponse(
        payer_id=actor.user_id,
        is_locked=is_locked,
        version=version,
        updated_at=updated_at,
    )


@safe_lock_router.get("", response_model=SafeLockStatusResponse, status_code=status.HTTP_200_OK)
def get_safe_lock(
    actor: Annotated[TrustedActorContext, Depends(get_current_actor)],
    engine: Annotated[Any, Depends(get_payment_engine)],
) -> SafeLockStatusResponse:
    """Retrieve current Safe-Lock status for the authenticated payer."""
    is_locked, version, updated_at = engine.get_safe_lock_status(actor.user_id)
    return SafeLockStatusResponse(
        payer_id=actor.user_id,
        is_locked=is_locked,
        version=version,
        updated_at=updated_at,
    )


# ---------------------------------------------------------------------------
# Safety Checks Endpoints
# ---------------------------------------------------------------------------

@safety_router.post("/purpose-challenge", response_model=PurposeChallengeResponse)
def check_purpose_challenge(
    actor: Annotated[TrustedActorContext, Depends(get_current_actor)],
    request: PurposeChallengeRequest,
) -> PurposeChallengeResponse:
    """Evaluate payment purpose text for coercion indicators and suspicious keywords."""
    res = assess_purpose(request.purpose)
    return PurposeChallengeResponse(
        suspicious=res.suspicious,
        reasons=list(res.reasons),
    )


@safety_router.post("/anti-smurfing/check", response_model=AntiSmurfingCheckResponse)
def check_anti_smurfing(
    actor: Annotated[TrustedActorContext, Depends(get_current_actor)],
    request: AntiSmurfingCheckRequest,
) -> AntiSmurfingCheckResponse:
    """Evaluate rapid transfer structuring and rolling velocity indicators."""
    privileged = bool(actor.roles & {UserRole.ANALYST, UserRole.ADMIN})
    if request.subject_id is not None and not privileged and request.subject_id != str(actor.user_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Non-privileged actors cannot evaluate velocity for another subject_id",
        )
    subject_id = request.subject_id if (privileged and request.subject_id) else str(actor.user_id)
    res = _global_smurfing_detector.record_attempt(
        subject_id=subject_id,
        attempt_id=str(uuid4()),
        amount_paise=request.amount_paise,
    )
    return AntiSmurfingCheckResponse(
        suspicious=res.suspicious,
        attempt_count=res.attempt_count,
        total_amount_paise=res.total_amount_paise,
        reasons=list(res.reasons),
    )


# ---------------------------------------------------------------------------
# Audit Chain & Anchors Endpoints
# ---------------------------------------------------------------------------

@audit_router.get("/verify", response_model=AuditVerificationResponse)
def verify_audit_chain_endpoint(
    actor: Annotated[TrustedActorContext, Depends(get_current_actor)],
    engine: Annotated[Any, Depends(get_payment_engine)],
) -> AuditVerificationResponse:
    """Verify cryptographic hash-chain integrity of audit events."""
    valid, total_events, head_hash = engine.verify_audit_chain()
    now_str = datetime.now(timezone.utc).isoformat()
    return AuditVerificationResponse(
        valid=valid,
        total_events=total_events,
        head_hash=head_hash,
        verified_at=now_str,
    )


@audit_router.post("/anchors", response_model=AuditAnchorResponse)
@anchors_router.post("", response_model=AuditAnchorResponse)
def create_audit_anchor_endpoint(
    actor: Annotated[TrustedActorContext, Depends(get_current_actor)],
    engine: Annotated[Any, Depends(get_payment_engine)],
) -> AuditAnchorResponse:
    """Prepare an audit anchor receipt checkpoint for external timestamping."""
    if hasattr(engine, "get_audit_chain"):
        chain = engine.get_audit_chain()
        anchor = create_anchor(chain)
        return AuditAnchorResponse(
            sequence=anchor.sequence,
            head_hash=anchor.head_hash,
            created_at=anchor.created_at,
            anchor_type="sha256_checkpoint",
        )

    # For durable PostgreSQL engine: verify chain first then checkpoint head
    valid, total_events, head_hash = engine.verify_audit_chain()
    if not valid:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot anchor an invalid audit chain",
        )
    if total_events == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot anchor an empty audit chain",
        )
    now_str = datetime.now(timezone.utc).isoformat()
    return AuditAnchorResponse(
        sequence=total_events,
        head_hash=head_hash,
        created_at=now_str,
        anchor_type="sha256_checkpoint",
    )


# ---------------------------------------------------------------------------
# Recovery Guide Endpoint
# ---------------------------------------------------------------------------

@recovery_router.get("/guide", response_model=RecoveryGuideResponse)
def get_recovery_guide(
    actor: Annotated[TrustedActorContext, Depends(get_current_actor)],
) -> RecoveryGuideResponse:
    """Retrieve official post-incident recovery steps and 1930 Cybercrime guidance."""
    return RecoveryGuideResponse(
        helpline_number="1930",
        portal_url="https://cybercrime.gov.in",
        immediate_steps=[
            "1. Dial 1930 immediately to register a complaint with the National Cyber Crime Helpline.",
            "2. File a formal cyber fraud complaint on https://cybercrime.gov.in within the golden hour.",
            "3. Notify your bank and request a freeze on the affected UPI/account transaction.",
            "4. Engage PauseGuard Safe-Lock immediately to block further outbound transfers.",
            "5. Export your privacy-safe transaction evidence packet for law enforcement.",
        ],
        disclaimer=(
            "PauseGuard mock rail prototype cannot reverse settled UPI transfers. "
            "Report fraudulent transactions immediately to your bank and the national cybercrime portal."
        ),
    )


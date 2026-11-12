"""FastAPI router for Phase 3 guardian enrollment, status, and telephony endpoints.

Endpoints:
- POST /guardian/enroll: Authenticated payer enrolls a guardian with explicit opt-in.
- GET  /guardian/status: Retrieve authenticated actor's guardian enrollment status.
- POST /guardian/revoke: Authenticated payer revokes their active guardian.
- GET  /guardian/calls/{id}/status: Retrieve simulated telephony call status.
- POST /guardian/calls/provider-callback: Webhook callback for telephony events.
"""

from typing import Annotated, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status

from app.auth.dependencies import get_current_actor
from app.auth.schemas import (
    CallCallbackRequest,
    CallCallbackResponse,
    CallStatusResponse,
    GuardianEnrollRequest,
    GuardianEnrollResponse,
    GuardianRevokeResponse,
    GuardianStatusResponse,
)
from app.config import load_settings
from app.services.guardian_service import get_guardian_service
from app.services.payment_guards import TrustedActorContext
from app.services.telephony_service import get_telephony_service

router = APIRouter(prefix="/api/v2/guardian", tags=["guardian"])

MOCK_PROVIDER_SIGNATURE = "mock-telephony-signature"


@router.post("/enroll", response_model=GuardianEnrollResponse, status_code=status.HTTP_200_OK)
def enroll_guardian(
    actor: Annotated[TrustedActorContext, Depends(get_current_actor)],
    request: GuardianEnrollRequest,
) -> GuardianEnrollResponse:
    """Enroll a guardian for the authenticated payer.

    Requires explicit opt-in confirmation. Self-guardianship is strictly rejected.
    """
    service = get_guardian_service()
    return service.enroll_guardian(actor, request)


@router.get("/status", response_model=GuardianStatusResponse)
def get_guardian_status(
    actor: Annotated[TrustedActorContext, Depends(get_current_actor)],
) -> GuardianStatusResponse:
    """Retrieve guardian enrollment status for the authenticated actor."""
    service = get_guardian_service()
    return service.get_status(actor)


@router.post("/revoke", response_model=GuardianRevokeResponse)
def revoke_guardian(
    actor: Annotated[TrustedActorContext, Depends(get_current_actor)],
    guardian_id: Optional[UUID] = Query(None, description="Optional specific guardian ID to verify"),
) -> GuardianRevokeResponse:
    """Revoke active guardian enrollment for the authenticated payer."""
    service = get_guardian_service()
    return service.revoke_guardian(actor, guardian_id=guardian_id)


@router.get("/calls/{call_id}/status", response_model=CallStatusResponse)
def get_call_status(
    call_id: str,
    actor: Annotated[TrustedActorContext, Depends(get_current_actor)],
) -> CallStatusResponse:
    """Retrieve delivery and answer status of a simulated guardian phone call.

    Invariant: Call answer is NOT payment approval.
    """
    service = get_telephony_service()
    return service.get_call_status(actor, call_id)


@router.post("/calls/provider-callback", response_model=CallCallbackResponse)
def record_provider_callback(
    request: CallCallbackRequest,
    raw_request: Request,
    x_mock_provider_signature: Annotated[Optional[str], Header()] = None,
) -> CallCallbackResponse:
    """Receive and record provider telephony delivery status.

    SECURITY INVARIANTS:
    1. Unsigned or untrusted callbacks must NEVER be accepted as authenticated provider events.
    2. In production or real mode, unverified webhooks fail closed (HTTP 501 Not Implemented).
    3. In local mock/test environments, requires explicit mock provider signature authentication.
    4. Webhook status CANNOT authorize or execute payments (can_authorize_payment=False).
    """
    app_settings = getattr(raw_request.app.state, "settings", None)
    settings = app_settings if app_settings is not None else load_settings()
    if getattr(settings, "environment", None) not in ("local", "test") or getattr(settings, "mode", None) != "mock":
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Signed provider webhook verification is not implemented; callbacks are disabled outside local mock/test environments",
        )

    if x_mock_provider_signature != MOCK_PROVIDER_SIGNATURE:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing mock provider webhook signature",
        )

    service = get_telephony_service()
    return service.record_provider_callback(request)


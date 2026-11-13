"""FastAPI router for Phase 3 guardian enrollment, status, and telephony endpoints.

Endpoints:
- POST /guardian/enroll: Authenticated payer enrolls a guardian with explicit opt-in.
- GET  /guardian/status: Retrieve authenticated actor's guardian enrollment status.
- POST /guardian/revoke: Authenticated payer revokes their active guardian.
- GET  /guardian/calls/{id}/status: Retrieve simulated telephony call status.
- POST /guardian/calls/provider-callback: Webhook callback for telephony events.
"""

from typing import Annotated, Any, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status

from app.api.payments import get_payment_engine
from app.api.v5_auth import get_v5_context
from app.auth.dependencies import get_current_actor
from app.auth.schemas import (
    CallCallbackRequest,
    CallCallbackResponse,
    CallStatusResponse,
    GuardianDashboardResponse,
    GuardianEnrollRequest,
    GuardianEnrollResponse,
    GuardianRevokeResponse,
    GuardianStatusResponse,
)
from app.auth.v5_schemas import (
    GuardianInvitationAcceptRequest,
    GuardianInvitationCreateRequest,
    GuardianInvitationListResponse,
    GuardianInvitationSuspendRequest,
    GuardianInvitationView,
)
from app.config import load_settings
from app.models.roles import UserRole
from app.services.guardian_invitation_service import GuardianInvitationService
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
    ctx: Annotated[dict[str, Any], Depends(get_v5_context)],
) -> GuardianStatusResponse:
    """Retrieve guardian enrollment status for the authenticated actor."""
    db_session = ctx.get("db_session")
    if db_session is not None:
        from app.models.identity import GuardianInvitation

        if UserRole.PAYER in actor.roles:
            inv = (
                db_session.query(GuardianInvitation)
                .filter(
                    GuardianInvitation.payer_id == actor.user_id,
                    GuardianInvitation.status == "ACTIVE",
                    GuardianInvitation.guardian_user_id.isnot(None),
                )
                .order_by(GuardianInvitation.role_slot.asc())
                .first()
            )
            if inv is not None and inv.guardian_user_id is not None:
                return GuardianStatusResponse(
                    has_guardian=True,
                    enrollment=GuardianEnrollResponse(
                        enrollment_id=str(inv.id),
                        payer_id=inv.payer_id,
                        guardian_id=inv.guardian_user_id,
                        relationship=inv.relationship_label,
                        notification_channel=inv.notification_channel,
                        status="active",
                        enrolled_at=(inv.accepted_at or inv.created_at).isoformat(),
                    ),
                    guarded_payers=[],
                )
        if UserRole.GUARDIAN in actor.roles:
            invs = (
                db_session.query(GuardianInvitation)
                .filter(
                    GuardianInvitation.guardian_user_id == actor.user_id,
                    GuardianInvitation.status == "ACTIVE",
                )
                .all()
            )
            if invs:
                return GuardianStatusResponse(
                    has_guardian=True,
                    enrollment=None,
                    guarded_payers=[inv.payer_id for inv in invs],
                )

    service = get_guardian_service()
    return service.get_status(actor)


@router.get("/dashboard", response_model=GuardianDashboardResponse)
def get_guardian_dashboard(
    actor: Annotated[TrustedActorContext, Depends(get_current_actor)],
    engine: Annotated[Any, Depends(get_payment_engine)],
    ctx: Annotated[dict[str, Any], Depends(get_v5_context)],
) -> GuardianDashboardResponse:
    """Retrieve dashboard summary for an enrolled guardian."""
    if UserRole.GUARDIAN not in actor.roles and UserRole.ADMIN not in actor.roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Only authenticated guardians can access the guardian dashboard",
        )
    service = get_guardian_service()
    active_count = service.count_active_guardianships(actor.user_id)
    db_session = ctx.get("db_session")
    if db_session is not None:
        from app.models.identity import GuardianInvitation

        db_active = (
            db_session.query(GuardianInvitation)
            .filter(
                GuardianInvitation.guardian_user_id == actor.user_id,
                GuardianInvitation.status == "ACTIVE",
            )
            .count()
        )
        active_count = max(active_count, db_active)
    pending_reviews = engine.get_guardian_pending_reviews(actor.user_id)
    return GuardianDashboardResponse(
        guardian_id=actor.user_id,
        active_guardianships_count=active_count,
        pending_reviews_count=len(pending_reviews),
        pending_reviews=pending_reviews,
    )


@router.post("/invitations", response_model=GuardianInvitationView, status_code=status.HTTP_201_CREATED)
def create_guardian_invitation(
    payload: GuardianInvitationCreateRequest,
    actor: Annotated[TrustedActorContext, Depends(get_current_actor)],
    ctx: Annotated[dict[str, Any], Depends(get_v5_context)],
) -> GuardianInvitationView:
    """Create a durable guardian invitation with server-side invite token hashing."""
    svc = GuardianInvitationService(**ctx)
    res = svc.create_invitation(
        payer=actor,
        guardian_email=payload.guardian_email,
        relationship=payload.relationship,
        role_slot=payload.role_slot,
        notification_channel=payload.notification_channel,
    )
    return GuardianInvitationView(**res)


@router.get("/invitations", response_model=GuardianInvitationListResponse)
def list_guardian_invitations(
    actor: Annotated[TrustedActorContext, Depends(get_current_actor)],
    ctx: Annotated[dict[str, Any], Depends(get_v5_context)],
) -> GuardianInvitationListResponse:
    """List guardian invitations sent by or addressed to the authenticated actor."""
    svc = GuardianInvitationService(**ctx)
    res = svc.list_invitations(actor=actor)
    return GuardianInvitationListResponse(
        sent=[GuardianInvitationView(**item) for item in res["sent"]],
        received=[GuardianInvitationView(**item) for item in res["received"]],
    )


@router.post("/invitations/{invitation_id}/accept", response_model=GuardianInvitationView)
def accept_guardian_invitation(
    invitation_id: UUID,
    payload: GuardianInvitationAcceptRequest,
    actor: Annotated[TrustedActorContext, Depends(get_current_actor)],
    ctx: Annotated[dict[str, Any], Depends(get_v5_context)],
) -> GuardianInvitationView:
    """Accept guardian invitation after OTP, independent IdentityAssurance, collusion check, and consent."""
    svc = GuardianInvitationService(**ctx)
    res = svc.accept_invitation(
        guardian=actor,
        invitation_id=invitation_id,
        invite_token=payload.invite_token,
        otp_challenge_id=payload.otp_challenge_id,
        otp_code=payload.otp_code,
        explicit_consent=payload.explicit_consent,
    )
    return GuardianInvitationView(**res)


@router.post("/invitations/{invitation_id}/decline", response_model=GuardianInvitationView)
def decline_guardian_invitation(
    invitation_id: UUID,
    actor: Annotated[TrustedActorContext, Depends(get_current_actor)],
    ctx: Annotated[dict[str, Any], Depends(get_v5_context)],
) -> GuardianInvitationView:
    """Guardian declines an active or pending guardian invitation."""
    svc = GuardianInvitationService(**ctx)
    res = svc.decline_invitation(guardian=actor, invitation_id=invitation_id)
    return GuardianInvitationView(**res)


@router.post("/invitations/{invitation_id}/revoke", response_model=GuardianInvitationView)
def revoke_guardian_invitation(
    invitation_id: UUID,
    actor: Annotated[TrustedActorContext, Depends(get_current_actor)],
    ctx: Annotated[dict[str, Any], Depends(get_v5_context)],
) -> GuardianInvitationView:
    """Payer or guardian revokes a guardian invitation or active guardianship link."""
    svc = GuardianInvitationService(**ctx)
    res = svc.revoke_invitation(actor=actor, invitation_id=invitation_id)
    return GuardianInvitationView(**res)


@router.post("/invitations/{invitation_id}/suspend", response_model=GuardianInvitationView)
def suspend_guardian_invitation(
    invitation_id: UUID,
    payload: GuardianInvitationSuspendRequest,
    actor: Annotated[TrustedActorContext, Depends(get_current_actor)],
    ctx: Annotated[dict[str, Any], Depends(get_v5_context)],
) -> GuardianInvitationView:
    """Immediately suspend a potentially compromised guardian link (payer, analyst, or admin)."""
    svc = GuardianInvitationService(**ctx)
    res = svc.suspend_invitation(actor=actor, invitation_id=invitation_id, reason=payload.reason)
    return GuardianInvitationView(**res)



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


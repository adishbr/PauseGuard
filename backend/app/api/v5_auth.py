"""V5 FastAPI routes for real account signup, OTP verification, login/logout, and identity assurance.

Endpoints:
- POST /api/v2/auth/signup: Register real payer or guardian account (admin/analyst forbidden).
- POST /api/v2/auth/otp/challenge: Issue salted HMAC OTP challenge with cooldown throttling.
- POST /api/v2/auth/otp/verify: Verify OTP with attempt limits and activate signup email verification.
- POST /api/v2/auth/login: Authenticate verified email + password and issue opaque session token.
- POST /api/v2/auth/logout: Revoke current bearer session token.
- POST /api/v2/identity/verify: Record server-issued opaque trusted_person_ref via SyntheticLocalIdentityProvider.
- GET  /api/v2/identity/status: Retrieve caller's active identity assurance summary.
"""

from collections.abc import Iterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials

from app.auth.dependencies import bearer_scheme, get_current_actor
from app.auth.v5_schemas import (
    IdentityAssuranceResponse,
    IdentityVerifyRequest,
    LoginRequest,
    LoginResponse,
    LogoutResponse,
    OtpChallengeRequest,
    OtpChallengeResponse,
    OtpVerifyRequest,
    OtpVerifyResponse,
    SignupRequest,
    SignupResponse,
)
from app.config import load_settings
from app.services.account_auth_service import AccountAuthService
from app.services.identity_assurance_service import IdentityAssuranceService
from app.services.otp_service import OtpService
from app.services.payment_guards import TrustedActorContext
from app.services.v5_store import get_or_create_v5_mock_store

auth_v5_router = APIRouter(prefix="/api/v2/auth", tags=["v5-auth"])
identity_router = APIRouter(prefix="/api/v2/identity", tags=["v5-identity"])


def get_v5_context(request: Request) -> Iterator[dict[str, Any]]:
    """Yield transactional DB session + settings or explicitly isolated mock store."""
    session_factory = getattr(request.app.state, "session_factory", None)
    settings = getattr(request.app.state, "settings", None) or load_settings()

    if session_factory is not None:
        session = session_factory()
        try:
            yield {"settings": settings, "db_session": session, "mock_store": None}
            session.commit()
        except BaseException:
            session.rollback()
            raise
        finally:
            session.close()
        return

    if getattr(settings, "mode", None) != "mock":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Identity database session is unavailable.",
        )

    mock_store = get_or_create_v5_mock_store(request.app.state)
    yield {"settings": settings, "db_session": None, "mock_store": mock_store}


@auth_v5_router.post("/signup", response_model=SignupResponse, status_code=status.HTTP_201_CREATED)
def signup_account(
    payload: SignupRequest,
    ctx: Annotated[dict[str, Any], Depends(get_v5_context)],
) -> SignupResponse:
    svc = AccountAuthService(**ctx)
    res = svc.signup(
        email=payload.email,
        password=payload.password,
        full_name=payload.full_name,
        role=payload.role,
    )
    return SignupResponse(**res)


@auth_v5_router.post("/otp/challenge", response_model=OtpChallengeResponse)
def request_otp_challenge(
    payload: OtpChallengeRequest,
    ctx: Annotated[dict[str, Any], Depends(get_v5_context)],
) -> OtpChallengeResponse:
    otp_svc = OtpService(**ctx)
    dispatch = otp_svc.create_challenge(
        contact=payload.contact,
        purpose=payload.purpose,
        channel=payload.channel,
    )
    return OtpChallengeResponse(
        challenge_id=dispatch.challenge_id,
        contact=dispatch.contact,
        purpose=dispatch.purpose,
        channel=dispatch.channel,
        expires_at=dispatch.expires_at,
        is_mock_delivery=dispatch.is_mock_delivery,
        provider_name=dispatch.provider_name,
        dev_otp_preview=dispatch.dev_otp_preview,
    )


@auth_v5_router.post("/otp/verify", response_model=OtpVerifyResponse)
def verify_otp_challenge(
    payload: OtpVerifyRequest,
    ctx: Annotated[dict[str, Any], Depends(get_v5_context)],
) -> OtpVerifyResponse:
    svc = AccountAuthService(**ctx)
    res = svc.verify_otp_and_activate_if_signup(
        challenge_id=payload.challenge_id,
        otp_code=payload.otp_code,
    )
    return OtpVerifyResponse(**res)


@auth_v5_router.post("/login", response_model=LoginResponse)
def login_account(
    payload: LoginRequest,
    ctx: Annotated[dict[str, Any], Depends(get_v5_context)],
) -> LoginResponse:
    svc = AccountAuthService(**ctx)
    res = svc.login(email=payload.email, password=payload.password)
    return LoginResponse(**res)


@auth_v5_router.post("/logout", response_model=LogoutResponse)
def logout_account(
    actor: Annotated[TrustedActorContext, Depends(get_current_actor)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    ctx: Annotated[dict[str, Any], Depends(get_v5_context)],
) -> LogoutResponse:
    token = credentials.credentials.strip() if credentials else ""
    svc = AccountAuthService(**ctx)
    revoked = svc.revoke_session(token) if token else False
    return LogoutResponse(
        revoked=revoked,
        message="Session revoked cleanly." if revoked else "No persistent session required revocation.",
    )


@identity_router.post("/verify", response_model=IdentityAssuranceResponse)
def verify_identity_assurance(
    payload: IdentityVerifyRequest,
    actor: Annotated[TrustedActorContext, Depends(get_current_actor)],
    ctx: Annotated[dict[str, Any], Depends(get_v5_context)],
) -> IdentityAssuranceResponse:
    svc = IdentityAssuranceService(**ctx)
    view = svc.verify_and_record(
        user_id=actor.user_id,
        full_name=payload.full_name,
        synthetic_document_ref=payload.synthetic_document_ref,
        consent_confirmed=payload.consent_confirmed,
        provider_name=payload.provider,
    )
    return IdentityAssuranceResponse(
        verified=True,
        assurance_id=view.assurance_id,
        user_id=view.user_id,
        trusted_person_ref=view.trusted_person_ref,
        provider=view.provider,
        assurance_level=view.assurance_level,
        is_mock_assurance=view.is_mock_assurance,
        revoked=view.revoked,
        verified_at=view.verified_at,
        expires_at=view.expires_at,
    )


@identity_router.get("/status", response_model=IdentityAssuranceResponse)
def get_identity_assurance_status(
    actor: Annotated[TrustedActorContext, Depends(get_current_actor)],
    ctx: Annotated[dict[str, Any], Depends(get_v5_context)],
) -> IdentityAssuranceResponse:
    svc = IdentityAssuranceService(**ctx)
    view = svc.get_active_assurance(actor.user_id)
    if view is None:
        return IdentityAssuranceResponse(verified=False, user_id=actor.user_id, is_mock_assurance=True)
    return IdentityAssuranceResponse(
        verified=True,
        assurance_id=view.assurance_id,
        user_id=view.user_id,
        trusted_person_ref=view.trusted_person_ref,
        provider=view.provider,
        assurance_level=view.assurance_level,
        is_mock_assurance=view.is_mock_assurance,
        revoked=view.revoked,
        verified_at=view.verified_at,
        expires_at=view.expires_at,
    )


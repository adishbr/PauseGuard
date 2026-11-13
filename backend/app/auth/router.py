"""FastAPI router for authentication and profile endpoints.

Provides:
- GET /profile: Server-resolved profile of authenticated caller.
- POST /demo/session: Local demo authentication bridge issuing synthetic demo bearer tokens.
- GET /demo/session: Inspect active local demo session.
"""

import ipaddress
import time
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.auth.dependencies import get_current_actor
from app.auth.identities import (
    DEMO_SESSION_STORE,
    get_authorized_synthetic_identity,
    get_synthetic_identity_by_actor,
    is_demo_mode_allowed,
)
from app.auth.schemas import (
    ActorProfileResponse,
    DemoSessionLogoutResponse,
    DemoSessionProfile,
    DemoSessionRequest,
    DemoSessionResponse,
)
from app.config import Settings, load_settings
from app.models.roles import UserRole
from app.services.payment_guards import TrustedActorContext

router = APIRouter(prefix="/api/v2", tags=["auth"])


def is_loopback_client(request: Request) -> bool:
    """Determine whether the incoming request originated from a loopback address.

    Restricts local demo session token issuance strictly to localhost / loopback callers.
    Accepts:
    - 127.0.0.1, ::1 (IPv4 / IPv6 loopback)
    - "localhost"
    - "testclient" (FastAPI / Starlette test client)
    Rejects any non-loopback host or untrusted forwarded client.
    """
    if not request.client:
        return False

    # Check forwarded headers first; if any non-loopback address is present, reject
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        for part in forwarded.split(","):
            ip_str = part.strip()
            if ip_str in ("testclient", "localhost"):
                continue
            try:
                if not ipaddress.ip_address(ip_str).is_loopback:
                    return False
            except ValueError:
                return False

    host = request.client.host
    if host in ("testclient", "localhost"):
        return True
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_loopback
    except ValueError:
        return False


def assert_demo_session_allowed(request: Request) -> Settings:
    """Enforce security invariants for local demo session endpoint.

    SECURITY INVARIANTS:
    1. Disabled by default: Requires explicit PAUSEGUARD_ALLOW_DEMO_AUTH=true.
    2. Environment restriction: Strictly local or test environment only.
    3. Mode restriction: Strictly mock mode only.
    4. Loopback restriction: Strictly loopback caller only.
    5. Fails closed with HTTP 403 Forbidden on any violation.
    """
    settings = getattr(request.app.state, "settings", None)
    if settings is None:
        try:
            settings = load_settings()
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Demo authentication is disabled in this environment",
            )

    if not is_demo_mode_allowed(settings):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Demo authentication is disabled in this environment",
        )

    if not is_loopback_client(request):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Demo session endpoint is restricted to loopback requests only",
        )

    return settings


@router.get("/profile", response_model=ActorProfileResponse)
def get_actor_profile(
    actor: Annotated[TrustedActorContext, Depends(get_current_actor)],
) -> ActorProfileResponse:
    """Return the authenticated actor's server-resolved profile.

    Roles and permissions are retrieved strictly from the server's trusted
    identity context, never from client-supplied claims or headers.
    """
    return ActorProfileResponse(
        user_id=actor.user_id,
        roles=sorted(list(actor.roles), key=lambda r: r.value),
        notification_preference_paise=None,
    )


@router.post("/demo/session", response_model=DemoSessionResponse)
def create_demo_session(
    request: Request,
    payload: DemoSessionRequest,
) -> DemoSessionResponse:
    """Establish a local synthetic demo session for authorized prototype actors.

    SECURITY INVARIANTS:
    1. Disabled by default: Gated by PAUSEGUARD_ALLOW_DEMO_AUTH=true.
    2. Strict environment check: Restricted to local/test environment in mock mode.
    3. Loopback-only caller restriction: Rejects non-loopback requests.
    4. Explicit synthetic identities: Rejects arbitrary unmapped contacts/emails.
    5. Admin privilege isolation: Admin sessions require PAUSEGUARD_ALLOW_DEMO_ADMIN=true.
    6. Does not override payment authorization: Normal payment APIs resolve roles server-side.
    """
    settings = assert_demo_session_allowed(request)

    # Enforce admin privilege isolation
    if payload.role == UserRole.ADMIN and not getattr(settings, "allow_demo_admin", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Admin demo session issuance is disabled. Set PAUSEGUARD_ALLOW_DEMO_ADMIN=true for isolated local admin testing.",
        )

    # Resolve authorized synthetic demo identity
    identity = get_authorized_synthetic_identity(
        role=payload.role,
        contact=payload.contact,
        identity_tag=payload.identity_tag,
    )
    if identity is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No authorized synthetic demo identity matches the requested contact",
        )

    # Lifespan: 1800s (30m) default or explicit parameter (up to 86400s)
    lifespan = payload.expires_in_seconds if payload.expires_in_seconds is not None else 1800

    # Create dynamic session with enforced expiration
    session_record = DEMO_SESSION_STORE.create_session(
        identity=identity,
        role=payload.role,
        expires_in_seconds=lifespan,
    )

    profile_data = DemoSessionProfile(
        id=str(identity.actor.user_id),
        role=payload.role.value,
        name=identity.name,
        contact=identity.contact,
        sample=True,
        category="personal",
        language="en",
        large_text=False,
        organization="",
        recurring_supplier="",
        threshold_paise=identity.threshold_paise,
        notifications=True,
        quiet_start="",
        quiet_end="",
        call_consent=False,
        safe_lock=False,
    )

    return DemoSessionResponse(
        token=session_record.token,
        token_type="Bearer",
        expires_in_seconds=lifespan,
        expires_at=session_record.expires_at_ms,
        user_id=identity.actor.user_id,
        role=payload.role,
        roles=sorted(list(identity.actor.roles), key=lambda r: r.value),
        profile=profile_data,
    )


@router.get("/demo/session", response_model=DemoSessionResponse)
def get_current_demo_session(
    request: Request,
    actor: Annotated[TrustedActorContext, Depends(get_current_actor)],
) -> DemoSessionResponse:
    """Return the active local demo session for the authenticated synthetic caller.

    Requires valid Bearer token and enforces loopback and demo mode security invariants.
    """
    settings = assert_demo_session_allowed(request)

    # Extract token from authorization header to look up active session record
    auth_header = request.headers.get("authorization", "")
    token = auth_header.removeprefix("Bearer ").strip() if auth_header.startswith("Bearer ") else ""

    session_record = DEMO_SESSION_STORE.get_session(token)
    identity = session_record.identity if session_record else get_synthetic_identity_by_actor(actor)
    if identity is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active synthetic demo session for this actor",
        )

    # If actor is admin, check admin privilege isolation
    if UserRole.ADMIN in actor.roles and not getattr(settings, "allow_demo_admin", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Admin demo session issuance is disabled. Set PAUSEGUARD_ALLOW_DEMO_ADMIN=true for isolated local admin testing.",
        )

    now_ms = int(time.time() * 1000)
    if session_record:
        expires_at_ms = session_record.expires_at_ms
        expires_in_seconds = max(0, int((expires_at_ms - now_ms) / 1000))
    else:
        expires_at_ms = now_ms + 1800 * 1000
        expires_in_seconds = 1800

    primary_role = next(iter(sorted(list(actor.roles), key=lambda r: r.value)))

    profile_data = DemoSessionProfile(
        id=str(actor.user_id),
        role=primary_role.value,
        name=identity.name,
        contact=identity.contact,
        sample=True,
        category="personal",
        language="en",
        large_text=False,
        organization="",
        recurring_supplier="",
        threshold_paise=identity.threshold_paise,
        notifications=True,
        quiet_start="",
        quiet_end="",
        call_consent=False,
        safe_lock=False,
    )

    return DemoSessionResponse(
        token=token or identity.token,
        token_type="Bearer",
        expires_in_seconds=expires_in_seconds,
        expires_at=expires_at_ms,
        user_id=actor.user_id,
        role=primary_role,
        roles=sorted(list(actor.roles), key=lambda r: r.value),
        profile=profile_data,
    )


@router.delete("/demo/session", response_model=DemoSessionLogoutResponse)
def terminate_demo_session(
    request: Request,
    actor: Annotated[TrustedActorContext, Depends(get_current_actor)],
) -> DemoSessionLogoutResponse:
    """Terminate and revoke the active local demo session.

    Enforces loopback restriction and purges the session token from memory.
    """
    assert_demo_session_allowed(request)

    auth_header = request.headers.get("authorization", "")
    token = auth_header.removeprefix("Bearer ").strip() if auth_header.startswith("Bearer ") else ""

    if token:
        DEMO_SESSION_STORE.revoke_session(token)

    return DemoSessionLogoutResponse(signed_out=True)


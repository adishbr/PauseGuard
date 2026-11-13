"""FastAPI authentication and role-authorization dependencies.

Extracts and validates bearer credentials, resolves trusted server actor contexts,
and enforces role boundaries server-side.
Client-supplied role claims, actor headers, or identity assertions are ignored.
"""

from typing import Annotated, Callable
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth.exceptions import AuthenticationError, AuthorizationError
from app.auth.identities import is_demo_mode_allowed, resolve_synthetic_token
from app.models.roles import UserRole
from app.services.account_auth_service import AccountAuthService
from app.services.payment_guards import TrustedActorContext
from app.services.v5_store import get_or_create_v5_mock_store

# HTTPBearer with auto_error=False to allow canonical 401 handling with WWW-Authenticate header
bearer_scheme = HTTPBearer(auto_error=False)


def _resolve_v5_session_actor(request: Request, token: str, settings: object | None) -> TrustedActorContext | None:
    if not token.startswith("pg_v5_"):
        return None
    session_factory = getattr(request.app.state, "session_factory", None)
    if session_factory is not None:
        session = session_factory()
        try:
            return AccountAuthService(
                settings=settings,
                db_session=session,
                mock_store=None,
            ).resolve_bearer_token(token)
        finally:
            session.close()

    if getattr(settings, "mode", "mock") == "mock":
        mock_store = getattr(request.app.state, "v5_identity_store", None)
        if mock_store is not None:
            return AccountAuthService(
                settings=settings,
                db_session=None,
                mock_store=mock_store,
            ).resolve_bearer_token(token)
    return None


def get_current_actor(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> TrustedActorContext:
    """Resolve the authenticated actor from the Authorization Bearer token.

    SECURITY INVARIANTS:
    - Resolves server-issued V5 session tokens first (DB or app mock store).
    - Falls back to synthetic demo tokens ONLY if demo mode is explicitly allowed.
    - Fails closed: Rejects demo tokens in production, real mode, or when demo auth is disabled.
    - Standard 401 with WWW-Authenticate: Bearer header.
    - Resolves identity strictly from trusted server state, ignoring client headers.
    """
    if credentials is None:
        raise AuthenticationError("Missing or malformed Authorization header with Bearer token")

    token = credentials.credentials.strip()
    if not token:
        raise AuthenticationError("Empty or invalid bearer token")

    settings = getattr(request.app.state, "settings", None)
    v5_actor = _resolve_v5_session_actor(request, token, settings)
    if v5_actor is not None:
        return v5_actor

    actor = resolve_synthetic_token(token, settings=settings)

    if actor is None:
        if not is_demo_mode_allowed(settings):
            raise AuthenticationError("Demo authentication is disabled in this environment")
        raise AuthenticationError("Invalid, expired, or unrecognized authentication token")

    return actor


def require_role(required_role: UserRole) -> Callable[[TrustedActorContext], TrustedActorContext]:
    """Dependency factory that requires the authenticated actor to have a specific role."""

    def role_dependency(
        actor: Annotated[TrustedActorContext, Depends(get_current_actor)],
    ) -> TrustedActorContext:
        if required_role not in actor.roles:
            raise AuthorizationError(f"Forbidden: Operation requires {required_role.value} role")
        return actor

    return role_dependency


def require_any_role(*roles: UserRole) -> Callable[[TrustedActorContext], TrustedActorContext]:
    """Dependency factory that requires the authenticated actor to have at least one of the roles."""
    expected_roles = frozenset(roles)

    def any_role_dependency(
        actor: Annotated[TrustedActorContext, Depends(get_current_actor)],
    ) -> TrustedActorContext:
        if not (expected_roles & actor.roles):
            role_names = ", ".join(r.value for r in roles)
            raise AuthorizationError(f"Forbidden: Operation requires one of [{role_names}] roles")
        return actor

    return any_role_dependency


def require_payer(
    actor: Annotated[TrustedActorContext, Depends(get_current_actor)],
) -> TrustedActorContext:
    """Dependency requiring the authenticated actor to hold the PAYER role."""
    if UserRole.PAYER not in actor.roles:
        raise AuthorizationError("Forbidden: Operation requires payer role")
    return actor


def require_guardian(
    actor: Annotated[TrustedActorContext, Depends(get_current_actor)],
) -> TrustedActorContext:
    """Dependency requiring the authenticated actor to hold the GUARDIAN role."""
    if UserRole.GUARDIAN not in actor.roles:
        raise AuthorizationError("Forbidden: Operation requires guardian role")
    return actor


def require_analyst(
    actor: Annotated[TrustedActorContext, Depends(get_current_actor)],
) -> TrustedActorContext:
    """Dependency requiring the authenticated actor to hold the ANALYST role."""
    if UserRole.ANALYST not in actor.roles:
        raise AuthorizationError("Forbidden: Operation requires analyst role")
    return actor


def require_admin(
    actor: Annotated[TrustedActorContext, Depends(get_current_actor)],
) -> TrustedActorContext:
    """Dependency requiring the authenticated actor to hold the ADMIN role."""
    if UserRole.ADMIN not in actor.roles:
        raise AuthorizationError("Forbidden: Operation requires admin role")
    return actor

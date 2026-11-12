"""Deterministic synthetic identities, demo token resolution, and server-side enrollments.

Provides known test identities and a prototype demo token registry for local
development, unit testing, and isolated security verification.

SECURITY CONTROLS:
- Fail-closed gating: Synthetic demo tokens are strictly prohibited in production
  or whenever demo/mock mode is not explicitly enabled.
- Server-managed relationships: Guardian-to-payer relationships are defined
  authoritatively on the server, never derived from client-supplied IDs.
- No real credentials, production IAM, or external network access.
"""

from collections.abc import Mapping
from types import MappingProxyType
from uuid import UUID

from app.config import Settings, load_settings
from app.models.roles import UserRole
from app.services.payment_guards import TrustedActorContext

# Canonical synthetic user IDs for local testing and demonstration
SYNTHETIC_PAYER_ID = UUID("00000000-0000-0000-0000-000000000001")
SYNTHETIC_GUARDIAN_ID = UUID("00000000-0000-0000-0000-000000000002")
SYNTHETIC_ANALYST_ID = UUID("00000000-0000-0000-0000-000000000003")
SYNTHETIC_ADMIN_ID = UUID("00000000-0000-0000-0000-000000000004")
SYNTHETIC_OTHER_PAYER_ID = UUID("00000000-0000-0000-0000-000000000005")

# Canonical synthetic actor contexts with immutable role grants
SYNTHETIC_PAYER = TrustedActorContext(
    user_id=SYNTHETIC_PAYER_ID,
    roles=frozenset({UserRole.PAYER}),
)

SYNTHETIC_GUARDIAN = TrustedActorContext(
    user_id=SYNTHETIC_GUARDIAN_ID,
    roles=frozenset({UserRole.GUARDIAN}),
)

SYNTHETIC_ANALYST = TrustedActorContext(
    user_id=SYNTHETIC_ANALYST_ID,
    roles=frozenset({UserRole.ANALYST}),
)

SYNTHETIC_ADMIN = TrustedActorContext(
    user_id=SYNTHETIC_ADMIN_ID,
    roles=frozenset({UserRole.ADMIN}),
)

SYNTHETIC_OTHER_PAYER = TrustedActorContext(
    user_id=SYNTHETIC_OTHER_PAYER_ID,
    roles=frozenset({UserRole.PAYER}),
)

# Immutable registry of prototype demo tokens to synthetic actor contexts
DEMO_TOKEN_REGISTRY: MappingProxyType[str, TrustedActorContext] = MappingProxyType({
    # Kebab-case variants
    "demo-token-payer": SYNTHETIC_PAYER,
    "demo-token-guardian": SYNTHETIC_GUARDIAN,
    "demo-token-analyst": SYNTHETIC_ANALYST,
    "demo-token-admin": SYNTHETIC_ADMIN,
    "demo-token-other-payer": SYNTHETIC_OTHER_PAYER,
    # Snake_case variants
    "demo_token_payer": SYNTHETIC_PAYER,
    "demo_token_guardian": SYNTHETIC_GUARDIAN,
    "demo_token_analyst": SYNTHETIC_ANALYST,
    "demo_token_admin": SYNTHETIC_ADMIN,
    "demo_token_other_payer": SYNTHETIC_OTHER_PAYER,
})

# Authoritative server-side synthetic guardian enrollment mapping (payer_id -> enrolled guardian_id)
SYNTHETIC_GUARDIAN_ENROLLMENTS: MappingProxyType[UUID, UUID] = MappingProxyType({
    SYNTHETIC_PAYER_ID: SYNTHETIC_GUARDIAN_ID,
})


def is_demo_mode_allowed(settings: Settings | None = None) -> bool:
    """Determine whether synthetic demo tokens are allowed to authenticate callers.

    SECURITY INVARIANTS:
    1. Fails closed: Disabled by default. Explicit authorization (allow_demo_auth=True) is required.
    2. Even with explicit authorization, only allowed when environment is 'local' or 'test'
       AND mode is 'mock'.
    3. Strictly prohibited in production or real mode, regardless of any opt-in flag.
    """
    if settings is None:
        try:
            settings = load_settings()
        except Exception:
            return False

    # 1. Require explicit authorization
    opted_in = getattr(settings, "allow_demo_auth", False) or getattr(settings, "enable_demo_auth", False)
    if not opted_in:
        return False

    # 2. Strict environment check: local or test only
    env = getattr(settings, "environment", None)
    if env not in ("local", "test"):
        return False

    # 3. Strict mode check: mock mode only
    mode = getattr(settings, "mode", None)
    if mode != "mock":
        return False

    return True


def get_authoritative_guardian_for_payer(
    payer_id: UUID,
    enrollments: Mapping[UUID, UUID] | None = None,
) -> UUID | None:
    """Retrieve the authoritative enrolled guardian ID for a payer from server state.

    Never reads client-supplied claims, headers, or query parameters.
    Returns None if no guardian is enrolled for this payer.
    """
    if not isinstance(payer_id, UUID):
        return None
    if enrollments is not None:
        return enrollments.get(payer_id)
    from app.services.guardian_service import get_guardian_service
    return get_guardian_service().get_guardian_for_payer(payer_id)


def resolve_synthetic_token(
    token: str,
    *,
    settings: Settings | None = None,
) -> TrustedActorContext | None:
    """Resolve a bearer token string to a TrustedActorContext if present in demo registry.

    Fails closed if demo mode is not permitted in the active settings environment.
    Client-supplied roles and metadata are never inspected here; only the
    server-persisted synthetic context mapping is returned.
    """
    if not isinstance(token, str):
        return None
    if not is_demo_mode_allowed(settings):
        return None
    return DEMO_TOKEN_REGISTRY.get(token.strip())

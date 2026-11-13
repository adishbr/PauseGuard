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
import threading
import time
from types import MappingProxyType
from uuid import UUID, uuid4

from app.config import Settings, load_settings
from app.models.roles import UserRole
from app.services.payment_guards import TrustedActorContext

# Canonical synthetic user IDs for local testing and demonstration
SYNTHETIC_PAYER_ID = UUID("00000000-0000-0000-0000-000000000001")
SYNTHETIC_GUARDIAN_ID = UUID("00000000-0000-0000-0000-000000000002")
SYNTHETIC_ANALYST_ID = UUID("00000000-0000-0000-0000-000000000003")
SYNTHETIC_ADMIN_ID = UUID("00000000-0000-0000-0000-000000000004")
SYNTHETIC_OTHER_PAYER_ID = UUID("00000000-0000-0000-0000-000000000005")

# Canonical synthetic demo tokens for local/test authorization
SYNTHETIC_PAYER_TOKEN = "demo-token-payer"
SYNTHETIC_GUARDIAN_TOKEN = "demo-token-guardian"
SYNTHETIC_ANALYST_TOKEN = "demo-token-analyst"
SYNTHETIC_ADMIN_TOKEN = "demo-token-admin"
SYNTHETIC_OTHER_PAYER_TOKEN = "demo-token-other-payer"

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
    now_ms: int | None = None,
) -> TrustedActorContext | None:
    """Resolve a bearer token string to a TrustedActorContext.

    Resolution Order:
    1. Fail closed if demo mode is not permitted in the active settings environment.
    2. Check dynamic DemoSessionStore: enforces strict 30m session expiration.
       Expired sessions return None (resulting in HTTP 401).
    3. Check static DEMO_TOKEN_REGISTRY: preserves approved synthetic test behavior
       for offline unit tests using static fixture tokens.
    """
    if not isinstance(token, str):
        return None
    if not is_demo_mode_allowed(settings):
        return None

    cleaned = token.strip()
    if not cleaned:
        return None

    # 1. Dynamic demo session store with strict fail-closed expiration check
    session = DEMO_SESSION_STORE.get_session(cleaned, now_ms=now_ms)
    if session is not None:
        return session.actor

    # 2. Static approved demo tokens for offline test suites
    return DEMO_TOKEN_REGISTRY.get(cleaned)


# ---------------------------------------------------------------------------
# Synthetic Demo Identity Registry & Resolution
# ---------------------------------------------------------------------------

class SyntheticDemoIdentity:
    """Immutable metadata describing a known authorized synthetic demo identity."""

    __slots__ = ("actor", "token", "name", "contact", "aliases", "threshold_paise", "is_admin")

    def __init__(
        self,
        actor: TrustedActorContext,
        token: str,
        name: str,
        contact: str,
        aliases: tuple[str, ...],
        threshold_paise: int | None = None,
        is_admin: bool = False,
    ) -> None:
        self.actor = actor
        self.token = token
        self.name = name
        self.contact = contact
        self.aliases = aliases
        self.threshold_paise = threshold_paise
        self.is_admin = is_admin


SYNTHETIC_DEMO_IDENTITIES: tuple[SyntheticDemoIdentity, ...] = (
    SyntheticDemoIdentity(
        actor=SYNTHETIC_PAYER,
        token=SYNTHETIC_PAYER_TOKEN,
        name="Asha Demo",
        contact="asha@pauseguard.test",
        aliases=("asha@pauseguard.test", "+919876543210", "9876543210", "demo-payer", "primary"),
        threshold_paise=5500000,
    ),
    SyntheticDemoIdentity(
        actor=SYNTHETIC_GUARDIAN,
        token=SYNTHETIC_GUARDIAN_TOKEN,
        name="Ravi Demo",
        contact="ravi@pauseguard.test",
        aliases=("ravi@pauseguard.test", "+919876543211", "9876543211", "demo-guardian", "primary"),
        threshold_paise=None,
    ),
    SyntheticDemoIdentity(
        actor=SYNTHETIC_OTHER_PAYER,
        token=SYNTHETIC_OTHER_PAYER_TOKEN,
        name="Admin Sandbox Payer",
        contact="sandbox-payer@pauseguard.test",
        aliases=("sandbox-payer@pauseguard.test", "other", "secondary", "other_payer", "admin-synthetic-payer"),
        threshold_paise=None,
    ),
    SyntheticDemoIdentity(
        actor=SYNTHETIC_ANALYST,
        token=SYNTHETIC_ANALYST_TOKEN,
        name="Analyst Demo",
        contact="analyst@pauseguard.test",
        aliases=("analyst@pauseguard.test", "primary"),
        threshold_paise=None,
    ),
    SyntheticDemoIdentity(
        actor=SYNTHETIC_ADMIN,
        token=SYNTHETIC_ADMIN_TOKEN,
        name="Admin Demo",
        contact="admin@pauseguard.test",
        aliases=("admin@pauseguard.test", "demo-admin", "primary"),
        threshold_paise=None,
        is_admin=True,
    ),
)


# ---------------------------------------------------------------------------
# Dynamic Local Demo Session Store & Expiration Management
# ---------------------------------------------------------------------------

class DemoSessionRecord:
    """Server-side record of an active or expired local prototype demo session."""

    __slots__ = (
        "session_id",
        "token",
        "user_id",
        "role",
        "actor",
        "identity",
        "created_at_ms",
        "expires_at_ms",
    )

    def __init__(
        self,
        session_id: str,
        token: str,
        user_id: UUID,
        role: UserRole,
        actor: TrustedActorContext,
        identity: SyntheticDemoIdentity,
        created_at_ms: int,
        expires_at_ms: int,
    ) -> None:
        self.session_id = session_id
        self.token = token
        self.user_id = user_id
        self.role = role
        self.actor = actor
        self.identity = identity
        self.created_at_ms = created_at_ms
        self.expires_at_ms = expires_at_ms

    def is_expired(self, now_ms: int | None = None) -> bool:
        current = int(time.time() * 1000) if now_ms is None else now_ms
        return current >= self.expires_at_ms


class DemoSessionStore:
    """Thread-safe, fail-closed in-memory session registry for local prototype demo sessions.

    SECURITY INVARIANTS:
    1. Ephemeral: In-memory only; cleared on process restart.
    2. Fail-closed expiration: Sessions expire strictly after lifespan (default 1800s / 30m).
    3. Revocable: Explicit deletion on logout / session termination.
    4. Deterministic identity: Bound strictly to server-managed SyntheticDemoIdentity.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sessions: dict[str, DemoSessionRecord] = {}

    def create_session(
        self,
        identity: SyntheticDemoIdentity,
        role: UserRole,
        expires_in_seconds: int = 1800,
        now_ms: int | None = None,
    ) -> DemoSessionRecord:
        current_time = int(time.time() * 1000) if now_ms is None else now_ms
        expires_at = current_time + (expires_in_seconds * 1000)
        session_id = f"pg_demo_{uuid4().hex[:16]}"
        role_tag = role.value.lower()
        token = f"demo-session-{role_tag}-{uuid4().hex[:12]}"

        record = DemoSessionRecord(
            session_id=session_id,
            token=token,
            user_id=identity.actor.user_id,
            role=role,
            actor=identity.actor,
            identity=identity,
            created_at_ms=current_time,
            expires_at_ms=expires_at,
        )
        with self._lock:
            self._sessions[token] = record
        return record

    def get_session(self, token: str, now_ms: int | None = None) -> DemoSessionRecord | None:
        if not isinstance(token, str):
            return None
        cleaned = token.strip()
        with self._lock:
            record = self._sessions.get(cleaned)
            if record is None:
                return None
            if record.is_expired(now_ms):
                # Fail closed: Purge expired session from registry
                self._sessions.pop(cleaned, None)
                return None
            return record

    def revoke_session(self, token: str) -> bool:
        if not isinstance(token, str):
            return False
        with self._lock:
            return self._sessions.pop(token.strip(), None) is not None

    def clear(self) -> None:
        with self._lock:
            self._sessions.clear()


DEMO_SESSION_STORE = DemoSessionStore()


def _normalize_contact(contact: str) -> str:
    cleaned = contact.strip().lower()
    cleaned = cleaned.replace(" ", "").replace("-", "")
    if cleaned.startswith("+91") and len(cleaned) == 13:
        return cleaned[3:]
    return cleaned


def get_authorized_synthetic_identity(
    role: UserRole,
    contact: str | None = None,
    identity_tag: str | None = None,
) -> SyntheticDemoIdentity | None:
    """Resolve an authorized synthetic demo identity by role and optional contact/tag.

    SECURITY INVARIANTS:
    - Never provisions dynamic accounts or accepts arbitrary contacts.
    - If contact is provided, it must strictly match an authorized synthetic identity.
    - If no contact is provided, defaults to the primary synthetic identity for that role.
    """
    if contact is not None and contact.strip():
        norm_contact = _normalize_contact(contact)
        for identity in SYNTHETIC_DEMO_IDENTITIES:
            if role in identity.actor.roles:
                for alias in identity.aliases:
                    if _normalize_contact(alias) == norm_contact:
                        return identity
        return None

    if identity_tag is not None and identity_tag.strip():
        tag = identity_tag.strip().lower()
        for identity in SYNTHETIC_DEMO_IDENTITIES:
            if role in identity.actor.roles:
                for alias in identity.aliases:
                    if alias.lower() == tag:
                        return identity
        return None

    # Default to the primary synthetic identity for this role
    for identity in SYNTHETIC_DEMO_IDENTITIES:
        if role in identity.actor.roles and "primary" in identity.aliases:
            return identity

    return None


def get_synthetic_identity_by_actor(actor: TrustedActorContext) -> SyntheticDemoIdentity | None:
    """Find the synthetic demo identity matching the given actor user ID."""
    for identity in SYNTHETIC_DEMO_IDENTITIES:
        if identity.actor.user_id == actor.user_id:
            return identity
    return None

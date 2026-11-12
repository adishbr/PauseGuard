"""Authentication and authorization foundation for PauseGuard V2.

Provides server-enforced actor context resolution, role checking,
ownership/cross-account boundary enforcement, and privacy-preserving view levels.
"""

from app.auth.authorization import (
    assert_guardian_cannot_execute,
    authorize_account_access,
    authorize_payment_view_level,
    authorize_resource_owner,
    verify_guardian_to_payer_relationship,
)
from app.auth.dependencies import (
    get_current_actor,
    require_admin,
    require_analyst,
    require_any_role,
    require_guardian,
    require_payer,
    require_role,
)
from app.auth.exceptions import (
    AuthenticationError,
    AuthorizationError,
    CrossAccountAccessError,
    GuardianAssignmentError,
)
from app.auth.identities import (
    DEMO_TOKEN_REGISTRY,
    SYNTHETIC_ADMIN,
    SYNTHETIC_ADMIN_ID,
    SYNTHETIC_ANALYST,
    SYNTHETIC_ANALYST_ID,
    SYNTHETIC_GUARDIAN,
    SYNTHETIC_GUARDIAN_ENROLLMENTS,
    SYNTHETIC_GUARDIAN_ID,
    SYNTHETIC_OTHER_PAYER,
    SYNTHETIC_OTHER_PAYER_ID,
    SYNTHETIC_PAYER,
    SYNTHETIC_PAYER_ID,
    get_authoritative_guardian_for_payer,
    is_demo_mode_allowed,
    resolve_synthetic_token,
)
from app.auth.router import router as auth_router
from app.auth.schemas import (
    ActorProfileResponse,
    FullPaymentView,
    GuardianDecisionRequest,
    RedactedPaymentView,
)

__all__ = [
    # Exceptions
    "AuthenticationError",
    "AuthorizationError",
    "CrossAccountAccessError",
    "GuardianAssignmentError",
    # Schemas
    "ActorProfileResponse",
    "RedactedPaymentView",
    "FullPaymentView",
    "GuardianDecisionRequest",
    # Identities & tokens
    "SYNTHETIC_PAYER_ID",
    "SYNTHETIC_GUARDIAN_ID",
    "SYNTHETIC_ANALYST_ID",
    "SYNTHETIC_ADMIN_ID",
    "SYNTHETIC_OTHER_PAYER_ID",
    "SYNTHETIC_PAYER",
    "SYNTHETIC_GUARDIAN",
    "SYNTHETIC_ANALYST",
    "SYNTHETIC_ADMIN",
    "SYNTHETIC_OTHER_PAYER",
    "DEMO_TOKEN_REGISTRY",
    "SYNTHETIC_GUARDIAN_ENROLLMENTS",
    "is_demo_mode_allowed",
    "get_authoritative_guardian_for_payer",
    "resolve_synthetic_token",
    # Dependencies
    "get_current_actor",
    "require_role",
    "require_any_role",
    "require_payer",
    "require_guardian",
    "require_analyst",
    "require_admin",
    # Authorization checks
    "authorize_resource_owner",
    "authorize_account_access",
    "verify_guardian_to_payer_relationship",
    "assert_guardian_cannot_execute",
    "authorize_payment_view_level",
    # Routers
    "auth_router",
]


"""Security boundary for the optional Razorpay merchant Test Mode sandbox.

This module validates configuration and trusted admin access only.
It does not create orders, execute payments, process webhooks, or settle funds.
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import FrozenSet

from app.models.roles import UserRole
from app.services.payment_guards import TrustedActorContext


class RazorpaySandboxError(ValueError):
    """Safe, non-secret sandbox configuration or authorization error."""


@dataclass(frozen=True)
class RazorpaySandboxConfig:
    """Validated Test Mode credentials; never expose credentials in repr."""

    key_id: str = field(repr=False)
    key_secret: str = field(repr=False)


def load_sandbox_config(
    environ: Mapping[str, str] | None = None,
) -> RazorpaySandboxConfig:
    """Load explicitly enabled Razorpay Test Mode credentials.

    No dotenv loading, credential logging, live keys, or implicit enablement.
    """
    source = os.environ if environ is None else environ

    enabled_value = source.get("PAUSEGUARD_RAZORPAY_TEST_ENABLED", "")

    if not isinstance(enabled_value, str):
        raise RazorpaySandboxError(
            "Razorpay sandbox configuration is invalid"
        )

    enabled = enabled_value.strip().lower()

    if enabled != "true":
        raise RazorpaySandboxError("Razorpay sandbox is disabled")

    key_id = source.get("RZP_TEST_KEY_ID", "")
    key_secret = source.get("RZP_TEST_KEY_SECRET", "")

    if not isinstance(key_id, str) or not isinstance(key_secret, str):
        raise RazorpaySandboxError(
            "Razorpay Test Mode credentials are invalid"
        )

    key_id = key_id.strip()
    key_secret = key_secret.strip()

    if not key_id or not key_secret:
        raise RazorpaySandboxError(
            "Razorpay Test Mode credentials are missing"
        )

    if not key_id.startswith("rzp_test_"):
        raise RazorpaySandboxError(
            "Only Razorpay Test Mode keys are permitted"
        )

    if key_id.startswith("rzp_live_"):
        raise RazorpaySandboxError(
            "Live Razorpay keys are prohibited"
        )

    return RazorpaySandboxConfig(
        key_id=key_id,
        key_secret=key_secret,
    )


def require_sandbox_admin(actor: TrustedActorContext) -> None:
    """Require a server-resolved admin identity before sandbox access."""
    if not isinstance(actor, TrustedActorContext):
        raise RazorpaySandboxError(
            "Trusted administrator authentication is required"
        )

    roles: FrozenSet[UserRole] = actor.roles

    if UserRole.ADMIN not in roles:
        raise RazorpaySandboxError(
            "Administrator access is required"
        )


def authorize_sandbox_access(
    actor: TrustedActorContext,
    environ: Mapping[str, str] | None = None,
) -> RazorpaySandboxConfig:
    """Authorize an admin and return validated Test Mode configuration."""
    require_sandbox_admin(actor)

    return load_sandbox_config(environ)

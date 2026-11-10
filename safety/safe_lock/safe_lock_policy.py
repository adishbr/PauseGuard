
"""Safe-Lock policy checks for PauseGuard.

Advisory policy evaluation only.
This module never approves, rejects, or executes payments.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class SafeLockAssessment:
    restricted: bool
    reasons: tuple[str, ...]


def assess_safe_lock(
    safe_lock_enabled: bool,
    amount_paise: int,
    max_amount_paise: int,
    allowed_categories: set[str] | None = None,
    payment_category: str | None = None,
) -> SafeLockAssessment:
    """Evaluate a payment against configured Safe-Lock restrictions."""

    if not isinstance(safe_lock_enabled, bool):
        raise ValueError("safe_lock_enabled must be boolean")

    if (
        isinstance(amount_paise, bool)
        or not isinstance(amount_paise, int)
        or amount_paise <= 0
    ):
        raise ValueError("amount_paise must be a positive integer")

    if (
        isinstance(max_amount_paise, bool)
        or not isinstance(max_amount_paise, int)
        or max_amount_paise <= 0
    ):
        raise ValueError("max_amount_paise must be a positive integer")

    reasons = []

    if not safe_lock_enabled:
        return SafeLockAssessment(False, ())

    if amount_paise > max_amount_paise:
        reasons.append("amount_exceeds_safe_lock_limit")

    if allowed_categories is not None:
        if payment_category is None:
            reasons.append("payment_category_missing")
        elif payment_category not in allowed_categories:
            reasons.append("payment_category_not_allowed")

    return SafeLockAssessment(
        restricted=bool(reasons),
        reasons=tuple(reasons),
    )

"""Advisory guardian timeout policy."""

from datetime import datetime, timedelta


GUARDIAN_TIMEOUT_SECONDS = 30


def evaluate_guardian_timeout(
    started_at: datetime,
    checked_at: datetime,
) -> dict:
    """Evaluate whether the guardian response window has expired."""

    if not isinstance(started_at, datetime):
        raise TypeError("started_at must be a datetime")

    if not isinstance(checked_at, datetime):
        raise TypeError("checked_at must be a datetime")

    if started_at.tzinfo is None or checked_at.tzinfo is None:
        raise ValueError("Timezone-aware timestamps are required")

    if checked_at < started_at:
        raise ValueError("checked_at cannot be before started_at")

    deadline = started_at + timedelta(
        seconds=GUARDIAN_TIMEOUT_SECONDS
    )

    expired = checked_at >= deadline

    return {
        "expired": expired,
        "recommended_action": (
            "AWAITING_FALLBACK_REVIEW"
            if expired
            else "AWAITING_GUARDIAN"
        ),
        "can_authorize_payment": False,
        "can_execute_payment": False,
    }
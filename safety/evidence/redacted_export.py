
"""Privacy-minimizing evidence export for PauseGuard."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any


# Only these fields are permitted in an exported evidence record.
ALLOWED_FIELDS = {
    "case_id",
    "event_id",
    "event_type",
    "timestamp",
    "risk_level",
    "risk_indicators",
    "policy_version",
}

# Sensitive values must never be exported as separate fields.
FORBIDDEN_FIELDS = {
    "otp",
    "pin",
    "upi_pin",
    "password",
    "token",
    "access_token",
    "refresh_token",
    "secret",
    "authorization",
    "phone",
    "phone_number",
    "email",
    "upi_id",
    "account_number",
    "recipient",
    "recipient_name",
    "purpose",
    "full_name",
}


def _clean_text(value: str) -> str:
    """Mask common personal identifiers in text."""

    # Mask email addresses first.
    value = re.sub(
        r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
        "[REDACTED_EMAIL]",
        value,
        flags=re.IGNORECASE,
    )

    # Mask Indian mobile numbers:
    # 9876543210
    # 98765 43210
    # +91 9876543210
    # +91-9876543210
    # +919876543210
    value = re.sub(
        r"(?<!\w)(?:\+91[\s-]?)?[6-9]\d{4}[\s-]?\d{5}(?!\w)",
        "[REDACTED_PHONE]",
        value,
    )

    # Mask other exactly 10-digit phone-like numbers.
    value = re.sub(
        r"(?<!\d)\d{10}(?!\d)",
        "[REDACTED_PHONE]",
        value,
    )

    # Mask common UPI-like identifiers.
    value = re.sub(
        r"\b[\w.-]+@[\w.-]+\b",
        "[REDACTED_UPI_ID]",
        value,
    )

    return value


def _safe_value(value: Any) -> Any:
    """Allow only simple, predictable evidence values."""

    if isinstance(value, str):
        return _clean_text(value)

    if isinstance(value, bool) or value is None:
        return value

    if isinstance(value, int):
        return value

    if isinstance(value, list):
        # Keep only simple strings; never export arbitrary nested objects.
        return [
            _clean_text(item)
            for item in value
            if isinstance(item, str)
        ][:20]

    return None


def export_redacted_evidence(
    record: dict[str, Any],
) -> dict[str, Any]:
    """
    Create a minimized evidence export.

    Unknown fields and sensitive fields are omitted.
    This function does not submit or share the evidence.
    """

    if not isinstance(record, dict):
        raise TypeError("record must be a dictionary")

    exported = {}

    for field in ALLOWED_FIELDS:
        if field not in record:
            continue

        value = _safe_value(record[field])

        if value is not None:
            exported[field] = value

    exported["exported_at"] = datetime.now(
        timezone.utc
    ).isoformat()

    exported["redaction_applied"] = True
    exported["review_required_before_sharing"] = True

    return exported

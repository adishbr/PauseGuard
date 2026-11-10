
"""Advisory purpose-challenge checks for PauseGuard."""

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class PurposeAssessment:
    suspicious: bool
    reasons: tuple[str, ...]


COERCION_PATTERNS = {
    "urgency": r"\b(urgent|immediately|right now|emergency)\b",
    "secrecy": r"\b(don't tell|do not tell|keep it secret|secretly)\b",
    "authority_impersonation": (
        r"\b(police|customs|tax officer|court|government official)\b"
    ),
    "threat": r"\b(arrest|jail|account will be blocked|legal action|fine)\b",
    "credential_request": (
        r"\b(otp|pin|password|upi pin|verification code)\b"
    ),
    "remote_control": (
        r"\b(screen sharing|remote access|anydesk|teamviewer)\b"
    ),
}


def assess_purpose(purpose: str) -> PurposeAssessment:
    """Return advisory warning indicators for a payment purpose."""

    if not isinstance(purpose, str):
        return PurposeAssessment(True, ("invalid_purpose_type",))

    normalized = re.sub(r"\s+", " ", purpose).strip().lower()

    if not normalized:
        return PurposeAssessment(True, ("empty_purpose",))

    reasons = tuple(
        reason
        for reason, pattern in COERCION_PATTERNS.items()
        if re.search(pattern, normalized)
    )

    return PurposeAssessment(bool(reasons), reasons)

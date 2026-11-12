
"""Fail-closed guardian identity verification policy.

This module evaluates identity-verification evidence supplied by a
trusted backend. It does not authenticate users, verify phone calls,
or authorize or execute payments.
"""

from dataclasses import dataclass


# Only methods explicitly approved by the backend security design
# may be accepted. This label represents trusted backend evidence,
# not a verification service implemented by this module.
ALLOWED_VERIFICATION_METHODS = frozenset({
    "trusted_backend_verification",
})


@dataclass(frozen=True)
class GuardianVerificationResult:
    verified: bool
    reason: str
    can_authorize_payment: bool = False
    can_execute_payment: bool = False


def evaluate_guardian_identity(
    expected_guardian_id: str,
    verified_guardian_id: str | None,
    identity_verified: bool,
    verification_method: str,
) -> GuardianVerificationResult:
    """Evaluate backend-supplied guardian identity evidence."""

    if (
        not isinstance(expected_guardian_id, str)
        or not expected_guardian_id.strip()
    ):
        return GuardianVerificationResult(
            False, "invalid_expected_guardian_id"
        )

    if (
        not isinstance(verified_guardian_id, str)
        or not verified_guardian_id.strip()
    ):
        return GuardianVerificationResult(
            False, "missing_verified_guardian_id"
        )

    if not isinstance(identity_verified, bool):
        return GuardianVerificationResult(
            False, "invalid_verification_status"
        )

    if identity_verified is not True:
        return GuardianVerificationResult(
            False, "identity_not_verified"
        )

    if not isinstance(verification_method, str):
        return GuardianVerificationResult(
            False, "invalid_verification_method"
        )

    method = verification_method.strip().lower()

    if not method:
        return GuardianVerificationResult(
            False, "missing_verification_method"
        )

    if method not in ALLOWED_VERIFICATION_METHODS:
        return GuardianVerificationResult(
            False, "unapproved_verification_method"
        )

    if verified_guardian_id != expected_guardian_id:
        return GuardianVerificationResult(
            False, "guardian_id_mismatch"
        )

    return GuardianVerificationResult(
        True,
        "identity_verified",
    )

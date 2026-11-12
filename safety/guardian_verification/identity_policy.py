
"""Fail-closed guardian identity verification policy.

This module evaluates identity-verification evidence supplied by a
trusted backend. It does not authenticate users, verify phone calls,
or authorize or execute payments.
"""

from dataclasses import dataclass


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
    """Evaluate backend-supplied guardian identity evidence.

    Only an explicit successful identity verification with a matching
    guardian ID and an accepted verification method passes.

    Phone-call connection and DTMF input are never sufficient evidence.
    """

    if (
        not isinstance(expected_guardian_id, str)
        or not expected_guardian_id.strip()
    ):
        return GuardianVerificationResult(
            False,
            "invalid_expected_guardian_id",
        )

    if (
        not isinstance(verified_guardian_id, str)
        or not verified_guardian_id.strip()
    ):
        return GuardianVerificationResult(
            False,
            "missing_verified_guardian_id",
        )

    if not isinstance(identity_verified, bool):
        return GuardianVerificationResult(
            False,
            "invalid_verification_status",
        )

    if identity_verified is not True:
        return GuardianVerificationResult(
            False,
            "identity_not_verified",
        )

    if not isinstance(verification_method, str):
        return GuardianVerificationResult(
            False,
            "invalid_verification_method",
        )

    method = verification_method.strip().lower()

    if method in {"call_connected", "dtmf", "dtmf_only"}:
        return GuardianVerificationResult(
            False,
            "insufficient_verification_method",
        )

    if not method:
        return GuardianVerificationResult(
            False,
            "missing_verification_method",
        )

    if verified_guardian_id != expected_guardian_id:
        return GuardianVerificationResult(
            False,
            "guardian_id_mismatch",
        )

    return GuardianVerificationResult(
        True,
        "identity_verified",
    )

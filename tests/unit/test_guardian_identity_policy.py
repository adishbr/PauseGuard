
import unittest

from safety.guardian_verification.identity_policy import (
    GuardianVerificationResult,
    evaluate_guardian_identity,
)


class TestGuardianIdentityPolicy(unittest.TestCase):

    def test_matching_verified_guardian_is_accepted(self):
        result = evaluate_guardian_identity(
            expected_guardian_id="GUARDIAN-001",
            verified_guardian_id="GUARDIAN-001",
            identity_verified=True,
            verification_method="trusted_backend_verification",
        )

        self.assertTrue(result.verified)
        self.assertEqual(result.reason, "identity_verified")

    def test_mismatched_guardian_is_rejected(self):
        result = evaluate_guardian_identity(
            "GUARDIAN-001",
            "GUARDIAN-002",
            True,
            "trusted_backend_verification",
        )

        self.assertFalse(result.verified)
        self.assertEqual(result.reason, "guardian_id_mismatch")

    def test_unverified_identity_is_rejected(self):
        result = evaluate_guardian_identity(
            "GUARDIAN-001",
            "GUARDIAN-001",
            False,
            "trusted_backend_verification",
        )

        self.assertFalse(result.verified)
        self.assertEqual(result.reason, "identity_not_verified")

    def test_connected_call_alone_is_rejected(self):
        result = evaluate_guardian_identity(
            "GUARDIAN-001",
            "GUARDIAN-001",
            True,
            "call_connected",
        )

        self.assertFalse(result.verified)
        self.assertEqual(
            result.reason,
            "unapproved_verification_method",
        )

    def test_dtmf_alone_is_rejected(self):
        for method in ("dtmf", "dtmf_only"):
            with self.subTest(method=method):
                result = evaluate_guardian_identity(
                    "GUARDIAN-001",
                    "GUARDIAN-001",
                    True,
                    method,
                )

                self.assertFalse(result.verified)
                self.assertEqual(
                    result.reason,
                    "unapproved_verification_method",
                )

    def test_missing_guardian_id_is_rejected(self):
        result = evaluate_guardian_identity(
            "GUARDIAN-001",
            None,
            True,
            "trusted_backend_verification",
        )

        self.assertFalse(result.verified)
        self.assertEqual(
            result.reason,
            "missing_verified_guardian_id",
        )

    def test_empty_expected_id_is_rejected(self):
        result = evaluate_guardian_identity(
            " ",
            "GUARDIAN-001",
            True,
            "trusted_backend_verification",
        )

        self.assertFalse(result.verified)
        self.assertEqual(
            result.reason,
            "invalid_expected_guardian_id",
        )

    def test_empty_verification_method_is_rejected(self):
        result = evaluate_guardian_identity(
            "GUARDIAN-001",
            "GUARDIAN-001",
            True,
            " ",
        )

        self.assertFalse(result.verified)
        self.assertEqual(
            result.reason,
            "missing_verification_method",
        )

    def test_invalid_verification_status_is_rejected(self):
        result = evaluate_guardian_identity(
            "GUARDIAN-001",
            "GUARDIAN-001",
            "true",
            "trusted_backend_verification",
        )

        self.assertFalse(result.verified)
        self.assertEqual(
            result.reason,
            "invalid_verification_status",
        )

    def test_invalid_verification_method_type_is_rejected(self):
        result = evaluate_guardian_identity(
            "GUARDIAN-001",
            "GUARDIAN-001",
            True,
            None,
        )

        self.assertFalse(result.verified)
        self.assertEqual(
            result.reason,
            "invalid_verification_method",
        )

    def test_invalid_expected_id_type_is_rejected(self):
        result = evaluate_guardian_identity(
            None,
            "GUARDIAN-001",
            True,
            "trusted_backend_verification",
        )

        self.assertFalse(result.verified)
        self.assertEqual(
            result.reason,
            "invalid_expected_guardian_id",
        )

    def test_payment_authorization_is_never_granted(self):
        result = evaluate_guardian_identity(
            "GUARDIAN-001",
            "GUARDIAN-001",
            True,
            "trusted_backend_verification",
        )

        self.assertFalse(result.can_authorize_payment)
        self.assertFalse(result.can_execute_payment)

    def test_payment_authorization_is_never_granted_on_failure(self):
        result = evaluate_guardian_identity(
            "GUARDIAN-001",
            "GUARDIAN-002",
            True,
            "trusted_backend_verification",
        )

        self.assertFalse(result.can_authorize_payment)
        self.assertFalse(result.can_execute_payment)

    def test_result_is_immutable(self):
        result = GuardianVerificationResult(
            True,
            "identity_verified",
        )

        with self.assertRaises(AttributeError):
            result.verified = False

    # Phase 7: Additional security tests

    def test_unknown_verification_method_is_rejected(self):
        result = evaluate_guardian_identity(
            "GUARDIAN-001",
            "GUARDIAN-001",
            True,
            "email_claim",
        )

        self.assertFalse(result.verified)
        self.assertEqual(
            result.reason,
            "unapproved_verification_method",
        )

    def test_arbitrary_non_empty_methods_are_rejected(self):
        for method in (
            "sms",
            "email",
            "biometric",
            "admin_override",
        ):
            with self.subTest(method=method):
                result = evaluate_guardian_identity(
                    "GUARDIAN-001",
                    "GUARDIAN-001",
                    True,
                    method,
                )

                self.assertFalse(result.verified)
                self.assertFalse(result.can_authorize_payment)
                self.assertFalse(result.can_execute_payment)

    def test_approved_method_is_case_insensitive(self):
        result = evaluate_guardian_identity(
            "GUARDIAN-001",
            "GUARDIAN-001",
            True,
            "TRUSTED_BACKEND_VERIFICATION",
        )

        self.assertTrue(result.verified)
        self.assertEqual(result.reason, "identity_verified")

    def test_unapproved_method_with_matching_id_is_rejected(self):
        result = evaluate_guardian_identity(
            "GUARDIAN-001",
            "GUARDIAN-001",
            True,
            "unknown_method",
        )

        self.assertFalse(result.verified)
        self.assertEqual(
            result.reason,
            "unapproved_verification_method",
        )


if __name__ == "__main__":
    unittest.main()

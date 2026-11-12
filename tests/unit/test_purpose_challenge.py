
import unittest
from dataclasses import FrozenInstanceError

from safety.purpose_challenge.purpose_challenge import (
    assess_purpose,
    PurposeAssessment,
)


class TestPurposeChallenge(unittest.TestCase):

    def test_normal_purpose(self):
        result = assess_purpose("Payment for groceries")
        self.assertFalse(result.suspicious)

    def test_urgency(self):
        result = assess_purpose("Send the money immediately")
        self.assertIn("urgency", result.reasons)

    def test_secrecy(self):
        result = assess_purpose("Don't tell anyone about this transfer")
        self.assertIn("secrecy", result.reasons)

    def test_authority_impersonation(self):
        result = assess_purpose("The police need this payment")
        self.assertIn("authority_impersonation", result.reasons)

    def test_threat(self):
        result = assess_purpose("Your account will be blocked")
        self.assertIn("threat", result.reasons)

    def test_credential_request(self):
        result = assess_purpose("Share your UPI PIN")
        self.assertIn("credential_request", result.reasons)

    def test_remote_access(self):
        result = assess_purpose("Install AnyDesk for verification")
        self.assertIn("remote_control", result.reasons)

    def test_multiple_indicators(self):
        result = assess_purpose(
            "Urgent! Don't tell anyone. Share your OTP."
        )
        self.assertGreaterEqual(len(result.reasons), 3)

    def test_empty_purpose(self):
        result = assess_purpose("   ")
        self.assertIn("empty_purpose", result.reasons)

    def test_invalid_input(self):
        result = assess_purpose(None)
        self.assertIn("invalid_purpose_type", result.reasons)

    # Additional edge-case and negative tests

    def test_empty_string_is_suspicious(self):
        result = assess_purpose("")
        self.assertTrue(result.suspicious)
        self.assertEqual(result.reasons, ("empty_purpose",))

    def test_non_string_inputs_are_rejected(self):
        for value in (None, 123, 12.5, [], {}, True):
            with self.subTest(value=value):
                result = assess_purpose(value)
                self.assertTrue(result.suspicious)
                self.assertEqual(
                    result.reasons,
                    ("invalid_purpose_type",),
                )

    def test_urgency_detection_is_case_insensitive(self):
        result = assess_purpose("URGENT PAYMENT")
        self.assertIn("urgency", result.reasons)

    def test_secrecy_detection_is_case_insensitive(self):
        result = assess_purpose("KEEP IT SECRET")
        self.assertIn("secrecy", result.reasons)

    def test_multiple_whitespace_characters_are_normalized(self):
        result = assess_purpose("Send money right   now")
        self.assertIn("urgency", result.reasons)

    def test_newlines_and_tabs_are_normalized(self):
        result = assess_purpose("Send money immediately\n\tplease")
        self.assertIn("urgency", result.reasons)

    def test_all_six_coercion_categories_can_be_detected(self):
        result = assess_purpose(
            "Urgent! Don't tell anyone. "
            "Police demand payment or you face arrest. "
            "Share your OTP and install AnyDesk."
        )

        expected = {
            "urgency",
            "secrecy",
            "authority_impersonation",
            "threat",
            "credential_request",
            "remote_control",
        }

        self.assertEqual(set(result.reasons), expected)
        self.assertTrue(result.suspicious)

    def test_unrelated_words_do_not_trigger_substring_matches(self):
        result = assess_purpose(
            "The emergencydepartment is not involved. "
            "Policework is not my payment purpose."
        )
        self.assertFalse(result.suspicious)

    def test_normal_purpose_has_empty_reasons_tuple(self):
        result = assess_purpose("Monthly electricity bill")
        self.assertEqual(result.reasons, ())
        self.assertFalse(result.suspicious)

    def test_assessment_is_immutable(self):
        result = assess_purpose("Payment for groceries")

        with self.assertRaises(FrozenInstanceError):
            result.suspicious = True

    def test_assessment_returns_expected_dataclass(self):
        result = assess_purpose("Payment for groceries")
        self.assertIsInstance(result, PurposeAssessment)
        self.assertIsInstance(result.reasons, tuple)


if __name__ == "__main__":
    unittest.main()

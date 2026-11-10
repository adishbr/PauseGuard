
import unittest

from safety.purpose_challenge.purpose_challenge import assess_purpose


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


if __name__ == "__main__":
    unittest.main()

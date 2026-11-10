import unittest

from safety.guardian_alerts.guardian_alert import (
    build_guardian_alert,
)


class TestGuardianAlert(unittest.TestCase):

    def test_alert_contains_case_reference(self):
        alert = build_guardian_alert("CASE-001")
        self.assertEqual(alert["case_id"], "CASE-001")

    def test_alert_does_not_expose_payment_details(self):
        alert = build_guardian_alert("CASE-002")

        self.assertNotIn("amount", alert)
        self.assertNotIn("recipient", alert)
        self.assertNotIn("upi_id", alert)
        self.assertNotIn("purpose", alert)
        self.assertNotIn("phone_number", alert)

    def test_alert_does_not_request_approval(self):
        alert = build_guardian_alert("CASE-003")
        self.assertFalse(alert["approval_requested"])

    def test_english_locale(self):
        alert = build_guardian_alert("CASE-004", "en")
        self.assertEqual(alert["locale"], "en")

    def test_hindi_locale(self):
        alert = build_guardian_alert("CASE-005", "hi")
        self.assertEqual(alert["locale"], "hi")

    def test_kannada_locale(self):
        alert = build_guardian_alert("CASE-006", "kn")
        self.assertEqual(alert["locale"], "kn")

    def test_unknown_locale_falls_back_to_english(self):
        alert = build_guardian_alert("CASE-007", "fr")
        self.assertEqual(alert["locale"], "en")

    def test_empty_case_id_is_rejected(self):
        with self.assertRaises(ValueError):
            build_guardian_alert("")

    def test_whitespace_case_id_is_rejected(self):
        with self.assertRaises(ValueError):
            build_guardian_alert("CASE 001")

    def test_alert_timestamp_exists(self):
        alert = build_guardian_alert("CASE-008")
        self.assertIn("created_at", alert)


if __name__ == "__main__":
    unittest.main()

import unittest
from datetime import datetime

from safety.guardian_alerts.guardian_alert import (
    build_guardian_alert,
    MESSAGES,
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

    # Additional negative and edge-case tests

    def test_case_id_with_exactly_100_characters_is_accepted(self):
        case_id = "A" * 100
        alert = build_guardian_alert(case_id)
        self.assertEqual(alert["case_id"], case_id)

    def test_case_id_over_100_characters_is_rejected(self):
        with self.assertRaises(ValueError):
            build_guardian_alert("A" * 101)

    def test_whitespace_only_case_id_is_rejected(self):
        with self.assertRaises(ValueError):
            build_guardian_alert("   ")

    def test_non_string_case_id_is_rejected(self):
        for invalid_id in (None, 123, [], {}):
            with self.subTest(case_id=invalid_id):
                with self.assertRaises(ValueError):
                    build_guardian_alert(invalid_id)

    def test_uppercase_english_locale_is_normalized(self):
        alert = build_guardian_alert("CASE-009", "EN")
        self.assertEqual(alert["locale"], "en")
        self.assertEqual(alert["message"], MESSAGES["en"])

    def test_regional_hindi_locale_uses_hindi(self):
        alert = build_guardian_alert("CASE-010", "HI-IN")
        self.assertEqual(alert["locale"], "hi")
        self.assertEqual(alert["message"], MESSAGES["hi"])

    def test_regional_kannada_locale_uses_kannada(self):
        alert = build_guardian_alert("CASE-011", "kn-IN")
        self.assertEqual(alert["locale"], "kn")
        self.assertEqual(alert["message"], MESSAGES["kn"])

    def test_non_string_locale_falls_back_to_english(self):
        for invalid_locale in (None, 123, [], {}):
            with self.subTest(locale=invalid_locale):
                alert = build_guardian_alert(
                    "CASE-012", invalid_locale
                )
                self.assertEqual(alert["locale"], "en")
                self.assertEqual(alert["message"], MESSAGES["en"])

    def test_alert_contains_only_expected_fields(self):
        alert = build_guardian_alert("CASE-013")

        self.assertEqual(
            set(alert.keys()),
            {
                "case_id",
                "message",
                "locale",
                "created_at",
                "contains_payment_details",
                "approval_requested",
            },
        )

    def test_alert_always_marks_payment_details_absent(self):
        for locale in ("en", "hi", "kn", "fr"):
            with self.subTest(locale=locale):
                alert = build_guardian_alert("CASE-014", locale)
                self.assertIs(
                    alert["contains_payment_details"], False
                )

    def test_alert_timestamp_is_valid_iso_format(self):
        alert = build_guardian_alert("CASE-015")

        parsed = datetime.fromisoformat(
            alert["created_at"]
        )

        self.assertIsNotNone(parsed.tzinfo)
        self.assertIsNotNone(parsed.utcoffset())

    def test_message_is_non_empty_for_all_supported_locales(self):
        for locale in ("en", "hi", "kn"):
            with self.subTest(locale=locale):
                alert = build_guardian_alert(
                    "CASE-016", locale
                )
                self.assertTrue(alert["message"].strip())


if __name__ == "__main__":
    unittest.main()

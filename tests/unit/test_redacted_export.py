import unittest

from safety.evidence.redacted_export import (
    export_redacted_evidence,
)


class TestRedactedEvidenceExport(unittest.TestCase):

    def test_allowed_fields_are_exported(self):
        record = {
            "case_id": "CASE-001",
            "event_id": "EVENT-001",
            "event_type": "RISK_WARNING",
            "risk_level": "HIGH",
            "unknown_field": "must not appear",
        }

        result = export_redacted_evidence(record)

        self.assertEqual(result["case_id"], "CASE-001")
        self.assertEqual(result["event_type"], "RISK_WARNING")
        self.assertNotIn("unknown_field", result)

    def test_phone_number_is_redacted(self):
        record = {
            "case_id": "CASE-002",
            "event_type": "REVIEW",
            "risk_indicators": ["Contact 9876543210"],
        }

        result = export_redacted_evidence(record)

        self.assertNotIn("9876543210", str(result))
        self.assertIn("[REDACTED_PHONE]", str(result))

    def test_email_is_redacted(self):
        record = {
            "case_id": "CASE-003",
            "event_type": "REVIEW",
            "risk_indicators": ["Contact user@example.com"],
        }

        result = export_redacted_evidence(record)

        self.assertNotIn("user@example.com", str(result))
        self.assertIn("[REDACTED_EMAIL]", str(result))

    def test_sensitive_fields_are_omitted(self):
        record = {
            "case_id": "CASE-004",
            "event_type": "REVIEW",
            "otp": "123456",
            "upi_pin": "1234",
            "password": "secret",
            "phone_number": "9876543210",
            "recipient_name": "Example Person",
        }

        result = export_redacted_evidence(record)

        for field in (
            "otp",
            "upi_pin",
            "password",
            "phone_number",
            "recipient_name",
        ):
            self.assertNotIn(field, result)

        self.assertNotIn("123456", str(result))
        self.assertNotIn("secret", str(result))

    def test_nested_objects_are_not_exported(self):
        record = {
            "case_id": "CASE-005",
            "event_type": "REVIEW",
            "risk_indicators": [
                "unusual activity",
                {"phone": "9876543210"},
            ],
        }

        result = export_redacted_evidence(record)

        self.assertEqual(
            result["risk_indicators"],
            ["unusual activity"],
        )

    def test_export_has_review_warning(self):
        result = export_redacted_evidence({
            "case_id": "CASE-006",
        })

        self.assertTrue(result["redaction_applied"])
        self.assertTrue(
            result["review_required_before_sharing"]
        )
        self.assertIn("exported_at", result)

    def test_invalid_input_is_rejected(self):
        with self.assertRaises(TypeError):
            export_redacted_evidence("not a dictionary")


if __name__ == "__main__":
    unittest.main()
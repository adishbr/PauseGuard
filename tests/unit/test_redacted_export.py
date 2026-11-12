
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

    # Additional negative and edge-case tests

    def test_all_allowed_fields_can_be_exported(self):
        record = {
            "case_id": "CASE-007",
            "event_id": "EVENT-007",
            "event_type": "REVIEW",
            "timestamp": "2026-01-01T12:00:00Z",
            "risk_level": "HIGH",
            "risk_indicators": ["unusual activity"],
            "policy_version": "v1",
        }

        result = export_redacted_evidence(record)

        for field in (
            "case_id",
            "event_id",
            "event_type",
            "timestamp",
            "risk_level",
            "risk_indicators",
            "policy_version",
        ):
            self.assertIn(field, result)

    def test_all_forbidden_fields_are_omitted(self):
        forbidden_fields = {
            "otp": "123456",
            "pin": "1234",
            "upi_pin": "1234",
            "password": "secret",
            "token": "token-value",
            "access_token": "access-value",
            "refresh_token": "refresh-value",
            "secret": "secret-value",
            "authorization": "Bearer abc",
            "phone": "9876543210",
            "phone_number": "9876543210",
            "email": "user@example.com",
            "upi_id": "user@upi",
            "account_number": "123456789",
            "recipient": "Person",
            "recipient_name": "Person",
            "purpose": "private purpose",
            "full_name": "Example Person",
        }

        result = export_redacted_evidence({
            "case_id": "CASE-008",
            **forbidden_fields,
        })

        for field in forbidden_fields:
            self.assertNotIn(field, result)

    def test_upi_id_is_redacted_in_text(self):
        record = {
            "case_id": "CASE-009",
            "risk_indicators": ["Payment made to user@bank"],
        }

        result = export_redacted_evidence(record)

        self.assertNotIn("user@bank", str(result))
        self.assertIn("[REDACTED_UPI_ID]", str(result))

    def test_list_is_limited_to_twenty_strings(self):
        indicators = [
            f"indicator_{number}"
            for number in range(25)
        ]

        result = export_redacted_evidence({
            "risk_indicators": indicators,
        })

        self.assertEqual(len(result["risk_indicators"]), 20)

    def test_non_string_list_items_are_filtered(self):
        record = {
            "risk_indicators": [
                "valid indicator",
                123,
                None,
                True,
                {"private": "data"},
                ["nested"],
            ],
        }

        result = export_redacted_evidence(record)

        self.assertEqual(
            result["risk_indicators"],
            ["valid indicator"],
        )

    def test_boolean_values_are_preserved(self):
        result = export_redacted_evidence({
            "case_id": "CASE-010",
            "risk_level": False,
        })

        self.assertIs(result["risk_level"], False)

    def test_integer_values_are_preserved(self):
        result = export_redacted_evidence({
            "case_id": "CASE-011",
            "risk_level": 5,
        })

        self.assertEqual(result["risk_level"], 5)

    def test_float_values_are_omitted(self):
        result = export_redacted_evidence({
            "case_id": "CASE-012",
            "risk_level": 4.5,
        })

        self.assertNotIn("risk_level", result)

    def test_dictionary_values_are_omitted(self):
        result = export_redacted_evidence({
            "case_id": "CASE-013",
            "risk_level": {"level": "HIGH"},
        })

        self.assertNotIn("risk_level", result)

    def test_none_values_are_omitted(self):
        result = export_redacted_evidence({
            "case_id": "CASE-014",
            "event_id": None,
        })

        self.assertNotIn("event_id", result)

    def test_empty_string_is_preserved(self):
        result = export_redacted_evidence({
            "case_id": "",
        })

        self.assertIn("case_id", result)
        self.assertEqual(result["case_id"], "")

    def test_redaction_flags_are_always_true(self):
        result = export_redacted_evidence({})

        self.assertIs(result["redaction_applied"], True)
        self.assertIs(
            result["review_required_before_sharing"],
            True,
        )

    def test_export_does_not_modify_original_record(self):
        record = {
            "case_id": "CASE-015",
            "risk_indicators": ["Contact user@example.com"],
            "password": "secret",
        }

        original = {
            "case_id": "CASE-015",
            "risk_indicators": ["Contact user@example.com"],
            "password": "secret",
        }

        export_redacted_evidence(record)

        self.assertEqual(record, original)


if __name__ == "__main__":
    unittest.main()

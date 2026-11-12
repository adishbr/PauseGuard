
import unittest
from dataclasses import replace

from safety.audit.audit_chain import AuditChain, GENESIS_HASH


class TestAuditChain(unittest.TestCase):

    def test_empty_chain_is_valid(self):
        chain = AuditChain()
        self.assertTrue(chain.verify())

    def test_single_record_is_valid(self):
        chain = AuditChain()
        chain.append("PAYMENT_CREATED", {"amount_paise": 5000})
        self.assertTrue(chain.verify())

    def test_multiple_records_are_valid(self):
        chain = AuditChain()
        chain.append("PAYMENT_CREATED", {"amount_paise": 5000})
        chain.append("WARNING_SHOWN", {"risk_level": "high"})
        chain.append("PAYMENT_CANCELLED", {"reason": "user_cancelled"})
        self.assertTrue(chain.verify())

    def test_modified_data_is_detected(self):
        chain = AuditChain()
        chain.append("PAYMENT_CREATED", {"amount_paise": 5000})

        chain.records[0] = replace(
            chain.records[0],
            data={"amount_paise": 9000},
        )

        self.assertFalse(chain.verify())

    def test_deleted_record_is_detected(self):
        chain = AuditChain()
        chain.append("EVENT_ONE", {"value": 1})
        chain.append("EVENT_TWO", {"value": 2})
        chain.append("EVENT_THREE", {"value": 3})

        del chain.records[1]

        self.assertFalse(chain.verify())

    def test_reordered_records_are_detected(self):
        chain = AuditChain()
        chain.append("EVENT_ONE", {"value": 1})
        chain.append("EVENT_TWO", {"value": 2})

        chain.records.reverse()

        self.assertFalse(chain.verify())

    def test_modified_hash_is_detected(self):
        chain = AuditChain()
        chain.append("PAYMENT_CREATED", {"amount_paise": 5000})

        chain.records[0] = replace(
            chain.records[0],
            record_hash="invalid_hash",
        )

        self.assertFalse(chain.verify())

    def test_empty_event_type_is_rejected(self):
        chain = AuditChain()

        with self.assertRaises(ValueError):
            chain.append("", {"value": 1})

    def test_non_dictionary_data_is_rejected(self):
        chain = AuditChain()

        with self.assertRaises(ValueError):
            chain.append("TEST_EVENT", ["not", "a", "dictionary"])

    def test_non_json_data_is_rejected(self):
        chain = AuditChain()

        with self.assertRaises(ValueError):
            chain.append("TEST_EVENT", {"invalid": object()})

    # Additional audit integrity tests

    def test_record_sequences_increment(self):
        chain = AuditChain()

        first = chain.append("EVENT_ONE", {"value": 1})
        second = chain.append("EVENT_TWO", {"value": 2})
        third = chain.append("EVENT_THREE", {"value": 3})

        self.assertEqual(first.sequence, 1)
        self.assertEqual(second.sequence, 2)
        self.assertEqual(third.sequence, 3)

    def test_first_record_uses_genesis_hash(self):
        chain = AuditChain()

        record = chain.append("EVENT_ONE", {"value": 1})

        self.assertEqual(record.previous_hash, GENESIS_HASH)

    def test_records_link_to_previous_hash(self):
        chain = AuditChain()

        first = chain.append("EVENT_ONE", {"value": 1})
        second = chain.append("EVENT_TWO", {"value": 2})

        self.assertEqual(second.previous_hash, first.record_hash)

    def test_append_returns_audit_record(self):
        chain = AuditChain()

        record = chain.append("EVENT_ONE", {"value": 1})

        self.assertEqual(record.event_type, "EVENT_ONE")
        self.assertEqual(record.data, {"value": 1})
        self.assertEqual(len(record.record_hash), 64)

    def test_modified_timestamp_is_detected(self):
        chain = AuditChain()
        chain.append("EVENT_ONE", {"value": 1})

        chain.records[0] = replace(
            chain.records[0],
            timestamp="modified_timestamp",
        )

        self.assertFalse(chain.verify())

    def test_modified_event_type_is_detected(self):
        chain = AuditChain()
        chain.append("EVENT_ONE", {"value": 1})

        chain.records[0] = replace(
            chain.records[0],
            event_type="EVENT_MODIFIED",
        )

        self.assertFalse(chain.verify())

    def test_modified_previous_hash_is_detected(self):
        chain = AuditChain()
        chain.append("EVENT_ONE", {"value": 1})
        chain.append("EVENT_TWO", {"value": 2})

        chain.records[1] = replace(
            chain.records[1],
            previous_hash="invalid_previous_hash",
        )

        self.assertFalse(chain.verify())

    def test_modified_sequence_is_detected(self):
        chain = AuditChain()
        chain.append("EVENT_ONE", {"value": 1})

        chain.records[0] = replace(
            chain.records[0],
            sequence=5,
        )

        self.assertFalse(chain.verify())

    def test_nested_data_modification_is_detected(self):
        chain = AuditChain()

        chain.append(
            "EVENT_ONE",
            {"details": {"risk": "high", "amount": 5000}},
        )

        chain.records[0].data["details"]["amount"] = 9000

        self.assertFalse(chain.verify())

    def test_nan_value_is_rejected(self):
        chain = AuditChain()

        with self.assertRaises(ValueError):
            chain.append("TEST_EVENT", {"value": float("nan")})

    def test_infinity_value_is_rejected(self):
        chain = AuditChain()

        with self.assertRaises(ValueError):
            chain.append("TEST_EVENT", {"value": float("inf")})

    def test_unicode_data_is_valid(self):
        chain = AuditChain()

        chain.append(
            "GUARDIAN_ALERT",
            {"message": "सुरक्षा सूचना", "locale": "kn"},
        )

        self.assertTrue(chain.verify())


if __name__ == "__main__":
    unittest.main()

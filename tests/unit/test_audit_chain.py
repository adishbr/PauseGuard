
import unittest
from dataclasses import replace

from safety.audit.audit_chain import AuditChain


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


if __name__ == "__main__":
    unittest.main()

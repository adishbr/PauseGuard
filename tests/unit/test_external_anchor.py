"""Tests for local external audit-anchor preparation and verification."""

import unittest
from dataclasses import replace

from safety.audit.audit_chain import AuditChain
from safety.audit.external_anchor import (
    AuditAnchor,
    create_anchor,
    verify_anchor,
)


class TestExternalAnchor(unittest.TestCase):

    def setUp(self):
        self.chain = AuditChain()
        self.chain.append("PAYMENT_CREATED", {"amount_paise": 5000})

    def test_create_anchor_from_valid_chain(self):
        anchor = create_anchor(self.chain)

        self.assertEqual(anchor.sequence, 1)
        self.assertEqual(anchor.head_hash, self.chain.records[-1].record_hash)
        self.assertTrue(anchor.created_at)

    def test_empty_chain_cannot_be_anchored(self):
        with self.assertRaises(ValueError):
            create_anchor(AuditChain())

    def test_invalid_chain_cannot_be_anchored(self):
        self.chain.records[0] = replace(
            self.chain.records[0],
            record_hash="invalid",
        )

        with self.assertRaises(ValueError):
            create_anchor(self.chain)

    def test_valid_anchor_verifies(self):
        anchor = create_anchor(self.chain)

        result = verify_anchor(anchor, self.chain)

        self.assertTrue(result.valid)
        self.assertEqual(result.reason, "checkpoint_matches")

    def test_anchor_remains_valid_after_new_records(self):
        anchor = create_anchor(self.chain)
        self.chain.append("WARNING_SHOWN", {"risk_level": "high"})

        result = verify_anchor(anchor, self.chain)

        self.assertTrue(result.valid)

    def test_anchor_hash_mismatch_is_rejected(self):
        anchor = create_anchor(self.chain)
        altered = replace(anchor, head_hash="a" * 64)

        result = verify_anchor(altered, self.chain)

        self.assertFalse(result.valid)
        self.assertEqual(result.reason, "anchor_hash_mismatch")

    def test_anchor_with_future_sequence_is_rejected(self):
        anchor = create_anchor(self.chain)
        altered = replace(anchor, sequence=99)

        result = verify_anchor(altered, self.chain)

        self.assertFalse(result.valid)
        self.assertEqual(result.reason, "anchor_sequence_not_found")

    def test_invalid_anchor_type_is_rejected(self):
        result = verify_anchor({}, self.chain)

        self.assertFalse(result.valid)
        self.assertEqual(result.reason, "invalid_anchor_type")

    def test_invalid_chain_is_rejected(self):
        self.chain.records[0] = replace(
            self.chain.records[0],
            data={"amount_paise": 9000},
        )
        anchor = AuditAnchor(
            sequence=1,
            head_hash="a" * 64,
            created_at="2026-11-12T10:00:00+00:00",
        )

        result = verify_anchor(anchor, self.chain)

        self.assertFalse(result.valid)
        self.assertEqual(result.reason, "invalid_local_chain")

    def test_malformed_hash_is_rejected(self):
        anchor = create_anchor(self.chain)
        altered = replace(anchor, head_hash="not-a-hash")

        result = verify_anchor(altered, self.chain)

        self.assertFalse(result.valid)
        self.assertEqual(result.reason, "invalid_anchor_hash")

    def test_naive_timestamp_is_rejected(self):
        anchor = create_anchor(self.chain)
        altered = replace(anchor, created_at="2026-11-12T10:00:00")

        result = verify_anchor(altered, self.chain)

        self.assertFalse(result.valid)
        self.assertEqual(result.reason, "naive_anchor_timestamp")

    def test_invalid_timestamp_is_rejected(self):
        anchor = create_anchor(self.chain)
        altered = replace(anchor, created_at="not-a-timestamp")

        result = verify_anchor(altered, self.chain)

        self.assertFalse(result.valid)
        self.assertEqual(result.reason, "invalid_anchor_timestamp")


if __name__ == "__main__":
    unittest.main()
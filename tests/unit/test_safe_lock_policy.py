
import unittest

from safety.safe_lock.safe_lock_policy import assess_safe_lock


class TestSafeLockPolicy(unittest.TestCase):

    def test_disabled_safe_lock_does_not_restrict(self):
        result = assess_safe_lock(False, 5000, 10000)
        self.assertFalse(result.restricted)

    def test_amount_within_limit(self):
        result = assess_safe_lock(True, 5000, 10000)
        self.assertFalse(result.restricted)

    def test_amount_above_limit(self):
        result = assess_safe_lock(True, 15000, 10000)
        self.assertTrue(result.restricted)
        self.assertIn(
            "amount_exceeds_safe_lock_limit", result.reasons
        )

    def test_allowed_category(self):
        result = assess_safe_lock(
            True, 5000, 10000,
            {"groceries", "utilities"},
            "groceries",
        )
        self.assertFalse(result.restricted)

    def test_disallowed_category(self):
        result = assess_safe_lock(
            True, 5000, 10000,
            {"groceries", "utilities"},
            "electronics",
        )
        self.assertTrue(result.restricted)
        self.assertIn(
            "payment_category_not_allowed", result.reasons
        )

    def test_missing_category(self):
        result = assess_safe_lock(
            True, 5000, 10000,
            {"groceries"},
        )
        self.assertIn("payment_category_missing", result.reasons)

    def test_invalid_amount(self):
        with self.assertRaises(ValueError):
            assess_safe_lock(True, -100, 10000)

    def test_boolean_amount_rejected(self):
        with self.assertRaises(ValueError):
            assess_safe_lock(True, True, 10000)


if __name__ == "__main__":
    unittest.main()

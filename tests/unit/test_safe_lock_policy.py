
import unittest
from dataclasses import FrozenInstanceError

from safety.safe_lock.safe_lock_policy import (
    assess_safe_lock,
    SafeLockAssessment,
)


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

    # Additional edge-case and negative tests

    def test_amount_exactly_at_limit_is_allowed(self):
        result = assess_safe_lock(True, 10000, 10000)
        self.assertFalse(result.restricted)
        self.assertEqual(result.reasons, ())

    def test_one_paise_above_limit_is_restricted(self):
        result = assess_safe_lock(True, 10001, 10000)
        self.assertTrue(result.restricted)
        self.assertIn(
            "amount_exceeds_safe_lock_limit", result.reasons
        )

    def test_zero_amount_is_rejected(self):
        with self.assertRaises(ValueError):
            assess_safe_lock(True, 0, 10000)

    def test_float_amount_is_rejected(self):
        with self.assertRaises(ValueError):
            assess_safe_lock(True, 5000.0, 10000)

    def test_string_amount_is_rejected(self):
        with self.assertRaises(ValueError):
            assess_safe_lock(True, "5000", 10000)

    def test_zero_maximum_amount_is_rejected(self):
        with self.assertRaises(ValueError):
            assess_safe_lock(True, 5000, 0)

    def test_negative_maximum_amount_is_rejected(self):
        with self.assertRaises(ValueError):
            assess_safe_lock(True, 5000, -100)

    def test_boolean_maximum_amount_is_rejected(self):
        with self.assertRaises(ValueError):
            assess_safe_lock(True, 5000, True)

    def test_non_integer_maximum_amount_is_rejected(self):
        with self.assertRaises(ValueError):
            assess_safe_lock(True, 5000, 10000.5)

    def test_non_boolean_safe_lock_flag_is_rejected(self):
        for value in (None, 0, 1, "true"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    assess_safe_lock(value, 5000, 10000)

    def test_amount_and_category_violations_are_both_reported(self):
        result = assess_safe_lock(
            True,
            15000,
            10000,
            {"groceries"},
            "electronics",
        )

        self.assertTrue(result.restricted)
        self.assertIn(
            "amount_exceeds_safe_lock_limit", result.reasons
        )
        self.assertIn(
            "payment_category_not_allowed", result.reasons
        )

    def test_disabled_safe_lock_skips_category_restrictions(self):
        result = assess_safe_lock(
            False,
            5000,
            10000,
            {"groceries"},
            "electronics",
        )

        self.assertFalse(result.restricted)
        self.assertEqual(result.reasons, ())


if __name__ == "__main__":
    unittest.main()

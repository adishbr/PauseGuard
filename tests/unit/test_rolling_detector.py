
import unittest
from datetime import datetime, timedelta, timezone

from safety.anti_smurfing.rolling_detector import (
    RollingSmurfingDetector,
)


class TestRollingSmurfingDetector(unittest.TestCase):

    def setUp(self):
        self.detector = RollingSmurfingDetector(
            window_seconds=600,
            minimum_attempts=3,
            amount_threshold_paise=100_000,
        )
        self.now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)

    def test_three_attempts_trigger_repeated_attempt_indicator(self):
        self.detector.record_attempt("user1", "a1", 20_000, self.now)
        self.detector.record_attempt("user1", "a2", 20_000, self.now)
        result = self.detector.record_attempt(
            "user1", "a3", 20_000, self.now
        )

        self.assertTrue(result.suspicious)
        self.assertIn(
            "repeated_attempts_in_rolling_window", result.reasons
        )
        self.assertEqual(result.attempt_count, 3)

    def test_cumulative_amount_threshold(self):
        self.detector.record_attempt("user1", "a1", 40_000, self.now)
        self.detector.record_attempt("user1", "a2", 40_000, self.now)
        result = self.detector.record_attempt(
            "user1", "a3", 30_000, self.now
        )

        self.assertIn(
            "cumulative_amount_threshold_reached", result.reasons
        )
        self.assertEqual(result.total_amount_paise, 110_000)

    def test_duplicate_attempt_is_not_counted_twice(self):
        self.detector.record_attempt("user1", "a1", 40_000, self.now)
        self.detector.record_attempt("user1", "a2", 30_000, self.now)

        result = self.detector.record_attempt(
            "user1", "a2", 30_000, self.now
        )

        self.assertEqual(result.attempt_count, 2)
        self.assertEqual(result.total_amount_paise, 70_000)

    def test_old_attempt_expires_from_window(self):
        self.detector.record_attempt("user1", "a1", 20_000, self.now)

        later = self.now + timedelta(seconds=601)
        result = self.detector.record_attempt(
            "user1", "a2", 20_000, later
        )

        self.assertEqual(result.attempt_count, 1)
        self.assertFalse(result.suspicious)

    def test_subjects_are_isolated(self):
        self.detector.record_attempt("user1", "a1", 20_000, self.now)
        result = self.detector.record_attempt(
            "user2", "a2", 20_000, self.now
        )

        self.assertEqual(result.attempt_count, 1)

    def test_zero_amount_is_rejected(self):
        with self.assertRaises(ValueError):
            self.detector.record_attempt("user1", "a1", 0, self.now)

    def test_naive_timestamp_is_rejected(self):
        with self.assertRaises(ValueError):
            self.detector.record_attempt(
                "user1",
                "a1",
                20_000,
                datetime(2026, 1, 1, 12, 0),
            )

    # Additional negative and edge-case tests

    def test_empty_subject_id_is_rejected(self):
        with self.assertRaises(ValueError):
            self.detector.record_attempt("", "a1", 20_000, self.now)

    def test_whitespace_subject_id_is_rejected(self):
        with self.assertRaises(ValueError):
            self.detector.record_attempt("   ", "a1", 20_000, self.now)

    def test_empty_attempt_id_is_rejected(self):
        with self.assertRaises(ValueError):
            self.detector.record_attempt("user1", "", 20_000, self.now)

    def test_whitespace_attempt_id_is_rejected(self):
        with self.assertRaises(ValueError):
            self.detector.record_attempt("user1", "   ", 20_000, self.now)

    def test_boolean_amount_is_rejected(self):
        with self.assertRaises(ValueError):
            self.detector.record_attempt("user1", "a1", True, self.now)

    def test_float_amount_is_rejected(self):
        with self.assertRaises(ValueError):
            self.detector.record_attempt("user1", "a1", 100.5, self.now)

    def test_string_amount_is_rejected(self):
        with self.assertRaises(ValueError):
            self.detector.record_attempt("user1", "a1", "1000", self.now)

    def test_negative_amount_is_rejected(self):
        with self.assertRaises(ValueError):
            self.detector.record_attempt("user1", "a1", -100, self.now)

    def test_attempt_exactly_at_window_boundary_is_retained(self):
        self.detector.record_attempt("user1", "a1", 20_000, self.now)

        boundary = self.now + timedelta(seconds=600)
        result = self.detector.record_attempt(
            "user1", "a2", 20_000, boundary
        )

        self.assertEqual(result.attempt_count, 2)
        self.assertEqual(result.total_amount_paise, 40_000)

    def test_future_attempt_is_not_counted_in_current_assessment(self):
        later = self.now + timedelta(seconds=100)

        self.detector.record_attempt("user1", "a1", 20_000, later)
        result = self.detector.record_attempt(
            "user1", "a2", 20_000, self.now
        )

        self.assertEqual(result.attempt_count, 1)
        self.assertEqual(result.total_amount_paise, 20_000)
        self.assertFalse(result.suspicious)

    def test_expired_attempt_id_can_be_recorded_again(self):
        self.detector.record_attempt("user1", "a1", 20_000, self.now)

        later = self.now + timedelta(seconds=601)
        self.detector.record_attempt("user1", "a2", 20_000, later)

        result = self.detector.record_attempt(
            "user1", "a1", 30_000, later
        )

        self.assertEqual(result.attempt_count, 2)
        self.assertEqual(result.total_amount_paise, 50_000)

    def test_missing_timestamp_uses_current_utc_time(self):
        result = self.detector.record_attempt(
            "user1", "a1", 20_000
        )

        self.assertEqual(result.attempt_count, 1)
        self.assertEqual(result.total_amount_paise, 20_000)
        self.assertFalse(result.suspicious)


if __name__ == "__main__":
    unittest.main()

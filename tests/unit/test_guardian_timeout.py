import unittest
from datetime import datetime, timedelta, timezone

from safety.guardian_timeout.timeout_policy import (
    evaluate_guardian_timeout,
)


class TestGuardianTimeout(unittest.TestCase):

    def setUp(self):
        self.started = datetime(
            2026, 11, 9, 12, 0, 0, tzinfo=timezone.utc
        )

    def test_before_30_seconds_is_not_expired(self):
        result = evaluate_guardian_timeout(
            self.started,
            self.started + timedelta(seconds=29),
        )
        self.assertFalse(result["expired"])

    def test_exactly_30_seconds_is_expired(self):
        result = evaluate_guardian_timeout(
            self.started,
            self.started + timedelta(seconds=30),
        )
        self.assertTrue(result["expired"])

    def test_after_30_seconds_is_expired(self):
        result = evaluate_guardian_timeout(
            self.started,
            self.started + timedelta(seconds=45),
        )
        self.assertTrue(result["expired"])

    def test_timeout_recommends_fallback_review(self):
        result = evaluate_guardian_timeout(
            self.started,
            self.started + timedelta(seconds=30),
        )
        self.assertEqual(
            result["recommended_action"],
            "AWAITING_FALLBACK_REVIEW",
        )

    def test_timeout_never_authorizes_payment(self):
        result = evaluate_guardian_timeout(
            self.started,
            self.started + timedelta(seconds=60),
        )
        self.assertFalse(result["can_authorize_payment"])

    def test_timeout_never_executes_payment(self):
        result = evaluate_guardian_timeout(
            self.started,
            self.started + timedelta(seconds=60),
        )
        self.assertFalse(result["can_execute_payment"])

    def test_naive_timestamp_is_rejected(self):
        with self.assertRaises(ValueError):
            evaluate_guardian_timeout(
                datetime(2026, 11, 9, 12, 0),
                datetime(2026, 11, 9, 12, 1),
            )

    def test_time_before_start_is_rejected(self):
        with self.assertRaises(ValueError):
            evaluate_guardian_timeout(
                self.started,
                self.started - timedelta(seconds=1),
            )


if __name__ == "__main__":
    unittest.main()
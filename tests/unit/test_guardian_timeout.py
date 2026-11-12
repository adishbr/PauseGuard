
import unittest
from datetime import datetime, timedelta, timezone

from safety.guardian_timeout.timeout_policy import (
    evaluate_guardian_timeout,
    GUARDIAN_TIMEOUT_SECONDS,
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

    # Additional edge-case and negative tests

    def test_non_datetime_started_at_is_rejected(self):
        with self.assertRaises(TypeError):
            evaluate_guardian_timeout(
                "2026-11-09T12:00:00Z",
                self.started,
            )

    def test_non_datetime_checked_at_is_rejected(self):
        with self.assertRaises(TypeError):
            evaluate_guardian_timeout(
                self.started,
                "2026-11-09T12:00:30Z",
            )

    def test_none_started_at_is_rejected(self):
        with self.assertRaises(TypeError):
            evaluate_guardian_timeout(None, self.started)

    def test_none_checked_at_is_rejected(self):
        with self.assertRaises(TypeError):
            evaluate_guardian_timeout(self.started, None)

    def test_naive_started_at_with_aware_checked_at_is_rejected(self):
        with self.assertRaises(ValueError):
            evaluate_guardian_timeout(
                datetime(2026, 11, 9, 12, 0),
                self.started,
            )

    def test_aware_started_at_with_naive_checked_at_is_rejected(self):
        with self.assertRaises(ValueError):
            evaluate_guardian_timeout(
                self.started,
                datetime(2026, 11, 9, 12, 0, 30),
            )

    def test_zero_elapsed_time_is_not_expired(self):
        result = evaluate_guardian_timeout(
            self.started,
            self.started,
        )
        self.assertFalse(result["expired"])
        self.assertEqual(
            result["recommended_action"],
            "AWAITING_GUARDIAN",
        )

    def test_fractional_time_before_deadline_is_not_expired(self):
        result = evaluate_guardian_timeout(
            self.started,
            self.started + timedelta(seconds=29, milliseconds=999),
        )
        self.assertFalse(result["expired"])

    def test_one_microsecond_after_deadline_is_expired(self):
        result = evaluate_guardian_timeout(
            self.started,
            self.started + timedelta(seconds=30, microseconds=1),
        )
        self.assertTrue(result["expired"])

    def test_before_deadline_recommends_awaiting_guardian(self):
        result = evaluate_guardian_timeout(
            self.started,
            self.started + timedelta(seconds=10),
        )
        self.assertEqual(
            result["recommended_action"],
            "AWAITING_GUARDIAN",
        )

    def test_payment_permissions_are_false_before_timeout(self):
        result = evaluate_guardian_timeout(
            self.started,
            self.started + timedelta(seconds=10),
        )
        self.assertIs(result["can_authorize_payment"], False)
        self.assertIs(result["can_execute_payment"], False)

    def test_timeout_result_contains_only_expected_fields(self):
        result = evaluate_guardian_timeout(
            self.started,
            self.started + timedelta(seconds=30),
        )
        self.assertEqual(
            set(result.keys()),
            {
                "expired",
                "recommended_action",
                "can_authorize_payment",
                "can_execute_payment",
            },
        )

    def test_timeout_constant_is_30_seconds(self):
        self.assertEqual(GUARDIAN_TIMEOUT_SECONDS, 30)

    def test_different_timezones_compare_correctly(self):
        # 12:00 UTC and 13:00 at UTC+1 represent the same instant.
        checked = datetime(
            2026, 11, 9, 13, 0, 30,
            tzinfo=timezone(timedelta(hours=1)),
        )
        result = evaluate_guardian_timeout(self.started, checked)
        self.assertTrue(result["expired"])


if __name__ == "__main__":
    unittest.main()

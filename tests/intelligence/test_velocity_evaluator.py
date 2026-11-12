"""Unit tests for Velocity Evaluator.

Verifies:
- Unavailable status when context is None.
- Measurement capture with valid context.
- Structuring classification logic.
- Rejection of booleans for integer measurement and threshold fields.
- Lookback window bounds (1 to 1440 minutes).
- Non-negative measurement constraints.
"""

import unittest

from intelligence.advisory.velocity_evaluator import evaluate_velocity
from intelligence.advisory.types import VelocityContext
from intelligence.schemas.risk_signals import (
    CalculationMethod,
    DataOrigin,
    VelocitySignal,
)


class TestVelocityEvaluator(unittest.TestCase):

    def test_velocity_unavailable_when_context_none(self):
        """Verify unavailable status when no velocity context provided."""
        result = evaluate_velocity(None)

        self.assertEqual(result.signal.status, "unavailable")
        self.assertIsNone(result.signal.rolling_window_minutes)
        self.assertIsNone(result.signal.attempts_in_window)
        self.assertIsNone(result.signal.total_amount_paise_in_window)
        self.assertIsNone(result.signal.structuring_suspected)
        self.assertEqual(result.signal.provenance.data_origin, DataOrigin.UNAVAILABLE)
        self.assertEqual(result.signal.provenance.calculation_method, CalculationMethod.UNPERFORMED)
        self.assertGreaterEqual(result.elapsed_ms, 0)

    def test_velocity_evaluated_with_measurements(self):
        """Verify evaluated status with valid measurements."""
        ctx = VelocityContext(
            rolling_window_minutes=60,
            attempts_in_window=3,
            total_amount_paise_in_window=1500000,
        )
        result = evaluate_velocity(ctx)

        self.assertEqual(result.signal.status, "evaluated")
        self.assertEqual(result.signal.rolling_window_minutes, 60)
        self.assertEqual(result.signal.attempts_in_window, 3)
        self.assertEqual(result.signal.total_amount_paise_in_window, 1500000)
        self.assertIsNone(result.signal.structuring_suspected)
        self.assertEqual(result.signal.provenance.data_origin, DataOrigin.MOCK_LEDGER_HISTORY)
        self.assertEqual(result.signal.provenance.calculation_method, CalculationMethod.HEURISTIC_RULE_ENGINE)

    def test_velocity_structuring_suspected_true_when_thresholds_met(self):
        """Verify structuring_suspected=True when both thresholds exceeded."""
        ctx = VelocityContext(
            rolling_window_minutes=60,
            attempts_in_window=5,
            total_amount_paise_in_window=5000000,
            structuring_threshold_attempts=4,
            structuring_threshold_amount_paise=4000000,
        )
        result = evaluate_velocity(ctx)

        self.assertTrue(result.signal.structuring_suspected)

    def test_velocity_structuring_suspected_false_when_thresholds_not_met(self):
        """Verify structuring_suspected=False when thresholds not met."""
        ctx = VelocityContext(
            rolling_window_minutes=60,
            attempts_in_window=2,
            total_amount_paise_in_window=1000000,
            structuring_threshold_attempts=4,
            structuring_threshold_amount_paise=4000000,
        )
        result = evaluate_velocity(ctx)

        self.assertFalse(result.signal.structuring_suspected)

    def test_velocity_structuring_suspected_none_when_thresholds_partial(self):
        """Verify structuring_suspected=None when only one threshold provided."""
        ctx = VelocityContext(
            rolling_window_minutes=60,
            attempts_in_window=5,
            total_amount_paise_in_window=5000000,
            structuring_threshold_attempts=4,
        )
        result = evaluate_velocity(ctx)

        self.assertIsNone(result.signal.structuring_suspected)

    def test_velocity_invalid_window_rejected(self):
        """Verify invalid rolling window raises ValueError."""
        with self.assertRaises(ValueError):
            VelocityContext(
                rolling_window_minutes=0,
                attempts_in_window=3,
                total_amount_paise_in_window=1500000,
            )
        with self.assertRaises(ValueError):
            VelocityContext(
                rolling_window_minutes=1441,
                attempts_in_window=3,
                total_amount_paise_in_window=1500000,
            )

    def test_velocity_negative_attempts_rejected(self):
        """Verify negative attempts raises ValueError."""
        with self.assertRaises(ValueError):
            VelocityContext(
                rolling_window_minutes=60,
                attempts_in_window=-1,
                total_amount_paise_in_window=1500000,
            )

    def test_velocity_negative_amount_rejected(self):
        """Verify negative total amount raises ValueError."""
        with self.assertRaises(ValueError):
            VelocityContext(
                rolling_window_minutes=60,
                attempts_in_window=3,
                total_amount_paise_in_window=-100,
            )

    def test_velocity_invalid_threshold_attempts_rejected(self):
        """Verify invalid structuring threshold attempts raises ValueError."""
        with self.assertRaises(ValueError):
            VelocityContext(
                rolling_window_minutes=60,
                attempts_in_window=3,
                total_amount_paise_in_window=1500000,
                structuring_threshold_attempts=0,
            )

    def test_velocity_invalid_threshold_amount_rejected(self):
        """Verify invalid structuring threshold amount raises ValueError."""
        with self.assertRaises(ValueError):
            VelocityContext(
                rolling_window_minutes=60,
                attempts_in_window=3,
                total_amount_paise_in_window=1500000,
                structuring_threshold_amount_paise=-1,
            )

    # -------------------------------------------------------------------------
    # Boolean Rejection Tests for Strict Integer Fields
    # -------------------------------------------------------------------------

    def test_velocity_rejects_boolean_rolling_window(self):
        """Verify boolean rolling_window_minutes is rejected."""
        with self.assertRaises(ValueError):
            VelocityContext(
                rolling_window_minutes=True,
                attempts_in_window=3,
                total_amount_paise_in_window=1500000,
            )

    def test_velocity_rejects_boolean_attempts(self):
        """Verify boolean attempts_in_window is rejected."""
        with self.assertRaises(ValueError):
            VelocityContext(
                rolling_window_minutes=60,
                attempts_in_window=True,
                total_amount_paise_in_window=1500000,
            )

    def test_velocity_rejects_boolean_amount(self):
        """Verify boolean total_amount_paise_in_window is rejected."""
        with self.assertRaises(ValueError):
            VelocityContext(
                rolling_window_minutes=60,
                attempts_in_window=3,
                total_amount_paise_in_window=True,
            )

    def test_velocity_rejects_boolean_threshold_attempts(self):
        """Verify boolean structuring_threshold_attempts is rejected."""
        with self.assertRaises(ValueError):
            VelocityContext(
                rolling_window_minutes=60,
                attempts_in_window=3,
                total_amount_paise_in_window=1500000,
                structuring_threshold_attempts=True,
            )

    def test_velocity_rejects_boolean_threshold_amount(self):
        """Verify boolean structuring_threshold_amount_paise is rejected."""
        with self.assertRaises(ValueError):
            VelocityContext(
                rolling_window_minutes=60,
                attempts_in_window=3,
                total_amount_paise_in_window=1500000,
                structuring_threshold_amount_paise=True,
            )


if __name__ == "__main__":
    unittest.main()

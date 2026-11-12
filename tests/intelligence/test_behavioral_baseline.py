"""Unit tests for PauseGuard Behavioral Baseline Evaluator.

Tests profile-aware deviation calculation, cold-start honesty, and schema validation.
"""

import unittest

from intelligence.behavioral.baseline_evaluator import (
    PayerHistoryProfile,
    evaluate_behavioral_baseline,
)
from intelligence.schemas.risk_signals import (
    AccountProfileType,
    CalculationMethod,
    DataOrigin,
    SourceCategory,
)


class TestBehavioralBaselineEvaluator(unittest.TestCase):

    def test_routine_personal_payment(self):
        """Verify everyday personal payment yields low deviation and familiar status."""
        history = PayerHistoryProfile(
            payer_id="usr_pers_01",
            profile_type=AccountProfileType.PERSONAL,
            settled_amounts_paise=(20000, 30000, 35000, 40000, 50000),  # median = 35000
            beneficiary_history={"ben_grocer": 12},
        )
        signal = evaluate_behavioral_baseline(history, "ben_grocer", 25000)

        self.assertEqual(signal.status, "evaluated")
        self.assertEqual(signal.profile_type, AccountProfileType.PERSONAL)
        self.assertEqual(signal.baseline_median_paise, 35000)
        self.assertAlmostEqual(signal.deviation_multiple, 0.71, places=2)
        self.assertFalse(signal.is_new_beneficiary)
        self.assertEqual(signal.prior_transfers_count, 12)
        self.assertEqual(signal.provenance.data_origin, DataOrigin.MOCK_LEDGER_HISTORY)

    def test_high_deviation_personal_payment(self):
        """Verify large personal transfer to new payee reports high deviation."""
        history = PayerHistoryProfile(
            payer_id="usr_pers_02",
            profile_type=AccountProfileType.PERSONAL,
            settled_amounts_paise=(80000, 100000, 120000),  # median = 100000 (₹1,000)
            beneficiary_history={"ben_family": 5},
        )
        # ₹55,000 = 5,500,000 paise -> 55x deviation
        signal = evaluate_behavioral_baseline(history, "ben_new_scammer", 5500000)

        self.assertEqual(signal.status, "evaluated")
        self.assertEqual(signal.baseline_median_paise, 100000)
        self.assertEqual(signal.deviation_multiple, 55.0)
        self.assertTrue(signal.is_new_beneficiary)
        self.assertEqual(signal.prior_transfers_count, 0)

    def test_business_payment_within_baseline(self):
        """Verify commercial payment to new supplier is NOT flagged as high deviation."""
        history = PayerHistoryProfile(
            payer_id="usr_biz_01",
            profile_type=AccountProfileType.SMALL_BUSINESS,
            settled_amounts_paise=(5000000, 6500000, 8000000),  # median = 6,500,000 paise (₹65,000)
            beneficiary_history={"ben_old_vendor": 8},
        )
        # ₹50,000 to a new supplier
        signal = evaluate_behavioral_baseline(history, "ben_new_vendor", 5000000)

        self.assertEqual(signal.status, "evaluated")
        self.assertEqual(signal.profile_type, AccountProfileType.SMALL_BUSINESS)
        self.assertEqual(signal.baseline_median_paise, 6500000)
        self.assertAlmostEqual(signal.deviation_multiple, 0.77, places=2)
        self.assertTrue(signal.is_new_beneficiary)
        self.assertEqual(signal.prior_transfers_count, 0)

    def test_cold_start_uninitialized_profile(self):
        """Verify cold-start payer returns uninitialized status with explicit nulls."""
        history = PayerHistoryProfile(
            payer_id="usr_new",
            profile_type=AccountProfileType.PERSONAL,
            settled_amounts_paise=(),
            beneficiary_history={},
        )
        signal = evaluate_behavioral_baseline(history, "ben_any", 100000)

        self.assertEqual(signal.status, "uninitialized")
        self.assertIsNone(signal.baseline_median_paise)
        self.assertIsNone(signal.deviation_multiple)
        self.assertIsNone(signal.is_new_beneficiary)
        self.assertIsNone(signal.prior_transfers_count)
        self.assertEqual(signal.provenance.data_origin, DataOrigin.UNAVAILABLE)
        self.assertEqual(signal.provenance.calculation_method, CalculationMethod.UNPERFORMED)

    def test_none_profile_handling(self):
        """Verify None profile object returns uninitialized status safely."""
        signal = evaluate_behavioral_baseline(None, "ben_any", 100000)

        self.assertEqual(signal.status, "uninitialized")
        self.assertIsNone(signal.profile_type)
        self.assertIsNone(signal.baseline_median_paise)


if __name__ == "__main__":
    unittest.main()

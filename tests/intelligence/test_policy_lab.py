"""Comprehensive unit tests for PauseGuard Policy Lab (Member 3).

Verifies all 18 required test criteria from the Policy Lab specification:
1. Baseline A with explicit threshold.
2. Baseline A without threshold.
3. Baseline B with familiar beneficiary.
4. Baseline B with new beneficiary.
5. Policy C with personal profile.
6. Policy C with business profile.
7. Personal versus business FP comparison.
8. Confusion matrix correctness.
9. Precision and recall calculation.
10. Zero-denominator handling without division errors or fabricated 0.0.
11. Held-out test split enforcement (rejects non-test splits).
12. Payer leakage prevention across partitions.
13. Ground-truth exclusion from model inference features.
14. Representation across all six scenario categories.
15. Deterministic reproducibility with fixed seed.
16. Transparent handling of unavailable optional metrics (friction, workload, lag).
17. Empty dataset handling.
18. Invalid configuration handling.
"""

from dataclasses import FrozenInstanceError
import json
import unittest

from intelligence.advisory.types import AdvisoryScoringConfig, get_default_scoring_config
from intelligence.policy_lab.metrics import (
    ConfusionMatrix,
    MetricRate,
    PolicyEvaluationMetrics,
    calculate_evaluation_metrics,
    get_standard_unavailable_metrics,
)
from intelligence.policy_lab.policy_evaluator import (
    BaselineAPolicy,
    BaselineBPolicy,
    PolicyCPauseGuard,
    PolicyDecision,
    PolicyLab,
    PolicyLabReport,
    SyntheticVelocityThresholds,
    get_default_synthetic_velocity_thresholds,
)
from intelligence.schemas.risk_signals import AccountProfileType
from synthetic_data.generator import (
    CustomerProfileType,
    ScenarioCategory,
    ScenarioFeatures,
    SyntheticPaymentScenario,
    generate_scenario_dataset,
    split_dataset,
)


class TestPolicyLab(unittest.TestCase):

    def _sample_features(self, **overrides) -> ScenarioFeatures:
        """Create a sample ScenarioFeatures instance with optional overrides."""
        defaults = {
            "amount_paise": 50000,
            "profile_type": "personal",
            "payer_baseline_median_paise": 50000,
            "is_new_beneficiary": False,
            "prior_transfers_count": 5,
            "recent_attempts_in_window": 1,
            "recent_amount_paise_in_window": 50000,
            "transcript_text": None,
            "transcript_consented": False,
        }
        defaults.update(overrides)
        return ScenarioFeatures(**defaults)

    # -------------------------------------------------------------------------
    # 1. Baseline A with Explicit Threshold
    # -------------------------------------------------------------------------

    def test_baseline_a_with_explicit_threshold(self):
        """1. Verify Baseline A flags payments meeting or exceeding explicit threshold."""
        # Threshold: Rs. 10,000 (1,000,000 paise)
        policy = BaselineAPolicy(threshold_paise=1000000)
        self.assertTrue(policy.is_available)
        self.assertEqual(policy.threshold_paise, 1000000)

        # Above threshold -> Flagged
        feat_high = self._sample_features(amount_paise=1500000)
        dec_high = policy.evaluate(feat_high)
        self.assertTrue(dec_high.flagged)
        self.assertEqual(dec_high.tier, 2)
        self.assertIn("exceeds_threshold", dec_high.reason)

        # Below threshold -> Allowed
        feat_low = self._sample_features(amount_paise=500000)
        dec_low = policy.evaluate(feat_low)
        self.assertFalse(dec_low.flagged)
        self.assertEqual(dec_low.tier, 0)
        self.assertEqual(dec_low.reason, "amount_within_threshold")

    # -------------------------------------------------------------------------
    # 2. Baseline A Without Threshold
    # -------------------------------------------------------------------------

    def test_baseline_a_without_threshold(self):
        """2. Verify unconfigured Baseline A reports unavailable and raises on evaluation."""
        policy = BaselineAPolicy(threshold_paise=None)
        self.assertFalse(policy.is_available)
        self.assertIsNone(policy.threshold_paise)

        with self.assertRaises(ValueError) as ctx:
            policy.evaluate(self._sample_features())
        self.assertIn("unconfigured", str(ctx.exception))

    # -------------------------------------------------------------------------
    # 3. Baseline B with Familiar Beneficiary
    # -------------------------------------------------------------------------

    def test_baseline_b_with_familiar_beneficiary(self):
        """3. Verify Baseline B allows familiar beneficiary without warning."""
        policy = BaselineBPolicy()
        self.assertTrue(policy.is_available)

        feat_familiar = self._sample_features(is_new_beneficiary=False)
        decision = policy.evaluate(feat_familiar)

        self.assertFalse(decision.flagged)
        self.assertEqual(decision.tier, 0)
        self.assertEqual(decision.reason, "familiar_beneficiary_allowed")

    # -------------------------------------------------------------------------
    # 4. Baseline B with New Beneficiary
    # -------------------------------------------------------------------------

    def test_baseline_b_with_new_beneficiary(self):
        """4. Verify Baseline B flags any new beneficiary with advisory warning."""
        policy = BaselineBPolicy()
        feat_new = self._sample_features(is_new_beneficiary=True)
        decision = policy.evaluate(feat_new)

        self.assertTrue(decision.flagged)
        self.assertEqual(decision.tier, 1)
        self.assertEqual(decision.reason, "new_beneficiary_warning")

    # -------------------------------------------------------------------------
    # 5. Policy C with Personal Profile
    # -------------------------------------------------------------------------

    def test_policy_c_with_personal_profile(self):
        """5. Verify Policy C evaluates personal profile relative to personal baseline."""
        policy = PolicyCPauseGuard(scoring_config=get_default_scoring_config())
        self.assertTrue(policy.is_available)

        # Routine personal payment (Rs. 500 on Rs. 500 median) -> Not flagged
        feat_routine = self._sample_features(
            profile_type="personal",
            amount_paise=50000,
            payer_baseline_median_paise=50000,
            is_new_beneficiary=False,
        )
        dec_routine = policy.evaluate(feat_routine)
        self.assertFalse(dec_routine.flagged)
        self.assertEqual(dec_routine.tier, 0)

        # Coerced personal payment with urgent transcript -> Flagged Tier 3
        feat_coerced = self._sample_features(
            profile_type="personal",
            amount_paise=5000000,  # Rs. 50,000 on Rs. 500 median (100x!)
            payer_baseline_median_paise=50000,
            is_new_beneficiary=True,
            transcript_text="URGENT: Inspector Sharma Cyber Cell. Transfer immediately or arrest warrant issued. Keep secret.",
            transcript_consented=True,
        )
        dec_coerced = policy.evaluate(feat_coerced)
        self.assertTrue(dec_coerced.flagged)
        self.assertIn(dec_coerced.tier, (2, 3))

    # -------------------------------------------------------------------------
    # 6. Policy C with Business Profile
    # -------------------------------------------------------------------------

    def test_policy_c_with_business_profile(self):
        """6. Verify Policy C does not flag routine supplier payments to new vendors."""
        policy = PolicyCPauseGuard(scoring_config=get_default_scoring_config())

        # Routine small-business supplier payment to new vendor:
        # Amount: Rs. 50,000 (5,000,000 paise) against Rs. 50,000 baseline median (1.0x deviation)
        feat_biz_routine = self._sample_features(
            profile_type="small_business",
            amount_paise=5000000,
            payer_baseline_median_paise=5000000,
            is_new_beneficiary=True,  # Business routinely adds suppliers!
            prior_transfers_count=0,
        )
        dec_biz = policy.evaluate(feat_biz_routine)

        # Must NOT flag normal business supplier payments as fraud friction
        self.assertFalse(dec_biz.flagged)
        self.assertIn(dec_biz.tier, (0, 1))

    # -------------------------------------------------------------------------
    # 7. Personal vs Business False-Positive Comparison
    # -------------------------------------------------------------------------

    def test_personal_vs_business_fp_comparison(self):
        """7. Verify Policy C reduces business false positives compared to naive Baseline B."""
        dataset = generate_scenario_dataset(seed=42, count_per_category=20)
        report = PolicyLab.run_comparison(
            scenarios=dataset,
            policies=[
                BaselineBPolicy(),
                PolicyCPauseGuard(
                    scoring_config=get_default_scoring_config(),
                    synthetic_velocity_thresholds=get_default_synthetic_velocity_thresholds(),
                ),
            ],
            seed=42,
        )

        metrics_b = report.policy_metrics["Baseline B (Always Warn on New Beneficiary)"]
        metrics_c = report.policy_metrics["Policy C (Profile-Aware PauseGuard)"]

        # Baseline B flags all new beneficiaries, causing massive business disruption
        # (40% of legitimate business transactions pay new vendors)
        self.assertIsNotNone(metrics_b.business_cohort.false_positive_rate.rate)
        self.assertGreater(metrics_b.business_cohort.false_positive_rate.rate, 0.20)

        # Policy C profile-awareness substantially lowers business disruption
        self.assertIsNotNone(metrics_c.business_cohort.false_positive_rate.rate)
        self.assertLess(
            metrics_c.business_cohort.false_positive_rate.rate,
            metrics_b.business_cohort.false_positive_rate.rate,
        )

    # -------------------------------------------------------------------------
    # 8. Confusion Matrix Correctness
    # -------------------------------------------------------------------------

    def test_confusion_matrix_correctness(self):
        """8. Verify confusion matrix arithmetic matches known predictions."""
        # 2 TP, 1 FP, 2 TN, 1 FN
        predictions = [True, True, True, False, False, False]
        ground_truth = ["fraud", "fraud", "legitimate", "legitimate", "legitimate", "fraud"]
        profiles = ["personal"] * 6

        metrics = calculate_evaluation_metrics("TestPolicy", predictions, ground_truth, profiles)
        cm = metrics.confusion_matrix

        self.assertEqual(cm.true_positives, 2)
        self.assertEqual(cm.false_positives, 1)
        self.assertEqual(cm.true_negatives, 2)
        self.assertEqual(cm.false_negatives, 1)
        self.assertEqual(cm.total_evaluated, 6)

    # -------------------------------------------------------------------------
    # 9. Precision and Recall Calculation
    # -------------------------------------------------------------------------

    def test_precision_and_recall_calculation(self):
        """9. Verify precision and recall formulas with exact numerator and denominator."""
        predictions = [True, True, True, False, False, False]
        ground_truth = ["fraud", "fraud", "legitimate", "legitimate", "legitimate", "fraud"]
        profiles = ["personal"] * 6

        metrics = calculate_evaluation_metrics("TestPolicy", predictions, ground_truth, profiles)

        # Precision = TP / (TP + FP) = 2 / (2 + 1) = 2/3 = 0.6667
        self.assertEqual(metrics.precision.numerator, 2)
        self.assertEqual(metrics.precision.denominator, 3)
        self.assertAlmostEqual(metrics.precision.rate, 0.6667, places=3)

        # Recall = TP / (TP + FN) = 2 / (2 + 1) = 2/3 = 0.6667
        self.assertEqual(metrics.recall.numerator, 2)
        self.assertEqual(metrics.recall.denominator, 3)
        self.assertAlmostEqual(metrics.recall.rate, 0.6667, places=3)

        # Specificity = TN / (TN + FP) = 2 / (2 + 1) = 2/3 = 0.6667
        self.assertEqual(metrics.specificity.numerator, 2)
        self.assertEqual(metrics.specificity.denominator, 3)

        # FPR = FP / (FP + TN) = 1 / 3 = 0.3333
        self.assertEqual(metrics.false_positive_rate.numerator, 1)
        self.assertEqual(metrics.false_positive_rate.denominator, 3)

        # FNR = FN / (FN + TP) = 1 / 3 = 0.3333
        self.assertEqual(metrics.false_negative_rate.numerator, 1)
        self.assertEqual(metrics.false_negative_rate.denominator, 3)

    # -------------------------------------------------------------------------
    # 10. Zero-Denominator Handling
    # -------------------------------------------------------------------------

    def test_zero_denominator_handling(self):
        """10. Verify zero denominators produce rate=None without division error or fabrication."""
        # Dataset with 0 positive predictions: TP=0, FP=0 -> Precision denominator is 0
        predictions = [False, False]
        ground_truth = ["legitimate", "legitimate"]
        profiles = ["personal", "personal"]

        metrics = calculate_evaluation_metrics("TestPolicy", predictions, ground_truth, profiles)

        self.assertIsNone(metrics.precision.rate)
        self.assertEqual(metrics.precision.numerator, 0)
        self.assertEqual(metrics.precision.denominator, 0)

        # Business denominator is 0 (all samples were personal)
        self.assertIsNone(metrics.business_cohort.false_positive_rate.rate)
        self.assertEqual(metrics.business_cohort.false_positive_rate.denominator, 0)
        self.assertIsNone(metrics.business_disruption_rate.rate)

    # -------------------------------------------------------------------------
    # 11. Held-Out Test Split Enforcement
    # -------------------------------------------------------------------------

    def test_held_out_test_split_enforcement(self):
        """11. Verify PolicyLab strictly enforces split='test' and rejects train/val splits."""
        dataset = generate_scenario_dataset(seed=42, count_per_category=5)

        with self.assertRaises(ValueError) as ctx:
            PolicyLab.run_comparison(dataset, split="train")
        self.assertIn("requires split='test'", str(ctx.exception))

        with self.assertRaises(ValueError) as ctx:
            PolicyLab.run_comparison(dataset, split="val")
        self.assertIn("requires split='test'", str(ctx.exception))

        report = PolicyLab.run_comparison(dataset, split="test", seed=42)
        self.assertEqual(report.dataset_split, "test")

    # -------------------------------------------------------------------------
    # 12. Payer Leakage Prevention
    # -------------------------------------------------------------------------

    def test_payer_leakage_prevention(self):
        """12. Verify zero payer overlap between train/val and test splits."""
        dataset = generate_scenario_dataset(seed=42, count_per_category=25)
        splits = split_dataset(dataset, train_ratio=0.70, val_ratio=0.15, test_ratio=0.15, seed=42)

        train_payers = {s.payer_id for s in splits.train}
        val_payers = {s.payer_id for s in splits.val}
        test_payers = {s.payer_id for s in splits.test}

        self.assertEqual(len(train_payers & test_payers), 0)
        self.assertEqual(len(val_payers & test_payers), 0)

    # -------------------------------------------------------------------------
    # 13. Ground-Truth Exclusion from Features
    # -------------------------------------------------------------------------

    def test_ground_truth_exclusion_from_features(self):
        """13. Verify policies receive only ScenarioFeatures, excluding targets and labels."""
        dataset = generate_scenario_dataset(seed=42, count_per_category=5)
        for s in dataset:
            feats = s.to_features()
            feat_dict = feats.to_dict()

            self.assertFalse(hasattr(feats, "ground_truth_label"))
            self.assertFalse(hasattr(feats, "expected_policy_tier"))
            self.assertFalse(hasattr(feats, "scenario_id"))
            self.assertNotIn("ground_truth_label", feat_dict)
            self.assertNotIn("expected_policy_tier", feat_dict)

    # -------------------------------------------------------------------------
    # 14. All Six Scenario Categories
    # -------------------------------------------------------------------------

    def test_all_six_scenario_categories(self):
        """14. Verify all 6 benchmark scenario categories are evaluated in Policy Lab."""
        dataset = generate_scenario_dataset(seed=42, count_per_category=15)
        report = PolicyLab.run_comparison(dataset, seed=42)

        expected_categories = {
            ScenarioCategory.LEGITIMATE_PERSONAL.value,
            ScenarioCategory.LEGITIMATE_BUSINESS.value,
            ScenarioCategory.APP_COERCION_FRAUD.value,
            ScenarioCategory.BENIGN_ANOMALOUS.value,
            ScenarioCategory.MULE_PROXIMITY.value,
            ScenarioCategory.VELOCITY_STRUCTURING.value,
        }
        self.assertEqual(set(report.category_counts.keys()), expected_categories)

    # -------------------------------------------------------------------------
    # 15. Reproducibility with Fixed Seed
    # -------------------------------------------------------------------------

    def test_reproducibility_with_fixed_seed(self):
        """15. Verify identical seed produces 100% identical Policy Lab report."""
        dataset = generate_scenario_dataset(seed=42, count_per_category=10)

        report1 = PolicyLab.run_comparison(dataset, seed=123)
        report2 = PolicyLab.run_comparison(dataset, seed=123)

        self.assertEqual(report1.to_dict(), report2.to_dict())

    # -------------------------------------------------------------------------
    # 16. Missing Optional Metrics Handling
    # -------------------------------------------------------------------------

    def test_missing_optional_metrics_handling(self):
        """16. Verify friction, workload, and lag are explicitly reported unavailable."""
        dataset = generate_scenario_dataset(seed=42, count_per_category=5)
        report = PolicyLab.run_comparison(dataset, seed=42)

        for pol_name, metrics in report.policy_metrics.items():
            unavail = metrics.unavailable_metrics
            self.assertIn("payer_friction", unavail)
            self.assertIn("guardian_workload", unavail)
            self.assertIn("recovery_lag", unavail)

            self.assertEqual(unavail["payer_friction"].status, "unavailable")
            self.assertTrue(len(unavail["payer_friction"].reason) > 10)
            self.assertEqual(unavail["guardian_workload"].status, "unavailable")
            self.assertEqual(unavail["recovery_lag"].status, "unavailable")

    # -------------------------------------------------------------------------
    # 17. Empty Dataset Handling
    # -------------------------------------------------------------------------

    def test_empty_dataset_handling(self):
        """17. Verify passing empty scenario list raises ValueError safely."""
        with self.assertRaises(ValueError):
            PolicyLab.run_comparison(scenarios=[])

        # calculate_evaluation_metrics handles empty inputs without crashing
        empty_metrics = calculate_evaluation_metrics("EmptyPolicy", [], [], [])
        self.assertEqual(empty_metrics.total_scenarios, 0)
        self.assertIsNone(empty_metrics.precision.rate)
        self.assertEqual(empty_metrics.precision.denominator, 0)

    # -------------------------------------------------------------------------
    # 18. Invalid Configuration Handling
    # -------------------------------------------------------------------------

    def test_invalid_configuration_handling(self):
        """18. Verify invalid policy configurations raise explicit ValueErrors."""
        # Non-integer / boolean threshold in Baseline A
        with self.assertRaises(ValueError):
            BaselineAPolicy(threshold_paise=True)

        with self.assertRaises(ValueError):
            BaselineAPolicy(threshold_paise=-500)

        with self.assertRaises(ValueError):
            BaselineAPolicy(threshold_paise=0)

        # Policy C evaluate without scoring config
        unconfigured_c = PolicyCPauseGuard(scoring_config=None)
        self.assertFalse(unconfigured_c.is_available)
        with self.assertRaises(ValueError) as ctx:
            unconfigured_c.evaluate(self._sample_features())
        self.assertIn("unconfigured", str(ctx.exception))

        # Mismatched list lengths in metrics calculation
        with self.assertRaises(ValueError):
            calculate_evaluation_metrics("Bad", [True], ["fraud"], [])

    # -------------------------------------------------------------------------
    # Correction B Tests: Velocity Structuring Configuration & Evaluation
    # -------------------------------------------------------------------------

    def test_synthetic_velocity_config_validation_rejects_booleans(self):
        """B.6: Verify SyntheticVelocityThresholds rejects boolean types for integer fields."""
        with self.assertRaises(ValueError):
            SyntheticVelocityThresholds(
                structuring_threshold_attempts=True,
                structuring_threshold_amount_paise=3000000,
            )
        with self.assertRaises(ValueError):
            SyntheticVelocityThresholds(
                structuring_threshold_attempts=4,
                structuring_threshold_amount_paise=False,
            )
        with self.assertRaises(ValueError):
            SyntheticVelocityThresholds(
                structuring_threshold_attempts=4,
                structuring_threshold_amount_paise=3000000,
                rolling_window_minutes=True,
            )

    def test_synthetic_velocity_config_is_synthetic_immutability(self):
        """Verify is_synthetic is strictly immutable, default True, and cannot be passed in constructor."""
        thresholds = SyntheticVelocityThresholds(
            structuring_threshold_attempts=4,
            structuring_threshold_amount_paise=3000000,
            rolling_window_minutes=60,
        )
        # Default is_synthetic is True
        self.assertTrue(thresholds.is_synthetic)

        # Passing is_synthetic=False is rejected because init=False
        with self.assertRaises(TypeError):
            SyntheticVelocityThresholds(
                structuring_threshold_attempts=4,
                structuring_threshold_amount_paise=3000000,
                rolling_window_minutes=60,
                is_synthetic=False,
            )

        # Passing is_synthetic=True explicitly is also rejected because init=False
        with self.assertRaises(TypeError):
            SyntheticVelocityThresholds(
                structuring_threshold_attempts=4,
                structuring_threshold_amount_paise=3000000,
                rolling_window_minutes=60,
                is_synthetic=True,
            )

        # Reassigning the attribute after construction raises FrozenInstanceError
        with self.assertRaises(FrozenInstanceError):
            thresholds.is_synthetic = False

    def test_synthetic_velocity_config_validation_rejects_invalid_values(self):
        """B.5: Verify SyntheticVelocityThresholds rejects non-positive or out-of-range values."""
        # Non-positive attempts
        with self.assertRaises(ValueError):
            SyntheticVelocityThresholds(structuring_threshold_attempts=0, structuring_threshold_amount_paise=3000000)
        with self.assertRaises(ValueError):
            SyntheticVelocityThresholds(structuring_threshold_attempts=-3, structuring_threshold_amount_paise=3000000)

        # Non-positive amount
        with self.assertRaises(ValueError):
            SyntheticVelocityThresholds(structuring_threshold_attempts=4, structuring_threshold_amount_paise=0)
        with self.assertRaises(ValueError):
            SyntheticVelocityThresholds(structuring_threshold_attempts=4, structuring_threshold_amount_paise=-500)

        # Invalid rolling window minutes
        with self.assertRaises(ValueError):
            SyntheticVelocityThresholds(
                structuring_threshold_attempts=4,
                structuring_threshold_amount_paise=3000000,
                rolling_window_minutes=0,
            )
        with self.assertRaises(ValueError):
            SyntheticVelocityThresholds(
                structuring_threshold_attempts=4,
                structuring_threshold_amount_paise=3000000,
                rolling_window_minutes=2000,
            )

    def test_velocity_unconfigured_yields_unknown_without_fabrication(self):
        """B.1: Verify PolicyCPauseGuard without velocity thresholds leaves structuring classification unknown (None)."""
        policy = PolicyCPauseGuard(
            scoring_config=get_default_scoring_config(),
            synthetic_velocity_thresholds=None,
        )
        self.assertIsNone(policy.synthetic_velocity_thresholds)

        feat = self._sample_features(
            profile_type="personal",
            amount_paise=50000,
            payer_baseline_median_paise=50000,
            recent_attempts_in_window=10,
            recent_amount_paise_in_window=50000000,
            is_new_beneficiary=False,
        )

        signal = policy.evaluate_velocity_signal(feat)
        self.assertEqual(signal.status, "evaluated")
        self.assertIsNone(signal.structuring_suspected)

        dec = policy.evaluate(feat)
        self.assertFalse(dec.flagged)
        self.assertIsNone(dec.metadata.get("structuring_suspected"))

    def test_velocity_configured_triggers_expected_condition(self):
        """B.2 & B.4: Verify explicit synthetic configuration triggers when thresholds met/exceeded."""
        thresholds = SyntheticVelocityThresholds(
            structuring_threshold_attempts=4,
            structuring_threshold_amount_paise=3000000,
            rolling_window_minutes=60,
        )
        policy = PolicyCPauseGuard(
            scoring_config=get_default_scoring_config(),
            synthetic_velocity_thresholds=thresholds,
        )

        # Exact equality at threshold triggers
        feat_equal = self._sample_features(
            recent_attempts_in_window=4,
            recent_amount_paise_in_window=3000000,
        )
        dec_equal = policy.evaluate(feat_equal)
        self.assertTrue(dec_equal.flagged)
        self.assertEqual(dec_equal.tier, 3)
        self.assertEqual(dec_equal.reason, "velocity_structuring_suspected")
        self.assertTrue(dec_equal.metadata.get("structuring_suspected"))

        # Strictly above threshold triggers
        feat_above = self._sample_features(
            recent_attempts_in_window=5,
            recent_amount_paise_in_window=4000000,
        )
        dec_above = policy.evaluate(feat_above)
        self.assertTrue(dec_above.flagged)
        self.assertEqual(dec_above.tier, 3)
        self.assertEqual(dec_above.reason, "velocity_structuring_suspected")

    def test_velocity_below_threshold_does_not_trigger(self):
        """B.3: Verify values below threshold do not trigger structuring classification."""
        thresholds = SyntheticVelocityThresholds(
            structuring_threshold_attempts=4,
            structuring_threshold_amount_paise=3000000,
            rolling_window_minutes=60,
        )
        policy = PolicyCPauseGuard(
            scoring_config=get_default_scoring_config(),
            synthetic_velocity_thresholds=thresholds,
        )

        # Attempts below threshold
        feat_attempts_low = self._sample_features(
            profile_type="personal",
            amount_paise=50000,
            payer_baseline_median_paise=50000,
            recent_attempts_in_window=3,
            recent_amount_paise_in_window=5000000,
            is_new_beneficiary=False,
        )
        sig_attempts_low = policy.evaluate_velocity_signal(feat_attempts_low)
        self.assertFalse(sig_attempts_low.structuring_suspected)
        dec_attempts_low = policy.evaluate(feat_attempts_low)
        self.assertFalse(dec_attempts_low.flagged)
        self.assertFalse(dec_attempts_low.metadata.get("structuring_suspected"))

        # Amount below threshold
        feat_amount_low = self._sample_features(
            profile_type="personal",
            amount_paise=50000,
            payer_baseline_median_paise=50000,
            recent_attempts_in_window=5,
            recent_amount_paise_in_window=2999999,
            is_new_beneficiary=False,
        )
        sig_amount_low = policy.evaluate_velocity_signal(feat_amount_low)
        self.assertFalse(sig_amount_low.structuring_suspected)
        dec_amount_low = policy.evaluate(feat_amount_low)
        self.assertFalse(dec_amount_low.flagged)
        self.assertFalse(dec_amount_low.metadata.get("structuring_suspected"))

    def test_velocity_missing_inputs_yields_unknown(self):
        """B.7: Verify missing attempts or amount leaves classification unknown without fabrication."""
        thresholds = SyntheticVelocityThresholds(
            structuring_threshold_attempts=4,
            structuring_threshold_amount_paise=3000000,
        )
        policy = PolicyCPauseGuard(
            scoring_config=get_default_scoring_config(),
            synthetic_velocity_thresholds=thresholds,
        )

        # Missing attempts
        feat_no_attempts = self._sample_features(
            recent_attempts_in_window=None,
            recent_amount_paise_in_window=5000000,
        )
        sig1 = policy.evaluate_velocity_signal(feat_no_attempts)
        self.assertEqual(sig1.status, "unavailable")
        self.assertIsNone(sig1.structuring_suspected)

        # Missing amount
        feat_no_amount = self._sample_features(
            recent_attempts_in_window=5,
            recent_amount_paise_in_window=None,
        )
        sig2 = policy.evaluate_velocity_signal(feat_no_amount)
        self.assertEqual(sig2.status, "unavailable")
        self.assertIsNone(sig2.structuring_suspected)

    # -------------------------------------------------------------------------
    # Correction C Tests: Exhaustive Zero-Denominator & Undefined Metric Handling
    # -------------------------------------------------------------------------

    def test_metric_rate_zero_denominator_behavior(self):
        """C: Verify MetricRate behavior when denominator is zero."""
        mr = MetricRate.compute(numerator=0, denominator=0)
        self.assertIsNone(mr.rate)
        self.assertEqual(mr.numerator, 0)
        self.assertEqual(mr.denominator, 0)
        self.assertTrue(mr.is_undefined)
        self.assertIsNot(mr.rate, 0.0)

        # Verify serialization
        d = mr.to_dict()
        self.assertIsNone(d["rate"])
        self.assertEqual(d["numerator"], 0)
        self.assertEqual(d["denominator"], 0)
        self.assertTrue(d["is_undefined"])

        j = json.dumps(d)
        self.assertIn('"rate": null', j)
        self.assertIn('"is_undefined": true', j)

    def test_metric_rate_rejects_booleans_and_floats(self):
        """C: Verify MetricRate rejects booleans and invalid types."""
        with self.assertRaises(ValueError):
            MetricRate.compute(numerator=True, denominator=10)
        with self.assertRaises(ValueError):
            MetricRate.compute(numerator=5, denominator=False)
        with self.assertRaises(ValueError):
            MetricRate.compute(numerator="5", denominator=10)

    def test_all_eight_zero_denominator_metrics_return_none(self):
        """C: Verify all 8 rate metrics return rate=None when their respective denominator is 0."""
        # 1. Precision zero-denominator: no positive predictions (TP=0, FP=0)
        m_prec_zero = calculate_evaluation_metrics(
            "Test",
            predictions=[False, False],
            ground_truth_labels=["legitimate", "fraud"],
            profile_types=["personal", "personal"],
        )
        self.assertIsNone(m_prec_zero.precision.rate)
        self.assertTrue(m_prec_zero.precision.is_undefined)
        self.assertEqual(m_prec_zero.precision.denominator, 0)

        # 2. Recall zero-denominator: no fraud ground truth (TP=0, FN=0)
        m_rec_zero = calculate_evaluation_metrics(
            "Test",
            predictions=[True, False],
            ground_truth_labels=["legitimate", "legitimate"],
            profile_types=["personal", "personal"],
        )
        self.assertIsNone(m_rec_zero.recall.rate)
        self.assertTrue(m_rec_zero.recall.is_undefined)
        self.assertEqual(m_rec_zero.recall.denominator, 0)

        # 3. Specificity zero-denominator: no legitimate ground truth (TN=0, FP=0)
        m_spec_zero = calculate_evaluation_metrics(
            "Test",
            predictions=[True, False],
            ground_truth_labels=["fraud", "fraud"],
            profile_types=["personal", "personal"],
        )
        self.assertIsNone(m_spec_zero.specificity.rate)
        self.assertTrue(m_spec_zero.specificity.is_undefined)
        self.assertEqual(m_spec_zero.specificity.denominator, 0)

        # 4. FPR zero-denominator: no legitimate ground truth (FP=0, TN=0)
        self.assertIsNone(m_spec_zero.false_positive_rate.rate)
        self.assertTrue(m_spec_zero.false_positive_rate.is_undefined)
        self.assertEqual(m_spec_zero.false_positive_rate.denominator, 0)

        # 5. FNR zero-denominator: no fraud ground truth (FN=0, TP=0)
        self.assertIsNone(m_rec_zero.false_negative_rate.rate)
        self.assertTrue(m_rec_zero.false_negative_rate.is_undefined)
        self.assertEqual(m_rec_zero.false_negative_rate.denominator, 0)

        # 6. Personal FPR zero-denominator: no legitimate personal payments
        m_no_pers = calculate_evaluation_metrics(
            "Test",
            predictions=[True],
            ground_truth_labels=["legitimate"],
            profile_types=["small_business"],
        )
        self.assertIsNone(m_no_pers.personal_cohort.false_positive_rate.rate)
        self.assertTrue(m_no_pers.personal_cohort.false_positive_rate.is_undefined)
        self.assertEqual(m_no_pers.personal_cohort.legitimate_total, 0)

        # 7. Business FPR zero-denominator: no legitimate business payments
        m_no_biz = calculate_evaluation_metrics(
            "Test",
            predictions=[True],
            ground_truth_labels=["legitimate"],
            profile_types=["personal"],
        )
        self.assertIsNone(m_no_biz.business_cohort.false_positive_rate.rate)
        self.assertTrue(m_no_biz.business_cohort.false_positive_rate.is_undefined)
        self.assertEqual(m_no_biz.business_cohort.legitimate_total, 0)

        # 8. Business disruption rate zero-denominator: no legitimate business payments
        self.assertIsNone(m_no_biz.business_disruption_rate.rate)
        self.assertTrue(m_no_biz.business_disruption_rate.is_undefined)
        self.assertEqual(m_no_biz.business_disruption_rate.denominator, 0)

    def test_nonzero_denominator_metrics_remain_mathematically_exact(self):
        """C: Verify non-zero denominator metrics calculate exact mathematical ratios."""
        # 3 TP, 1 FP, 4 TN, 2 FN (Total: 10)
        # Profiles: 3 legitimate personal (1 FP, 2 TN); 2 legitimate business (0 FP, 2 TN)
        predictions = [True, True, True, True, False, False, False, False, False, False]
        ground_truth = [
            "fraud", "fraud", "fraud",      # 3 TP
            "legitimate",                    # 1 FP (personal)
            "legitimate", "legitimate",      # 2 TN (personal)
            "legitimate", "legitimate",      # 2 TN (business)
            "fraud", "fraud",                # 2 FN
        ]
        profiles = [
            "personal", "personal", "personal",
            "personal",
            "personal", "personal",
            "small_business", "enterprise",
            "personal", "personal",
        ]

        m = calculate_evaluation_metrics("MathExactTest", predictions, ground_truth, profiles)

        # Precision = 3 / (3 + 1) = 3/4 = 0.75
        self.assertFalse(m.precision.is_undefined)
        self.assertEqual(m.precision.numerator, 3)
        self.assertEqual(m.precision.denominator, 4)
        self.assertEqual(m.precision.rate, 0.75)

        # Recall = 3 / (3 + 2) = 3/5 = 0.6
        self.assertFalse(m.recall.is_undefined)
        self.assertEqual(m.recall.numerator, 3)
        self.assertEqual(m.recall.denominator, 5)
        self.assertEqual(m.recall.rate, 0.6)

        # Specificity = 4 / (4 + 1) = 4/5 = 0.8
        self.assertFalse(m.specificity.is_undefined)
        self.assertEqual(m.specificity.numerator, 4)
        self.assertEqual(m.specificity.denominator, 5)
        self.assertEqual(m.specificity.rate, 0.8)

        # FPR = 1 / (1 + 4) = 1/5 = 0.2
        self.assertFalse(m.false_positive_rate.is_undefined)
        self.assertEqual(m.false_positive_rate.numerator, 1)
        self.assertEqual(m.false_positive_rate.denominator, 5)
        self.assertEqual(m.false_positive_rate.rate, 0.2)

        # FNR = 2 / (2 + 3) = 2/5 = 0.4
        self.assertFalse(m.false_negative_rate.is_undefined)
        self.assertEqual(m.false_negative_rate.numerator, 2)
        self.assertEqual(m.false_negative_rate.denominator, 5)
        self.assertEqual(m.false_negative_rate.rate, 0.4)

        # Personal FPR = 1 / 3 = 0.3333
        self.assertFalse(m.personal_cohort.false_positive_rate.is_undefined)
        self.assertEqual(m.personal_cohort.false_positive_rate.numerator, 1)
        self.assertEqual(m.personal_cohort.false_positive_rate.denominator, 3)
        self.assertEqual(m.personal_cohort.false_positive_rate.rate, 0.3333)

        # Business FPR = 0 / 2 = 0.0
        self.assertFalse(m.business_cohort.false_positive_rate.is_undefined)
        self.assertEqual(m.business_cohort.false_positive_rate.numerator, 0)
        self.assertEqual(m.business_cohort.false_positive_rate.denominator, 2)
        self.assertEqual(m.business_cohort.false_positive_rate.rate, 0.0)

        # Business Disruption = 0 / 2 = 0.0
        self.assertFalse(m.business_disruption_rate.is_undefined)
        self.assertEqual(m.business_disruption_rate.numerator, 0)
        self.assertEqual(m.business_disruption_rate.denominator, 2)
        self.assertEqual(m.business_disruption_rate.rate, 0.0)

    # -------------------------------------------------------------------------
    # Correction A Tests: Canonical Benchmark Configuration & Verification
    # -------------------------------------------------------------------------

    def test_canonical_benchmark_execution_and_metrics(self):
        """A: Verify canonical benchmark (seed=42, count_per_category=20) evaluates exactly 18 test scenarios."""
        dataset = generate_scenario_dataset(seed=42, count_per_category=20)
        self.assertEqual(len(dataset), 120)

        report = PolicyLab.run_comparison(
            scenarios=dataset,
            seed=42,
            split="test",
        )

        # 18 test scenarios evaluated (3 per category)
        self.assertEqual(report.total_scenarios_evaluated, 18)
        self.assertEqual(sum(report.category_counts.values()), 18)
        for cat, cnt in report.category_counts.items():
            self.assertEqual(cnt, 3)

        # Check all three policies
        m_a = report.policy_metrics["Baseline A (Amount-only Hard Threshold)"]
        m_b = report.policy_metrics["Baseline B (Always Warn on New Beneficiary)"]
        m_c = report.policy_metrics["Policy C (Profile-Aware PauseGuard)"]

        # Sum of confusion matrix components must equal 18
        for m in (m_a, m_b, m_c):
            cm = m.confusion_matrix
            self.assertEqual(cm.true_positives + cm.false_positives + cm.true_negatives + cm.false_negatives, 18)

        # Policy C specific numbers
        cm_c = m_c.confusion_matrix
        self.assertEqual(cm_c.true_positives, 9)
        self.assertEqual(cm_c.false_positives, 1)
        self.assertEqual(cm_c.true_negatives, 8)
        self.assertEqual(cm_c.false_negatives, 0)
        self.assertEqual(m_c.precision.rate, 0.9)
        self.assertEqual(m_c.recall.rate, 1.0)
        self.assertEqual(m_c.business_disruption_rate.rate, 0.0)


if __name__ == "__main__":
    unittest.main()

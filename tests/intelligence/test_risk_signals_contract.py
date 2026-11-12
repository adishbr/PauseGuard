"""Comprehensive Unit Tests for PauseGuard V2 RiskSignals Contract.

Validates Revision 2 schema consistency, strict integer paise validation,
Pydantic V2 model validators, degraded state consistency, and safety invariants.
"""

from datetime import datetime, timezone, timedelta
import unittest
from pydantic import ValidationError

from intelligence.schemas.risk_signals import (
    AccountProfileType,
    BehavioralSignal,
    CalculationMethod,
    DataOrigin,
    EvaluationStatus,
    MuleGraphSignal,
    RegistrySignal,
    RiskSignals,
    SignalProvenance,
    SourceCategory,
    SuggestedCautionLevel,
    TranscriptCoercionSignal,
    VelocitySignal,
    make_degraded_advisory,
)


class TestRiskSignalsContract(unittest.TestCase):

    def setUp(self):
        self.now_utc = datetime.now(timezone.utc)
        self.base_provenance = {
            "source_category": "model_inference",
            "data_origin": "mock_ledger_history",
            "calculation_method": "statistical_baseline",
            "is_synthetic": True,
        }

    # -------------------------------------------------------------------------
    # 16. Existing Four Scenario Tests
    # -------------------------------------------------------------------------

    def test_example_1_legitimate_personal_transaction(self):
        """Verify Example 1: Legitimate personal transaction validates successfully."""
        payload = {
            "schema_version": "2.0.0",
            "data_environment": "synthetic_lab",
            "model_name": "pauseguard-heuristics-engine",
            "model_version": "0.1.0-alpha",
            "generated_at": self.now_utc.isoformat(),
            "evaluation_latency_ms": 3.4,
            "evaluation_status": "complete",
            "degraded_reasons": [],
            "payment_id": "pg_synth_legit_pers_001",
            "payer_id": "usr_synth_amit_88",
            "beneficiary_id": "ben_synth_grocer_familiar_01",
            "amount_paise": 25000,
            "advisory_score": 5,
            "calibrated_fraud_probability": None,
            "calibration_caveat": "Advisory heuristic score derived from synthetic/rule baselines; not a real-world calibrated probability.",
            "suggested_caution_level": "low",
            "reason_codes": [
                "RC_FAMILIAR_BENEFICIARY",
                "RC_AMOUNT_WITHIN_BASELINE",
            ],
            "behavioral": {
                "status": "evaluated",
                "profile_type": "personal",
                "baseline_median_paise": 35000,
                "deviation_multiple": 0.71,
                "is_new_beneficiary": False,
                "prior_transfers_count": 14,
                "provenance": self.base_provenance,
            },
            "velocity": {
                "status": "evaluated",
                "rolling_window_minutes": 60,
                "attempts_in_window": 1,
                "total_amount_paise_in_window": 25000,
                "structuring_suspected": False,
                "provenance": {
                    "source_category": "trusted_source",
                    "data_origin": "mock_ledger_history",
                    "calculation_method": "deterministic_lookup",
                    "is_synthetic": True,
                },
            },
            "registry": {
                "check_status": "performed",
                "is_listed_high_risk": False,
                "registry_category": None,
                "provenance": {
                    "source_category": "trusted_source",
                    "data_origin": "mock_registry_table",
                    "calculation_method": "deterministic_lookup",
                    "is_synthetic": True,
                },
            },
            "mule_graph": {
                "status": "evaluated",
                "in_degree_incoming_unique_payers": 3,
                "hop_distance_to_flagged_mule": None,
                "cluster_risk_score": 0,
                "provenance": {
                    "source_category": "model_inference",
                    "data_origin": "synthetic_fixture",
                    "calculation_method": "graph_traversal",
                    "is_synthetic": True,
                },
            },
            "transcript": {
                "status": "absent",
                "coercion_detected": None,
                "coercion_indicators": [],
                "suspected_prompt_injection": None,
                "provenance": {
                    "source_category": "model_inference",
                    "data_origin": "unavailable",
                    "calculation_method": "unperformed",
                    "is_synthetic": True,
                },
            },
            "can_authorize_payment": False,
            "can_execute_payment": False,
            "advisory_only": True,
        }

        signal = RiskSignals.model_validate(payload)
        self.assertEqual(signal.schema_version, "2.0.0")
        self.assertEqual(signal.advisory_score, 5)
        self.assertFalse(signal.can_authorize_payment)
        self.assertFalse(signal.can_execute_payment)
        self.assertTrue(signal.advisory_only)
        self.assertIsNone(signal.calibrated_fraud_probability)

    def test_example_2_legitimate_business_transaction(self):
        """Verify Example 2: Legitimate small business transaction validates."""
        payload = {
            "schema_version": "2.0.0",
            "data_environment": "synthetic_lab",
            "model_name": "pauseguard-heuristics-engine",
            "model_version": "0.1.0-alpha",
            "generated_at": self.now_utc.isoformat(),
            "evaluation_latency_ms": 4.1,
            "evaluation_status": "complete",
            "degraded_reasons": [],
            "payment_id": "pg_synth_legit_biz_002",
            "payer_id": "usr_synth_sharma_hardware_101",
            "beneficiary_id": "ben_synth_supplier_metals_corp",
            "amount_paise": 5000000,
            "advisory_score": 18,
            "calibrated_fraud_probability": None,
            "calibration_caveat": "Advisory heuristic score derived from synthetic/rule baselines; not a real-world calibrated probability.",
            "suggested_caution_level": "low",
            "reason_codes": [
                "RC_PROFILE_BUSINESS_BENIGN",
                "RC_NEW_BENEFICIARY_EXPECTED_FOR_PROFILE",
            ],
            "behavioral": {
                "status": "evaluated",
                "profile_type": "small_business",
                "baseline_median_paise": 6500000,
                "deviation_multiple": 0.77,
                "is_new_beneficiary": True,
                "prior_transfers_count": 0,
                "provenance": self.base_provenance,
            },
            "velocity": {
                "status": "evaluated",
                "rolling_window_minutes": 60,
                "attempts_in_window": 2,
                "total_amount_paise_in_window": 9500000,
                "structuring_suspected": False,
                "provenance": {
                    "source_category": "trusted_source",
                    "data_origin": "mock_ledger_history",
                    "calculation_method": "deterministic_lookup",
                    "is_synthetic": True,
                },
            },
            "registry": {
                "check_status": "performed",
                "is_listed_high_risk": False,
                "registry_category": None,
                "provenance": {
                    "source_category": "trusted_source",
                    "data_origin": "mock_registry_table",
                    "calculation_method": "deterministic_lookup",
                    "is_synthetic": True,
                },
            },
            "mule_graph": {
                "status": "evaluated",
                "in_degree_incoming_unique_payers": 8,
                "hop_distance_to_flagged_mule": None,
                "cluster_risk_score": 5,
                "provenance": {
                    "source_category": "model_inference",
                    "data_origin": "synthetic_fixture",
                    "calculation_method": "graph_traversal",
                    "is_synthetic": True,
                },
            },
            "transcript": {
                "status": "absent",
                "coercion_detected": None,
                "coercion_indicators": [],
                "suspected_prompt_injection": None,
                "provenance": {
                    "source_category": "model_inference",
                    "data_origin": "unavailable",
                    "calculation_method": "unperformed",
                    "is_synthetic": True,
                },
            },
            "can_authorize_payment": False,
            "can_execute_payment": False,
            "advisory_only": True,
        }

        signal = RiskSignals.model_validate(payload)
        self.assertEqual(signal.behavioral.profile_type, AccountProfileType.SMALL_BUSINESS)
        self.assertEqual(signal.amount_paise, 5000000)

    def test_example_3_suspicious_coercion_transaction(self):
        """Verify Example 3: Suspicious coercion transaction validates."""
        payload = {
            "schema_version": "2.0.0",
            "data_environment": "synthetic_lab",
            "model_name": "pauseguard-heuristics-engine",
            "model_version": "0.1.0-alpha",
            "generated_at": self.now_utc.isoformat(),
            "evaluation_latency_ms": 6.8,
            "evaluation_status": "complete",
            "degraded_reasons": [],
            "payment_id": "pg_synth_scam_coercion_003",
            "payer_id": "usr_synth_senior_ramesh_42",
            "beneficiary_id": "ben_synth_mule_account_rapid_09",
            "amount_paise": 5500000,
            "advisory_score": 95,
            "calibrated_fraud_probability": None,
            "calibration_caveat": "Advisory heuristic score derived from synthetic/rule baselines; not a real-world calibrated probability.",
            "suggested_caution_level": "critical",
            "reason_codes": [
                "RC_NEW_BENEFICIARY",
                "RC_LARGE_DEVIATION",
                "RC_COERCION_TRANSCRIPT",
                "RC_MULE_GRAPH_PROXIMITY",
            ],
            "behavioral": {
                "status": "evaluated",
                "profile_type": "personal",
                "baseline_median_paise": 150000,
                "deviation_multiple": 36.67,
                "is_new_beneficiary": True,
                "prior_transfers_count": 0,
                "provenance": self.base_provenance,
            },
            "velocity": {
                "status": "evaluated",
                "rolling_window_minutes": 60,
                "attempts_in_window": 1,
                "total_amount_paise_in_window": 5500000,
                "structuring_suspected": False,
                "provenance": {
                    "source_category": "trusted_source",
                    "data_origin": "mock_ledger_history",
                    "calculation_method": "deterministic_lookup",
                    "is_synthetic": True,
                },
            },
            "registry": {
                "check_status": "performed",
                "is_listed_high_risk": False,
                "registry_category": None,
                "provenance": {
                    "source_category": "trusted_source",
                    "data_origin": "mock_registry_table",
                    "calculation_method": "deterministic_lookup",
                    "is_synthetic": True,
                },
            },
            "mule_graph": {
                "status": "evaluated",
                "in_degree_incoming_unique_payers": 27,
                "hop_distance_to_flagged_mule": 1,
                "cluster_risk_score": 85,
                "provenance": {
                    "source_category": "model_inference",
                    "data_origin": "synthetic_fixture",
                    "calculation_method": "graph_traversal",
                    "is_synthetic": True,
                },
            },
            "transcript": {
                "status": "evaluated",
                "coercion_detected": True,
                "coercion_indicators": [
                    "urgency",
                    "authority_impersonation",
                    "threat",
                    "secrecy",
                ],
                "suspected_prompt_injection": False,
                "provenance": {
                    "source_category": "model_inference",
                    "data_origin": "consented_audio_transcript",
                    "calculation_method": "nlp_regex_coercion",
                    "is_synthetic": True,
                },
            },
            "can_authorize_payment": False,
            "can_execute_payment": False,
            "advisory_only": True,
        }

        signal = RiskSignals.model_validate(payload)
        self.assertEqual(signal.advisory_score, 95)
        self.assertEqual(signal.suggested_caution_level, SuggestedCautionLevel.CRITICAL)
        self.assertTrue(signal.transcript.coercion_detected)
        self.assertEqual(signal.mule_graph.hop_distance_to_flagged_mule, 1)

    def test_example_4_degraded_mode_transaction(self):
        """Verify Example 4: Degraded mode with explicit nulls and no fabricated scores."""
        degraded = make_degraded_advisory(
            payment_id="pg_synth_degraded_004",
            payer_id="usr_synth_new_customer_999",
            beneficiary_id="ben_synth_unknown_55",
            amount_paise=1000000,
            degraded_reasons=(
                "payer_baseline_uninitialized",
                "mule_graph_service_unavailable",
                "registry_lookup_timeout",
            ),
            reason_codes=(
                "RC_ADVISORY_SCORE_UNAVAILABLE",
                "RC_BASELINE_UNINITIALIZED",
                "RC_REGISTRY_UNAVAILABLE",
                "RC_GRAPH_UNAVAILABLE",
            ),
        )

        self.assertEqual(degraded.evaluation_status, EvaluationStatus.DEGRADED)
        self.assertIsNone(degraded.advisory_score)
        self.assertIsNone(degraded.suggested_caution_level)
        self.assertIsNone(degraded.behavioral.profile_type)
        self.assertIsNone(degraded.behavioral.baseline_median_paise)
        self.assertIsNone(degraded.registry.is_listed_high_risk)
        self.assertIsNone(degraded.mule_graph.cluster_risk_score)
        self.assertIsNone(degraded.transcript.suspected_prompt_injection)
        self.assertFalse(degraded.can_authorize_payment)
        self.assertFalse(degraded.can_execute_payment)
        self.assertTrue(degraded.advisory_only)

    # -------------------------------------------------------------------------
    # 1. Synthetic Calibration Enforcement
    # -------------------------------------------------------------------------

    def test_synthetic_environment_rejects_calibrated_fraud_probability(self):
        """Verify calibrated_fraud_probability is rejected when data_environment='synthetic_lab'."""
        degraded = make_degraded_advisory(
            payment_id="pg_1",
            payer_id="u_1",
            beneficiary_id="b_1",
            amount_paise=1000,
            degraded_reasons=(),
        )
        data = degraded.model_dump()
        data["calibrated_fraud_probability"] = 0.85

        with self.assertRaises(ValidationError) as ctx:
            RiskSignals.model_validate(data)
        self.assertIn("calibrated_fraud_probability must be None in synthetic_lab", str(ctx.exception))

    # -------------------------------------------------------------------------
    # 2 & 3. Degraded Status Score & Caution Rejection
    # -------------------------------------------------------------------------

    def test_degraded_status_rejects_non_null_advisory_score(self):
        """Verify non-null advisory_score is rejected when status is degraded/timeout/missing_inputs."""
        degraded = make_degraded_advisory(
            payment_id="pg_1",
            payer_id="u_1",
            beneficiary_id="b_1",
            amount_paise=1000,
            degraded_reasons=("timeout",),
        )
        data = degraded.model_dump()
        data["advisory_score"] = 50  # Fabricated score

        with self.assertRaises(ValidationError) as ctx:
            RiskSignals.model_validate(data)
        self.assertIn("advisory_score must be None when evaluation_status is 'degraded'", str(ctx.exception))

    def test_degraded_status_rejects_non_null_caution_level(self):
        """Verify non-null suggested_caution_level is rejected when status is degraded."""
        degraded = make_degraded_advisory(
            payment_id="pg_1",
            payer_id="u_1",
            beneficiary_id="b_1",
            amount_paise=1000,
            degraded_reasons=("timeout",),
        )
        data = degraded.model_dump()
        data["suggested_caution_level"] = "medium"

        with self.assertRaises(ValidationError) as ctx:
            RiskSignals.model_validate(data)
        self.assertIn("suggested_caution_level must be None when evaluation_status is 'degraded'", str(ctx.exception))

    # -------------------------------------------------------------------------
    # 4 & 5. Registry Consistency
    # -------------------------------------------------------------------------

    def test_unavailable_registry_cannot_claim_negative_match(self):
        """Verify registry with status 'unavailable' cannot set is_listed_high_risk=False."""
        degraded = make_degraded_advisory(
            payment_id="pg_1",
            payer_id="u_1",
            beneficiary_id="b_1",
            amount_paise=1000,
            degraded_reasons=(),
        )
        data = degraded.model_dump()
        data["registry"]["check_status"] = "unavailable"
        data["registry"]["is_listed_high_risk"] = False  # False claim of negative match

        with self.assertRaises(ValidationError) as ctx:
            RiskSignals.model_validate(data)
        self.assertIn("Cannot claim a negative match", str(ctx.exception))

    def test_performed_registry_must_provide_result(self):
        """Verify check_status='performed' requires is_listed_high_risk to not be None."""
        degraded = make_degraded_advisory(
            payment_id="pg_1",
            payer_id="u_1",
            beneficiary_id="b_1",
            amount_paise=1000,
            degraded_reasons=(),
        )
        data = degraded.model_dump()
        data["registry"]["check_status"] = "performed"
        data["registry"]["is_listed_high_risk"] = None

        with self.assertRaises(ValidationError) as ctx:
            RiskSignals.model_validate(data)
        self.assertIn("is_listed_high_risk must be True or False", str(ctx.exception))

    # -------------------------------------------------------------------------
    # 6 & 7. Velocity & Graph Metric Nullability on Unavailable Status
    # -------------------------------------------------------------------------

    def test_unavailable_velocity_fields_remain_null(self):
        """Verify status='unavailable' rejects populated velocity metrics."""
        degraded = make_degraded_advisory(
            payment_id="pg_1",
            payer_id="u_1",
            beneficiary_id="b_1",
            amount_paise=1000,
            degraded_reasons=(),
        )
        data = degraded.model_dump()
        data["velocity"]["status"] = "unavailable"
        data["velocity"]["attempts_in_window"] = 3

        with self.assertRaises(ValidationError) as ctx:
            RiskSignals.model_validate(data)
        self.assertIn("All measured velocity fields must be None", str(ctx.exception))

    def test_unavailable_graph_metrics_remain_null(self):
        """Verify status='unperformed' or 'unavailable' rejects populated graph metrics."""
        degraded = make_degraded_advisory(
            payment_id="pg_1",
            payer_id="u_1",
            beneficiary_id="b_1",
            amount_paise=1000,
            degraded_reasons=(),
        )
        data = degraded.model_dump()
        data["mule_graph"]["status"] = "unavailable"
        data["mule_graph"]["cluster_risk_score"] = 0  # Cannot assume 0 risk

        with self.assertRaises(ValidationError) as ctx:
            RiskSignals.model_validate(data)
        self.assertIn("All graph metric fields must be None", str(ctx.exception))

    # -------------------------------------------------------------------------
    # 8. Unconsented Transcript Restrictions
    # -------------------------------------------------------------------------

    def test_unconsented_transcript_cannot_report_analysed_coercion(self):
        """Verify unconsented/absent transcript cannot report coercion_detected=True."""
        degraded = make_degraded_advisory(
            payment_id="pg_1",
            payer_id="u_1",
            beneficiary_id="b_1",
            amount_paise=1000,
            degraded_reasons=(),
        )
        data = degraded.model_dump()
        data["transcript"]["status"] = "unconsented"
        data["transcript"]["coercion_detected"] = True

        with self.assertRaises(ValidationError) as ctx:
            RiskSignals.model_validate(data)
        self.assertIn("coercion_detected must be None", str(ctx.exception))

    def test_non_evaluated_transcript_rejects_false_prompt_injection(self):
        """Verify non-evaluated transcript cannot set suspected_prompt_injection=False."""
        degraded = make_degraded_advisory(
            payment_id="pg_1",
            payer_id="u_1",
            beneficiary_id="b_1",
            amount_paise=1000,
            degraded_reasons=(),
        )
        data = degraded.model_dump()
        data["transcript"]["status"] = "absent"
        data["transcript"]["suspected_prompt_injection"] = False

        with self.assertRaises(ValidationError) as ctx:
            RiskSignals.model_validate(data)
        self.assertIn("suspected_prompt_injection must be None", str(ctx.exception))

    def test_evaluated_transcript_rejects_none_prompt_injection(self):
        """Verify evaluated transcript with suspected_prompt_injection=None is rejected."""
        degraded = make_degraded_advisory(
            payment_id="pg_1",
            payer_id="u_1",
            beneficiary_id="b_1",
            amount_paise=1000,
            degraded_reasons=(),
        )
        data = degraded.model_dump()
        data["transcript"]["status"] = "evaluated"
        data["transcript"]["coercion_detected"] = False
        data["transcript"]["suspected_prompt_injection"] = None

        with self.assertRaises(ValidationError) as ctx:
            RiskSignals.model_validate(data)
        self.assertIn("suspected_prompt_injection must be True or False", str(ctx.exception))

    def test_evaluated_transcript_accepts_false_prompt_injection(self):
        """Verify evaluated transcript with suspected_prompt_injection=False is accepted."""
        degraded = make_degraded_advisory(
            payment_id="pg_1",
            payer_id="u_1",
            beneficiary_id="b_1",
            amount_paise=1000,
            degraded_reasons=(),
        )
        data = degraded.model_dump()
        data["transcript"]["status"] = "evaluated"
        data["transcript"]["coercion_detected"] = False
        data["transcript"]["suspected_prompt_injection"] = False

        validated = RiskSignals.model_validate(data)
        self.assertFalse(validated.transcript.suspected_prompt_injection)

    def test_evaluated_transcript_accepts_true_prompt_injection(self):
        """Verify evaluated transcript with suspected_prompt_injection=True is accepted."""
        degraded = make_degraded_advisory(
            payment_id="pg_1",
            payer_id="u_1",
            beneficiary_id="b_1",
            amount_paise=1000,
            degraded_reasons=(),
        )
        data = degraded.model_dump()
        data["transcript"]["status"] = "evaluated"
        data["transcript"]["coercion_detected"] = True
        data["transcript"]["suspected_prompt_injection"] = True

        validated = RiskSignals.model_validate(data)
        self.assertTrue(validated.transcript.suspected_prompt_injection)

    def test_degraded_fallback_produces_none_prompt_injection(self):
        """Verify degraded fallback produces suspected_prompt_injection=None."""
        degraded = make_degraded_advisory(
            payment_id="pg_1",
            payer_id="u_1",
            beneficiary_id="b_1",
            amount_paise=1000,
            degraded_reasons=("timeout",),
        )
        self.assertIsNone(degraded.transcript.suspected_prompt_injection)

    # -------------------------------------------------------------------------
    # 9, 10, 11. Security Invariants
    # -------------------------------------------------------------------------

    def test_cannot_authorize_payment_invariant(self):
        """Verify can_authorize_payment=True is rejected."""
        degraded = make_degraded_advisory(
            payment_id="pg_1",
            payer_id="u_1",
            beneficiary_id="b_1",
            amount_paise=1000,
            degraded_reasons=(),
        )
        data = degraded.model_dump()
        data["can_authorize_payment"] = True

        with self.assertRaises(ValidationError):
            RiskSignals.model_validate(data)

    def test_cannot_execute_payment_invariant(self):
        """Verify can_execute_payment=True is rejected."""
        degraded = make_degraded_advisory(
            payment_id="pg_1",
            payer_id="u_1",
            beneficiary_id="b_1",
            amount_paise=1000,
            degraded_reasons=(),
        )
        data = degraded.model_dump()
        data["can_execute_payment"] = True

        with self.assertRaises(ValidationError):
            RiskSignals.model_validate(data)

    def test_advisory_only_false_rejected(self):
        """Verify advisory_only=False is rejected."""
        degraded = make_degraded_advisory(
            payment_id="pg_1",
            payer_id="u_1",
            beneficiary_id="b_1",
            amount_paise=1000,
            degraded_reasons=(),
        )
        data = degraded.model_dump()
        data["advisory_only"] = False

        with self.assertRaises(ValidationError):
            RiskSignals.model_validate(data)

    # -------------------------------------------------------------------------
    # 12, 13, 14. Strict Integer Money Validation
    # -------------------------------------------------------------------------

    def test_fractional_paise_rejected(self):
        """Verify float amount_paise (e.g. 550.50) is rejected."""
        degraded = make_degraded_advisory(
            payment_id="pg_1",
            payer_id="u_1",
            beneficiary_id="b_1",
            amount_paise=1000,
            degraded_reasons=(),
        )
        data = degraded.model_dump()
        data["amount_paise"] = 550.50

        with self.assertRaises(ValidationError) as ctx:
            RiskSignals.model_validate(data)
        self.assertIn("strict integer", str(ctx.exception))

    def test_boolean_paise_rejected(self):
        """Verify boolean amount_paise (e.g. True) is rejected despite bool being int subclass."""
        degraded = make_degraded_advisory(
            payment_id="pg_1",
            payer_id="u_1",
            beneficiary_id="b_1",
            amount_paise=1000,
            degraded_reasons=(),
        )
        data = degraded.model_dump()
        data["amount_paise"] = True

        with self.assertRaises(ValidationError) as ctx:
            RiskSignals.model_validate(data)
        self.assertIn("booleans are rejected", str(ctx.exception))

    def test_numeric_string_paise_rejected(self):
        """Verify numeric string amount_paise (e.g. '50000') is rejected without silent coercion."""
        degraded = make_degraded_advisory(
            payment_id="pg_1",
            payer_id="u_1",
            beneficiary_id="b_1",
            amount_paise=1000,
            degraded_reasons=(),
        )
        data = degraded.model_dump()
        data["amount_paise"] = "50000"

        with self.assertRaises(ValidationError) as ctx:
            RiskSignals.model_validate(data)
        self.assertIn("strict integer", str(ctx.exception))

    # -------------------------------------------------------------------------
    # 15. Immutability & Extra Fields
    # -------------------------------------------------------------------------

    def test_model_immutability(self):
        """Verify RiskSignals models are frozen and reject attribute assignment."""
        degraded = make_degraded_advisory(
            payment_id="pg_1",
            payer_id="u_1",
            beneficiary_id="b_1",
            amount_paise=1000,
            degraded_reasons=(),
        )
        with self.assertRaises(ValidationError):
            degraded.amount_paise = 2000

    def test_extra_fields_forbidden(self):
        """Verify extra unexpected fields are rejected."""
        degraded = make_degraded_advisory(
            payment_id="pg_1",
            payer_id="u_1",
            beneficiary_id="b_1",
            amount_paise=1000,
            degraded_reasons=(),
        )
        data = degraded.model_dump()
        data["bypass_guardian"] = True

        with self.assertRaises(ValidationError) as ctx:
            RiskSignals.model_validate(data)
        self.assertIn("extra_forbidden", str(ctx.exception))

    def test_utc_timestamp_normalization(self):
        """Verify non-UTC timezone-aware timestamp is normalized to UTC."""
        ist = timezone(timedelta(hours=5, minutes=30))
        t_ist = datetime(2026, 11, 11, 20, 0, 0, tzinfo=ist)

        degraded = make_degraded_advisory(
            payment_id="pg_1",
            payer_id="u_1",
            beneficiary_id="b_1",
            amount_paise=1000,
            degraded_reasons=(),
        )
        data = degraded.model_dump()
        data["generated_at"] = t_ist

        validated = RiskSignals.model_validate(data)
        self.assertEqual(validated.generated_at.tzinfo, timezone.utc)
        self.assertEqual(validated.generated_at.hour, 14)
        self.assertEqual(validated.generated_at.minute, 30)

    def test_naive_timestamp_rejected(self):
        """Verify naive datetime (no tzinfo) is rejected."""
        naive_dt = datetime(2026, 11, 11, 14, 30, 0)
        degraded = make_degraded_advisory(
            payment_id="pg_1",
            payer_id="u_1",
            beneficiary_id="b_1",
            amount_paise=1000,
            degraded_reasons=(),
        )
        data = degraded.model_dump()
        data["generated_at"] = naive_dt

        with self.assertRaises(ValidationError) as ctx:
            RiskSignals.model_validate(data)
        self.assertIn("timezone-aware", str(ctx.exception))

    def test_future_timestamp_rejected_beyond_clock_skew(self):
        """Verify future timestamp exceeding 5 min clock skew is rejected."""
        future_dt = datetime.now(timezone.utc) + timedelta(minutes=10)
        degraded = make_degraded_advisory(
            payment_id="pg_1",
            payer_id="u_1",
            beneficiary_id="b_1",
            amount_paise=1000,
            degraded_reasons=(),
        )
        data = degraded.model_dump()
        data["generated_at"] = future_dt

        with self.assertRaises(ValidationError) as ctx:
            RiskSignals.model_validate(data)
        self.assertIn("future beyond acceptable clock skew", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()

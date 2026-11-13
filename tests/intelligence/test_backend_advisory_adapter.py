"""Unit tests for the standalone advisory integration adapter.

Tests cover:
1. Happy-path advisory evaluation delegation.
2. Uninitialized payer behavioral profile handling.
3. Missing optional contexts (graph, velocity, transcript).
4. Unconfigured scoring configuration (None -> honest degraded).
5. Evaluator exception isolation and error diagnostics.
6. Propagated TimeoutError handling without claiming runtime hard-timeout enforcement.
7. Registry high-risk priority preservation.
8. Advisory-only payment safety invariants.
9. Preservation of orchestrator degraded response without conversion to LOW risk.
10. Rejection of invalid request types.
11. Preservation of caller payment context.
12. Sanitized error reporting without raw exception or PII leakage.
13. Rejection of malformed response contract objects.
14. Response context mismatch rejection.
"""

from datetime import datetime, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from intelligence.advisory.adapter import (
    DIAGNOSTIC_CONTEXT_MISMATCH,
    DIAGNOSTIC_INVARIANT_VIOLATION,
    DIAGNOSTIC_TIMEOUT,
    DIAGNOSTIC_UNHANDLED_EXCEPTION,
    evaluate_advisory,
)
from intelligence.advisory.orchestrator import evaluate_risk_signals
from intelligence.advisory.types import (
    AdvisoryRequest,
    AdvisoryResponse,
    AdvisoryScoringConfig,
    RegistryContext,
    VelocityContext,
)
from intelligence.schemas.risk_signals import (
    EvaluationStatus,
    RiskSignals,
    SuggestedCautionLevel,
    make_degraded_advisory,
)


class TestBackendAdvisoryAdapter(unittest.TestCase):
    """Test suite for evaluate_advisory adapter."""

    def _make_base_request(self, **kwargs) -> AdvisoryRequest:
        defaults = {
            "payment_id": "pg_test_adapter_001",
            "payer_id": "payer_test_uuid_001",
            "beneficiary_id": "beneficiary_clean_001",
            "amount_paise": 150000,  # ₹1,500
        }
        defaults.update(kwargs)
        return AdvisoryRequest(**defaults)

    # -------------------------------------------------------------------------
    # 1. Happy Path
    # -------------------------------------------------------------------------
    def test_adapter_happy_path(self):
        """1. Happy path: valid request delegates to orchestrator and returns complete response."""
        scoring = AdvisoryScoringConfig()  # Explicit synthetic test scoring config
        request = self._make_base_request(scoring_config=scoring)

        response = evaluate_advisory(request)

        self.assertIsInstance(response, AdvisoryResponse)
        self.assertIsInstance(response.risk_signals, RiskSignals)
        self.assertEqual(response.risk_signals.evaluation_status, EvaluationStatus.COMPLETE)
        self.assertIsNotNone(response.risk_signals.advisory_score)
        self.assertIsInstance(response.risk_signals.advisory_score, int)
        self.assertIn("registry", response.evaluator_timings_ms)
        self.assertEqual(response.risk_signals.payment_id, "pg_test_adapter_001")
        self.assertEqual(response.risk_signals.payer_id, "payer_test_uuid_001")
        self.assertEqual(response.risk_signals.beneficiary_id, "beneficiary_clean_001")
        self.assertEqual(response.risk_signals.amount_paise, 150000)

    # -------------------------------------------------------------------------
    # 2. Uninitialized Profile
    # -------------------------------------------------------------------------
    def test_adapter_uninitialized_profile(self):
        """2. Uninitialized profile: missing payer history is handled without inventing baseline."""
        scoring = AdvisoryScoringConfig()
        request = self._make_base_request(profile=None, scoring_config=scoring)

        response = evaluate_advisory(request)

        self.assertEqual(response.risk_signals.behavioral.status, "uninitialized")
        self.assertIsNone(response.risk_signals.behavioral.deviation_multiple)
        self.assertIsNone(response.risk_signals.behavioral.is_new_beneficiary)

    # -------------------------------------------------------------------------
    # 3. Missing Optional Inputs
    # -------------------------------------------------------------------------
    def test_adapter_missing_optional_inputs(self):
        """3. Missing optional inputs: graph, velocity, and transcript remain honestly unavailable/absent."""
        scoring = AdvisoryScoringConfig()
        request = self._make_base_request(
            transaction_graph=None,
            velocity_context=None,
            transcript_text=None,
            transcript_consented=False,
            scoring_config=scoring,
        )

        response = evaluate_advisory(request)

        self.assertEqual(response.risk_signals.mule_graph.status, "unperformed")
        self.assertIsNone(response.risk_signals.mule_graph.cluster_risk_score)
        self.assertIsNone(response.risk_signals.mule_graph.hop_distance_to_flagged_mule)

        self.assertEqual(response.risk_signals.velocity.status, "unavailable")
        self.assertIsNone(response.risk_signals.velocity.structuring_suspected)

        self.assertEqual(response.risk_signals.transcript.status, "absent")
        self.assertIsNone(response.risk_signals.transcript.coercion_detected)

    # -------------------------------------------------------------------------
    # 4. Unconfigured Scoring
    # -------------------------------------------------------------------------
    def test_adapter_unconfigured_scoring(self):
        """4. Unconfigured scoring: scoring_config=None preserves orchestrator DEGRADED result."""
        request = self._make_base_request(scoring_config=None)

        response = evaluate_advisory(request)

        self.assertEqual(response.risk_signals.evaluation_status, EvaluationStatus.DEGRADED)
        self.assertIsNone(response.risk_signals.advisory_score)
        self.assertIsNone(response.risk_signals.suggested_caution_level)
        self.assertIn("RC_ADVISORY_SCORE_UNAVAILABLE", response.risk_signals.reason_codes)

    # -------------------------------------------------------------------------
    # 5. Evaluator Exception Isolation
    # -------------------------------------------------------------------------
    def test_adapter_evaluator_exception_isolation(self):
        """5. Exception isolation: unexpected orchestrator crash returns schema-valid degraded response."""
        request = self._make_base_request()

        with patch(
            "intelligence.advisory.adapter.evaluate_risk_signals",
            side_effect=RuntimeError("simulated_crash_with_sensitive_token_XYZ987"),
        ):
            response = evaluate_advisory(request)

        self.assertIsInstance(response, AdvisoryResponse)
        self.assertIsInstance(response.risk_signals, RiskSignals)
        self.assertEqual(response.risk_signals.evaluation_status, EvaluationStatus.DEGRADED)
        self.assertIsNone(response.risk_signals.advisory_score)
        self.assertIsNone(response.risk_signals.suggested_caution_level)
        self.assertIn("RC_ADVISORY_SCORE_UNAVAILABLE", response.risk_signals.reason_codes)
        self.assertIn("RC_ADVISORY_EVALUATION_ERROR", response.risk_signals.reason_codes)
        self.assertEqual(response.warnings, (DIAGNOSTIC_UNHANDLED_EXCEPTION,))

        # Verify no raw exception or sensitive token leakage
        all_text = " ".join(response.warnings) + " " + " ".join(response.risk_signals.degraded_reasons)
        self.assertNotIn("XYZ987", all_text)
        self.assertNotIn("RuntimeError", all_text)

    # -------------------------------------------------------------------------
    # 6. Timeout Exception Handling
    # -------------------------------------------------------------------------
    def test_adapter_timeout_exception_handling(self):
        """6. Timeout handling: propagated TimeoutError produces degraded response without claiming hard timeout."""
        request = self._make_base_request()

        with patch(
            "intelligence.advisory.adapter.evaluate_risk_signals",
            side_effect=TimeoutError("remote_evaluation_hung"),
        ):
            response = evaluate_advisory(request)

        self.assertIsInstance(response, AdvisoryResponse)
        self.assertEqual(response.risk_signals.evaluation_status, EvaluationStatus.DEGRADED)
        self.assertIsNone(response.risk_signals.advisory_score)
        self.assertIn("RC_ADVISORY_SCORE_UNAVAILABLE", response.risk_signals.reason_codes)
        self.assertIn("RC_ADVISORY_EVALUATION_TIMEOUT", response.risk_signals.reason_codes)
        self.assertEqual(response.warnings, (DIAGNOSTIC_TIMEOUT,))

    # -------------------------------------------------------------------------
    # 7. Registry High-Risk Priority
    # -------------------------------------------------------------------------
    def test_adapter_registry_high_risk_priority(self):
        """7. Registry priority: existing orchestrator registry priority is preserved intact."""
        flagged_beneficiary = "flagged_mule_account_99"
        registry_ctx = RegistryContext(
            check_status="performed",
            flagged_beneficiaries={flagged_beneficiary: "confirmed_fraud_ring"},
            registry_category="mule_account",
        )
        scoring = AdvisoryScoringConfig()
        request = self._make_base_request(
            beneficiary_id=flagged_beneficiary,
            registry_context=registry_ctx,
            scoring_config=scoring,
        )

        response = evaluate_advisory(request)

        self.assertTrue(response.risk_signals.registry.is_listed_high_risk)
        self.assertIn(
            response.risk_signals.suggested_caution_level,
            (SuggestedCautionLevel.HIGH, SuggestedCautionLevel.CRITICAL),
        )
        self.assertIn("RC_REGISTRY_HIGH_RISK", response.risk_signals.reason_codes)

    # -------------------------------------------------------------------------
    # 8. Advisory-Only Safety Invariants
    # -------------------------------------------------------------------------
    def test_adapter_safety_invariants(self):
        """8. Safety invariants: every returned RiskSignals preserves advisory-only constants."""
        # A. Normal happy path
        req_normal = self._make_base_request(scoring_config=AdvisoryScoringConfig())
        res_normal = evaluate_advisory(req_normal)
        self.assertIs(res_normal.risk_signals.can_authorize_payment, False)
        self.assertIs(res_normal.risk_signals.can_execute_payment, False)
        self.assertIs(res_normal.risk_signals.advisory_only, True)

        # B. Unconfigured / degraded path
        req_degraded = self._make_base_request(scoring_config=None)
        res_degraded = evaluate_advisory(req_degraded)
        self.assertIs(res_degraded.risk_signals.can_authorize_payment, False)
        self.assertIs(res_degraded.risk_signals.can_execute_payment, False)
        self.assertIs(res_degraded.risk_signals.advisory_only, True)

        # C. Exception path
        with patch("intelligence.advisory.adapter.evaluate_risk_signals", side_effect=Exception("boom")):
            res_error = evaluate_advisory(req_normal)
        self.assertIs(res_error.risk_signals.can_authorize_payment, False)
        self.assertIs(res_error.risk_signals.can_execute_payment, False)
        self.assertIs(res_error.risk_signals.advisory_only, True)

        # D. Malformed invariant violation defense
        # If a mocked orchestrator returned an invalid object attempting to authorize
        invalid_signal = SimpleNamespace(
            can_authorize_payment=True,  # VIOLATION
            can_execute_payment=False,
            advisory_only=True,
        )
        invalid_response = SimpleNamespace(risk_signals=invalid_signal)
        with patch("intelligence.advisory.adapter.evaluate_risk_signals", return_value=invalid_response):
            res_defended = evaluate_advisory(req_normal)
        self.assertIs(res_defended.risk_signals.can_authorize_payment, False)
        self.assertIs(res_defended.risk_signals.can_execute_payment, False)
        self.assertIs(res_defended.risk_signals.advisory_only, True)
        self.assertEqual(res_defended.warnings, (DIAGNOSTIC_INVARIANT_VIOLATION,))

    # -------------------------------------------------------------------------
    # 9. Preserves Existing Degraded Response
    # -------------------------------------------------------------------------
    def test_adapter_preserves_existing_degraded_response(self):
        """9. Degraded preservation: orchestrator degraded output is returned without converting to LOW risk."""
        request = self._make_base_request(scoring_config=None)

        response = evaluate_advisory(request)

        # Must not fabricate score=0 or caution=LOW
        self.assertEqual(response.risk_signals.evaluation_status, EvaluationStatus.DEGRADED)
        self.assertIsNone(response.risk_signals.advisory_score)
        self.assertIsNone(response.risk_signals.suggested_caution_level)
        self.assertIn("RC_ADVISORY_SCORE_UNAVAILABLE", response.risk_signals.reason_codes)
        # Evaluator timings are preserved from the actual sub-evaluator executions
        self.assertIn("registry", response.evaluator_timings_ms)

    # -------------------------------------------------------------------------
    # 10. Rejects Invalid Request Type
    # -------------------------------------------------------------------------
    def test_adapter_rejects_invalid_request_type(self):
        """10. Type guard: non-AdvisoryRequest objects are rejected clearly with TypeError."""
        invalid_inputs = [
            None,
            {},
            {"payment_id": "pg_123"},
            12345,
            "pg_test_request",
            SimpleNamespace(payment_id="pg_fake"),
        ]

        for bad_input in invalid_inputs:
            with self.subTest(bad_input=bad_input):
                with self.assertRaises(TypeError) as ctx:
                    evaluate_advisory(bad_input)
                self.assertIn("Expected request to be an AdvisoryRequest instance", str(ctx.exception))

    # -------------------------------------------------------------------------
    # 11. Preserves Caller Payment Context
    # -------------------------------------------------------------------------
    def test_adapter_preserves_caller_payment_context(self):
        """11. Context integrity: payment_id, payer_id, beneficiary_id, amount_paise are preserved."""
        request = self._make_base_request(
            payment_id="pg_custom_id_777",
            payer_id="payer_uuid_444",
            beneficiary_id="payee_id_999",
            amount_paise=9876543,
            scoring_config=AdvisoryScoringConfig(),
        )

        response = evaluate_advisory(request)

        self.assertEqual(response.risk_signals.payment_id, "pg_custom_id_777")
        self.assertEqual(response.risk_signals.payer_id, "payer_uuid_444")
        self.assertEqual(response.risk_signals.beneficiary_id, "payee_id_999")
        self.assertEqual(response.risk_signals.amount_paise, 9876543)

    # -------------------------------------------------------------------------
    # 12. Consented Transcript Coercion
    # -------------------------------------------------------------------------
    def test_adapter_consented_transcript_coercion_preserved(self):
        """12. Consented transcript: coercion signals are detected and preserved."""
        coercive_transcript = "Police arrest warrant urgent fine immediately. Do not hang up."
        request = self._make_base_request(
            transcript_text=coercive_transcript,
            transcript_consented=True,
            scoring_config=AdvisoryScoringConfig(),
        )

        response = evaluate_advisory(request)

        self.assertEqual(response.risk_signals.transcript.status, "evaluated")
        self.assertTrue(response.risk_signals.transcript.coercion_detected)
        self.assertIn("RC_COERCION_TRANSCRIPT", response.risk_signals.reason_codes)

    # -------------------------------------------------------------------------
    # 13. Malformed Response Contract Rejection
    # -------------------------------------------------------------------------
    def test_adapter_malformed_response_object_rejected(self):
        """13. Contract validation: malformed outer or inner response objects produce degraded AdvisoryResponse."""
        req = self._make_base_request(scoring_config=AdvisoryScoringConfig())

        # Case A: Object has risk_signals attribute with correct booleans, but outer object is not AdvisoryResponse
        fake_signals_correct_flags = SimpleNamespace(
            can_authorize_payment=False,
            can_execute_payment=False,
            advisory_only=True,
        )
        fake_outer = SimpleNamespace(risk_signals=fake_signals_correct_flags, evaluator_timings_ms={})
        with patch("intelligence.advisory.adapter.evaluate_risk_signals", return_value=fake_outer):
            res_a = evaluate_advisory(req)

        self.assertIsInstance(res_a, AdvisoryResponse)
        self.assertNotIsInstance(res_a, SimpleNamespace)
        self.assertIsInstance(res_a.risk_signals, RiskSignals)
        self.assertEqual(res_a.risk_signals.evaluation_status, EvaluationStatus.DEGRADED)
        self.assertEqual(res_a.warnings, (DIAGNOSTIC_INVARIANT_VIOLATION,))
        self.assertIn("RC_ADVISORY_INVARIANT_VIOLATION", res_a.risk_signals.reason_codes)

        # Case B: Outer object is an AdvisoryResponse, but response.risk_signals is not a RiskSignals instance
        malformed_resp = object.__new__(AdvisoryResponse)
        object.__setattr__(malformed_resp, "risk_signals", {"not_a": "RiskSignals_instance"})
        object.__setattr__(malformed_resp, "evaluator_timings_ms", {})
        object.__setattr__(malformed_resp, "warnings", ())
        with patch("intelligence.advisory.adapter.evaluate_risk_signals", return_value=malformed_resp):
            res_b = evaluate_advisory(req)

        self.assertIsInstance(res_b, AdvisoryResponse)
        self.assertIsInstance(res_b.risk_signals, RiskSignals)
        self.assertEqual(res_b.risk_signals.evaluation_status, EvaluationStatus.DEGRADED)
        self.assertEqual(res_b.warnings, (DIAGNOSTIC_INVARIANT_VIOLATION,))
        self.assertIn("RC_ADVISORY_INVARIANT_VIOLATION", res_b.risk_signals.reason_codes)

        # Case C: Outer object has a genuine RiskSignals instance, but outer object itself is not an AdvisoryResponse
        real_signals = make_degraded_advisory(
            payment_id="pg_test_adapter_001",
            payer_id="payer_test_uuid_001",
            beneficiary_id="beneficiary_clean_001",
            amount_paise=150000,
            degraded_reasons=("synthetic_test",),
        )
        non_advisory_outer = SimpleNamespace(risk_signals=real_signals, evaluator_timings_ms={})
        with patch("intelligence.advisory.adapter.evaluate_risk_signals", return_value=non_advisory_outer):
            res_c = evaluate_advisory(req)

        self.assertIsInstance(res_c, AdvisoryResponse)
        self.assertNotIsInstance(res_c, SimpleNamespace)
        self.assertIsInstance(res_c.risk_signals, RiskSignals)
        self.assertEqual(res_c.risk_signals.evaluation_status, EvaluationStatus.DEGRADED)
        self.assertEqual(res_c.warnings, (DIAGNOSTIC_INVARIANT_VIOLATION,))

    # -------------------------------------------------------------------------
    # 14. Response Context Mismatch Rejection
    # -------------------------------------------------------------------------
    def test_adapter_context_mismatch_rejection(self):
        """14. Context validation: mismatched payment_id, payer_id, beneficiary_id, or amount degrades cleanly."""
        req = self._make_base_request(
            payment_id="pg_orig_123",
            payer_id="payer_orig_456",
            beneficiary_id="beneficiary_orig_789",
            amount_paise=250000,
            scoring_config=AdvisoryScoringConfig(),
        )

        # Baseline valid response from real orchestrator
        valid_resp = evaluate_risk_signals(req)
        self.assertEqual(valid_resp.risk_signals.evaluation_status, EvaluationStatus.COMPLETE)

        mismatches = [
            ("payment_id", {"payment_id": "pg_tampered_999"}),
            ("payer_id", {"payer_id": "payer_tampered_999"}),
            ("beneficiary_id", {"beneficiary_id": "beneficiary_tampered_999"}),
            ("amount_paise", {"amount_paise": 99999999}),
        ]

        for field_name, update_dict in mismatches:
            with self.subTest(mismatched_field=field_name):
                # Construct an otherwise valid response with exactly one mismatched context field
                mismatched_signals = valid_resp.risk_signals.model_copy(update=update_dict)
                mismatched_resp = AdvisoryResponse(
                    risk_signals=mismatched_signals,
                    evaluator_timings_ms=valid_resp.evaluator_timings_ms,
                    warnings=valid_resp.warnings,
                )

                with patch("intelligence.advisory.adapter.evaluate_risk_signals", return_value=mismatched_resp):
                    res = evaluate_advisory(req)

                # 1. Output is an AdvisoryResponse
                self.assertIsInstance(res, AdvisoryResponse)
                # 2. risk_signals is a RiskSignals instance
                self.assertIsInstance(res.risk_signals, RiskSignals)
                # 3. evaluation_status is DEGRADED
                self.assertEqual(res.risk_signals.evaluation_status, EvaluationStatus.DEGRADED)
                # 4. advisory_score is None
                self.assertIsNone(res.risk_signals.advisory_score)
                # 5. suggested_caution_level is None
                self.assertIsNone(res.risk_signals.suggested_caution_level)
                # 6. Reason codes contain expected markers
                self.assertIn("RC_ADVISORY_SCORE_UNAVAILABLE", res.risk_signals.reason_codes)
                self.assertIn("RC_ADVISORY_CONTEXT_MISMATCH", res.risk_signals.reason_codes)
                # 7. Warning is the sanitized diagnostic
                self.assertEqual(res.warnings, (DIAGNOSTIC_CONTEXT_MISMATCH,))
                # 8. All four returned context fields match the ORIGINAL request
                self.assertEqual(res.risk_signals.payment_id, req.payment_id)
                self.assertEqual(res.risk_signals.payer_id, req.payer_id)
                self.assertEqual(res.risk_signals.beneficiary_id, req.beneficiary_id)
                self.assertEqual(res.risk_signals.amount_paise, req.amount_paise)
                # 9. All three advisory-only invariants are preserved
                self.assertIs(res.risk_signals.can_authorize_payment, False)
                self.assertIs(res.risk_signals.can_execute_payment, False)
                self.assertIs(res.risk_signals.advisory_only, True)


if __name__ == "__main__":
    unittest.main()

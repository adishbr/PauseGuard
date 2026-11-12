"""Unified Advisory Orchestrator for PauseGuard V2.

Composes behavioral, velocity, registry, mule graph, and transcript
evaluators into a validated RiskSignals advisory envelope.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from time import perf_counter
from typing import Optional

from intelligence.schemas.risk_signals import (
    AccountProfileType,
    BehavioralSignal,
    CalculationMethod,
    DataOrigin,
    EvaluationStatus,
    MuleGraphSignal,
    RegistrySignal,
    RiskSignals,
    SuggestedCautionLevel,
    SignalProvenance,
    SourceCategory,
    TranscriptCoercionSignal,
    VelocitySignal,
)
from intelligence.behavioral.baseline_evaluator import evaluate_behavioral_baseline
from intelligence.mule_graph.graph_proximity import evaluate_mule_proximity
from intelligence.advisory.types import (
    AdvisoryRequest,
    AdvisoryResponse,
    AdvisoryScoringConfig,
    RegistryContext,
)
from intelligence.advisory.velocity_evaluator import evaluate_velocity
from intelligence.advisory.transcript_evaluator import evaluate_transcript
from synthetic_data.generator import load_mock_registry_with_status


@dataclass(frozen=True)
class _EvaluatorResult:
    """Internal result from a single evaluator."""
    name: str
    signal: object
    elapsed_ms: float
    error: Optional[str] = None


class _AdvisoryScorer:
    """Injectable advisory scoring strategy.

    When an explicit scoring configuration is provided, computes weighted
    advisory score and caution level.
    """

    def __init__(self, config: Optional[AdvisoryScoringConfig] = None):
        self.config = config

    def compute_score_and_caution(
        self,
        behavioral: object,
        velocity: object,
        registry: RegistrySignal,
        mule_graph: object,
        transcript: object,
    ) -> tuple[Optional[int], Optional[SuggestedCautionLevel], tuple[str, ...]]:
        """Compute aggregate advisory score and caution level.

        Returns (advisory_score, suggested_caution_level, reason_codes).
        If scoring is not configured, returns (None, None, reason_codes).
        """
        reasons: list[str] = []

        if registry.is_listed_high_risk is True:
            reasons.append("RC_REGISTRY_HIGH_RISK")

        if self.config is None:
            return None, None, tuple(reasons)

        score = 0
        total_weight = 0.0

        if getattr(behavioral, "status", None) == "evaluated" and getattr(behavioral, "deviation_multiple", None) is not None:
            dev = behavioral.deviation_multiple
            if dev > 10:
                score += int(self.config.behavioral_weight * 40)
                reasons.append("RC_LARGE_DEVIATION")
            elif dev > 3:
                score += int(self.config.behavioral_weight * 25)
                reasons.append("RC_MODERATE_DEVIATION")
            elif dev > 1.5:
                score += int(self.config.behavioral_weight * 10)
                reasons.append("RC_SLIGHT_DEVIATION")
            total_weight += self.config.behavioral_weight
            if getattr(behavioral, "is_new_beneficiary", False):
                score += int(self.config.behavioral_weight * 5)
                reasons.append("RC_NEW_BENEFICIARY")

        if getattr(velocity, "status", None) == "evaluated" and getattr(velocity, "structuring_suspected", None) is True:
            score += int(self.config.velocity_weight * 30)
            reasons.append("RC_STRUCTURING_SUSPECTED")
            total_weight += self.config.velocity_weight

        if getattr(mule_graph, "status", None) == "evaluated" and getattr(mule_graph, "cluster_risk_score", None) is not None:
            graph_score = mule_graph.cluster_risk_score
            if graph_score >= 50:
                score += int(self.config.mule_graph_weight * 35)
                reasons.append("RC_MULE_GRAPH_PROXIMITY")
            elif graph_score >= 25:
                score += int(self.config.mule_graph_weight * 20)
                reasons.append("RC_MULE_GRAPH_ADJACENT")
            total_weight += self.config.mule_graph_weight

        if getattr(transcript, "status", None) == "evaluated":
            if getattr(transcript, "coercion_detected", None) is True:
                score += int(self.config.transcript_weight * 40)
                reasons.append("RC_COERCION_TRANSCRIPT")
            if getattr(transcript, "suspected_prompt_injection", None) is True:
                score += int(self.config.transcript_weight * 20)
                reasons.append("RC_PROMPT_INJECTION_SUSPECTED")
            total_weight += self.config.transcript_weight

        # Add contribution from positive registry if applicable
        if registry.is_listed_high_risk is True:
            score += int(self.config.registry_weight * 40)
            total_weight += self.config.registry_weight

        if total_weight > 0:
            score = min(100, int(score / total_weight * 100))
        else:
            score = 0

        # Normal caution mapping from score
        if score <= self.config.score_low_max:
            caution = SuggestedCautionLevel.LOW
        elif score <= self.config.score_medium_max:
            caution = SuggestedCautionLevel.MEDIUM
        elif score <= self.config.score_high_max:
            caution = SuggestedCautionLevel.HIGH
        else:
            caution = SuggestedCautionLevel.CRITICAL

        # Registry Priority Rule:
        # A positive registry match must never receive LOW or MEDIUM in a COMPLETE response.
        # HIGH is the minimum advisory caution. Preserve HIGH or CRITICAL when supplied.
        # Do not force CRITICAL.
        if registry.is_listed_high_risk is True:
            if caution in (SuggestedCautionLevel.LOW, SuggestedCautionLevel.MEDIUM):
                caution = SuggestedCautionLevel.HIGH

        return score, caution, tuple(reasons)


def _evaluate_registry(
    request: AdvisoryRequest,
    registry_context: Optional[RegistryContext],
) -> tuple[RegistrySignal, Optional[str]]:
    """Evaluate registry signal with full exception isolation.

    Returns:
        (RegistrySignal, Optional[error_string])
    """
    if registry_context is not None:
        if registry_context.check_status == "performed":
            is_listed = request.beneficiary_id in registry_context.flagged_beneficiaries
            category = registry_context.registry_category if is_listed else None
            signal = RegistrySignal(
                check_status="performed",
                is_listed_high_risk=is_listed,
                registry_category=category,
                provenance=SignalProvenance(
                    source_category=SourceCategory.TRUSTED_SOURCE,
                    data_origin=DataOrigin.MOCK_REGISTRY_TABLE,
                    calculation_method=CalculationMethod.DETERMINISTIC_LOOKUP,
                    is_synthetic=True,
                ),
            )
            return signal, None
        else:
            signal = RegistrySignal(
                check_status=registry_context.check_status,
                is_listed_high_risk=None,
                registry_category=None,
                provenance=SignalProvenance(
                    source_category=SourceCategory.TRUSTED_SOURCE,
                    data_origin=DataOrigin.UNAVAILABLE,
                    calculation_method=CalculationMethod.UNPERFORMED,
                    is_synthetic=True,
                ),
            )
            return signal, None

    # Fallback to repository mock registry fixture with exception safety
    try:
        flagged_dict, check_status = load_mock_registry_with_status()
        if check_status == "performed" and flagged_dict is not None:
            is_listed = request.beneficiary_id in flagged_dict
            signal = RegistrySignal(
                check_status="performed",
                is_listed_high_risk=is_listed,
                registry_category="confirmed_mule" if is_listed else None,
                provenance=SignalProvenance(
                    source_category=SourceCategory.TRUSTED_SOURCE,
                    data_origin=DataOrigin.MOCK_REGISTRY_TABLE,
                    calculation_method=CalculationMethod.DETERMINISTIC_LOOKUP,
                    is_synthetic=True,
                ),
            )
            return signal, None
        else:
            signal = RegistrySignal(
                check_status="unavailable",
                is_listed_high_risk=None,
                registry_category=None,
                provenance=SignalProvenance(
                    source_category=SourceCategory.TRUSTED_SOURCE,
                    data_origin=DataOrigin.UNAVAILABLE,
                    calculation_method=CalculationMethod.UNPERFORMED,
                    is_synthetic=True,
                ),
            )
            return signal, None
    except Exception as exc:
        err_msg = f"registry_evaluator_failed: {exc}"
        signal = RegistrySignal(
            check_status="unavailable",
            is_listed_high_risk=None,
            registry_category=None,
            provenance=SignalProvenance(
                source_category=SourceCategory.TRUSTED_SOURCE,
                data_origin=DataOrigin.UNAVAILABLE,
                calculation_method=CalculationMethod.UNPERFORMED,
                is_synthetic=True,
            ),
        )
        return signal, err_msg


def evaluate_risk_signals(
    request: AdvisoryRequest,
    scoring_config: Optional[AdvisoryScoringConfig] = None,
) -> AdvisoryResponse:
    """Unified advisory evaluation entry point.

    Composes all sub-signals into a validated RiskSignals envelope.

    Args:
        request: Validated AdvisoryRequest containing payment context and evaluators input.
        scoring_config: Optional advisory scoring configuration. Defaults to None.
                       When None, returns honest degraded aggregate status without
                       fabricating scores or caution levels.

    Returns:
        AdvisoryResponse containing validated RiskSignals and timing metadata.
    """
    overall_start = perf_counter()
    evaluator_timings: dict[str, float] = {}
    warnings: list[str] = []
    evaluator_results: list[_EvaluatorResult] = []

    # Determine effective scoring strategy (request attribute or argument)
    effective_scoring_config = scoring_config if scoring_config is not None else request.scoring_config

    # 1. Registry Evaluation (Isolated with error handling)
    reg_start = perf_counter()
    registry_signal, reg_error = _evaluate_registry(request, request.registry_context)
    reg_elapsed = (perf_counter() - reg_start) * 1000
    evaluator_timings["registry"] = reg_elapsed
    if reg_error:
        warnings.append(reg_error)
    evaluator_results.append(_EvaluatorResult(
        name="registry",
        signal=registry_signal,
        elapsed_ms=reg_elapsed,
        error=reg_error,
    ))

    # 2. Behavioral Baseline Evaluation
    beh_start = perf_counter()
    try:
        behavioral_signal = evaluate_behavioral_baseline(
            profile=request.profile,
            beneficiary_id=request.beneficiary_id,
            amount_paise=request.amount_paise,
        )
        beh_elapsed = (perf_counter() - beh_start) * 1000
        evaluator_timings["behavioral"] = beh_elapsed
        evaluator_results.append(_EvaluatorResult(
            name="behavioral",
            signal=behavioral_signal,
            elapsed_ms=beh_elapsed,
        ))
    except Exception as e:
        beh_elapsed = (perf_counter() - beh_start) * 1000
        evaluator_timings["behavioral"] = beh_elapsed
        warnings.append(f"behavioral_evaluator_failed: {e}")
        behavioral_signal = BehavioralSignal(
            status="unavailable",
            profile_type=None,
            baseline_median_paise=None,
            deviation_multiple=None,
            is_new_beneficiary=None,
            prior_transfers_count=None,
            provenance=SignalProvenance(
                source_category=SourceCategory.MODEL_INFERENCE,
                data_origin=DataOrigin.UNAVAILABLE,
                calculation_method=CalculationMethod.UNPERFORMED,
                is_synthetic=True,
            ),
        )
        evaluator_results.append(_EvaluatorResult(
            name="behavioral",
            signal=behavioral_signal,
            elapsed_ms=beh_elapsed,
            error=str(e),
        ))

    # 3. Velocity Evaluation
    try:
        velocity_result = evaluate_velocity(request.velocity_context)
        velocity_signal = velocity_result.signal
        evaluator_timings["velocity"] = velocity_result.elapsed_ms
        evaluator_results.append(_EvaluatorResult(
            name="velocity",
            signal=velocity_signal,
            elapsed_ms=velocity_result.elapsed_ms,
        ))
    except Exception as e:
        warnings.append(f"velocity_evaluator_failed: {e}")
        evaluator_timings["velocity"] = 0.1
        velocity_signal = VelocitySignal(
            status="unavailable",
            rolling_window_minutes=None,
            attempts_in_window=None,
            total_amount_paise_in_window=None,
            structuring_suspected=None,
            provenance=SignalProvenance(
                source_category=SourceCategory.TRUSTED_SOURCE,
                data_origin=DataOrigin.UNAVAILABLE,
                calculation_method=CalculationMethod.UNPERFORMED,
                is_synthetic=True,
            ),
        )
        evaluator_results.append(_EvaluatorResult(
            name="velocity",
            signal=velocity_signal,
            elapsed_ms=0.1,
            error=str(e),
        ))

    # 4. Mule Graph Evaluation
    mg_start = perf_counter()
    try:
        mule_graph_signal = evaluate_mule_proximity(
            graph=request.transaction_graph,
            beneficiary_id=request.beneficiary_id,
        )
        mg_elapsed = (perf_counter() - mg_start) * 1000
        evaluator_timings["mule_graph"] = mg_elapsed
        evaluator_results.append(_EvaluatorResult(
            name="mule_graph",
            signal=mule_graph_signal,
            elapsed_ms=mg_elapsed,
        ))
    except Exception as e:
        mg_elapsed = (perf_counter() - mg_start) * 1000
        evaluator_timings["mule_graph"] = mg_elapsed
        warnings.append(f"mule_graph_evaluator_failed: {e}")
        mule_graph_signal = MuleGraphSignal(
            status="unavailable",
            in_degree_incoming_unique_payers=None,
            hop_distance_to_flagged_mule=None,
            cluster_risk_score=None,
            provenance=SignalProvenance(
                source_category=SourceCategory.MODEL_INFERENCE,
                data_origin=DataOrigin.UNAVAILABLE,
                calculation_method=CalculationMethod.UNPERFORMED,
                is_synthetic=True,
            ),
        )
        evaluator_results.append(_EvaluatorResult(
            name="mule_graph",
            signal=mule_graph_signal,
            elapsed_ms=mg_elapsed,
            error=str(e),
        ))

    # 5. Transcript Coercion Evaluation
    try:
        transcript_result = evaluate_transcript(
            transcript_text=request.transcript_text,
            transcript_consented=request.transcript_consented,
        )
        transcript_signal = transcript_result.signal
        evaluator_timings["transcript"] = transcript_result.elapsed_ms
        evaluator_results.append(_EvaluatorResult(
            name="transcript",
            signal=transcript_signal,
            elapsed_ms=transcript_result.elapsed_ms,
        ))
    except Exception as e:
        warnings.append(f"transcript_evaluator_failed: {e}")
        evaluator_timings["transcript"] = 0.1
        transcript_signal = TranscriptCoercionSignal(
            status="unavailable",
            coercion_detected=None,
            coercion_indicators=(),
            suspected_prompt_injection=None,
            provenance=SignalProvenance(
                source_category=SourceCategory.MODEL_INFERENCE,
                data_origin=DataOrigin.UNAVAILABLE,
                calculation_method=CalculationMethod.UNPERFORMED,
                is_synthetic=True,
            ),
        )
        evaluator_results.append(_EvaluatorResult(
            name="transcript",
            signal=transcript_signal,
            elapsed_ms=0.1,
            error=str(e),
        ))

    has_errors = any(er.error for er in evaluator_results)

    required_signals = ["behavioral", "registry"]
    optional_signals = ["velocity", "mule_graph", "transcript"]

    def _get_signal_status(signal, name: str) -> str:
        """Get the appropriate status field for each signal type."""
        if name == "registry":
            return getattr(signal, "check_status", None)
        return getattr(signal, "status", None)

    required_evaluated = all(
        _get_signal_status(er.signal, er.name) in ("evaluated", "uninitialized", "performed", "bypassed_in_lab")
        for er in evaluator_results
        if er.name in required_signals
    )
    optional_valid = all(
        _get_signal_status(er.signal, er.name) in ("evaluated", "unavailable", "unperformed", "absent", "unconsented")
        for er in evaluator_results
        if er.name in optional_signals
    )

    # Determine status & reasons
    degraded_reasons_list: list[str] = []
    if has_errors:
        for er in evaluator_results:
            if er.error:
                degraded_reasons_list.append(er.error)

    if not required_evaluated or not optional_valid:
        for er in evaluator_results:
            st = _get_signal_status(er.signal, er.name)
            if er.name in required_signals and st not in ("evaluated", "uninitialized", "performed", "bypassed_in_lab"):
                degraded_reasons_list.append(f"{er.name}_status_{st}")
            elif er.name in optional_signals and st not in ("evaluated", "unavailable", "unperformed", "absent", "unconsented"):
                degraded_reasons_list.append(f"{er.name}_status_{st}")

    if effective_scoring_config is None:
        degraded_reasons_list.append("aggregate_scoring_strategy_unconfigured")

    if degraded_reasons_list:
        evaluation_status = EvaluationStatus.DEGRADED
        degraded_reasons = tuple(degraded_reasons_list)
    else:
        evaluation_status = EvaluationStatus.COMPLETE
        degraded_reasons = ()

    # Score and caution calculation
    scorer = _AdvisoryScorer(config=effective_scoring_config)
    advisory_score, suggested_caution, reason_codes_tuple = scorer.compute_score_and_caution(
        behavioral_signal,
        velocity_signal,
        registry_signal,
        mule_graph_signal,
        transcript_signal,
    )

    reason_codes = list(reason_codes_tuple)

    # In DEGRADED state: enforce null score and caution; prepend explanatory reason code
    if evaluation_status != EvaluationStatus.COMPLETE:
        advisory_score = None
        suggested_caution = None
        if "RC_ADVISORY_SCORE_UNAVAILABLE" not in reason_codes:
            reason_codes.insert(0, "RC_ADVISORY_SCORE_UNAVAILABLE")
    elif not reason_codes:
        reason_codes = ["RC_NO_RISK_INDICATORS"]

    risk_signals = RiskSignals(
        schema_version="2.0.0",
        data_environment="synthetic_lab",
        model_name="pauseguard-heuristics-engine",
        model_version="0.1.0-alpha",
        generated_at=datetime.now(timezone.utc),
        evaluation_latency_ms=(perf_counter() - overall_start) * 1000,
        evaluation_status=evaluation_status,
        degraded_reasons=degraded_reasons,
        payment_id=request.payment_id,
        payer_id=request.payer_id,
        beneficiary_id=request.beneficiary_id,
        amount_paise=request.amount_paise,
        advisory_score=advisory_score,
        calibrated_fraud_probability=None,
        calibration_caveat="Advisory heuristic score derived from synthetic/rule baselines; not a real-world calibrated probability.",
        suggested_caution_level=suggested_caution,
        reason_codes=tuple(reason_codes),
        behavioral=behavioral_signal,
        velocity=velocity_signal,
        registry=registry_signal,
        mule_graph=mule_graph_signal,
        transcript=transcript_signal,
        can_authorize_payment=False,
        can_execute_payment=False,
        advisory_only=True,
    )

    return AdvisoryResponse(
        risk_signals=risk_signals,
        evaluator_timings_ms=evaluator_timings,
        warnings=tuple(warnings),
    )

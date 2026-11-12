"""Velocity / Structuring Evaluator for PauseGuard V2.

Evaluates short-term payment frequency and smurfing indicators
using backend-provided measurement context.
"""

from dataclasses import dataclass
from time import perf_counter
from typing import Optional

from intelligence.schemas.risk_signals import (
    CalculationMethod,
    DataOrigin,
    SignalProvenance,
    SourceCategory,
    VelocitySignal,
)
from intelligence.advisory.types import VelocityContext


@dataclass(frozen=True)
class VelocityEvaluationResult:
    """Result of velocity evaluation with timing."""
    signal: VelocitySignal
    elapsed_ms: float


def evaluate_velocity(velocity_context: Optional[VelocityContext]) -> VelocityEvaluationResult:
    """Evaluate velocity/structuring signal from measurement context.

    Args:
        velocity_context: Backend-provided velocity measurements and optional
                         structuring classification thresholds.

    Returns:
        VelocityEvaluationResult with validated VelocitySignal and timing.
    """
    start = perf_counter()

    if velocity_context is None:
        signal = VelocitySignal(
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
        return VelocityEvaluationResult(signal=signal, elapsed_ms=(perf_counter() - start) * 1000)

    structuring_suspected: Optional[bool] = None
    if (
        velocity_context.structuring_threshold_attempts is not None
        and velocity_context.structuring_threshold_amount_paise is not None
    ):
        structuring_suspected = (
            velocity_context.attempts_in_window >= velocity_context.structuring_threshold_attempts
            and velocity_context.total_amount_paise_in_window >= velocity_context.structuring_threshold_amount_paise
        )

    signal = VelocitySignal(
        status="evaluated",
        rolling_window_minutes=velocity_context.rolling_window_minutes,
        attempts_in_window=velocity_context.attempts_in_window,
        total_amount_paise_in_window=velocity_context.total_amount_paise_in_window,
        structuring_suspected=structuring_suspected,
        provenance=SignalProvenance(
            source_category=SourceCategory.TRUSTED_SOURCE,
            data_origin=DataOrigin.MOCK_LEDGER_HISTORY,
            calculation_method=CalculationMethod.HEURISTIC_RULE_ENGINE,
            is_synthetic=True,
        ),
    )

    elapsed = (perf_counter() - start) * 1000
    return VelocityEvaluationResult(signal=signal, elapsed_ms=elapsed)

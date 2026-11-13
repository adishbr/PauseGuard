"""Standalone advisory integration adapter for PauseGuard V2.

This module provides a clean, decoupled adapter boundary wrapping Member 3's
Fraud Intelligence Advisory Orchestrator. It enforces strict type checking,
exception isolation, sanitized diagnostic reporting, and non-negotiable
payment-safety invariants.

SECURITY INVARIANTS:
1. Advisory Only: can_authorize_payment=False, can_execute_payment=False, advisory_only=True.
2. AI Advisory compute NEVER approves, rejects, or executes payments.
3. No database connection, no state mutation, no payment ledger debits.
4. Failure Isolation: Unhandled evaluator exceptions fail closed into schema-valid degraded responses.
5. Synchronous Execution: The underlying orchestrator is synchronous; propagated TimeoutErrors are
   handled safely as degraded states, but hard runtime timeout enforcement is an orthogonal backend concern.
"""

from typing import Final

from intelligence.advisory.orchestrator import evaluate_risk_signals
from intelligence.advisory.types import AdvisoryRequest, AdvisoryResponse
from intelligence.schemas.risk_signals import RiskSignals, make_degraded_advisory


# Stable sanitized diagnostic codes
DIAGNOSTIC_TIMEOUT: Final[str] = "advisory_evaluation_timeout"
DIAGNOSTIC_UNHANDLED_EXCEPTION: Final[str] = "advisory_evaluator_unhandled_exception"
DIAGNOSTIC_INVARIANT_VIOLATION: Final[str] = "advisory_response_safety_invariant_violation"


def evaluate_advisory(request: AdvisoryRequest) -> AdvisoryResponse:
    """Evaluate multidimensional advisory risk signals with full exception isolation.

    Wraps the existing Member 3 advisory orchestrator, ensuring that unexpected
    evaluator exceptions or propagated timeouts degrade gracefully without
    crashing the caller or producing unsafe fallback decisions.

    Args:
        request: Validated AdvisoryRequest containing payment context and evaluators input.

    Returns:
        AdvisoryResponse containing validated RiskSignals and timing metadata.

    Raises:
        TypeError: If request is not an instance of AdvisoryRequest.
    """
    if not isinstance(request, AdvisoryRequest):
        raise TypeError(
            f"Expected request to be an AdvisoryRequest instance, got {type(request).__name__}"
        )

    try:
        response = evaluate_risk_signals(request)

        # Defensive contract and invariant verification on returned response
        if (
            not isinstance(response, AdvisoryResponse)
            or not isinstance(getattr(response, "risk_signals", None), RiskSignals)
            or response.risk_signals.can_authorize_payment is not False
            or response.risk_signals.can_execute_payment is not False
            or response.risk_signals.advisory_only is not True
        ):
            degraded_signals = make_degraded_advisory(
                payment_id=request.payment_id,
                payer_id=request.payer_id,
                beneficiary_id=request.beneficiary_id,
                amount_paise=request.amount_paise,
                degraded_reasons=(DIAGNOSTIC_INVARIANT_VIOLATION,),
                reason_codes=(
                    "RC_ADVISORY_SCORE_UNAVAILABLE",
                    "RC_ADVISORY_INVARIANT_VIOLATION",
                ),
            )
            return AdvisoryResponse(
                risk_signals=degraded_signals,
                evaluator_timings_ms={},
                warnings=(DIAGNOSTIC_INVARIANT_VIOLATION,),
            )

        return response

    except TimeoutError:
        degraded_signals = make_degraded_advisory(
            payment_id=request.payment_id,
            payer_id=request.payer_id,
            beneficiary_id=request.beneficiary_id,
            amount_paise=request.amount_paise,
            degraded_reasons=(DIAGNOSTIC_TIMEOUT,),
            reason_codes=(
                "RC_ADVISORY_SCORE_UNAVAILABLE",
                "RC_ADVISORY_EVALUATION_TIMEOUT",
            ),
        )
        return AdvisoryResponse(
            risk_signals=degraded_signals,
            evaluator_timings_ms={},
            warnings=(DIAGNOSTIC_TIMEOUT,),
        )

    except Exception:
        degraded_signals = make_degraded_advisory(
            payment_id=request.payment_id,
            payer_id=request.payer_id,
            beneficiary_id=request.beneficiary_id,
            amount_paise=request.amount_paise,
            degraded_reasons=(DIAGNOSTIC_UNHANDLED_EXCEPTION,),
            reason_codes=(
                "RC_ADVISORY_SCORE_UNAVAILABLE",
                "RC_ADVISORY_EVALUATION_ERROR",
            ),
        )
        return AdvisoryResponse(
            risk_signals=degraded_signals,
            evaluator_timings_ms={},
            warnings=(DIAGNOSTIC_UNHANDLED_EXCEPTION,),
        )

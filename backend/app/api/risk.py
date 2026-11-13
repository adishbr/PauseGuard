"""FastAPI router for AI and rule-based risk advisory evaluations.

Endpoints:
- POST /risk/advice: Evaluate behavioral, velocity, registry, mule graph, and transcript indicators.
"""

from typing import Annotated
from fastapi import APIRouter, Depends, status

from app.auth.dependencies import get_current_actor
from app.auth.schemas import RiskAdviceRequest, RiskAdviceResponse
from app.services.payment_guards import TrustedActorContext
from intelligence.advisory.adapter import evaluate_advisory
from intelligence.advisory.types import AdvisoryRequest, AdvisoryResponse, get_default_scoring_config
from intelligence.schemas.risk_signals import make_degraded_advisory

router = APIRouter(prefix="/api/v2/risk", tags=["risk"])


@router.post("/advice", response_model=RiskAdviceResponse, status_code=status.HTTP_200_OK)
def get_risk_advice(
    actor: Annotated[TrustedActorContext, Depends(get_current_actor)],
    request: RiskAdviceRequest,
) -> RiskAdviceResponse:
    """Evaluate multidimensional advisory risk signals for a proposed transaction.

    SECURITY INVARIANTS:
    1. AI advisory signals provide decision support only.
    2. Signals CANNOT authorize, execute, or override hard payment blocks (can_authorize_payment=False).
    3. Evaluator exceptions and timeouts fail closed into schema-valid degraded responses.
    """
    adv_req = AdvisoryRequest(
        payment_id=request.payment_id,
        payer_id=str(actor.user_id),
        beneficiary_id=request.beneficiary_id,
        amount_paise=request.amount_paise,
        transcript_text=request.transcript_text,
        transcript_consented=request.transcript_consented,
        scoring_config=get_default_scoring_config(),
    )

    try:
        adv_res = evaluate_advisory(adv_req)
    except Exception:
        degraded_signals = make_degraded_advisory(
            payment_id=request.payment_id,
            payer_id=str(actor.user_id),
            beneficiary_id=request.beneficiary_id,
            amount_paise=request.amount_paise,
            degraded_reasons=("advisory_evaluator_unhandled_exception",),
            reason_codes=(
                "RC_ADVISORY_SCORE_UNAVAILABLE",
                "RC_ADVISORY_EVALUATION_ERROR",
            ),
        )
        adv_res = AdvisoryResponse(
            risk_signals=degraded_signals,
            evaluator_timings_ms={},
            warnings=("advisory_evaluator_unhandled_exception",),
        )

    sig = adv_res.risk_signals

    caution_level = (
        sig.suggested_caution_level.value
        if hasattr(sig.suggested_caution_level, "value")
        else (str(sig.suggested_caution_level) if sig.suggested_caution_level else None)
    )
    eval_status = (
        sig.evaluation_status.value
        if hasattr(sig.evaluation_status, "value")
        else str(sig.evaluation_status)
    )

    return RiskAdviceResponse(
        payment_id=request.payment_id,
        advisory_score=sig.advisory_score,
        suggested_caution_level=caution_level,
        reason_codes=list(sig.reason_codes),
        can_authorize_payment=False,
        evaluation_status=eval_status,
        calibration_caveat=sig.calibration_caveat,
    )


"""FastAPI router for Phase 3 payment state machine and review endpoints.

Endpoints:
- POST /payments: Payer creates a risk-evaluated mock payment.
- GET  /payments/{id}: Retrieve payment view (full for payer, redacted for guardian).
- POST /payments/{id}/guardian/decision: Assigned guardian submits time-bound decision.
- POST /payments/{id}/fallback/activate: Owning payer activates fallback after deadline expiry.
- POST /payments/{id}/confirm: Owning payer confirms final payment execution.
"""

from typing import Annotated, Union
from fastapi import APIRouter, Depends, status

from app.auth.dependencies import get_current_actor
from app.auth.schemas import (
    FullPaymentView,
    GuardianDecisionRequest,
    PaymentConfirmRequest,
    PaymentConfirmResponse,
    PaymentCreateRequest,
    PaymentDecisionResponse,
    PaymentFallbackResponse,
    RedactedPaymentView,
)
from app.services.payment_guards import TrustedActorContext
from app.services.payment_service import get_payment_service

router = APIRouter(prefix="/api/v2/payments", tags=["payments"])


@router.post("", response_model=FullPaymentView, status_code=status.HTTP_201_CREATED)
def create_payment(
    actor: Annotated[TrustedActorContext, Depends(get_current_actor)],
    request: PaymentCreateRequest,
) -> FullPaymentView:
    """Create a new risk-evaluated mock payment.

    If high risk / tier 3, requires an authoritative enrolled guardian and
    initiates the 30-second review countdown.
    """
    service = get_payment_service()
    return service.create_payment(actor, request)


@router.get("/{payment_id}", response_model=Union[FullPaymentView, RedactedPaymentView])
def get_payment(
    payment_id: str,
    actor: Annotated[TrustedActorContext, Depends(get_current_actor)],
) -> Union[FullPaymentView, RedactedPaymentView]:
    """Retrieve payment view with role-based privacy redaction.

    Payers receive FullPaymentView.
    Assigned guardians receive RedactedPaymentView (no amounts/beneficiaries).
    Unauthorized actors are rejected with 403 Forbidden.
    """
    service = get_payment_service()
    return service.get_payment_view(actor, payment_id)


@router.post("/{payment_id}/guardian/decision", response_model=PaymentDecisionResponse)
def submit_guardian_decision(
    payment_id: str,
    actor: Annotated[TrustedActorContext, Depends(get_current_actor)],
    request: GuardianDecisionRequest,
) -> PaymentDecisionResponse:
    """Submit an authenticated guardian decision for a payment awaiting review.

    Enforces 30-second server deadline, anti-replay, and the invariant that
    guardian approval NEVER executes payments.
    """
    service = get_payment_service()
    return service.submit_guardian_decision(actor, payment_id, request)


@router.post("/{payment_id}/fallback/activate", response_model=PaymentFallbackResponse)
def activate_fallback(
    payment_id: str,
    actor: Annotated[TrustedActorContext, Depends(get_current_actor)],
) -> PaymentFallbackResponse:
    """Activate fallback review after guardian deadline expiry.

    Only callable by the owning payer when server_now >= guardian_deadline.
    Invariant: Fallback transition cannot authorize payment execution.
    """
    service = get_payment_service()
    return service.activate_fallback(actor, payment_id)


@router.post("/{payment_id}/confirm", response_model=PaymentConfirmResponse)
def confirm_payment(
    payment_id: str,
    actor: Annotated[TrustedActorContext, Depends(get_current_actor)],
    request: PaymentConfirmRequest,
) -> PaymentConfirmResponse:
    """Confirm final payment execution by the authenticated owning payer.

    Strictly denies non-payer and guardian callers. Rechecks binary Safe-Lock
    and hard policy before execution.
    """
    service = get_payment_service()
    return service.confirm_payment(actor, payment_id, request)


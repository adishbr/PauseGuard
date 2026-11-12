"""FastAPI router for V2 payment state machine and review endpoints.

Endpoints:
- POST /payments: Payer creates a risk-evaluated mock payment.
- GET  /payments/{id}: Retrieve payment view (full for payer, redacted for guardian).
- POST /payments/{id}/warning/acknowledge: Payer acknowledges risk warning.
- POST /payments/{id}/guardian/decision: Assigned guardian submits time-bound decision.
- POST /payments/{id}/fallback/activate: Owning payer activates fallback after deadline expiry.
- POST /payments/{id}/cancel: Owning payer cancels eligible non-terminal payment.
- POST /payments/{id}/confirm: Owning payer confirms final payment execution.
"""

from collections.abc import Iterator
from typing import TYPE_CHECKING, Annotated, Any, Union
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_actor
from app.auth.schemas import (
    FullPaymentView,
    GuardianDecisionRequest,
    PaymentConfirmRequest,
    PaymentConfirmResponse,
    PaymentCreateRequest,
    PaymentDecisionResponse,
    PaymentFallbackResponse,
    PaymentWarningAckResponse,
    RedactedPaymentView,
)
from app.config import load_settings
from app.services.payment_guards import TrustedActorContext
from app.services.payment_service import PaymentService, get_payment_service

if TYPE_CHECKING:
    from app.services.durable_payment_engine import DurablePaymentEngine

router = APIRouter(prefix="/api/v2/payments", tags=["payments"])


def get_payment_engine(
    request: Request,
) -> Iterator[Any]:
    """Resolve authoritative database-backed engine or explicitly configured mock service.

    Production-intended execution must not silently fall back to in-memory payment state.
    If session_factory is present on application.state, binds a transactional session to DurablePaymentEngine.
    If session_factory is absent and mode is mock, uses PaymentService.
    If session_factory is absent and mode is not mock, raises 503 Service Unavailable.
    """
    session_factory = getattr(request.app.state, "session_factory", None)
    settings = getattr(request.app.state, "settings", None) or load_settings()

    if session_factory is not None:
        from app.services.durable_payment_engine import DurablePaymentEngine

        session: Session = session_factory()
        try:
            yield DurablePaymentEngine(session)
            session.commit()
        except BaseException:
            session.rollback()
            raise
        finally:
            session.close()
    else:
        is_approved_mock = (
            getattr(settings, "environment", "development") in ("local", "test", "development")
            and getattr(settings, "mode", "mock") == "mock"
        )
        if not is_approved_mock:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Durable persistence is required but database session factory is not configured.",
            )
        yield get_payment_service()


@router.post("", response_model=FullPaymentView, status_code=status.HTTP_201_CREATED)
def create_payment(
    actor: Annotated[TrustedActorContext, Depends(get_current_actor)],
    request: PaymentCreateRequest,
    engine: Annotated[Any, Depends(get_payment_engine)],
) -> FullPaymentView:
    """Create a new risk-evaluated mock payment.

    If high risk / tier 3, requires an authoritative enrolled guardian and
    initiates the 30-second review countdown.
    """
    return engine.create_payment(actor, request)


@router.get("/{payment_id}", response_model=Union[FullPaymentView, RedactedPaymentView])
def get_payment(
    payment_id: str,
    actor: Annotated[TrustedActorContext, Depends(get_current_actor)],
    engine: Annotated[Any, Depends(get_payment_engine)],
) -> Union[FullPaymentView, RedactedPaymentView]:
    """Retrieve payment view with role-based privacy redaction.

    Payers receive FullPaymentView.
    Assigned guardians receive RedactedPaymentView (no amounts/beneficiaries).
    Unauthorized actors are rejected with 403 Forbidden.
    """
    return engine.get_payment_view(actor, payment_id)


@router.post("/{payment_id}/warning/acknowledge", response_model=PaymentWarningAckResponse)
def acknowledge_warning(
    payment_id: str,
    actor: Annotated[TrustedActorContext, Depends(get_current_actor)],
    engine: Annotated[Any, Depends(get_payment_engine)],
) -> PaymentWarningAckResponse:
    """Acknowledge a high-risk or threshold warning to transition to READY_TO_EXECUTE.

    Only callable by the owning payer. Invariant: Acknowledgment does NOT execute the payment.
    """
    return engine.acknowledge_warning(actor, payment_id)


@router.post("/{payment_id}/guardian/decision", response_model=PaymentDecisionResponse)
def submit_guardian_decision(
    payment_id: str,
    actor: Annotated[TrustedActorContext, Depends(get_current_actor)],
    request: GuardianDecisionRequest,
    engine: Annotated[Any, Depends(get_payment_engine)],
) -> PaymentDecisionResponse:
    """Submit an authenticated guardian decision for a payment awaiting review.

    Enforces 30-second server deadline, anti-replay, and the invariant that
    guardian approval NEVER executes payments.
    """
    return engine.submit_guardian_decision(actor, payment_id, request)


@router.post("/{payment_id}/fallback/activate", response_model=PaymentFallbackResponse)
def activate_fallback(
    payment_id: str,
    actor: Annotated[TrustedActorContext, Depends(get_current_actor)],
    engine: Annotated[Any, Depends(get_payment_engine)],
) -> PaymentFallbackResponse:
    """Activate fallback review after guardian deadline expiry.

    Only callable by the owning payer when server_now >= guardian_deadline.
    Invariant: Fallback transition cannot authorize payment execution.
    """
    return engine.activate_fallback(actor, payment_id)


@router.post("/{payment_id}/cancel", response_model=PaymentConfirmResponse)
def cancel_payment(
    payment_id: str,
    actor: Annotated[TrustedActorContext, Depends(get_current_actor)],
    engine: Annotated[Any, Depends(get_payment_engine)],
) -> PaymentConfirmResponse:
    """Cancel an eligible non-terminal payment by the authenticated owning payer.

    Terminal payments (EXECUTED, REJECTED, CANCELLED, etc.) cannot be cancelled.
    Non-owning payers and non-payers are rejected with 403 Forbidden.
    """
    return engine.cancel_payment(actor, payment_id)


@router.post("/{payment_id}/confirm", response_model=PaymentConfirmResponse)
def confirm_payment(
    payment_id: str,
    actor: Annotated[TrustedActorContext, Depends(get_current_actor)],
    request: PaymentConfirmRequest,
    engine: Annotated[Any, Depends(get_payment_engine)],
) -> PaymentConfirmResponse:
    """Confirm final payment execution by the authenticated owning payer.

    Strictly denies non-payer and guardian callers. Rechecks binary Safe-Lock
    and hard policy before execution.
    """
    return engine.confirm_payment(actor, payment_id, request)

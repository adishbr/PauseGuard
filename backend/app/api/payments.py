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
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Annotated, Any, Union
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_actor
from app.auth.schemas import (
    EvidenceExportResponse,
    FullPaymentView,
    GuardianDecisionRequest,
    PaymentConfirmRequest,
    PaymentConfirmResponse,
    PaymentCreateRequest,
    PaymentDecisionResponse,
    PaymentFallbackResponse,
    PaymentRiskExplanationResponse,
    PaymentWarningAckResponse,
    RedactedPaymentView,
)
from app.config import load_settings
from app.models.roles import UserRole
from app.services.events import broadcast_event_sync
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


@router.get("", response_model=list[Union[FullPaymentView, RedactedPaymentView]])
def list_payments(
    actor: Annotated[TrustedActorContext, Depends(get_current_actor)],
    engine: Annotated[Any, Depends(get_payment_engine)],
    limit: int = 20,
    offset: int = 0,
) -> list[Union[FullPaymentView, RedactedPaymentView]]:
    """List payments accessible to the authenticated actor with pagination."""
    return engine.list_payments(actor, limit=limit, offset=offset)


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
    res = engine.create_payment(actor, request)
    gid = None
    if getattr(res, "assigned_guardian_id", None):
        try:
            gid = UUID(res.assigned_guardian_id)
        except (ValueError, TypeError):
            pass
    broadcast_event_sync(
        payment_id=res.id,
        event_type="PAYMENT_CREATED",
        status=res.status,
        payer_id=actor.user_id,
        assigned_guardian_id=gid,
        tier=res.tier,
        amount_paise=res.amount_paise,
        guardian_deadline=res.guardian_deadline,
    )
    return res


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


@router.get("/{payment_id}/events")
def get_payment_events(
    payment_id: str,
    actor: Annotated[TrustedActorContext, Depends(get_current_actor)],
    engine: Annotated[Any, Depends(get_payment_engine)],
) -> list[dict]:
    """Retrieve audit/lifecycle events for a payment."""
    return engine.get_payment_events(actor, payment_id)


@router.get("/{payment_id}/risk", response_model=PaymentRiskExplanationResponse)
def get_payment_risk(
    payment_id: str,
    actor: Annotated[TrustedActorContext, Depends(get_current_actor)],
    engine: Annotated[Any, Depends(get_payment_engine)],
) -> PaymentRiskExplanationResponse:
    """Retrieve policy risk explanation for a payment."""
    view = engine.get_payment_view(actor, payment_id)
    if isinstance(view, RedactedPaymentView):
        return PaymentRiskExplanationResponse(
            payment_id=payment_id,
            tier=view.tier,
            is_hard_blocked=False,
            requires_guardian=(view.tier == 3),
            requires_warning_ack=False,
            reasons=["Transaction flagged for secondary security review"],
        )
    reasons = []
    if view.tier == 3:
        reasons.append("High amount or elevated risk score requires guardian review")
    elif view.tier == 1:
        reasons.append("Medium risk requires payer acknowledgment")
    elif view.status == "REJECTED":
        reasons.append("Transaction violated hard risk policy")
    else:
        reasons.append("Routine transaction within normal baseline")

    return PaymentRiskExplanationResponse(
        payment_id=payment_id,
        tier=view.tier,
        is_hard_blocked=(view.status == "REJECTED"),
        requires_guardian=(view.tier == 3),
        requires_warning_ack=(view.tier == 1),
        reasons=reasons,
    )


@router.get("/{payment_id}/evidence", response_model=EvidenceExportResponse)
def get_payment_evidence(
    payment_id: str,
    actor: Annotated[TrustedActorContext, Depends(get_current_actor)],
    engine: Annotated[Any, Depends(get_payment_engine)],
) -> EvidenceExportResponse:
    """Retrieve privacy-minimizing redacted evidence export for a payment."""
    from safety.evidence.redacted_export import export_redacted_evidence

    view = engine.get_payment_view(actor, payment_id)
    if isinstance(view, RedactedPaymentView) and UserRole.ADMIN not in actor.roles and UserRole.ANALYST not in actor.roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Assigned guardian cannot export evidence packet",
        )

    risk_level = "HIGH" if view.tier == 3 else ("MEDIUM" if view.tier == 1 else "LOW")
    raw_record = {
        "case_id": payment_id,
        "event_id": f"ev_{payment_id}",
        "event_type": "PAYMENT_EVIDENCE",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "risk_level": risk_level,
        "risk_indicators": [f"tier_{view.tier}", f"status_{view.status}"],
        "policy_version": "2.0.0",
    }
    redacted = export_redacted_evidence(raw_record)
    return EvidenceExportResponse(
        payment_id=payment_id,
        event_type=redacted["event_type"],
        timestamp=redacted["timestamp"],
        risk_level=redacted["risk_level"],
        risk_indicators=redacted.get("risk_indicators", []),
        policy_version=redacted.get("policy_version", "2.0.0"),
        redaction_applied=redacted.get("redaction_applied", True),
        review_required_before_sharing=redacted.get("review_required_before_sharing", True),
        exported_at=redacted["exported_at"],
    )




@router.post("/{payment_id}/warning/acknowledge", response_model=PaymentWarningAckResponse)
def acknowledge_warning(
    payment_id: str,
    actor: Annotated[TrustedActorContext, Depends(get_current_actor)],
    engine: Annotated[Any, Depends(get_payment_engine)],
) -> PaymentWarningAckResponse:
    """Acknowledge a high-risk or threshold warning to transition to READY_TO_EXECUTE.

    Only callable by the owning payer. Invariant: Acknowledgment does NOT execute the payment.
    """
    res = engine.acknowledge_warning(actor, payment_id)
    broadcast_event_sync(
        payment_id=res.payment_id,
        event_type="PAYMENT_WARNING_ACKNOWLEDGED",
        status=res.status,
        payer_id=actor.user_id,
    )
    return res


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
    res = engine.submit_guardian_decision(actor, payment_id, request)
    broadcast_event_sync(
        payment_id=res.payment_id,
        event_type="GUARDIAN_DECISION",
        status=res.status,
        payer_id=getattr(res, "payer_id", actor.user_id),
        assigned_guardian_id=actor.user_id,
    )
    return res


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
    res = engine.activate_fallback(actor, payment_id)
    broadcast_event_sync(
        payment_id=res.payment_id,
        event_type="FALLBACK_ACTIVATED",
        status=res.status,
        payer_id=actor.user_id,
    )
    return res


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
    res = engine.cancel_payment(actor, payment_id)
    broadcast_event_sync(
        payment_id=res.payment_id,
        event_type="PAYMENT_CANCELLED",
        status=res.status,
        payer_id=actor.user_id,
        amount_paise=res.amount_paise,
    )
    return res


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
    res = engine.confirm_payment(actor, payment_id, request)
    broadcast_event_sync(
        payment_id=res.payment_id,
        event_type="PAYMENT_EXECUTED",
        status=res.status,
        payer_id=actor.user_id,
        amount_paise=res.amount_paise,
    )
    return res

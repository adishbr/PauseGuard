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
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Annotated, Any, Optional, Union
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
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
from app.auth.v5_schemas import (
    BackupGuardianActivateResponse,
    PaymentAppealCreateRequest,
    PaymentAppealResolveRequest,
    PaymentAppealView,
    PaymentRetryRequest,
    PaymentStepUpRequest,
    PaymentStepUpResponse,
    PaymentUpdateRequest,
)
from app.config import load_settings
from app.models.roles import UserRole
from app.services.events import broadcast_event_sync
from app.services.notification_service import NotificationOutboxService
from app.services.payment_guards import TrustedActorContext
from app.services.payment_service import PaymentService, get_payment_service
from app.services.v5_store import get_or_create_v5_mock_store
from intelligence.advisory.adapter import DIAGNOSTIC_TIMEOUT, DIAGNOSTIC_UNHANDLED_EXCEPTION, evaluate_advisory
from intelligence.advisory.types import AdvisoryRequest, get_default_scoring_config
from intelligence.schemas.risk_signals import RiskSignals, make_degraded_advisory

if TYPE_CHECKING:
    from app.services.durable_payment_engine import DurablePaymentEngine

router = APIRouter(prefix="/api/v2/payments", tags=["payments"])

_ADVISORY_TIMEOUT_SECONDS = 0.5
_ADVISORY_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="pauseguard-advisory")


def _schedule_post_commit_broadcast(http_request: Optional[Request], **event_kwargs: Any) -> None:
    """Queue WebSocket notification for post-commit dispatch when inside get_payment_engine."""
    pending = getattr(getattr(http_request, "state", None), "_post_commit_events", None)
    if isinstance(pending, list):
        pending.append(event_kwargs)
    else:
        broadcast_event_sync(**event_kwargs)


def _evaluate_payment_advisory_bounded(
    actor: TrustedActorContext,
    request: PaymentCreateRequest,
) -> RiskSignals:
    """Evaluate AI risk advisory signals outside DB locks with fail-closed timeout handling."""
    preview_id = f"pre_{request.idempotency_key[:32]}"
    adv_req = AdvisoryRequest(
        payment_id=preview_id,
        payer_id=str(actor.user_id),
        beneficiary_id=request.beneficiary_id,
        amount_paise=request.amount_paise,
        transcript_text=None,
        transcript_consented=False,
        scoring_config=get_default_scoring_config(),
    )
    future = _ADVISORY_EXECUTOR.submit(evaluate_advisory, adv_req)
    try:
        adv_res = future.result(timeout=_ADVISORY_TIMEOUT_SECONDS)
        return adv_res.risk_signals
    except FuturesTimeoutError:
        future.cancel()
        return make_degraded_advisory(
            payment_id=preview_id,
            payer_id=str(actor.user_id),
            beneficiary_id=request.beneficiary_id,
            amount_paise=request.amount_paise,
            degraded_reasons=(DIAGNOSTIC_TIMEOUT,),
            reason_codes=("RC_ADVISORY_SCORE_UNAVAILABLE", "RC_ADVISORY_EVALUATION_TIMEOUT"),
        )
    except Exception:
        return make_degraded_advisory(
            payment_id=preview_id,
            payer_id=str(actor.user_id),
            beneficiary_id=request.beneficiary_id,
            amount_paise=request.amount_paise,
            degraded_reasons=(DIAGNOSTIC_UNHANDLED_EXCEPTION,),
            reason_codes=("RC_ADVISORY_SCORE_UNAVAILABLE", "RC_ADVISORY_EVALUATION_ERROR"),
        )


def _record_outbox_events(
    pending_events: list[dict[str, Any]],
    *,
    settings: object,
    db_session: Session | None,
    app_state: object,
) -> None:
    if not pending_events:
        return
    outbox = NotificationOutboxService(
        settings=settings,
        db_session=db_session,
        mock_store=None if db_session is not None else get_or_create_v5_mock_store(app_state),
    )
    for ev in pending_events:
        outbox.record_payment_transition(
            payment_id=ev["payment_id"],
            event_type=ev["event_type"],
            status=ev["status"],
            payer_id=ev["payer_id"],
            assigned_guardian_id=ev.get("assigned_guardian_id"),
            tier=ev.get("tier", 0),
            amount_paise=ev.get("amount_paise"),
            guardian_deadline=ev.get("guardian_deadline"),
            extra=ev.get("extra"),
        )


def get_payment_engine(
    request: Request,
) -> Iterator[Any]:
    """Resolve authoritative database-backed engine or explicitly configured mock service.

    Production-intended execution must not silently fall back to in-memory payment state.
    If session_factory is present on application.state, binds a transactional session to DurablePaymentEngine
    and dispatches queued WebSocket notifications strictly AFTER session.commit() succeeds.
    If session_factory is absent and mode is mock, uses PaymentService and emits queued events after route return.
    If session_factory is absent and mode is not mock, raises 503 Service Unavailable.
    """
    session_factory = getattr(request.app.state, "session_factory", None)
    settings = getattr(request.app.state, "settings", None) or load_settings()
    pending_events: list[dict[str, Any]] = []
    if hasattr(request, "state"):
        request.state._post_commit_events = pending_events

    if session_factory is not None:
        from app.services.durable_payment_engine import DurablePaymentEngine

        session: Session = session_factory()
        try:
            yield DurablePaymentEngine(session)
            _record_outbox_events(
                pending_events,
                settings=settings,
                db_session=session,
                app_state=request.app.state,
            )
            session.commit()
        except BaseException:
            pending_events.clear()
            session.rollback()
            raise
        else:
            for ev in pending_events:
                broadcast_event_sync(**ev)
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
        try:
            yield get_payment_service()
            _record_outbox_events(
                pending_events,
                settings=settings,
                db_session=None,
                app_state=request.app.state,
            )
        except BaseException:
            pending_events.clear()
            raise
        else:
            for ev in pending_events:
                broadcast_event_sync(**ev)


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
    http_request: Request,
    actor: Annotated[TrustedActorContext, Depends(get_current_actor)],
    request: PaymentCreateRequest,
    engine: Annotated[Any, Depends(get_payment_engine)],
) -> FullPaymentView:
    """Create a new risk-evaluated mock payment.

    If high risk / tier 3, requires an authoritative enrolled guardian and
    initiates the 30-second review countdown.
    """
    advisory_signals = _evaluate_payment_advisory_bounded(actor, request)
    res = engine.create_payment(actor, request, advisory_signals=advisory_signals)
    gid = None
    if getattr(res, "assigned_guardian_id", None):
        try:
            gid = UUID(res.assigned_guardian_id)
        except (ValueError, TypeError):
            pass
    _schedule_post_commit_broadcast(
        http_request,
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
    http_request: Request,
    actor: Annotated[TrustedActorContext, Depends(get_current_actor)],
    engine: Annotated[Any, Depends(get_payment_engine)],
) -> PaymentWarningAckResponse:
    """Acknowledge a high-risk or threshold warning to transition to READY_TO_EXECUTE.

    Only callable by the owning payer. Invariant: Acknowledgment does NOT execute the payment.
    """
    res = engine.acknowledge_warning(actor, payment_id)
    _schedule_post_commit_broadcast(
        http_request,
        payment_id=res.payment_id,
        event_type="PAYMENT_WARNING_ACKNOWLEDGED",
        status=res.status,
        payer_id=actor.user_id,
    )
    return res


@router.post("/{payment_id}/guardian/decision", response_model=PaymentDecisionResponse)
def submit_guardian_decision(
    payment_id: str,
    http_request: Request,
    actor: Annotated[TrustedActorContext, Depends(get_current_actor)],
    request: GuardianDecisionRequest,
    engine: Annotated[Any, Depends(get_payment_engine)],
) -> Union[PaymentDecisionResponse, JSONResponse]:
    """Submit an authenticated guardian decision for a payment awaiting review.

    Enforces 30-second server deadline, anti-replay, and the invariant that
    guardian approval NEVER executes payments.

    If the guardian decision arrives after the deadline, the engine transitions
    the payment to AWAITING_FALLBACK_REVIEW and records a
    GUARDIAN_DEADLINE_EXPIRED audit event in the same transaction. The API route
    returns HTTP 409 through the normal response path without raising an
    exception, allowing the get_payment_engine dependency to commit state and
    audit atomically.
    """
    res = engine.submit_guardian_decision(actor, payment_id, request)
    # Lazy import to avoid registering SQLAlchemy models on Base.metadata at app creation time.
    from app.services.durable_payment_engine import GuardianLateDecisionOutcome
    if isinstance(res, GuardianLateDecisionOutcome):
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "detail": "Guardian response deadline has expired; payment transitioned to fallback review",
                "payment_id": res.payment_id,
                "status": res.status,
            },
        )
    payer_id = (
        engine.get_payment_payer_id(payment_id)
        if hasattr(engine, "get_payment_payer_id")
        else getattr(res, "payer_id", None)
    ) or actor.user_id
    _schedule_post_commit_broadcast(
        http_request,
        payment_id=res.payment_id,
        event_type="GUARDIAN_DECISION",
        status=res.status,
        payer_id=payer_id,
        assigned_guardian_id=actor.user_id,
    )
    return res


@router.post("/{payment_id}/fallback/activate", response_model=PaymentFallbackResponse)
def activate_fallback(
    payment_id: str,
    http_request: Request,
    actor: Annotated[TrustedActorContext, Depends(get_current_actor)],
    engine: Annotated[Any, Depends(get_payment_engine)],
) -> PaymentFallbackResponse:
    """Activate fallback review after guardian deadline expiry.

    Only callable by the owning payer when server_now >= guardian_deadline.
    Invariant: Fallback transition cannot authorize payment execution.
    """
    res = engine.activate_fallback(actor, payment_id)
    _schedule_post_commit_broadcast(
        http_request,
        payment_id=res.payment_id,
        event_type="FALLBACK_ACTIVATED",
        status=res.status,
        payer_id=actor.user_id,
    )
    return res


@router.post("/{payment_id}/cancel", response_model=PaymentConfirmResponse)
def cancel_payment(
    payment_id: str,
    http_request: Request,
    actor: Annotated[TrustedActorContext, Depends(get_current_actor)],
    engine: Annotated[Any, Depends(get_payment_engine)],
) -> PaymentConfirmResponse:
    """Cancel an eligible non-terminal payment by the authenticated owning payer.

    Terminal payments (EXECUTED, REJECTED, CANCELLED, etc.) cannot be cancelled.
    Non-owning payers and non-payers are rejected with 403 Forbidden.
    """
    res = engine.cancel_payment(actor, payment_id)
    _schedule_post_commit_broadcast(
        http_request,
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
    http_request: Request,
    actor: Annotated[TrustedActorContext, Depends(get_current_actor)],
    request: PaymentConfirmRequest,
    engine: Annotated[Any, Depends(get_payment_engine)],
) -> PaymentConfirmResponse:
    """Confirm final payment execution by the authenticated owning payer.

    Strictly denies non-payer and guardian callers. Rechecks binary Safe-Lock
    and hard policy before execution.
    """
    res = engine.confirm_payment(actor, payment_id, request)
    _schedule_post_commit_broadcast(
        http_request,
        payment_id=res.payment_id,
        event_type="PAYMENT_EXECUTED",
        status=res.status,
        payer_id=actor.user_id,
        amount_paise=res.amount_paise,
    )
    return res


@router.patch("/{payment_id}", response_model=FullPaymentView)
def update_payment(
    payment_id: str,
    http_request: Request,
    actor: Annotated[TrustedActorContext, Depends(get_current_actor)],
    request: PaymentUpdateRequest,
    engine: Annotated[Any, Depends(get_payment_engine)],
) -> FullPaymentView:
    """Modify non-terminal payment fields; invalidates any prior guardian approval on payee/amount change."""
    res = engine.update_payment(actor, payment_id, request)
    gid = UUID(res.assigned_guardian_id) if res.assigned_guardian_id else None
    _schedule_post_commit_broadcast(
        http_request,
        payment_id=res.id,
        event_type="PAYMENT_MODIFIED",
        status=res.status,
        payer_id=actor.user_id,
        assigned_guardian_id=gid,
        tier=res.tier,
        amount_paise=res.amount_paise,
        guardian_deadline=res.guardian_deadline,
    )
    return res


@router.post("/{payment_id}/step-up/verify", response_model=PaymentStepUpResponse)
def verify_payment_step_up(
    payment_id: str,
    http_request: Request,
    actor: Annotated[TrustedActorContext, Depends(get_current_actor)],
    request: PaymentStepUpRequest,
    engine: Annotated[Any, Depends(get_payment_engine)],
) -> PaymentStepUpResponse:
    """Verify payer step-up authentication challenge (WebAuthn stub or OTP step-up)."""
    res = engine.verify_step_up(actor, payment_id, request)
    _schedule_post_commit_broadcast(
        http_request,
        payment_id=res.payment_id,
        event_type="STEP_UP_VERIFIED",
        status=res.status,
        payer_id=actor.user_id,
    )
    return res


@router.post("/{payment_id}/fallback/backup", response_model=BackupGuardianActivateResponse)
def activate_backup_guardian(
    payment_id: str,
    http_request: Request,
    actor: Annotated[TrustedActorContext, Depends(get_current_actor)],
    engine: Annotated[Any, Depends(get_payment_engine)],
) -> BackupGuardianActivateResponse:
    """Re-route pending/fallback payment review to an active enrolled backup guardian."""
    res = engine.activate_backup_guardian(actor, payment_id)
    _schedule_post_commit_broadcast(
        http_request,
        payment_id=res.payment_id,
        event_type="BACKUP_GUARDIAN_ACTIVATED",
        status=res.status,
        payer_id=actor.user_id,
        assigned_guardian_id=res.assigned_guardian_id,
        guardian_deadline=res.guardian_deadline.isoformat(),
    )
    return res


@router.post("/{payment_id}/appeals", response_model=PaymentAppealView, status_code=status.HTTP_201_CREATED)
def create_payment_appeal(
    payment_id: str,
    actor: Annotated[TrustedActorContext, Depends(get_current_actor)],
    request: PaymentAppealCreateRequest,
    engine: Annotated[Any, Depends(get_payment_engine)],
) -> PaymentAppealView:
    """Submit a payer false-alert or fallback appeal on an eligible blocked/failed payment."""
    return engine.create_appeal(actor, payment_id, request)


@router.get("/{payment_id}/appeals", response_model=list[PaymentAppealView])
def list_payment_appeals(
    payment_id: str,
    actor: Annotated[TrustedActorContext, Depends(get_current_actor)],
    engine: Annotated[Any, Depends(get_payment_engine)],
) -> list[PaymentAppealView]:
    """List appeals filed for a payment (owning payer, analyst, or admin)."""
    return engine.list_appeals(actor, payment_id)


@router.post("/{payment_id}/appeals/{appeal_id}/resolve", response_model=PaymentAppealView)
def resolve_payment_appeal(
    payment_id: str,
    appeal_id: UUID,
    actor: Annotated[TrustedActorContext, Depends(get_current_actor)],
    request: PaymentAppealResolveRequest,
    engine: Annotated[Any, Depends(get_payment_engine)],
) -> PaymentAppealView:
    """Analyst/Admin-only appeal resolution (never callable by payer for self-approval)."""
    return engine.resolve_appeal(actor, payment_id, appeal_id, request)


@router.post("/{payment_id}/retry", response_model=FullPaymentView, status_code=status.HTTP_201_CREATED)
def retry_payment(
    payment_id: str,
    http_request: Request,
    actor: Annotated[TrustedActorContext, Depends(get_current_actor)],
    request: PaymentRetryRequest,
    engine: Annotated[Any, Depends(get_payment_engine)],
) -> FullPaymentView:
    """Create a safe child payment preserving parent fraud lineage after eligible failure/appeal."""
    child_advisory_stub = PaymentCreateRequest(
        beneficiary_id="retry_lineage_check",
        amount_paise=100,
        purpose=request.purpose or "retry",
        idempotency_key=request.idempotency_key,
    )
    advisory_signals = _evaluate_payment_advisory_bounded(actor, child_advisory_stub)
    res = engine.retry_payment(actor, payment_id, request, advisory_signals=advisory_signals)
    gid = UUID(res.assigned_guardian_id) if res.assigned_guardian_id else None
    _schedule_post_commit_broadcast(
        http_request,
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

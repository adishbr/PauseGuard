"""FastAPI router for provider-abstracted Mock Bank pre-execution intents and settlement webhooks.

Endpoints:
- POST /api/v2/bank/intents: Create a pre-execution hold intent for an active payment.
- POST /api/v2/bank/webhooks/settlement: Reconcile settlement state from HMAC-signed bank callback.

SECURITY INVARIANTS:
1. Bank adapters NEVER bypass PauseGuard's guardian/warning/Safe-Lock state machine.
2. External webhooks MUST pass constant-time HMAC-SHA256 verification and replay protection.
3. Settlement reconciliation refuses SETTLED events unless PauseGuard's backend state is EXECUTED.
"""

from datetime import datetime, timezone
import json
from typing import Annotated, Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status

from app.api.payments import get_payment_engine
from app.auth.dependencies import get_current_actor
from app.auth.v5_schemas import (
    BankIntentCreateRequest,
    BankIntentView,
    BankSettlementWebhookResponse,
)
from app.config import load_settings
from app.integrations.bank_adapter import BankAdapterError, MockBankRailAdapter
from app.models.roles import UserRole
from app.services.payment_guards import TrustedActorContext
from app.services.payment_service import get_payment_service
from app.services.v5_store import MockBankIntentRecord, get_or_create_v5_mock_store

router = APIRouter(prefix="/api/v2/bank", tags=["bank-adapter"])

_DISALLOWED_INTENT_STATUSES = frozenset({
    "REJECTED",
    "CANCELLED",
    "EXPIRED",
    "FAILED",
})


def _to_intent_view(rec: MockBankIntentRecord) -> BankIntentView:
    return BankIntentView(
        intent_id=rec.intent_id,
        payment_id=rec.payment_id,
        payer_id=rec.payer_id,
        amount_paise=rec.amount_paise,
        rail=rec.rail,
        adapter=rec.adapter,
        settlement_status=rec.settlement_status,
        is_mock=rec.is_mock,
        created_at=rec.created_at,
        settled_at=rec.settled_at,
    )


@router.post("/intents", response_model=BankIntentView, status_code=status.HTTP_201_CREATED)
def create_bank_intent(
    http_request: Request,
    request: BankIntentCreateRequest,
    actor: Annotated[TrustedActorContext, Depends(get_current_actor)],
    engine: Annotated[Any, Depends(get_payment_engine)],
) -> BankIntentView:
    """Create a pre-execution bank rail hold intent linked to an active PauseGuard payment."""
    if UserRole.PAYER not in actor.roles and UserRole.ADMIN not in actor.roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Only payers or administrators can register bank intents",
        )

    settings = getattr(http_request.app.state, "settings", None) or load_settings()
    payment = engine.get_payment_view(actor, request.payment_id)
    if str(payment.status) in _DISALLOWED_INTENT_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot create bank intent for payment in terminal/blocked state {payment.status}",
        )

    store = get_or_create_v5_mock_store(http_request.app.state)
    with store.lock:
        existing_intent_id = store.bank_intents_by_payment.get(payment.id)
        if existing_intent_id and existing_intent_id in store.bank_intents_by_id:
            return _to_intent_view(store.bank_intents_by_id[existing_intent_id])

        adapter = MockBankRailAdapter()
        try:
            created = adapter.create_intent(
                payment_id=payment.id,
                payer_id=actor.user_id,
                amount_paise=int(payment.amount_paise),
                rail=request.rail,
                settings=settings,
            )
        except BankAdapterError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(exc),
            ) from exc

        record = MockBankIntentRecord(
            intent_id=created.intent_id,
            payment_id=created.payment_id,
            payer_id=created.payer_id,
            amount_paise=created.amount_paise,
            rail=created.rail,
            adapter=created.adapter,
            settlement_status=created.settlement_status,
            is_mock=created.is_mock,
            created_at=created.created_at,
        )
        store.bank_intents_by_id[record.intent_id] = record
        store.bank_intents_by_payment[record.payment_id] = record.intent_id
        return _to_intent_view(record)


def _lookup_payment_status(http_request: Request, payment_id: str) -> str | None:
    session_factory = getattr(http_request.app.state, "session_factory", None)
    if session_factory is not None:
        from sqlalchemy import select
        from app.models.payment import Payment

        session = session_factory()
        try:
            row = session.execute(
                select(Payment.status).where(Payment.id == payment_id)
            ).scalar_one_or_none()
            return str(row) if row is not None else None
        finally:
            session.close()
    svc = get_payment_service()
    with svc._lock:
        rec = svc._payments.get(payment_id)
        return str(rec.status.value) if rec is not None else None


@router.post(
    "/webhooks/settlement",
    response_model=BankSettlementWebhookResponse,
    status_code=status.HTTP_200_OK,
)
async def reconcile_bank_settlement_webhook(
    http_request: Request,
    x_pauseguard_bank_signature: Annotated[
        Optional[str], Header(alias="X-PauseGuard-Bank-Signature")
    ] = None,
) -> BankSettlementWebhookResponse:
    """Verify HMAC-SHA256 bank settlement webhook and reconcile intent status."""
    if not x_pauseguard_bank_signature:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing required X-PauseGuard-Bank-Signature header",
        )

    settings = getattr(http_request.app.state, "settings", None) or load_settings()
    raw_body = await http_request.body()
    adapter = MockBankRailAdapter()
    try:
        verified = adapter.verify_webhook_signature(
            raw_body=raw_body,
            signature_header=x_pauseguard_bank_signature,
            settings=settings,
        )
    except BankAdapterError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    if not verified:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid bank webhook HMAC signature",
        )

    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Malformed JSON webhook payload",
        ) from exc

    event_id = str(payload.get("event_id", "")).strip()
    intent_id = str(payload.get("intent_id", "")).strip()
    settlement_status = str(payload.get("settlement_status", "")).strip().upper()
    if not event_id or not intent_id or settlement_status not in ("SETTLED", "RELEASED", "FAILED"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Webhook payload must specify event_id, intent_id, and settlement_status",
        )

    store = get_or_create_v5_mock_store(http_request.app.state)
    with store.lock:
        if event_id in store.bank_webhook_events_seen:
            intent = store.bank_intents_by_id.get(intent_id)
            return BankSettlementWebhookResponse(
                accepted=True,
                duplicate=True,
                event_id=event_id,
                intent_id=intent_id,
                payment_id=intent.payment_id if intent else "",
                settlement_status=store.bank_webhook_events_seen[event_id],
                adapter=adapter.adapter_name,
            )

        intent = store.bank_intents_by_id.get(intent_id)
        if intent is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Unknown bank intent_id",
            )

        current_payment_status = _lookup_payment_status(http_request, intent.payment_id)
        if settlement_status == "SETTLED" and current_payment_status != "EXECUTED":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Cannot reconcile SETTLED webhook while payment is in {current_payment_status} state; "
                    "PauseGuard confirmation state machine execution is required first."
                ),
            )

        intent.settlement_status = settlement_status
        if settlement_status == "SETTLED":
            intent.settled_at = datetime.now(timezone.utc)
        store.bank_webhook_events_seen[event_id] = settlement_status

        return BankSettlementWebhookResponse(
            accepted=True,
            duplicate=False,
            event_id=event_id,
            intent_id=intent_id,
            payment_id=intent.payment_id,
            settlement_status=intent.settlement_status,
            adapter=adapter.adapter_name,
        )

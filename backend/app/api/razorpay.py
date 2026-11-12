"""FastAPI router for Razorpay Test Mode merchant sandbox operations.

Endpoints:
- POST /api/v2/sandbox/razorpay/orders: Create a Razorpay Test Mode merchant order (Admin only).
- POST /api/v2/sandbox/razorpay/verify: Verify checkout payment signature and reconcile with provider (Admin only).
- POST /api/v2/sandbox/razorpay/webhook: Inbound Razorpay webhook receiver with HMAC signature verification and replay protection.
- GET  /api/v2/sandbox/razorpay/orders/{order_id}: Inspect stored merchant order and payment history (Admin only).

SECURITY INVARIANTS:
1. Merchant sandbox operations are strictly decoupled from PauseGuard mock UPI/P2P payments.
2. Webhook events CANNOT authorize, confirm, or execute P2P payment requests or debit user ledger balances.
3. Order creation, checkout verification, and order inspection require trusted Administrator authentication.
4. Webhook receiver validates raw-body HMAC-SHA256 signatures and suppresses duplicate replays.
"""

from collections.abc import Iterator
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_actor
from app.auth.schemas import (
    RazorpayOrderCreateRequest,
    RazorpayOrderResponse,
    RazorpayVerifyRequest,
    RazorpayVerifyResponse,
    RazorpayWebhookResponse,
)
from app.services.payment_guards import TrustedActorContext
from app.services.razorpay_service import (
    RazorpayMerchantService,
    get_razorpay_service,
)

router = APIRouter(prefix="/api/v2/sandbox/razorpay", tags=["razorpay-sandbox"])


def get_razorpay_merchant_service(
    request: Request,
) -> Iterator[RazorpayMerchantService]:
    """Resolve database-backed or mock Razorpay merchant service."""
    session_factory = getattr(request.app.state, "session_factory", None)
    if session_factory is not None:
        session: Session = session_factory()
        try:
            yield RazorpayMerchantService(session=session)
            session.commit()
        except BaseException:
            session.rollback()
            raise
        finally:
            session.close()
    else:
        yield get_razorpay_service()


@router.post(
    "/orders",
    response_model=RazorpayOrderResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_order(
    request: RazorpayOrderCreateRequest,
    actor: Annotated[TrustedActorContext, Depends(get_current_actor)],
    service: Annotated[RazorpayMerchantService, Depends(get_razorpay_merchant_service)],
    idempotency_key: Annotated[Optional[str], Header(alias="Idempotency-Key")] = None,
    x_idempotency_key: Annotated[Optional[str], Header(alias="X-Idempotency-Key")] = None,
) -> RazorpayOrderResponse:
    """Create a genuine or simulated Razorpay Test Mode merchant order."""
    effective_idempotency_key = idempotency_key or x_idempotency_key or request.idempotency_key
    return service.create_order(actor, request, idempotency_key=effective_idempotency_key)


@router.post(
    "/verify",
    response_model=RazorpayVerifyResponse,
    status_code=status.HTTP_200_OK,
)
def verify_checkout(
    request: RazorpayVerifyRequest,
    actor: Annotated[TrustedActorContext, Depends(get_current_actor)],
    service: Annotated[RazorpayMerchantService, Depends(get_razorpay_merchant_service)],
) -> RazorpayVerifyResponse:
    """Verify client-submitted payment signature and reconcile status against provider."""
    return service.verify_checkout(actor, request)


@router.post(
    "/webhook",
    response_model=RazorpayWebhookResponse,
    status_code=status.HTTP_200_OK,
)
async def process_webhook(
    request: Request,
    service: Annotated[RazorpayMerchantService, Depends(get_razorpay_merchant_service)],
    x_razorpay_signature: Annotated[Optional[str], Header(alias="X-Razorpay-Signature")] = None,
) -> RazorpayWebhookResponse:
    """Inbound Razorpay webhook receiver with HMAC signature verification and replay protection."""
    if not x_razorpay_signature:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing required X-Razorpay-Signature header",
        )
    raw_body = await request.body()
    return service.process_webhook(raw_body, x_razorpay_signature)


@router.get(
    "/orders/{order_id}",
    response_model=dict,
    status_code=status.HTTP_200_OK,
)
def get_order(
    order_id: str,
    actor: Annotated[TrustedActorContext, Depends(get_current_actor)],
    service: Annotated[RazorpayMerchantService, Depends(get_razorpay_merchant_service)],
) -> dict:
    """Inspect stored merchant order and payment history."""
    return service.get_order(actor, order_id)


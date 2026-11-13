"""Authoritative backend service for Razorpay Test Mode merchant sandbox operations.

SECURITY INVARIANTS:
1. Test Mode isolation: Operates strictly with Test Mode credentials (rzp_test_*).
   Live keys (rzp_live_*) are strictly prohibited and rejected fail-closed.
2. Separation of concerns: Merchant checkout is completely decoupled from PauseGuard P2P mock payments.
   Webhook events and checkout success CANNOT authorize or execute P2P payments or alter UPI ledger states.
3. Signature & amount verification: Never trust client-supplied status or amounts.
   Signatures are verified via constant-time HMAC-SHA256, and payments are reconciled against the provider.
4. Idempotency & replay protection: Inbound webhooks are deduplicated against durable/retained event IDs.
5. Admin authorization: All merchant sandbox endpoints require trusted administrator authentication.
"""

from datetime import datetime, timezone
import hashlib
import json
import logging
import threading
from typing import Any, Dict, Optional
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.auth.schemas import (
    RazorpayOrderCreateRequest,
    RazorpayOrderResponse,
    RazorpayVerifyRequest,
    RazorpayVerifyResponse,
    RazorpayWebhookResponse,
)
from app.config import load_settings
from app.integrations.razorpay_replay_guard import WebhookReplayGuard
from app.integrations.razorpay_sandbox import (
    RazorpaySandboxConfig,
    RazorpaySandboxError,
    get_razorpay_client,
    load_sandbox_config,
    require_sandbox_admin,
)
from app.integrations.razorpay_signatures import (
    verify_payment_signature,
    verify_webhook_signature,
)
from app.services.payment_guards import TrustedActorContext

logger = logging.getLogger("pauseguard.razorpay")


class RazorpayMerchantService:
    """Thread-safe orchestrator for Razorpay Test Mode merchant payments."""

    def __init__(
        self,
        session: Optional[Session] = None,
        config: Optional[RazorpaySandboxConfig] = None,
        client: Optional[Any] = None,
    ) -> None:
        self.session = session
        self._config = config
        self.client = client
        self._lock = threading.RLock()

        # In-memory mock storage for local testing when session is absent
        self._mock_orders: Dict[str, dict] = {}
        self._mock_payments: Dict[str, dict] = {}
        self._idempotency_records: Dict[str, dict] = {}
        self._replay_guard = WebhookReplayGuard(max_events=10_000)

    def _resolve_config(self) -> RazorpaySandboxConfig:
        if self._config is not None:
            return self._config
        try:
            return load_sandbox_config()
        except RazorpaySandboxError as e:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Razorpay sandbox unavailable: {e}",
            )

    def _get_client(self, config: RazorpaySandboxConfig) -> Any:
        if self.client is not None:
            return self.client
        return get_razorpay_client(config)

    def reset_for_testing(self) -> None:
        """Reset in-memory storage for test isolation."""
        with self._lock:
            self._mock_orders.clear()
            self._mock_payments.clear()
            self._idempotency_records.clear()
            self._replay_guard = WebhookReplayGuard(max_events=10_000)

    def create_order(
        self,
        actor: TrustedActorContext,
        request: RazorpayOrderCreateRequest,
        idempotency_key: Optional[str] = None,
    ) -> RazorpayOrderResponse:
        """Create a genuine or simulated Razorpay Test Mode merchant order with admin-scoped idempotency."""
        try:
            require_sandbox_admin(actor)
        except RazorpaySandboxError as e:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Sandbox authorization failed: {e}",
            )

        effective_key = idempotency_key or request.idempotency_key
        endpoint = "/api/v2/sandbox/razorpay/orders"

        # Check idempotency if key is provided
        request_hash: Optional[str] = None
        if effective_key:
            hash_payload = {
                "amount_paise": request.amount_paise,
                "currency": request.currency,
                "receipt": request.receipt,
                "notes": request.notes or {},
            }
            request_hash = hashlib.sha256(
                json.dumps(hash_payload, sort_keys=True).encode("utf-8")
            ).hexdigest()

            if self.session is not None:
                from app.models.idempotency import IdempotencyRecord
                existing_record = (
                    self.session.query(IdempotencyRecord)
                    .filter(IdempotencyRecord.key == effective_key)
                    .one_or_none()
                )
                if existing_record is not None:
                    if existing_record.caller_id != actor.user_id or existing_record.endpoint != endpoint:
                        raise HTTPException(
                            status_code=status.HTTP_409_CONFLICT,
                            detail="Idempotency key collision across caller or endpoint",
                        )
                    if existing_record.request_hash != request_hash:
                        raise HTTPException(
                            status_code=status.HTTP_409_CONFLICT,
                            detail="Idempotency key reused with conflicting request parameters",
                        )
                    return RazorpayOrderResponse(**existing_record.response_body)
            else:
                with self._lock:
                    if effective_key in self._idempotency_records:
                        cached = self._idempotency_records[effective_key]
                        if cached["caller_id"] != actor.user_id or cached["endpoint"] != endpoint:
                            raise HTTPException(
                                status_code=status.HTTP_409_CONFLICT,
                                detail="Idempotency key collision across caller or endpoint",
                            )
                        if cached["request_hash"] != request_hash:
                            raise HTTPException(
                                status_code=status.HTTP_409_CONFLICT,
                                detail="Idempotency key reused with conflicting request parameters",
                            )
                        return RazorpayOrderResponse(**cached["response_body"])

        config = self._resolve_config()
        rzp_client = self._get_client(config)

        internal_id = f"rzp_ord_{uuid4().hex[:16]}"
        now = datetime.now(timezone.utc)
        now_str = now.isoformat()

        # Invoke Razorpay SDK order creation
        order_payload = {
            "amount": request.amount_paise,
            "currency": request.currency,
            "receipt": request.receipt or internal_id,
            "notes": request.notes or {},
        }
        try:
            rzp_order = rzp_client.order.create(data=order_payload)
            razorpay_order_id = rzp_order.get("id")
            if not razorpay_order_id:
                raise ValueError("Provider did not return order id")
        except Exception as e:
            logger.error(f"Failed to create order via Razorpay client: {e}")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Razorpay provider error: {e}",
            )

        # Persist order record
        if self.session is not None:
            from app.models.razorpay import RazorpayOrder
            order_entity = RazorpayOrder(
                id=internal_id,
                razorpay_order_id=razorpay_order_id,
                admin_id=actor.user_id,
                amount_paise=request.amount_paise,
                currency=request.currency,
                status="created",
                receipt=request.receipt or internal_id,
                notes_json=request.notes,
            )
            self.session.add(order_entity)
            self.session.flush()
        else:
            with self._lock:
                self._mock_orders[razorpay_order_id] = {
                    "id": internal_id,
                    "razorpay_order_id": razorpay_order_id,
                    "admin_id": actor.user_id,
                    "amount_paise": request.amount_paise,
                    "currency": request.currency,
                    "status": "created",
                    "receipt": request.receipt or internal_id,
                    "notes_json": request.notes,
                    "created_at": now_str,
                    "updated_at": now_str,
                }

        response = RazorpayOrderResponse(
            id=internal_id,
            razorpay_order_id=razorpay_order_id,
            amount_paise=request.amount_paise,
            currency=request.currency,
            status="created",
            receipt=request.receipt,
            key_id=config.key_id,
            created_at=now_str,
        )

        # Persist idempotency record
        if effective_key and request_hash:
            if self.session is not None:
                from app.models.idempotency import IdempotencyRecord
                idem_entry = IdempotencyRecord(
                    key=effective_key,
                    caller_id=actor.user_id,
                    endpoint=endpoint,
                    request_hash=request_hash,
                    response_status=status.HTTP_201_CREATED,
                    response_body=response.model_dump(),
                )
                self.session.add(idem_entry)
                self.session.flush()
            else:
                with self._lock:
                    self._idempotency_records[effective_key] = {
                        "caller_id": actor.user_id,
                        "endpoint": endpoint,
                        "request_hash": request_hash,
                        "response_body": response.model_dump(),
                    }

        return response

    def verify_checkout(
        self,
        actor: TrustedActorContext,
        request: RazorpayVerifyRequest,
    ) -> RazorpayVerifyResponse:
        """Verify client-submitted payment signature and reconcile status against provider."""
        try:
            require_sandbox_admin(actor)
        except RazorpaySandboxError as e:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Sandbox authorization failed: {e}",
            )

        config = self._resolve_config()

        # 1. Server-side payment signature verification
        is_valid = verify_payment_signature(
            order_id=request.razorpay_order_id,
            payment_id=request.razorpay_payment_id,
            signature=request.razorpay_signature,
            key_secret=config.key_secret,
        )
        if not is_valid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid payment signature; authenticity verification failed",
            )

        # 2. Match against stored internal order
        stored_order = None
        if self.session is not None:
            from app.models.razorpay import RazorpayOrder, RazorpayPayment
            stored_order = (
                self.session.query(RazorpayOrder)
                .filter(RazorpayOrder.razorpay_order_id == request.razorpay_order_id)
                .one_or_none()
            )
        else:
            with self._lock:
                stored_order = self._mock_orders.get(request.razorpay_order_id)

        if stored_order is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No matching order found for Razorpay order ID {request.razorpay_order_id}",
            )

        # Enforce admin ownership of merchant order
        order_owner_id = (
            stored_order.admin_id if hasattr(stored_order, "admin_id") else stored_order["admin_id"]
        )
        if order_owner_id != actor.user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Unauthorized: Admin does not own this merchant order",
            )

        stored_amount = (
            stored_order.amount_paise if hasattr(stored_order, "amount_paise") else stored_order["amount_paise"]
        )
        internal_order_id = stored_order.id if hasattr(stored_order, "id") else stored_order["id"]

        # 3. Reconcile with provider
        rzp_client = self._get_client(config)
        try:
            payment_info = rzp_client.payment.fetch(request.razorpay_payment_id)
        except Exception as e:
            logger.error(f"Failed to fetch payment from Razorpay: {e}")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Provider reconciliation error: {e}",
            )

        provider_order_id = payment_info.get("order_id")
        provider_amount = payment_info.get("amount")
        provider_status = payment_info.get("status")

        if provider_order_id != request.razorpay_order_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Payment order ID mismatch with stored order",
            )

        if provider_amount != stored_amount:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Amount mismatch: provider reported {provider_amount} paise, order has {stored_amount} paise",
            )

        if provider_status not in ("authorized", "captured"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Payment status is {provider_status}, not successful",
            )

        now = datetime.now(timezone.utc)
        now_str = now.isoformat()

        # 4. Update status and record payment atomically
        if self.session is not None:
            stored_order.status = "paid"
            payment_record = (
                self.session.query(RazorpayPayment)
                .filter(RazorpayPayment.id == request.razorpay_payment_id)
                .one_or_none()
            )
            if payment_record is None:
                payment_record = RazorpayPayment(
                    id=request.razorpay_payment_id,
                    order_id=internal_order_id,
                    razorpay_order_id=request.razorpay_order_id,
                    amount_paise=stored_amount,
                    currency="INR",
                    status=provider_status,
                    method=payment_info.get("method"),
                    signature=request.razorpay_signature,
                    verified_at=now,
                )
                self.session.add(payment_record)
            else:
                payment_record.status = provider_status
                payment_record.verified_at = now
            self.session.flush()
        else:
            with self._lock:
                stored_order["status"] = "paid"
                stored_order["updated_at"] = now_str
                self._mock_payments[request.razorpay_payment_id] = {
                    "id": request.razorpay_payment_id,
                    "order_id": internal_order_id,
                    "razorpay_order_id": request.razorpay_order_id,
                    "amount_paise": stored_amount,
                    "currency": "INR",
                    "status": provider_status,
                    "method": payment_info.get("method"),
                    "signature": request.razorpay_signature,
                    "verified_at": now_str,
                    "created_at": now_str,
                }

        return RazorpayVerifyResponse(
            verified=True,
            status="paid",
            order_id=internal_order_id,
            razorpay_order_id=request.razorpay_order_id,
            razorpay_payment_id=request.razorpay_payment_id,
            amount_paise=stored_amount,
            currency="INR",
            reconciled_with_provider=True,
            verified_at=now_str,
        )

    def process_webhook(
        self,
        raw_body: bytes,
        signature: str,
    ) -> RazorpayWebhookResponse:
        """Process inbound Razorpay webhook event with signature verification and replay protection."""
        config = self._resolve_config()

        webhook_secret = config.webhook_secret
        if not webhook_secret:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Razorpay webhook secret is not configured",
            )

        # 1. Verify HMAC-SHA256 signature against original raw request bytes
        is_valid = verify_webhook_signature(
            raw_body=raw_body,
            signature=signature,
            webhook_secret=webhook_secret,
        )
        if not is_valid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid webhook signature; authentication failed",
            )

        # 2. Parse event payload
        try:
            event_data = json.loads(raw_body.decode("utf-8"))
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Malformed webhook JSON payload",
            )

        if not isinstance(event_data, dict):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Webhook JSON payload must be an object",
            )
        event_id = event_data.get("id")
        event_type = event_data.get("event")
        if not isinstance(event_id, str) or not event_id.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Webhook event payload missing unique event ID",
            )
        event_id = event_id.strip()
        payment_entity = self._extract_webhook_payment_entity(event_data)
        payment_id = payment_entity.get("id") if isinstance(payment_entity.get("id"), str) else None
        rzp_order_id = payment_entity.get("order_id") if isinstance(payment_entity.get("order_id"), str) else None

        # Check durable configuration availability if session is missing
        if self.session is None:
            try:
                settings = load_settings()
                is_local_mock = (
                    getattr(settings, "environment", "development") in ("local", "test", "development")
                    and getattr(settings, "mode", "mock") == "mock"
                )
            except Exception:
                is_local_mock = False

            if not is_local_mock:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Durable persistence is required for webhook replay protection but database session is not configured",
                )

        now = datetime.now(timezone.utc)

        # 3. Deduplication and Replay Protection
        if self.session is not None:
            from app.models.razorpay import RazorpayOrder, RazorpayPayment, RazorpayWebhookEvent
            from sqlalchemy.exc import IntegrityError

            existing_event = (
                self.session.query(RazorpayWebhookEvent)
                .filter(RazorpayWebhookEvent.id == event_id)
                .one_or_none()
            )
            if existing_event is not None:
                return RazorpayWebhookResponse(
                    status="duplicate",
                    event_id=event_id,
                    event_type=event_type or "unknown",
                    message="Webhook event previously processed; duplicate suppressed",
                    can_authorize_p2p_payment=False,
                )

            # Record event in database with atomic uniqueness guard
            webhook_entity = RazorpayWebhookEvent(
                id=event_id,
                event_type=event_type or "unknown",
                entity_id=payment_id,
                payload_json=event_data,
                status="processed",
            )
            try:
                self.session.add(webhook_entity)
                self.session.flush()
            except IntegrityError:
                self.session.rollback()
                return RazorpayWebhookResponse(
                    status="duplicate",
                    event_id=event_id,
                    event_type=event_type or "unknown",
                    message="Concurrent duplicate webhook suppressed by unique constraint",
                    can_authorize_p2p_payment=False,
                )

            # Reconcile if payment captured
            if event_type == "payment.captured":
                if rzp_order_id:
                    order_obj = (
                        self.session.query(RazorpayOrder)
                        .filter(RazorpayOrder.razorpay_order_id == rzp_order_id)
                        .one_or_none()
                    )
                    if order_obj:
                        order_obj.status = "paid"
                    if payment_id and order_obj:
                        pay_record = (
                            self.session.query(RazorpayPayment)
                            .filter(RazorpayPayment.id == payment_id)
                            .one_or_none()
                        )
                        if pay_record is None:
                            pay_record = RazorpayPayment(
                                id=payment_id,
                                order_id=order_obj.id,
                                razorpay_order_id=rzp_order_id,
                                amount_paise=payment_entity.get("amount", order_obj.amount_paise),
                                currency=payment_entity.get("currency", "INR"),
                                status="captured",
                                method=payment_entity.get("method"),
                                verified_at=now,
                            )
                            self.session.add(pay_record)
                        elif pay_record.status not in ("captured", "refunded"):
                            pay_record.status = "captured"
                            pay_record.verified_at = now
            elif event_type == "payment.failed":
                if rzp_order_id:
                    order_obj = (
                        self.session.query(RazorpayOrder)
                        .filter(RazorpayOrder.razorpay_order_id == rzp_order_id)
                        .one_or_none()
                    )
                    # Out-of-order protection: NEVER revert an already-paid order to failed
                    if order_obj and order_obj.status != "paid":
                        order_obj.status = "failed"
            self.session.flush()
        else:
            with self._lock:
                if not self._replay_guard.record_if_new(event_id):
                    return RazorpayWebhookResponse(
                        status="duplicate",
                        event_id=event_id,
                        event_type=event_type or "unknown",
                        message="Webhook event previously processed; duplicate suppressed",
                        can_authorize_p2p_payment=False,
                    )

                if event_type == "payment.captured":
                    if rzp_order_id in self._mock_orders:
                        self._mock_orders[rzp_order_id]["status"] = "paid"
                elif event_type == "payment.failed":
                    if rzp_order_id in self._mock_orders:
                        # Out-of-order protection: NEVER revert an already-paid order to failed
                        if self._mock_orders[rzp_order_id]["status"] != "paid":
                            self._mock_orders[rzp_order_id]["status"] = "failed"

        return RazorpayWebhookResponse(
            status="processed",
            event_id=event_id,
            event_type=event_type or "unknown",
            message="Webhook event verified and processed successfully",
            can_authorize_p2p_payment=False,
        )

    @staticmethod
    def _extract_webhook_payment_entity(event_data: dict[str, Any]) -> dict[str, Any]:
        """Validate nested webhook payload/payment/entity objects and return the payment entity."""
        current: dict[str, Any] = event_data
        for key, detail in (
            ("payload", "Webhook payload field must be an object"),
            ("payment", "Webhook payment field must be an object"),
            ("entity", "Webhook payment entity must be an object"),
        ):
            if key not in current:
                return {}
            nxt = current[key]
            if not isinstance(nxt, dict):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=detail,
                )
            current = nxt
        return current

    def get_order(
        self,
        actor: TrustedActorContext,
        order_id: str,
    ) -> dict:
        """Retrieve stored merchant order and payment history."""
        try:
            require_sandbox_admin(actor)
        except RazorpaySandboxError as e:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Sandbox authorization failed: {e}",
            )

        if self.session is not None:
            from app.models.razorpay import RazorpayOrder
            order = (
                self.session.query(RazorpayOrder)
                .filter((RazorpayOrder.id == order_id) | (RazorpayOrder.razorpay_order_id == order_id))
                .one_or_none()
            )
            if not order:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
            if order.admin_id != actor.user_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Unauthorized: Admin does not own this merchant order",
                )
            return {
                "id": order.id,
                "razorpay_order_id": order.razorpay_order_id,
                "admin_id": str(order.admin_id),
                "amount_paise": order.amount_paise,
                "currency": order.currency,
                "status": order.status,
                "receipt": order.receipt,
                "created_at": order.created_at.isoformat(),
                "payments": [
                    {
                        "id": p.id,
                        "status": p.status,
                        "amount_paise": p.amount_paise,
                        "method": p.method,
                        "verified_at": p.verified_at.isoformat() if p.verified_at else None,
                    }
                    for p in order.payments
                ],
            }
        else:
            with self._lock:
                for ord_data in self._mock_orders.values():
                    if ord_data["id"] == order_id or ord_data["razorpay_order_id"] == order_id:
                        if ord_data["admin_id"] != actor.user_id:
                            raise HTTPException(
                                status_code=status.HTTP_403_FORBIDDEN,
                                detail="Unauthorized: Admin does not own this merchant order",
                            )
                        payments = [
                            p for p in self._mock_payments.values()
                            if p["order_id"] == ord_data["id"] or p["razorpay_order_id"] == ord_data["razorpay_order_id"]
                        ]
                        return {**ord_data, "admin_id": str(ord_data["admin_id"]), "payments": payments}
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")


_global_razorpay_service: Optional[RazorpayMerchantService] = None


def get_razorpay_service() -> RazorpayMerchantService:
    """Retrieve or initialize the global in-memory Razorpay merchant service singleton."""
    global _global_razorpay_service
    if _global_razorpay_service is None:
        _global_razorpay_service = RazorpayMerchantService()
    return _global_razorpay_service

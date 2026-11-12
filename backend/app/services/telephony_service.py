"""In-app simulated telephony and call status service.

SECURITY INVARIANTS:
1. Call answered is NEVER payment approval: A phone call connecting or being
   answered by a guardian never authorizes, approves, or executes a payment.
2. Webhook status cannot execute: Provider callbacks record delivery metrics
   only and have can_authorize_payment=False.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
import threading
from typing import Dict, Optional
from uuid import UUID

from fastapi import HTTPException, status

from app.auth.exceptions import AuthorizationError
from app.auth.identities import SYNTHETIC_GUARDIAN_ID
from app.auth.schemas import (
    CallCallbackRequest,
    CallCallbackResponse,
    CallStatusResponse,
)
from app.models.roles import UserRole
from app.services.payment_guards import TrustedActorContext


@dataclass
class CallRecord:
    call_id: str
    payment_id: str
    guardian_id: UUID
    status: str
    answered: bool
    created_at: str
    updated_at: str


class TelephonyService:
    """Thread-safe simulated telephony call state manager."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._calls: Dict[str, CallRecord] = {}
        self._seed_default_calls()

    def _seed_default_calls(self) -> None:
        now_str = datetime.now(timezone.utc).isoformat()
        self._calls["call_synthetic_001"] = CallRecord(
            call_id="call_synthetic_001",
            payment_id="pg_synthetic_001",
            guardian_id=SYNTHETIC_GUARDIAN_ID,
            status="in-progress",
            answered=False,
            created_at=now_str,
            updated_at=now_str,
        )

    def reset_for_testing(self) -> None:
        with self._lock:
            self._calls.clear()
            self._seed_default_calls()

    def seed_call(self, record: CallRecord) -> None:
        with self._lock:
            self._calls[record.call_id] = record

    def get_call_status(
        self,
        actor: TrustedActorContext,
        call_id: str,
    ) -> CallStatusResponse:
        """Retrieve simulated call delivery and answer status."""
        if not isinstance(actor, TrustedActorContext):
            raise AuthorizationError("Valid server actor context required")

        with self._lock:
            record = self._calls.get(call_id)
            if record is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Call record not found")

            # Check actor role permission
            if UserRole.PAYER not in actor.roles and UserRole.GUARDIAN not in actor.roles and UserRole.ADMIN not in actor.roles:
                raise AuthorizationError("Forbidden: Insufficient privileges to view call status")

            return CallStatusResponse(
                call_id=record.call_id,
                payment_id=record.payment_id,
                guardian_id=record.guardian_id,
                status=record.status,
                answered=record.answered,
                can_authorize_payment=False,
            )

    def record_provider_callback(
        self,
        request: CallCallbackRequest,
    ) -> CallCallbackResponse:
        """Record an inbound telephony provider webhook callback."""
        now_str = datetime.now(timezone.utc).isoformat()
        with self._lock:
            record = self._calls.get(request.call_id)
            if record is not None:
                record.status = request.event
                if request.event.lower() in ("answered", "completed"):
                    record.answered = True
                record.updated_at = now_str
                status_label = record.status
            else:
                # Store new call status even if not previously tracked
                status_label = request.event

            return CallCallbackResponse(
                call_id=request.call_id,
                status=status_label,
                recorded=True,
                can_authorize_payment=False,
            )


_default_telephony_service: Optional[TelephonyService] = None


def get_telephony_service() -> TelephonyService:
    """Retrieve or initialize the global TelephonyService singleton."""
    global _default_telephony_service
    if _default_telephony_service is None:
        _default_telephony_service = TelephonyService()
    return _default_telephony_service


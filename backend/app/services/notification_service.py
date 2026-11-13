"""Provider-abstracted durable notification outbox service for PauseGuard V5.

SECURITY INVARIANTS:
1. Privacy redaction: Guardian outbox payloads NEVER contain amount_paise, beneficiary_id,
   beneficiary, account_balance, or payer_account details.
2. Fail-closed stub channels: WebPushStubProvider and SmsStubProvider are strictly mock-only
   and fail closed outside local/test mock mode.
3. Cold-import safe: Never imports ORM models at module top-level.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID, uuid4

from app.auth.v5_schemas import NotificationOutboxItemView, NotificationOutboxListResponse
from app.services.payment_guards import TrustedActorContext
from app.services.v5_store import MockNotificationOutboxRecord, V5MockIdentityStore

_GUARDIAN_FORBIDDEN_FIELDS = frozenset({
    "amount_paise",
    "beneficiary_id",
    "beneficiary",
    "account_balance",
    "payer_account",
    "upi_pin",
})


def sanitize_notification_payload(
    recipient_role: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Strip sensitive financial fields for non-payer (guardian/fallback) notifications."""
    cleaned = dict(payload)
    if recipient_role.upper() != "PAYER":
        for forbidden_key in _GUARDIAN_FORBIDDEN_FIELDS:
            cleaned.pop(forbidden_key, None)
        cleaned["redacted"] = True
        cleaned.setdefault(
            "message",
            "PauseGuard security review required: Please review this transaction.",
        )
    return cleaned


@dataclass(frozen=True)
class ProviderDispatchResult:
    channel: str
    delivery_provider: str
    status: str
    attempts: int = 1
    last_error: str | None = None


class NotificationProvider(ABC):
    """Abstract outbox delivery provider interface."""

    @property
    @abstractmethod
    def channel(self) -> str:
        """Delivery channel constant (IN_APP, WEB_PUSH, SMS_STUB)."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Provider identifier stored in audit/outbox."""

    @abstractmethod
    def dispatch(
        self,
        *,
        recipient_user_id: UUID,
        recipient_role: str,
        event_type: str,
        payload: dict[str, Any],
        settings: object | None = None,
    ) -> ProviderDispatchResult:
        """Execute outbound dispatch through this provider."""


class InAppOutboxProvider(NotificationProvider):
    """Durable in-app polling/WebSocket companion outbox provider."""

    @property
    def channel(self) -> str:
        return "IN_APP"

    @property
    def provider_name(self) -> str:
        return "in_app_outbox"

    def dispatch(
        self,
        *,
        recipient_user_id: UUID,
        recipient_role: str,
        event_type: str,
        payload: dict[str, Any],
        settings: object | None = None,
    ) -> ProviderDispatchResult:
        return ProviderDispatchResult(
            channel=self.channel,
            delivery_provider=self.provider_name,
            status="SENT",
            attempts=1,
        )


def _assert_stub_channel_allowed(settings: object | None, provider_label: str) -> None:
    env = getattr(settings, "environment", "local")
    mode = getattr(settings, "mode", "mock")
    if env == "production" or mode != "mock":
        raise RuntimeError(
            f"Mock notification stub '{provider_label}' is forbidden outside local/test mock mode."
        )


class WebPushStubProvider(NotificationProvider):
    """Offline mock stub simulating browser Web Push dispatch."""

    @property
    def channel(self) -> str:
        return "WEB_PUSH"

    @property
    def provider_name(self) -> str:
        return "web_push_stub"

    def dispatch(
        self,
        *,
        recipient_user_id: UUID,
        recipient_role: str,
        event_type: str,
        payload: dict[str, Any],
        settings: object | None = None,
    ) -> ProviderDispatchResult:
        _assert_stub_channel_allowed(settings, self.provider_name)
        return ProviderDispatchResult(
            channel=self.channel,
            delivery_provider=self.provider_name,
            status="SENT",
            attempts=1,
        )


class SmsStubProvider(NotificationProvider):
    """Offline mock stub simulating SMS notification dispatch."""

    @property
    def channel(self) -> str:
        return "SMS_STUB"

    @property
    def provider_name(self) -> str:
        return "sms_stub"

    def dispatch(
        self,
        *,
        recipient_user_id: UUID,
        recipient_role: str,
        event_type: str,
        payload: dict[str, Any],
        settings: object | None = None,
    ) -> ProviderDispatchResult:
        _assert_stub_channel_allowed(settings, self.provider_name)
        return ProviderDispatchResult(
            channel=self.channel,
            delivery_provider=self.provider_name,
            status="SENT",
            attempts=1,
        )


class NotificationOutboxService:
    """Persist and retrieve redacted outbox records across PostgreSQL or app mock store."""

    def __init__(
        self,
        *,
        settings: object | None = None,
        db_session: Any | None = None,
        mock_store: V5MockIdentityStore | None = None,
        providers: tuple[NotificationProvider, ...] | None = None,
    ) -> None:
        self._settings = settings
        self._db_session = db_session
        self._mock_store = mock_store
        self._providers = providers or (InAppOutboxProvider(),)

    def _enqueue_for_recipient(
        self,
        *,
        payment_id: str | None,
        recipient_user_id: UUID,
        recipient_role: str,
        event_type: str,
        raw_payload: dict[str, Any],
        providers: tuple[NotificationProvider, ...] | None = None,
    ) -> None:
        now = datetime.now(timezone.utc)
        sanitized = sanitize_notification_payload(recipient_role, raw_payload)
        active_providers = providers or self._providers

        for provider in active_providers:
            result = provider.dispatch(
                recipient_user_id=recipient_user_id,
                recipient_role=recipient_role,
                event_type=event_type,
                payload=sanitized,
                settings=self._settings,
            )
            if self._db_session is not None:
                from sqlalchemy import select
                from app.models.notifications import NotificationOutbox
                from app.models.user import SyntheticUser

                # Ensure parent users row exists before inserting FK-constrained outbox row
                exists = self._db_session.execute(
                    select(SyntheticUser.id).where(SyntheticUser.id == recipient_user_id)
                ).scalar_one_or_none()
                if exists is None:
                    continue
                row = NotificationOutbox(
                    id=uuid4(),
                    payment_id=payment_id,
                    recipient_user_id=recipient_user_id,
                    recipient_role=recipient_role,
                    channel=result.channel,
                    event_type=event_type,
                    payload_json=sanitized,
                    status=result.status,
                    delivery_provider=result.delivery_provider,
                    attempts=result.attempts,
                    last_error=result.last_error,
                    created_at=now,
                    delivered_at=now if result.status == "SENT" else None,
                )
                self._db_session.add(row)
            elif self._mock_store is not None:
                with self._mock_store.lock:
                    self._mock_store.notification_outbox.append(
                        MockNotificationOutboxRecord(
                            id=uuid4(),
                            payment_id=payment_id,
                            recipient_user_id=recipient_user_id,
                            recipient_role=recipient_role,
                            channel=result.channel,
                            event_type=event_type,
                            payload_json=sanitized,
                            status=result.status,
                            delivery_provider=result.delivery_provider,
                            attempts=result.attempts,
                            last_error=result.last_error,
                            created_at=now,
                            delivered_at=now if result.status == "SENT" else None,
                        )
                    )

    def record_payment_transition(
        self,
        *,
        payment_id: str,
        event_type: str,
        status: str,
        payer_id: UUID,
        assigned_guardian_id: Optional[UUID] = None,
        tier: int = 0,
        amount_paise: Optional[int] = None,
        guardian_deadline: Optional[str] = None,
        extra: Optional[dict[str, Any]] = None,
        include_stub_channel: NotificationProvider | None = None,
    ) -> None:
        """Persist outbox items for payer and assigned guardian (redacted)."""
        now_iso = datetime.now(timezone.utc).isoformat()
        payer_payload: dict[str, Any] = {
            "event_type": event_type,
            "payment_id": payment_id,
            "status": status,
            "tier": tier,
            "amount_paise": amount_paise,
            "guardian_deadline": guardian_deadline,
            "timestamp": now_iso,
        }
        if extra:
            payer_payload["extra"] = extra

        self._enqueue_for_recipient(
            payment_id=payment_id,
            recipient_user_id=payer_id,
            recipient_role="PAYER",
            event_type=event_type,
            raw_payload=payer_payload,
        )

        if assigned_guardian_id is not None:
            guardian_providers: tuple[NotificationProvider, ...] = (
                (InAppOutboxProvider(), include_stub_channel)
                if include_stub_channel is not None
                else (InAppOutboxProvider(),)
            )
            guardian_payload: dict[str, Any] = {
                "event_type": event_type,
                "payment_id": payment_id,
                "status": status,
                "tier": tier,
                "guardian_deadline": guardian_deadline,
                "timestamp": now_iso,
                "message": "PauseGuard security review required: Please review this transaction.",
                "redacted": True,
            }
            self._enqueue_for_recipient(
                payment_id=payment_id,
                recipient_user_id=assigned_guardian_id,
                recipient_role="GUARDIAN",
                event_type=event_type,
                raw_payload=guardian_payload,
                providers=guardian_providers,
            )

    def list_outbox_for_actor(
        self,
        actor: TrustedActorContext,
        *,
        limit: int = 50,
    ) -> NotificationOutboxListResponse:
        """Return only notifications belonging to the authenticated actor."""
        bounded_limit = max(1, min(limit, 200))
        items: list[NotificationOutboxItemView] = []
        if self._db_session is not None:
            from sqlalchemy import select
            from app.models.notifications import NotificationOutbox

            rows = self._db_session.execute(
                select(NotificationOutbox)
                .where(NotificationOutbox.recipient_user_id == actor.user_id)
                .order_by(NotificationOutbox.created_at.desc())
                .limit(bounded_limit)
            ).scalars().all()
            for r in rows:
                items.append(
                    NotificationOutboxItemView(
                        notification_id=r.id,
                        payment_id=r.payment_id,
                        recipient_user_id=r.recipient_user_id,
                        recipient_role=r.recipient_role,
                        channel=r.channel,
                        event_type=r.event_type,
                        payload=sanitize_notification_payload(r.recipient_role, dict(r.payload_json)),
                        status=r.status,
                        delivery_provider=r.delivery_provider,
                        attempts=r.attempts,
                        created_at=r.created_at,
                        delivered_at=r.delivered_at,
                    )
                )
        elif self._mock_store is not None:
            with self._mock_store.lock:
                matching = [
                    r for r in self._mock_store.notification_outbox
                    if r.recipient_user_id == actor.user_id
                ]
                matching.sort(key=lambda r: r.created_at, reverse=True)
                for r in matching[:bounded_limit]:
                    items.append(
                        NotificationOutboxItemView(
                            notification_id=r.id,
                            payment_id=r.payment_id,
                            recipient_user_id=r.recipient_user_id,
                            recipient_role=r.recipient_role,
                            channel=r.channel,
                            event_type=r.event_type,
                            payload=sanitize_notification_payload(
                                r.recipient_role, dict(r.payload_json)
                            ),
                            status=r.status,
                            delivery_provider=r.delivery_provider,
                            attempts=r.attempts,
                            created_at=r.created_at,
                            delivered_at=r.delivered_at,
                        )
                    )
        return NotificationOutboxListResponse(items=items, total=len(items))

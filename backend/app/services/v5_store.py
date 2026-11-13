"""Shared thread-safe in-memory mock store for V5 identity/OTP/enrollment when PostgreSQL is unset.

In PostgreSQL/production-configured runs (app.state.session_factory is present),
all services read and write SQLAlchemy ORM tables inside database transactions.
This in-memory store is strictly isolated per FastAPI app instance via app.state
for local mock-mode previews and unit tests without Docker.
"""

from dataclasses import dataclass
from datetime import datetime
import threading
from typing import Any
from uuid import UUID


@dataclass
class MockUserAccountRecord:
    id: UUID
    email: str
    full_name: str
    role: str
    password_hash: str
    email_verified: bool
    is_active: bool
    is_synthetic: bool
    email_verified_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass
class MockIdentityAssuranceRecord:
    id: UUID
    user_id: UUID
    trusted_person_ref: str
    provider: str
    assurance_level: str
    provider_evidence_ref: str
    is_mock_assurance: bool
    revoked: bool
    verified_at: datetime
    expires_at: datetime
    revoked_at: datetime | None
    created_at: datetime


@dataclass
class MockOtpChallengeRecord:
    id: UUID
    contact: str
    purpose: str
    channel: str
    otp_salt: str
    otp_hash: str
    attempts: int
    max_attempts: int
    status: str
    expires_at: datetime
    consumed_at: datetime | None
    created_at: datetime


@dataclass
class MockUserSessionRecord:
    id: UUID
    user_id: UUID
    token_hash: str
    auth_method: str
    expires_at: datetime
    revoked_at: datetime | None
    created_at: datetime


@dataclass
class MockGuardianInvitationRecord:
    id: UUID
    payer_id: UUID
    guardian_user_id: UUID | None
    guardian_email: str
    relationship_label: str
    role_slot: str
    notification_channel: str
    token_hash: str
    status: str
    payer_trusted_person_ref: str | None
    guardian_trusted_person_ref: str | None
    consent_confirmed: bool
    expires_at: datetime
    accepted_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass
class MockWebSocketTicketRecord:
    ticket_hash: str
    user_id: UUID
    roles: tuple[str, ...]
    expires_at: datetime
    consumed_at: datetime | None
    created_at: datetime


@dataclass
class MockNotificationOutboxRecord:
    id: UUID
    payment_id: str | None
    recipient_user_id: UUID
    recipient_role: str
    channel: str
    event_type: str
    payload_json: dict[str, Any]
    status: str
    delivery_provider: str
    attempts: int
    last_error: str | None
    created_at: datetime
    delivered_at: datetime | None


@dataclass
class MockBankIntentRecord:
    intent_id: str
    payment_id: str
    payer_id: UUID
    amount_paise: int
    rail: str
    adapter: str
    settlement_status: str
    is_mock: bool
    created_at: datetime
    settled_at: datetime | None = None


class V5MockIdentityStore:
    """Thread-safe container attached to FastAPI app.state for local mock mode."""

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.users_by_id: dict[UUID, MockUserAccountRecord] = {}
        self.users_by_email: dict[str, UUID] = {}
        self.assurances_by_user: dict[UUID, list[MockIdentityAssuranceRecord]] = {}
        self.otp_challenges: dict[UUID, MockOtpChallengeRecord] = {}
        self.sessions_by_token_hash: dict[str, MockUserSessionRecord] = {}
        self.invitations_by_id: dict[UUID, MockGuardianInvitationRecord] = {}
        self.ws_tickets_by_hash: dict[str, MockWebSocketTicketRecord] = {}
        self.notification_outbox: list[MockNotificationOutboxRecord] = []
        self.bank_intents_by_id: dict[str, MockBankIntentRecord] = {}
        self.bank_intents_by_payment: dict[str, str] = {}
        self.bank_webhook_events_seen: dict[str, str] = {}


def get_or_create_v5_mock_store(app_state: object) -> V5MockIdentityStore:
    """Return the per-app V5MockIdentityStore, creating it lazily if absent."""
    store = getattr(app_state, "v5_identity_store", None)
    if store is None:
        store = V5MockIdentityStore()
        setattr(app_state, "v5_identity_store", store)
    return store


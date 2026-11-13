"""Provider-agnostic OTP verification service with salted HMAC hashing and lockout.

SECURITY INVARIANTS:
- Plaintext OTP codes are NEVER stored in PostgreSQL or in-memory challenge records.
- Plaintext OTP codes are NEVER written to application logs or audit payloads.
- CSPRNG 6-digit OTPs are bound with per-challenge random salts + HMAC-SHA256.
- Single-use enforcement, short TTL (300s), cooldown throttling (30s), and 5-attempt lockout.
- Local deterministic delivery provider is strictly blocked outside local/test mock mode.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import secrets
from typing import Any
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, load_settings
from app.services.v5_store import MockOtpChallengeRecord, V5MockIdentityStore

_OTP_HMAC_PEPPER = b"pauseguard-v5-otp-hmac-pepper-local"
OTP_TTL_SECONDS = 300
OTP_COOLDOWN_SECONDS = 30
OTP_MAX_ATTEMPTS = 5
ALLOWED_OTP_PURPOSES = frozenset({"signup_email", "login_step_up", "guardian_invite"})
ALLOWED_OTP_CHANNELS = frozenset({"email", "sms_stub"})


@dataclass(frozen=True)
class OtpDispatchResult:
    challenge_id: UUID
    contact: str
    purpose: str
    channel: str
    expires_at: datetime
    is_mock_delivery: bool
    provider_name: str
    dev_otp_preview: str | None = None


@dataclass(frozen=True)
class OtpVerificationResult:
    challenge_id: UUID
    contact: str
    purpose: str
    verified: bool
    verified_at: datetime


class OtpProvider(ABC):
    """Abstract provider boundary for OTP delivery."""

    @property
    @abstractmethod
    def provider_name(self) -> str: ...

    @property
    @abstractmethod
    def is_mock(self) -> bool: ...

    @abstractmethod
    def deliver_otp(
        self,
        *,
        contact: str,
        purpose: str,
        channel: str,
        otp_code: str,
        settings: Settings,
    ) -> str | None:
        """Deliver OTP via transport; optionally return preview string in local mock mode only."""


class DeterministicLocalOtpProvider(OtpProvider):
    """Explicitly labeled local mock OTP transport (never allowed in production)."""

    @property
    def provider_name(self) -> str:
        return "local_mock_otp_provider"

    @property
    def is_mock(self) -> bool:
        return True

    def deliver_otp(
        self,
        *,
        contact: str,
        purpose: str,
        channel: str,
        otp_code: str,
        settings: Settings,
    ) -> str | None:
        if settings.environment not in {"local", "test"} or settings.mode != "mock":
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Local mock OTP provider is disabled in this environment.",
            )
        # Never write OTP to logs. Return strictly inside explicit mock response payload.
        return otp_code


class StagedExternalOtpProvider(OtpProvider):
    """Fail-closed placeholder for future authorized SMTP / SMS gateway credentials."""

    @property
    def provider_name(self) -> str:
        return "staged_external_otp_provider"

    @property
    def is_mock(self) -> bool:
        return False

    def deliver_otp(
        self,
        *,
        contact: str,
        purpose: str,
        channel: str,
        otp_code: str,
        settings: Settings,
    ) -> str | None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="External OTP delivery provider credentials are not configured.",
        )


def _normalize_contact(contact: str) -> str:
    return contact.strip().lower()


def _hash_otp(*, salt: str, contact: str, purpose: str, otp_code: str) -> str:
    payload = f"{salt}:{contact}:{purpose}:{otp_code}".encode("utf-8")
    return hmac.new(_OTP_HMAC_PEPPER, payload, hashlib.sha256).hexdigest()


class OtpService:
    """Durable/mock-parity OTP challenge lifecycle manager."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        db_session: Session | None = None,
        mock_store: V5MockIdentityStore | None = None,
        provider: OtpProvider | None = None,
        cooldown_seconds: int = OTP_COOLDOWN_SECONDS,
    ) -> None:
        self._settings = settings or load_settings()
        self._db = db_session
        self._mock_store = mock_store
        self._provider = provider or DeterministicLocalOtpProvider()
        self._cooldown_seconds = cooldown_seconds

        if self._db is None and (self._mock_store is None or self._settings.mode != "mock"):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="OTP persistence backend is unavailable.",
            )

    def create_challenge(
        self,
        *,
        contact: str,
        purpose: str,
        channel: str = "email",
        now: datetime | None = None,
        bypass_cooldown: bool = False,
    ) -> OtpDispatchResult:
        normalized = _normalize_contact(contact)
        if not normalized or len(normalized) > 255:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Valid contact is required.")
        if purpose not in ALLOWED_OTP_PURPOSES:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported OTP purpose.")
        if channel not in ALLOWED_OTP_CHANNELS:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported OTP channel.")

        current_time = now or datetime.now(timezone.utc)
        expires_at = current_time + timedelta(seconds=OTP_TTL_SECONDS)

        if not bypass_cooldown and self._cooldown_seconds > 0:
            recent = self._get_latest_challenge(contact=normalized, purpose=purpose)
            if recent is not None and recent.status == "PENDING":
                elapsed = (current_time - recent.created_at).total_seconds()
                if elapsed < self._cooldown_seconds:
                    remaining = max(1, int(self._cooldown_seconds - elapsed))
                    raise HTTPException(
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        detail=f"Please wait {remaining}s before requesting a new OTP.",
                    )

        otp_code = f"{secrets.randbelow(1_000_000):06d}"
        salt = secrets.token_hex(16)
        otp_hash = _hash_otp(salt=salt, contact=normalized, purpose=purpose, otp_code=otp_code)
        challenge_id = uuid4()

        # Call provider before committing challenge so disabled providers fail cleanly
        preview = self._provider.deliver_otp(
            contact=normalized,
            purpose=purpose,
            channel=channel,
            otp_code=otp_code,
            settings=self._settings,
        )

        if self._db is not None:
            from app.models.identity import OtpChallenge

            row = OtpChallenge(
                id=challenge_id,
                contact=normalized,
                purpose=purpose,
                channel=channel,
                otp_salt=salt,
                otp_hash=otp_hash,
                attempts=0,
                max_attempts=OTP_MAX_ATTEMPTS,
                status="PENDING",
                expires_at=expires_at,
                consumed_at=None,
                created_at=current_time,
            )
            self._db.add(row)
            self._db.flush()
        else:
            assert self._mock_store is not None
            with self._mock_store.lock:
                self._mock_store.otp_challenges[challenge_id] = MockOtpChallengeRecord(
                    id=challenge_id,
                    contact=normalized,
                    purpose=purpose,
                    channel=channel,
                    otp_salt=salt,
                    otp_hash=otp_hash,
                    attempts=0,
                    max_attempts=OTP_MAX_ATTEMPTS,
                    status="PENDING",
                    expires_at=expires_at,
                    consumed_at=None,
                    created_at=current_time,
                )

        return OtpDispatchResult(
            challenge_id=challenge_id,
            contact=normalized,
            purpose=purpose,
            channel=channel,
            expires_at=expires_at,
            is_mock_delivery=self._provider.is_mock,
            provider_name=self._provider.provider_name,
            dev_otp_preview=preview,
        )

    def verify_challenge(
        self,
        *,
        challenge_id: UUID,
        otp_code: str,
        expected_contact: str | None = None,
        expected_purpose: str | None = None,
        now: datetime | None = None,
    ) -> OtpVerificationResult:
        current_time = now or datetime.now(timezone.utc)
        cleaned_code = otp_code.strip()

        if self._db is not None:
            return self._verify_db(
                challenge_id=challenge_id,
                otp_code=cleaned_code,
                expected_contact=expected_contact,
                expected_purpose=expected_purpose,
                current_time=current_time,
            )

        assert self._mock_store is not None
        with self._mock_store.lock:
            record = self._mock_store.otp_challenges.get(challenge_id)
            return self._apply_verification(
                record=record,
                otp_code=cleaned_code,
                expected_contact=expected_contact,
                expected_purpose=expected_purpose,
                current_time=current_time,
                persist_fn=lambda: None,
            )

    def _verify_db(
        self,
        *,
        challenge_id: UUID,
        otp_code: str,
        expected_contact: str | None,
        expected_purpose: str | None,
        current_time: datetime,
    ) -> OtpVerificationResult:
        from app.models.identity import OtpChallenge

        assert self._db is not None
        stmt = select(OtpChallenge).where(OtpChallenge.id == challenge_id)
        bind = self._db.get_bind()
        if bind is not None and bind.dialect.name == "postgresql":
            stmt = stmt.with_for_update()
        row = self._db.execute(stmt).scalar_one_or_none()
        return self._apply_verification(
            record=row,
            otp_code=otp_code,
            expected_contact=expected_contact,
            expected_purpose=expected_purpose,
            current_time=current_time,
            persist_fn=self._db.flush,
        )

    def _apply_verification(
        self,
        *,
        record: Any,
        otp_code: str,
        expected_contact: str | None,
        expected_purpose: str | None,
        current_time: datetime,
        persist_fn: Any,
    ) -> OtpVerificationResult:
        if record is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="OTP challenge not found.")

        if expected_contact is not None and record.contact != _normalize_contact(expected_contact):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="OTP challenge does not belong to this contact.")

        if expected_purpose is not None and record.purpose != expected_purpose:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="OTP challenge purpose mismatch.")

        if record.status == "VERIFIED":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="OTP challenge has already been used.")

        if record.status == "LOCKED":
            raise HTTPException(status_code=status.HTTP_423_LOCKED, detail="OTP challenge locked after too many invalid attempts.")

        if record.status == "EXPIRED" or record.expires_at <= current_time:
            record.status = "EXPIRED"
            persist_fn()
            raise HTTPException(status_code=status.HTTP_410_GONE, detail="OTP challenge has expired.")

        candidate_hash = _hash_otp(
            salt=record.otp_salt,
            contact=record.contact,
            purpose=record.purpose,
            otp_code=otp_code,
        )
        if not hmac.compare_digest(candidate_hash, record.otp_hash):
            record.attempts += 1
            if record.attempts >= record.max_attempts:
                record.status = "LOCKED"
                persist_fn()
                raise HTTPException(
                    status_code=status.HTTP_423_LOCKED,
                    detail="OTP challenge locked after too many invalid attempts.",
                )
            persist_fn()
            remaining = record.max_attempts - record.attempts
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid OTP code ({remaining} attempt(s) remaining).",
            )

        record.status = "VERIFIED"
        record.consumed_at = current_time
        persist_fn()
        return OtpVerificationResult(
            challenge_id=record.id,
            contact=record.contact,
            purpose=record.purpose,
            verified=True,
            verified_at=current_time,
        )

    def _get_latest_challenge(self, *, contact: str, purpose: str) -> Any:
        if self._db is not None:
            from app.models.identity import OtpChallenge

            stmt = (
                select(OtpChallenge)
                .where(OtpChallenge.contact == contact, OtpChallenge.purpose == purpose)
                .order_by(OtpChallenge.created_at.desc())
                .limit(1)
            )
            return self._db.execute(stmt).scalar_one_or_none()
        assert self._mock_store is not None
        with self._mock_store.lock:
            matches = [
                c
                for c in self._mock_store.otp_challenges.values()
                if c.contact == contact and c.purpose == purpose
            ]
            if not matches:
                return None
            return max(matches, key=lambda c: c.created_at)


"""Provider-agnostic identity assurance service & synthetic local IDP adapter.

Distinguishes three trust layers strictly:
1. Contact verification (OTP controls email/phone) -> NOT identity assurance
2. Session authentication (user has valid session) -> NOT person distinctness
3. Identity assurance -> server-issued opaque trusted_person_ref from a trusted provider

SECURITY INVARIANTS:
- Raw document references are normalized in memory only to compute an irreversible
  HMAC-SHA256 trusted_person_ref and immediately discarded.
- Clients NEVER supply or override trusted_person_ref.
- SyntheticLocalIdentityProvider is explicitly labeled is_mock_assurance=True and
  fails closed outside local/test mock mode.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import re
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, load_settings
from app.services.v5_store import MockIdentityAssuranceRecord, V5MockIdentityStore

_IDENTITY_HMAC_KEY = b"pauseguard-v5-synthetic-idp-key-local"
_ASSURANCE_TTL_DAYS = 90
_SYNTHETIC_REF_PATTERN = re.compile(r"^[A-Za-z0-9._:@/-]{4,64}$")


@dataclass(frozen=True)
class AssuranceAssertion:
    """Provider verification output (free of raw document inputs)."""

    trusted_person_ref: str
    provider: str
    assurance_level: str
    provider_evidence_ref: str
    is_mock_assurance: bool


@dataclass(frozen=True)
class IdentityAssuranceView:
    assurance_id: UUID
    user_id: UUID
    trusted_person_ref: str
    provider: str
    assurance_level: str
    is_mock_assurance: bool
    revoked: bool
    verified_at: datetime
    expires_at: datetime


class IdentityAssuranceProvider(ABC):
    """Abstract identity assurance provider boundary."""

    @property
    @abstractmethod
    def provider_id(self) -> str: ...

    @abstractmethod
    def verify_person(
        self,
        *,
        full_name: str,
        synthetic_document_ref: str,
        settings: Settings,
    ) -> AssuranceAssertion: ...


class SyntheticLocalIdentityProvider(IdentityAssuranceProvider):
    """Explicitly synthetic offline/sandbox identity provider for local testing."""

    @property
    def provider_id(self) -> str:
        return "synthetic_local_idp"

    def verify_person(
        self,
        *,
        full_name: str,
        synthetic_document_ref: str,
        settings: Settings,
    ) -> AssuranceAssertion:
        if settings.environment not in {"local", "test"} or settings.mode != "mock":
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Synthetic identity provider is disabled in production environments.",
            )

        cleaned_name = " ".join(full_name.strip().split())
        if len(cleaned_name) < 2:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Full legal name must be at least 2 characters.",
            )

        normalized_ref = re.sub(r"[\s-]+", "", synthetic_document_ref.strip().upper())
        if not _SYNTHETIC_REF_PATTERN.match(normalized_ref):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid synthetic document reference format (4-64 alphanumeric characters).",
            )

        person_digest = hmac.new(
            _IDENTITY_HMAC_KEY,
            f"person:{normalized_ref}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()[:40]
        evidence_digest = hmac.new(
            _IDENTITY_HMAC_KEY,
            f"ev:{cleaned_name.upper()}:{normalized_ref}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()[:32]

        return AssuranceAssertion(
            trusted_person_ref=f"tpr_{person_digest}",
            provider=self.provider_id,
            assurance_level="SYNTHETIC_STANDARD",
            provider_evidence_ref=f"ev_{evidence_digest}",
            is_mock_assurance=True,
        )


class StagedBankKycIdentityProvider(IdentityAssuranceProvider):
    """Fail-closed placeholder for future bank-KYC / DigiLocker / UIDAI integration."""

    @property
    def provider_id(self) -> str:
        return "staged_bank_kyc_provider"

    def verify_person(
        self,
        *,
        full_name: str,
        synthetic_document_ref: str,
        settings: Settings,
    ) -> AssuranceAssertion:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="External bank/KYC identity provider is not authorized or configured.",
        )


class IdentityAssuranceService:
    """Server-side lifecycle manager for opaque IdentityAssurance records."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        db_session: Session | None = None,
        mock_store: V5MockIdentityStore | None = None,
    ) -> None:
        self._settings = settings or load_settings()
        self._db = db_session
        self._mock_store = mock_store

        if self._db is None and (self._mock_store is None or self._settings.mode != "mock"):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Identity assurance storage backend is unavailable.",
            )

    def _select_provider(self, provider_name: str) -> IdentityAssuranceProvider:
        if provider_name == "synthetic_local_idp":
            return SyntheticLocalIdentityProvider()
        if provider_name == "staged_bank_kyc_provider":
            return StagedBankKycIdentityProvider()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unknown identity assurance provider.",
        )

    def verify_and_record(
        self,
        *,
        user_id: UUID,
        full_name: str,
        synthetic_document_ref: str,
        consent_confirmed: bool,
        provider_name: str = "synthetic_local_idp",
        now: datetime | None = None,
    ) -> IdentityAssuranceView:
        if not consent_confirmed:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Explicit consent is required for identity assurance verification.",
            )

        provider = self._select_provider(provider_name)
        assertion = provider.verify_person(
            full_name=full_name,
            synthetic_document_ref=synthetic_document_ref,
            settings=self._settings,
        )

        current_time = now or datetime.now(timezone.utc)
        expires_at = current_time + timedelta(days=_ASSURANCE_TTL_DAYS)
        assurance_id = uuid4()

        if self._db is not None:
            from app.models.identity import IdentityAssurance

            # Revoke previous active assurances for clean single active record per user
            existing = self._db.execute(
                select(IdentityAssurance).where(
                    IdentityAssurance.user_id == user_id,
                    IdentityAssurance.revoked.is_(False),
                )
            ).scalars().all()
            for row in existing:
                row.revoked = True
                row.revoked_at = current_time

            new_row = IdentityAssurance(
                id=assurance_id,
                user_id=user_id,
                trusted_person_ref=assertion.trusted_person_ref,
                provider=assertion.provider,
                assurance_level=assertion.assurance_level,
                provider_evidence_ref=assertion.provider_evidence_ref,
                is_mock_assurance=assertion.is_mock_assurance,
                revoked=False,
                verified_at=current_time,
                expires_at=expires_at,
                revoked_at=None,
                created_at=current_time,
            )
            self._db.add(new_row)
            self._db.flush()
        else:
            assert self._mock_store is not None
            with self._mock_store.lock:
                prior = self._mock_store.assurances_by_user.get(user_id, [])
                for rec in prior:
                    if not rec.revoked:
                        rec.revoked = True
                        rec.revoked_at = current_time
                record = MockIdentityAssuranceRecord(
                    id=assurance_id,
                    user_id=user_id,
                    trusted_person_ref=assertion.trusted_person_ref,
                    provider=assertion.provider,
                    assurance_level=assertion.assurance_level,
                    provider_evidence_ref=assertion.provider_evidence_ref,
                    is_mock_assurance=assertion.is_mock_assurance,
                    revoked=False,
                    verified_at=current_time,
                    expires_at=expires_at,
                    revoked_at=None,
                    created_at=current_time,
                )
                prior.append(record)
                self._mock_store.assurances_by_user[user_id] = prior

        return IdentityAssuranceView(
            assurance_id=assurance_id,
            user_id=user_id,
            trusted_person_ref=assertion.trusted_person_ref,
            provider=assertion.provider,
            assurance_level=assertion.assurance_level,
            is_mock_assurance=assertion.is_mock_assurance,
            revoked=False,
            verified_at=current_time,
            expires_at=expires_at,
        )

    def get_active_assurance(
        self,
        user_id: UUID,
        *,
        now: datetime | None = None,
    ) -> IdentityAssuranceView | None:
        current_time = now or datetime.now(timezone.utc)
        if self._db is not None:
            from app.models.identity import IdentityAssurance

            row = (
                self._db.execute(
                    select(IdentityAssurance)
                    .where(
                        IdentityAssurance.user_id == user_id,
                        IdentityAssurance.revoked.is_(False),
                        IdentityAssurance.expires_at > current_time,
                    )
                    .order_by(IdentityAssurance.verified_at.desc())
                    .limit(1)
                )
                .scalar_one_or_none()
            )
            if row is not None:
                return IdentityAssuranceView(
                    assurance_id=row.id,
                    user_id=row.user_id,
                    trusted_person_ref=row.trusted_person_ref,
                    provider=row.provider,
                    assurance_level=row.assurance_level,
                    is_mock_assurance=row.is_mock_assurance,
                    revoked=row.revoked,
                    verified_at=row.verified_at,
                    expires_at=row.expires_at,
                )
        elif self._mock_store is not None:
            with self._mock_store.lock:
                records = self._mock_store.assurances_by_user.get(user_id, [])
                active = [r for r in records if not r.revoked and r.expires_at > current_time]
                if active:
                    latest = max(active, key=lambda r: r.verified_at)
                    return IdentityAssuranceView(
                        assurance_id=latest.id,
                        user_id=latest.user_id,
                        trusted_person_ref=latest.trusted_person_ref,
                        provider=latest.provider,
                        assurance_level=latest.assurance_level,
                        is_mock_assurance=latest.is_mock_assurance,
                        revoked=latest.revoked,
                        verified_at=latest.verified_at,
                        expires_at=latest.expires_at,
                    )

        # Preserve seeded V4.1 demo identities as having distinct synthetic trusted_person_refs
        from app.auth.identities import SYNTHETIC_GUARDIAN_ID, SYNTHETIC_PAYER_ID

        if user_id in (SYNTHETIC_PAYER_ID, SYNTHETIC_GUARDIAN_ID) and self._settings.mode == "mock":
            label = "SEEDED_PAYER" if user_id == SYNTHETIC_PAYER_ID else "SEEDED_GUARDIAN"
            tpr = f"tpr_seeded_{label.lower()}_{str(user_id).replace('-', '')[:16]}"
            return IdentityAssuranceView(
                assurance_id=user_id,
                user_id=user_id,
                trusted_person_ref=tpr,
                provider="synthetic_seeded_demo",
                assurance_level="SYNTHETIC_STANDARD",
                is_mock_assurance=True,
                revoked=False,
                verified_at=current_time,
                expires_at=current_time + timedelta(days=_ASSURANCE_TTL_DAYS),
            )
        return None


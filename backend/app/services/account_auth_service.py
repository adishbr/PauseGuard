"""Durable real-account registration, scrypt password authentication, and session resolution.

SECURITY INVARIANTS:
- Public signup strictly restricts role to ('payer', 'guardian'); 'admin'/'analyst' -> 403.
- Passwords hashed with hashlib.scrypt (N=16384, r=8, p=1) and 16-byte CSPRNG salt.
- Bearer session tokens are 256-bit CSPRNG URL-safe secrets; only SHA-256 digests are persisted.
- Login rejects unverified emails (403) and invalid passwords (401).
- Mock-mode signups initialize sandbox MockAccount and SafeLockState deterministically
  so real mock-mode tests work seamlessly across PostgreSQL and local mock previews.
"""

from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import os
import re
import secrets
from typing import Any
from uuid import NAMESPACE_DNS, UUID, uuid4, uuid5

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, load_settings
from app.models.roles import UserRole
from app.services.identity_assurance_service import IdentityAssuranceService
from app.services.otp_service import OtpService
from app.services.payment_guards import TrustedActorContext
from app.services.v5_store import MockUserAccountRecord, MockUserSessionRecord, V5MockIdentityStore

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PUBLIC_SIGNUP_ROLES = frozenset({UserRole.PAYER.value, UserRole.GUARDIAN.value})
_SESSION_TTL_HOURS = 12
_INITIAL_MOCK_BALANCE_PAISE = 25_000_000  # Rs 2,50,000 local mock sandbox balance


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    n, r, p = 16384, 8, 1
    derived = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=32)
    return f"scrypt${n}${r}${p}${salt.hex()}${derived.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        scheme, n_s, r_s, p_s, salt_hex, digest_hex = stored_hash.split("$", 5)
        if scheme != "scrypt":
            return False
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=int(n_s),
            r=int(r_s),
            p=int(p_s),
            dklen=len(expected),
        )
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def hash_session_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def normalize_email(email: str) -> str:
    return email.strip().lower()


def load_configured_admin_credentials(
    environ: Mapping[str, str] | None = None,
) -> tuple[str, str] | None:
    """Load optional server-configured Admin email and scrypt password hash.

    Fails closed (returns None) if either variable is missing or malformed.
    """
    source = os.environ if environ is None else environ
    raw_email = (source.get("PAUSEGUARD_ADMIN_EMAIL") or "").strip()
    raw_hash = (source.get("PAUSEGUARD_ADMIN_PASSWORD_HASH") or "").strip()
    if not raw_email or not raw_hash:
        return None
    cleaned_email = normalize_email(raw_email)
    if not _EMAIL_RE.match(cleaned_email):
        return None
    parts = raw_hash.split("$")
    if len(parts) != 6 or parts[0] != "scrypt":
        return None
    return cleaned_email, raw_hash


class AccountAuthService:
    """Authoritative V5 account lifecycle and bearer session service."""

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
                detail="Account authentication persistence backend is unavailable.",
            )

    def signup(
        self,
        *,
        email: str,
        password: str,
        full_name: str,
        role: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        cleaned_email = normalize_email(email)
        if not _EMAIL_RE.match(cleaned_email):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid email address format.")

        normalized_role = role.strip().lower()
        if normalized_role not in _PUBLIC_SIGNUP_ROLES:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Forbidden: Public registration only supports payer or guardian accounts.",
            )

        cleaned_name = " ".join(full_name.strip().split())
        if len(cleaned_name) < 2:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Full name is required.")

        if len(password) < 8:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Password must be at least 8 characters long.",
            )

        configured_admin = load_configured_admin_credentials()
        if (
            self.get_user_by_email(cleaned_email) is not None
            or (configured_admin is not None and cleaned_email == configured_admin[0])
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An account with this email already exists.",
            )

        current_time = now or datetime.now(timezone.utc)
        user_id = uuid4()
        pwd_hash = hash_password(password)
        role_enum = UserRole(normalized_role)

        if self._db is not None:
            from app.models.account import MockAccount
            from app.models.identity import UserAccount
            from app.models.safe_lock import SafeLockState
            from app.models.user import RoleBinding, SyntheticUser

            self._db.add(SyntheticUser(id=user_id, created_at=current_time))
            # Flush parent users row before adding child tables that have FK -> users.id
            # without an ORM relationship (e.g., UserAccount), guaranteeing INSERT order.
            self._db.flush()
            self._db.add(RoleBinding(user_id=user_id, role=role_enum, created_at=current_time))
            account_row = UserAccount(
                id=user_id,
                email=cleaned_email,
                full_name=cleaned_name,
                role=normalized_role,
                password_hash=pwd_hash,
                email_verified=False,
                is_active=True,
                is_synthetic=False,
                email_verified_at=None,
                created_at=current_time,
                updated_at=current_time,
            )
            self._db.add(account_row)
            self._db.add(
                MockAccount(
                    id=uuid4(),
                    owner_id=user_id,
                    balance_paise=_INITIAL_MOCK_BALANCE_PAISE if role_enum == UserRole.PAYER else 0,
                    version=1,
                    created_at=current_time,
                    updated_at=current_time,
                )
            )
            self._db.add(
                SafeLockState(
                    payer_id=user_id,
                    is_locked=False,
                    version=1,
                    created_at=current_time,
                    updated_at=current_time,
                )
            )
            self._db.flush()
        else:
            assert self._mock_store is not None
            with self._mock_store.lock:
                rec = MockUserAccountRecord(
                    id=user_id,
                    email=cleaned_email,
                    full_name=cleaned_name,
                    role=normalized_role,
                    password_hash=pwd_hash,
                    email_verified=False,
                    is_active=True,
                    is_synthetic=False,
                    email_verified_at=None,
                    created_at=current_time,
                    updated_at=current_time,
                )
                self._mock_store.users_by_id[user_id] = rec
                self._mock_store.users_by_email[cleaned_email] = user_id

            # Provision mock-mode runtime account balance & SafeLock state (unengaged)
            from app.services.payment_service import get_payment_service
            get_payment_service().ensure_user_initialized(
                user_id,
                balance_paise=_INITIAL_MOCK_BALANCE_PAISE if role_enum == UserRole.PAYER else 0,
            )

        otp_service = OtpService(
            settings=self._settings,
            db_session=self._db,
            mock_store=self._mock_store,
        )
        otp_dispatch = otp_service.create_challenge(
            contact=cleaned_email,
            purpose="signup_email",
            channel="email",
            now=current_time,
        )

        return {
            "user_id": user_id,
            "email": cleaned_email,
            "full_name": cleaned_name,
            "role": normalized_role,
            "email_verified": False,
            "requires_otp_verification": True,
            "challenge_id": otp_dispatch.challenge_id,
            "otp_expires_at": otp_dispatch.expires_at,
            "is_mock_otp_delivery": otp_dispatch.is_mock_delivery,
            "dev_otp_preview": otp_dispatch.dev_otp_preview,
            "message": "Account created. Complete email OTP verification before logging in.",
        }

    def verify_otp_and_activate_if_signup(
        self,
        *,
        challenge_id: UUID,
        otp_code: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        current_time = now or datetime.now(timezone.utc)
        otp_service = OtpService(
            settings=self._settings,
            db_session=self._db,
            mock_store=self._mock_store,
        )
        result = otp_service.verify_challenge(
            challenge_id=challenge_id,
            otp_code=otp_code,
            now=current_time,
        )

        email_verified = False
        if result.purpose == "signup_email":
            if self._db is not None:
                from app.models.identity import UserAccount

                user_row = self._db.execute(
                    select(UserAccount).where(UserAccount.email == result.contact)
                ).scalar_one_or_none()
                if user_row is not None:
                    user_row.email_verified = True
                    user_row.email_verified_at = current_time
                    user_row.updated_at = current_time
                    self._db.flush()
                    email_verified = True
            else:
                assert self._mock_store is not None
                with self._mock_store.lock:
                    uid = self._mock_store.users_by_email.get(result.contact)
                    if uid and uid in self._mock_store.users_by_id:
                        rec = self._mock_store.users_by_id[uid]
                        rec.email_verified = True
                        rec.email_verified_at = current_time
                        rec.updated_at = current_time
                        email_verified = True

        return {
            "challenge_id": result.challenge_id,
            "contact": result.contact,
            "purpose": result.purpose,
            "verified": True,
            "email_verified": email_verified,
            "verified_at": result.verified_at,
        }

    def _ensure_configured_admin_account(
        self,
        *,
        email: str,
        password_hash: str,
        current_time: datetime,
    ) -> Any:
        admin_id = uuid5(NAMESPACE_DNS, f"pauseguard-admin:{email}")
        if self._db is not None:
            from app.models.identity import UserAccount
            from app.models.user import RoleBinding, SyntheticUser

            existing = self.get_user_by_email(email)
            if existing is not None:
                existing.password_hash = password_hash
                existing.role = UserRole.ADMIN.value
                existing.is_active = True
                existing.email_verified = True
                existing.updated_at = current_time
                self._db.flush()
                return existing

            self._db.add(SyntheticUser(id=admin_id, created_at=current_time))
            self._db.flush()
            self._db.add(RoleBinding(user_id=admin_id, role=UserRole.ADMIN, created_at=current_time))
            account_row = UserAccount(
                id=admin_id,
                email=email,
                full_name="PauseGuard Admin",
                role=UserRole.ADMIN.value,
                password_hash=password_hash,
                email_verified=True,
                is_active=True,
                is_synthetic=False,
                email_verified_at=current_time,
                created_at=current_time,
                updated_at=current_time,
            )
            self._db.add(account_row)
            self._db.flush()
            return account_row

        assert self._mock_store is not None
        with self._mock_store.lock:
            existing_id = self._mock_store.users_by_email.get(email)
            if existing_id is not None and existing_id in self._mock_store.users_by_id:
                rec = self._mock_store.users_by_id[existing_id]
                rec.password_hash = password_hash
                rec.role = UserRole.ADMIN.value
                rec.is_active = True
                rec.email_verified = True
                rec.updated_at = current_time
                return rec

            rec = MockUserAccountRecord(
                id=admin_id,
                email=email,
                full_name="PauseGuard Admin",
                role=UserRole.ADMIN.value,
                password_hash=password_hash,
                email_verified=True,
                is_active=True,
                is_synthetic=False,
                email_verified_at=current_time,
                created_at=current_time,
                updated_at=current_time,
            )
            self._mock_store.users_by_id[admin_id] = rec
            self._mock_store.users_by_email[email] = admin_id
            return rec

    def _create_session_for_user(
        self,
        user: Any,
        *,
        current_time: datetime,
    ) -> dict[str, Any]:
        expires_at = current_time + timedelta(hours=_SESSION_TTL_HOURS)
        raw_token = f"pg_v5_{secrets.token_urlsafe(32)}"
        token_digest = hash_session_token(raw_token)
        session_id = uuid4()

        if self._db is not None:
            from app.models.identity import UserSession

            self._db.add(
                UserSession(
                    id=session_id,
                    user_id=user.id,
                    token_hash=token_digest,
                    auth_method="password_session",
                    expires_at=expires_at,
                    revoked_at=None,
                    created_at=current_time,
                )
            )
            self._db.flush()
        else:
            assert self._mock_store is not None
            with self._mock_store.lock:
                self._mock_store.sessions_by_token_hash[token_digest] = MockUserSessionRecord(
                    id=session_id,
                    user_id=user.id,
                    token_hash=token_digest,
                    auth_method="password_session",
                    expires_at=expires_at,
                    revoked_at=None,
                    created_at=current_time,
                )

        assurance = IdentityAssuranceService(
            settings=self._settings,
            db_session=self._db,
            mock_store=self._mock_store,
        ).get_active_assurance(user.id, now=current_time)

        return {
            "access_token": raw_token,
            "token_type": "bearer",
            "expires_at": expires_at,
            "user_id": user.id,
            "email": user.email,
            "full_name": user.full_name,
            "role": user.role,
            "identity_verified": assurance is not None,
            "is_synthetic": user.is_synthetic,
        }

    def login(
        self,
        *,
        email: str,
        password: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        cleaned_email = normalize_email(email)
        current_time = now or datetime.now(timezone.utc)

        configured_admin = load_configured_admin_credentials()
        if configured_admin is not None and cleaned_email == configured_admin[0]:
            if not verify_password(password, configured_admin[1]):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid email or password.",
                )
            admin_user = self._ensure_configured_admin_account(
                email=configured_admin[0],
                password_hash=configured_admin[1],
                current_time=current_time,
            )
            return self._create_session_for_user(admin_user, current_time=current_time)

        user = self.get_user_by_email(cleaned_email)
        if user is None or not verify_password(password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password.",
            )
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account is deactivated.",
            )
        if not user.email_verified:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Email address is not verified yet. Complete OTP verification before signing in.",
            )

        return self._create_session_for_user(user, current_time=current_time)

    def revoke_session(self, raw_token: str, *, now: datetime | None = None) -> bool:
        current_time = now or datetime.now(timezone.utc)
        digest = hash_session_token(raw_token.strip())
        if self._db is not None:
            from app.models.identity import UserSession

            row = self._db.execute(
                select(UserSession).where(UserSession.token_hash == digest)
            ).scalar_one_or_none()
            if row is not None and row.revoked_at is None:
                row.revoked_at = current_time
                self._db.flush()
                return True
            return False
        assert self._mock_store is not None
        with self._mock_store.lock:
            rec = self._mock_store.sessions_by_token_hash.get(digest)
            if rec is not None and rec.revoked_at is None:
                rec.revoked_at = current_time
                return True
            return False

    def resolve_bearer_token(
        self,
        raw_token: str,
        *,
        now: datetime | None = None,
    ) -> TrustedActorContext | None:
        current_time = now or datetime.now(timezone.utc)
        digest = hash_session_token(raw_token.strip())
        if self._db is not None:
            from app.models.identity import UserAccount, UserSession

            sess = self._db.execute(
                select(UserSession).where(
                    UserSession.token_hash == digest,
                    UserSession.revoked_at.is_(None),
                    UserSession.expires_at > current_time,
                )
            ).scalar_one_or_none()
            if sess is None:
                return None
            account = self._db.execute(
                select(UserAccount).where(
                    UserAccount.id == sess.user_id,
                    UserAccount.is_active.is_(True),
                )
            ).scalar_one_or_none()
            if account is None or not isinstance(account.role, str):
                return None
            return TrustedActorContext(
                user_id=account.id,
                roles=frozenset({UserRole(account.role)}),
            )

        if self._mock_store is None:
            return None
        with self._mock_store.lock:
            sess = self._mock_store.sessions_by_token_hash.get(digest)
            if sess is None or sess.revoked_at is not None or sess.expires_at <= current_time:
                return None
            account = self._mock_store.users_by_id.get(sess.user_id)
            if account is None or not account.is_active:
                return None
            return TrustedActorContext(
                user_id=account.id,
                roles=frozenset({UserRole(account.role)}),
            )

    def get_user_by_email(self, email: str) -> Any:
        cleaned = normalize_email(email)
        if self._db is not None:
            from app.models.identity import UserAccount

            return self._db.execute(
                select(UserAccount).where(UserAccount.email == cleaned)
            ).scalar_one_or_none()
        assert self._mock_store is not None
        with self._mock_store.lock:
            uid = self._mock_store.users_by_email.get(cleaned)
            return self._mock_store.users_by_id.get(uid) if uid else None

    def get_user_by_id(self, user_id: UUID) -> Any:
        if self._db is not None:
            from app.models.identity import UserAccount

            return self._db.execute(
                select(UserAccount).where(UserAccount.id == user_id)
            ).scalar_one_or_none()
        assert self._mock_store is not None
        with self._mock_store.lock:
            return self._mock_store.users_by_id.get(user_id)


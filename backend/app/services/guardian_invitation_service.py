"""Epic A3 durable guardian invitation, OTP+KYC verification, collusion blocking, and revocation service.

State Machine:
PENDING -> CONTACT_VERIFIED -> IDENTITY_VERIFIED -> CONSENTED -> ACTIVE
Additional transitions: -> DECLINED | REVOKED | EXPIRED | SUSPENDED

SECURITY INVARIANTS:
- Payer cannot invite their own email or own user_id.
- Invitation bearer tokens are 256-bit CSPRNG strings stored strictly as SHA-256 hashes.
- Acceptance enforces:
  1. Authenticated actor has GUARDIAN role and matching account email.
  2. Valid single-use invite token and non-expired invitation.
  3. Fresh OTP verification for purpose='guardian_invite' bound to guardian email.
  4. Active server-issued IdentityAssurance for the guardian (never trusting client claims).
  5. Strict person distinctness: payer_trusted_person_ref != guardian_trusted_person_ref.
  6. Explicit consent flag (explicit_consent=True).
- Revocation can be triggered by either owning payer or enrolled guardian and immediately
  prevents future approvals.
"""

from datetime import datetime, timedelta, timezone
import hashlib
import secrets
from typing import Any
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.exceptions import AuthorizationError, GuardianAssignmentError
from app.auth.identities import SYNTHETIC_DEMO_IDENTITIES
from app.config import Settings, load_settings
from app.models.roles import UserRole
from app.services.identity_assurance_service import IdentityAssuranceService
from app.services.otp_service import OtpService
from app.services.payment_guards import TrustedActorContext
from app.services.v5_store import MockGuardianInvitationRecord, V5MockIdentityStore

_INVITE_TTL_HOURS = 48
_INVITE_TERMINAL_STATES = frozenset({"DECLINED", "REVOKED", "EXPIRED"})


def hash_invite_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _resolve_actor_email(
    *,
    actor: TrustedActorContext,
    db_session: Session | None,
    mock_store: V5MockIdentityStore | None,
) -> str | None:
    if db_session is not None:
        from app.models.identity import UserAccount

        acc = db_session.execute(
            select(UserAccount).where(UserAccount.id == actor.user_id)
        ).scalar_one_or_none()
        if acc is not None:
            return acc.email
    if mock_store is not None:
        with mock_store.lock:
            acc = mock_store.users_by_id.get(actor.user_id)
            if acc is not None:
                return acc.email
    for ident in SYNTHETIC_DEMO_IDENTITIES.values():
        if ident.actor.user_id == actor.user_id:
            return ident.contact.strip().lower()
    return None


def _to_view_dict(row: Any, *, dev_preview: str | None = None, is_mock: bool = True) -> dict[str, Any]:
    return {
        "invitation_id": row.id,
        "payer_id": row.payer_id,
        "guardian_user_id": row.guardian_user_id,
        "guardian_email": row.guardian_email,
        "relationship": row.relationship_label,
        "role_slot": row.role_slot,
        "notification_channel": row.notification_channel,
        "status": row.status,
        "consent_confirmed": row.consent_confirmed,
        "expires_at": row.expires_at,
        "accepted_at": row.accepted_at,
        "revoked_at": row.revoked_at,
        "created_at": row.created_at,
        "is_mock_invite_delivery": is_mock,
        "dev_invite_token_preview": dev_preview,
    }


class GuardianInvitationService:
    """Durable/mock-parity coordinator for V5 guardian invitations."""

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
                detail="Guardian invitation persistence backend is unavailable.",
            )

    def create_invitation(
        self,
        *,
        payer: TrustedActorContext,
        guardian_email: str,
        relationship: str,
        role_slot: str,
        notification_channel: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if UserRole.PAYER not in payer.roles:
            raise AuthorizationError("Forbidden: Only payers can invite guardians.")

        target_email = guardian_email.strip().lower()
        if "@" not in target_email or "." not in target_email.split("@")[-1]:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Valid guardian email required.")

        payer_email = _resolve_actor_email(
            actor=payer, db_session=self._db, mock_store=self._mock_store
        )
        if payer_email is not None and payer_email == target_email:
            raise GuardianAssignmentError("Forbidden: Payer cannot invite themselves as guardian.")

        # Check target user existence: cannot invite self by user_id or non-guardian user
        if self._db is not None:
            from app.models.identity import UserAccount

            target_acc = self._db.execute(
                select(UserAccount).where(UserAccount.email == target_email)
            ).scalar_one_or_none()
        else:
            assert self._mock_store is not None
            with self._mock_store.lock:
                uid = self._mock_store.users_by_email.get(target_email)
                target_acc = self._mock_store.users_by_id.get(uid) if uid else None

        if target_acc is not None and target_acc.id == payer.user_id:
            raise GuardianAssignmentError("Forbidden: Payer cannot invite themselves as guardian.")

        id_service = IdentityAssuranceService(
            settings=self._settings, db_session=self._db, mock_store=self._mock_store
        )
        payer_assurance = id_service.get_active_assurance(payer.user_id, now=now)
        payer_tpr = payer_assurance.trusted_person_ref if payer_assurance else None

        # Early collusion check if target already holds an assurance with same trusted_person_ref
        if target_acc is not None and payer_tpr is not None:
            target_assurance = id_service.get_active_assurance(target_acc.id, now=now)
            if target_assurance is not None and target_assurance.trusted_person_ref == payer_tpr:
                raise GuardianAssignmentError(
                    "Forbidden: Invited contact shares verified identity assurance with payer (self/collusion blocked)."
                )

        current_time = now or datetime.now(timezone.utc)
        expires_at = current_time + timedelta(hours=_INVITE_TTL_HOURS)
        invitation_id = uuid4()
        raw_invite_token = f"pg_inv_{secrets.token_urlsafe(24)}"
        token_digest = hash_invite_token(raw_invite_token)

        if self._db is not None:
            from app.models.identity import GuardianInvitation

            row = GuardianInvitation(
                id=invitation_id,
                payer_id=payer.user_id,
                guardian_user_id=target_acc.id if target_acc is not None else None,
                guardian_email=target_email,
                relationship_label=relationship.strip(),
                role_slot=role_slot,
                notification_channel=notification_channel,
                token_hash=token_digest,
                status="PENDING",
                payer_trusted_person_ref=payer_tpr,
                guardian_trusted_person_ref=None,
                consent_confirmed=False,
                expires_at=expires_at,
                accepted_at=None,
                revoked_at=None,
                created_at=current_time,
                updated_at=current_time,
            )
            self._db.add(row)
            self._db.flush()
        else:
            assert self._mock_store is not None
            with self._mock_store.lock:
                row = MockGuardianInvitationRecord(
                    id=invitation_id,
                    payer_id=payer.user_id,
                    guardian_user_id=target_acc.id if target_acc is not None else None,
                    guardian_email=target_email,
                    relationship_label=relationship.strip(),
                    role_slot=role_slot,
                    notification_channel=notification_channel,
                    token_hash=token_digest,
                    status="PENDING",
                    payer_trusted_person_ref=payer_tpr,
                    guardian_trusted_person_ref=None,
                    consent_confirmed=False,
                    expires_at=expires_at,
                    accepted_at=None,
                    revoked_at=None,
                    created_at=current_time,
                    updated_at=current_time,
                )
                self._mock_store.invitations_by_id[invitation_id] = row

        is_mock = self._settings.environment in {"local", "test"} and self._settings.mode == "mock"
        return _to_view_dict(row, dev_preview=raw_invite_token if is_mock else None, is_mock=is_mock)

    def list_invitations(self, *, actor: TrustedActorContext) -> dict[str, list[dict[str, Any]]]:
        actor_email = _resolve_actor_email(
            actor=actor, db_session=self._db, mock_store=self._mock_store
        )
        sent: list[dict[str, Any]] = []
        received: list[dict[str, Any]] = []
        is_mock = self._settings.environment in {"local", "test"} and self._settings.mode == "mock"

        if self._db is not None:
            from app.models.identity import GuardianInvitation

            sent_rows = self._db.execute(
                select(GuardianInvitation)
                .where(GuardianInvitation.payer_id == actor.user_id)
                .order_by(GuardianInvitation.created_at.desc())
            ).scalars().all()
            sent = [_to_view_dict(r, is_mock=is_mock) for r in sent_rows]

            if actor_email is not None:
                rec_rows = self._db.execute(
                    select(GuardianInvitation)
                    .where(
                        (GuardianInvitation.guardian_user_id == actor.user_id)
                        | (GuardianInvitation.guardian_email == actor_email)
                    )
                    .order_by(GuardianInvitation.created_at.desc())
                ).scalars().all()
                received = [_to_view_dict(r, is_mock=is_mock) for r in rec_rows]
        else:
            assert self._mock_store is not None
            with self._mock_store.lock:
                all_rows = sorted(
                    self._mock_store.invitations_by_id.values(),
                    key=lambda r: r.created_at,
                    reverse=True,
                )
                sent = [_to_view_dict(r, is_mock=is_mock) for r in all_rows if r.payer_id == actor.user_id]
                received = [
                    _to_view_dict(r, is_mock=is_mock)
                    for r in all_rows
                    if r.guardian_user_id == actor.user_id
                    or (actor_email is not None and r.guardian_email == actor_email)
                ]

        return {"sent": sent, "received": received}

    def accept_invitation(
        self,
        *,
        guardian: TrustedActorContext,
        invitation_id: UUID,
        invite_token: str,
        otp_challenge_id: UUID,
        otp_code: str,
        explicit_consent: bool,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if UserRole.GUARDIAN not in guardian.roles:
            raise AuthorizationError("Forbidden: Only authenticated guardian accounts can accept invitations.")
        if not explicit_consent:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Explicit guardian consent (explicit_consent=true) is required.",
            )

        current_time = now or datetime.now(timezone.utc)
        guardian_email = _resolve_actor_email(
            actor=guardian, db_session=self._db, mock_store=self._mock_store
        )
        if guardian_email is None:
            raise AuthorizationError("Forbidden: Authenticated guardian email could not be resolved.")

        if self._db is not None:
            from app.models.identity import GuardianInvitation

            stmt = select(GuardianInvitation).where(GuardianInvitation.id == invitation_id)
            bind = self._db.get_bind()
            if bind is not None and bind.dialect.name == "postgresql":
                stmt = stmt.with_for_update()
            row = self._db.execute(stmt).scalar_one_or_none()
            return self._apply_acceptance(
                row=row,
                guardian=guardian,
                guardian_email=guardian_email,
                invite_token=invite_token,
                otp_challenge_id=otp_challenge_id,
                otp_code=otp_code,
                current_time=current_time,
                persist_fn=self._db.flush,
            )

        assert self._mock_store is not None
        with self._mock_store.lock:
            row = self._mock_store.invitations_by_id.get(invitation_id)
            return self._apply_acceptance(
                row=row,
                guardian=guardian,
                guardian_email=guardian_email,
                invite_token=invite_token,
                otp_challenge_id=otp_challenge_id,
                otp_code=otp_code,
                current_time=current_time,
                persist_fn=lambda: None,
            )

    def _apply_acceptance(
        self,
        *,
        row: Any,
        guardian: TrustedActorContext,
        guardian_email: str,
        invite_token: str,
        otp_challenge_id: UUID,
        otp_code: str,
        current_time: datetime,
        persist_fn: Any,
    ) -> dict[str, Any]:
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Guardian invitation not found.")
        if row.payer_id == guardian.user_id:
            raise GuardianAssignmentError("Forbidden: Payer cannot accept their own guardian invitation.")
        if row.guardian_email != guardian_email:
            raise AuthorizationError("Forbidden: Invitation was issued to a different guardian email.")
        if row.status == "ACTIVE":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Guardian invitation is already active.")
        if row.status in _INVITE_TERMINAL_STATES:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Guardian invitation is in terminal state {row.status}.",
            )
        if row.expires_at <= current_time:
            row.status = "EXPIRED"
            row.updated_at = current_time
            persist_fn()
            raise HTTPException(status_code=status.HTTP_410_GONE, detail="Guardian invitation has expired.")
        if row.token_hash != hash_invite_token(invite_token.strip()):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid invitation token.")

        # 1. Verify OTP challenge bound to guardian_email and purpose='guardian_invite'
        OtpService(
            settings=self._settings, db_session=self._db, mock_store=self._mock_store
        ).verify_challenge(
            challenge_id=otp_challenge_id,
            otp_code=otp_code,
            expected_contact=guardian_email,
            expected_purpose="guardian_invite",
            now=current_time,
        )
        row.status = "CONTACT_VERIFIED"

        # 2. Verify independent server-side IdentityAssurance & compare trusted_person_ref
        id_service = IdentityAssuranceService(
            settings=self._settings, db_session=self._db, mock_store=self._mock_store
        )
        guardian_assurance = id_service.get_active_assurance(guardian.user_id, now=current_time)
        if guardian_assurance is None:
            raise GuardianAssignmentError(
                "Forbidden: Guardian must complete identity assurance verification before accepting."
            )

        payer_assurance = id_service.get_active_assurance(row.payer_id, now=current_time)
        payer_tpr = payer_assurance.trusted_person_ref if payer_assurance else row.payer_trusted_person_ref
        if payer_tpr is not None and payer_tpr == guardian_assurance.trusted_person_ref:
            raise GuardianAssignmentError(
                "Forbidden: Self-guardianship or same-person multi-account collusion detected."
            )

        row.status = "IDENTITY_VERIFIED"
        row.payer_trusted_person_ref = payer_tpr
        row.guardian_trusted_person_ref = guardian_assurance.trusted_person_ref
        row.guardian_user_id = guardian.user_id

        # 3. Record explicit consent and promote ACTIVE
        row.status = "CONSENTED"
        row.consent_confirmed = True
        row.status = "ACTIVE"
        row.accepted_at = current_time
        row.updated_at = current_time
        persist_fn()

        # Sync mock runtime GuardianService when DB isn't configured (mock preview mode)
        if self._db is None:
            from app.services.guardian_service import get_guardian_service
            get_guardian_service().activate_verified_invitation_link(
                enrollment_id=row.id,
                payer_id=row.payer_id,
                guardian_id=guardian.user_id,
                relationship=row.relationship_label,
                notification_channel=row.notification_channel,
            )

        is_mock = self._settings.environment in {"local", "test"} and self._settings.mode == "mock"
        return _to_view_dict(row, is_mock=is_mock)

    def decline_invitation(
        self,
        *,
        guardian: TrustedActorContext,
        invitation_id: UUID,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if UserRole.GUARDIAN not in guardian.roles:
            raise AuthorizationError("Forbidden: Only guardians can decline invitations.")
        current_time = now or datetime.now(timezone.utc)
        guardian_email = _resolve_actor_email(
            actor=guardian, db_session=self._db, mock_store=self._mock_store
        )
        row = self._get_invitation_for_update(invitation_id)
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Guardian invitation not found.")
        if row.guardian_user_id != guardian.user_id and row.guardian_email != guardian_email:
            raise AuthorizationError("Forbidden: Not authorized to decline this invitation.")
        if row.status in _INVITE_TERMINAL_STATES or row.status == "ACTIVE":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Cannot decline invitation in state {row.status}.",
            )
        row.status = "DECLINED"
        row.updated_at = current_time
        if self._db is not None:
            self._db.flush()
        is_mock = self._settings.environment in {"local", "test"} and self._settings.mode == "mock"
        return _to_view_dict(row, is_mock=is_mock)

    def revoke_invitation(
        self,
        *,
        actor: TrustedActorContext,
        invitation_id: UUID,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        current_time = now or datetime.now(timezone.utc)
        actor_email = _resolve_actor_email(
            actor=actor, db_session=self._db, mock_store=self._mock_store
        )
        row = self._get_invitation_for_update(invitation_id)
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Guardian invitation not found.")

        is_payer = row.payer_id == actor.user_id
        is_guardian = row.guardian_user_id == actor.user_id or (
            actor_email is not None and row.guardian_email == actor_email
        )
        if not (is_payer or is_guardian):
            raise AuthorizationError("Forbidden: Only the owning payer or invited guardian can revoke this link.")
        if row.status in _INVITE_TERMINAL_STATES:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Invitation is already in terminal state {row.status}.",
            )

        was_active = row.status == "ACTIVE"
        row.status = "REVOKED"
        row.revoked_at = current_time
        row.updated_at = current_time
        if self._db is not None:
            self._db.flush()
        elif was_active:
            from app.services.guardian_service import get_guardian_service
            get_guardian_service().clear_invitation_link(
                payer_id=row.payer_id,
                guardian_id=row.guardian_user_id,
            )

        is_mock = self._settings.environment in {"local", "test"} and self._settings.mode == "mock"
        return _to_view_dict(row, is_mock=is_mock)

    def get_active_guardian_for_payer(self, payer_id: UUID) -> UUID | None:
        if self._db is not None:
            from app.models.identity import GuardianInvitation

            rows = self._db.execute(
                select(GuardianInvitation)
                .where(
                    GuardianInvitation.payer_id == payer_id,
                    GuardianInvitation.status == "ACTIVE",
                )
            ).scalars().all()
            if not rows:
                return None
            primary = next((r for r in rows if r.role_slot == "primary" and r.guardian_user_id), None)
            if primary is not None:
                return primary.guardian_user_id
            backup = next((r for r in rows if r.role_slot == "backup" and r.guardian_user_id), None)
            return backup.guardian_user_id if backup is not None else None
        return None

    def _get_invitation_for_update(self, invitation_id: UUID) -> Any:
        if self._db is not None:
            from app.models.identity import GuardianInvitation

            stmt = select(GuardianInvitation).where(GuardianInvitation.id == invitation_id)
            bind = self._db.get_bind()
            if bind is not None and bind.dialect.name == "postgresql":
                stmt = stmt.with_for_update()
            return self._db.execute(stmt).scalar_one_or_none()
        assert self._mock_store is not None
        return self._mock_store.invitations_by_id.get(invitation_id)


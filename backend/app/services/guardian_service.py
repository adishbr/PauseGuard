"""Authoritative server-side guardian enrollment and lifecycle management.

SECURITY INVARIANTS:
1. Payer-only: Only authenticated payers can enroll or revoke guardians.
2. Self-guardianship rejected: A payer cannot act as their own guardian.
3. Opt-in required: Explicit opt_in_confirmed flag is mandatory (defaults to False).
4. Genuine identity verification: Client-supplied UUID is NEVER accepted as verified
   identity evidence. The server requires trusted server-side identity records
   evaluated via safety.guardian_verification.identity_policy.evaluate_guardian_identity.
5. Invariant preservation: Guardian status/enrollment never executes payments.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
import threading
from typing import Dict, Optional
from uuid import UUID, uuid4

from fastapi import HTTPException, status

from app.auth.exceptions import (
    AuthorizationError,
    GuardianAssignmentError,
)
from app.auth.identities import (
    SYNTHETIC_GUARDIAN_ID,
    SYNTHETIC_PAYER_ID,
)
from app.auth.schemas import (
    GuardianEnrollRequest,
    GuardianEnrollResponse,
    GuardianRevokeResponse,
    GuardianStatusResponse,
)
from app.models.roles import UserRole
from app.services.payment_guards import TrustedActorContext


def _evaluate_identity(
    expected_guardian_id: str,
    verified_guardian_id: Optional[str],
    identity_verified: bool,
    verification_method: str,
):
    """Evaluate guardian identity evidence via safety verification policy."""
    from safety.guardian_verification.identity_policy import evaluate_guardian_identity
    return evaluate_guardian_identity(
        expected_guardian_id=expected_guardian_id,
        verified_guardian_id=verified_guardian_id,
        identity_verified=identity_verified,
        verification_method=verification_method,
    )


@dataclass(frozen=True)
class GuardianIdentityEvidence:
    """Trusted server-managed identity evidence for a registered guardian."""
    guardian_id: UUID
    is_verified: bool
    method: str = "trusted_backend_verification"


@dataclass
class EnrollmentRecord:
    enrollment_id: UUID
    payer_id: UUID
    guardian_id: UUID
    relationship: str
    notification_channel: str
    status: str
    enrolled_at: str
    revoked_at: Optional[str] = None


class GuardianService:
    """Thread-safe authoritative guardian enrollment and identity verification repository."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._enrollments: Dict[UUID, EnrollmentRecord] = {}
        self._verified_identities: Dict[UUID, GuardianIdentityEvidence] = {}
        self._seed_default_state()

    def _seed_default_state(self) -> None:
        """Seed default canonical synthetic identities and enrollment for offline tests and local demo."""
        now_str = datetime.now(timezone.utc).isoformat()
        
        # Canonical server-verified synthetic guardian
        self._verified_identities[SYNTHETIC_GUARDIAN_ID] = GuardianIdentityEvidence(
            guardian_id=SYNTHETIC_GUARDIAN_ID,
            is_verified=True,
            method="trusted_backend_verification",
        )

        # Default pre-enrolled synthetic relationship
        self._enrollments[SYNTHETIC_PAYER_ID] = EnrollmentRecord(
            enrollment_id=uuid4(),
            payer_id=SYNTHETIC_PAYER_ID,
            guardian_id=SYNTHETIC_GUARDIAN_ID,
            relationship="family",
            notification_channel="in_app",
            status="active",
            enrolled_at=now_str,
        )

    def reset_for_testing(self) -> None:
        """Reset repository to default seeded state for isolated test execution."""
        with self._lock:
            self._enrollments.clear()
            self._verified_identities.clear()
            self._seed_default_state()

    def register_verified_guardian(self, evidence: GuardianIdentityEvidence) -> None:
        """Register trusted server-side identity evidence for a guardian (e.g. for testing)."""
        with self._lock:
            self._verified_identities[evidence.guardian_id] = evidence

    def get_guardian_for_payer(self, payer_id: UUID) -> Optional[UUID]:
        """Return the authoritative active guardian ID for a payer, or None."""
        if not isinstance(payer_id, UUID):
            return None
        with self._lock:
            rec = self._enrollments.get(payer_id)
            if rec and rec.status == "active":
                return rec.guardian_id
        return None

    def enroll_guardian(
        self,
        actor: TrustedActorContext,
        request: GuardianEnrollRequest,
    ) -> GuardianEnrollResponse:
        """Enroll a guardian for the authenticated payer.

        Fails closed on self-enrollment, non-payer callers, missing opt-in,
        or unverified guardian identity evidence.
        """
        if not isinstance(actor, TrustedActorContext) or UserRole.PAYER not in actor.roles:
            raise AuthorizationError("Only authenticated payers can enroll a guardian")

        if actor.user_id == request.guardian_id:
            raise GuardianAssignmentError("Payer cannot enroll themselves as guardian")

        if not request.opt_in_confirmed:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Explicit guardian opt-in confirmation is required",
            )

        with self._lock:
            # Retrieve trusted server-side identity evidence; NEVER trust client claims
            evidence = self._verified_identities.get(request.guardian_id)

            eval_result = _evaluate_identity(
                expected_guardian_id=str(request.guardian_id),
                verified_guardian_id=str(evidence.guardian_id) if evidence else None,
                identity_verified=evidence.is_verified if evidence else False,
                verification_method=evidence.method if evidence else "unverified",
            )
            if not eval_result.verified:
                raise GuardianAssignmentError(
                    f"Guardian identity verification failed: {eval_result.reason}"
                )

            now_str = datetime.now(timezone.utc).isoformat()
            enrollment_id = uuid4()
            record = EnrollmentRecord(
                enrollment_id=enrollment_id,
                payer_id=actor.user_id,
                guardian_id=request.guardian_id,
                relationship=request.relationship,
                notification_channel=request.notification_channel,
                status="active",
                enrolled_at=now_str,
            )
            self._enrollments[actor.user_id] = record

        return GuardianEnrollResponse(
            enrollment_id=str(enrollment_id),
            payer_id=actor.user_id,
            guardian_id=request.guardian_id,
            relationship=request.relationship,
            notification_channel=request.notification_channel,
            status="active",
            enrolled_at=now_str,
        )

    def revoke_guardian(
        self,
        actor: TrustedActorContext,
        guardian_id: Optional[UUID] = None,
    ) -> GuardianRevokeResponse:
        """Revoke active guardian enrollment for the authenticated payer.

        Fails closed if the payer has no active guardian or mismatched ID.
        """
        if not isinstance(actor, TrustedActorContext) or UserRole.PAYER not in actor.roles:
            raise AuthorizationError("Only authenticated payers can revoke a guardian")

        with self._lock:
            rec = self._enrollments.get(actor.user_id)
            if rec is None or rec.status != "active":
                raise GuardianAssignmentError("No active guardian enrollment found for payer")

            if guardian_id is not None and rec.guardian_id != guardian_id:
                raise GuardianAssignmentError("Supplied guardian does not match enrolled guardian")

            now_str = datetime.now(timezone.utc).isoformat()
            revoked_enrollment_id = str(rec.enrollment_id)
            revoked_guardian_id = rec.guardian_id
            rec.status = "revoked"
            rec.revoked_at = now_str
            del self._enrollments[actor.user_id]

        return GuardianRevokeResponse(
            enrollment_id=revoked_enrollment_id,
            payer_id=actor.user_id,
            guardian_id=revoked_guardian_id,
            status="revoked",
            revoked_at=now_str,
        )

    def get_status(self, actor: TrustedActorContext) -> GuardianStatusResponse:
        """Return guardian enrollment summary for the authenticated actor."""
        if not isinstance(actor, TrustedActorContext):
            raise AuthorizationError("Valid server actor context required")

        with self._lock:
            if UserRole.PAYER in actor.roles:
                rec = self._enrollments.get(actor.user_id)
                if rec and rec.status == "active":
                    enrollment_resp = GuardianEnrollResponse(
                        enrollment_id=str(rec.enrollment_id),
                        payer_id=rec.payer_id,
                        guardian_id=rec.guardian_id,
                        relationship=rec.relationship,
                        notification_channel=rec.notification_channel,
                        status="active",
                        enrolled_at=rec.enrolled_at,
                    )
                    return GuardianStatusResponse(
                        has_guardian=True,
                        enrollment=enrollment_resp,
                        guarded_payers=[],
                    )
                return GuardianStatusResponse(
                    has_guardian=False,
                    enrollment=None,
                    guarded_payers=[],
                )

            if UserRole.GUARDIAN in actor.roles:
                guarded_payers = [
                    r.payer_id for r in self._enrollments.values()
                    if r.guardian_id == actor.user_id and r.status == "active"
                ]
                return GuardianStatusResponse(
                    has_guardian=bool(guarded_payers),
                    enrollment=None,
                    guarded_payers=guarded_payers,
                )

        return GuardianStatusResponse(
            has_guardian=False,
            enrollment=None,
            guarded_payers=[],
        )


_default_guardian_service: Optional[GuardianService] = None


def get_guardian_service() -> GuardianService:
    """Retrieve or initialize the global GuardianService singleton."""
    global _default_guardian_service
    if _default_guardian_service is None:
        _default_guardian_service = GuardianService()
    return _default_guardian_service

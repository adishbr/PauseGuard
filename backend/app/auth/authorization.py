"""Server-side authorization and permission verification functions.

Enforces server-managed access control, resource ownership boundaries,
privacy-preserving view levels, and the fundamental invariant that guardian
approval never executes a payment automatically.
"""

from uuid import UUID

from app.auth.exceptions import (
    AuthorizationError,
    CrossAccountAccessError,
    GuardianAssignmentError,
)
from app.auth.identities import get_authoritative_guardian_for_payer
from app.models.roles import UserRole
from app.services.payment_guards import TrustedActorContext


def authorize_resource_owner(actor: TrustedActorContext, owner_id: UUID) -> None:
    """Verify that the authenticated actor owns the requested resource.

    Raises CrossAccountAccessError (HTTP 403) if the actor's user_id does not
    match the resource owner_id.
    """
    if not isinstance(actor, TrustedActorContext) or not isinstance(owner_id, UUID):
        raise AuthorizationError("Valid server actor and owner context required")
    if actor.user_id != owner_id:
        raise CrossAccountAccessError(
            f"Forbidden: Actor {actor.user_id} cannot access resource owned by {owner_id}"
        )


def authorize_account_access(actor: TrustedActorContext, account_owner_id: UUID) -> None:
    """Verify that the authenticated actor is permitted to access the specified account.

    Raises CrossAccountAccessError (HTTP 403) if the account belongs to another user.
    """
    if not isinstance(actor, TrustedActorContext) or not isinstance(account_owner_id, UUID):
        raise AuthorizationError("Valid server actor and account context required")
    if actor.user_id != account_owner_id:
        raise CrossAccountAccessError(
            f"Forbidden: Actor {actor.user_id} cannot access account owned by {account_owner_id}"
        )


def verify_guardian_to_payer_relationship(
    actor: TrustedActorContext,
    *,
    assigned_guardian_id: UUID | None = None,
    payer_id: UUID,
) -> None:
    """Verify that the actor is the specifically assigned guardian for this transaction.

    SECURITY INVARIANTS:
    1. Guardian enrollment is authoritative server-side data, not client claims.
    2. Actor must hold the UserRole.GUARDIAN role.
    3. Actor cannot be the payer (self-guardianship is strictly rejected).
    4. If the payer has no enrolled guardian on record, request fails closed.
    5. If client provides assigned_guardian_id, it MUST match authoritative enrollment.
    6. Actor user_id must match the enrolled guardian ID.
    """
    if not isinstance(actor, TrustedActorContext) or not isinstance(payer_id, UUID):
        raise AuthorizationError("Valid server actor and payer context required")

    if UserRole.GUARDIAN not in actor.roles:
        raise AuthorizationError("Forbidden: Actor does not hold the guardian role")

    if actor.user_id == payer_id:
        raise GuardianAssignmentError("Forbidden: Payer cannot act as guardian for their own transaction")

    authoritative_guardian = get_authoritative_guardian_for_payer(payer_id)
    if authoritative_guardian is None:
        raise GuardianAssignmentError("Forbidden: Payer has no enrolled guardian on record")

    from app.services.guardian_service import get_guardian_service
    if not get_guardian_service().is_guardian_verified(authoritative_guardian):
        raise GuardianAssignmentError(
            "Forbidden: Assigned guardian lacks authoritative server-verified identity"
        )

    if assigned_guardian_id is not None:
        if not isinstance(assigned_guardian_id, UUID):
            raise AuthorizationError("Invalid assigned_guardian_id format")
        if assigned_guardian_id != authoritative_guardian:
            raise GuardianAssignmentError(
                "Forbidden: Supplied guardian does not match authoritative server enrollment"
            )

    if actor.user_id != authoritative_guardian:
        raise GuardianAssignmentError(
            "Forbidden: Actor is not the assigned guardian for this transaction"
        )


def assert_guardian_cannot_execute(
    target_state: str | None = None,
    actor: TrustedActorContext | None = None,
) -> None:
    """Enforce the absolute invariant: Guardian approval never executes payments.

    Payment execution (EXECUTED) requires direct, authenticated payer confirmation
    with atomic ledger debit. A guardian decision can at most transition a payment
    to READY_TO_EXECUTE or REJECTED.
    """
    if target_state is not None and target_state.upper() == "EXECUTED":
        raise AuthorizationError(
            "Invariant violation: Guardian approval cannot transition payment to EXECUTED"
        )
    if actor is not None and UserRole.GUARDIAN in actor.roles and UserRole.PAYER not in actor.roles:
        raise AuthorizationError("Invariant violation: Guardian role cannot execute payments")


def authorize_payment_view_level(
    actor: TrustedActorContext,
    *,
    payer_id: UUID,
    assigned_guardian_id: UUID | None = None,
) -> str:
    """Determine the permitted view level for a payment.

    Returns:
    - "full": Payer viewing their own transaction.
    - "redacted": Enrolled, assigned guardian viewing the transaction.

    Raises:
    - AuthorizationError (HTTP 403) if actor is unauthorized to view the transaction.
    """
    if not isinstance(actor, TrustedActorContext) or not isinstance(payer_id, UUID):
        raise AuthorizationError("Valid server actor context required")

    # Owning payer viewing own payment
    if actor.user_id == payer_id and UserRole.PAYER in actor.roles:
        return "full"

    # Assigned guardian viewing payment
    authoritative_guardian = get_authoritative_guardian_for_payer(payer_id)
    if authoritative_guardian is not None:
        if assigned_guardian_id is not None and assigned_guardian_id != authoritative_guardian:
            raise AuthorizationError(
                "Forbidden: Supplied guardian does not match authoritative server enrollment"
            )
        if actor.user_id == authoritative_guardian and UserRole.GUARDIAN in actor.roles:
            return "redacted"

    raise AuthorizationError("Forbidden: Actor is not authorized to view this payment")

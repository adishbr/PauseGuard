"""FastAPI router for authentication and profile endpoints.

Provides the canonical GET /profile endpoint returning the server-resolved
profile of the authenticated actor.
"""

from typing import Annotated
from fastapi import APIRouter, Depends

from app.auth.dependencies import get_current_actor
from app.auth.schemas import ActorProfileResponse
from app.services.payment_guards import TrustedActorContext

router = APIRouter(prefix="/api/v2", tags=["auth"])


@router.get("/profile", response_model=ActorProfileResponse)
def get_actor_profile(
    actor: Annotated[TrustedActorContext, Depends(get_current_actor)],
) -> ActorProfileResponse:
    """Return the authenticated actor's server-resolved profile.

    Roles and permissions are retrieved strictly from the server's trusted
    identity context, never from client-supplied claims or headers.
    """
    return ActorProfileResponse(
        user_id=actor.user_id,
        roles=sorted(list(actor.roles), key=lambda r: r.value),
        notification_preference_paise=None,
    )


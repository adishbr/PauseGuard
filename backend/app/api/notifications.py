"""FastAPI router for durable V5 notification outbox inspection."""

from typing import Annotated
from fastapi import APIRouter, Depends, Request

from app.auth.dependencies import get_current_actor
from app.auth.v5_schemas import NotificationOutboxListResponse
from app.config import load_settings
from app.services.notification_service import NotificationOutboxService
from app.services.payment_guards import TrustedActorContext
from app.services.v5_store import get_or_create_v5_mock_store

router = APIRouter(prefix="/api/v2/notifications", tags=["notifications"])


@router.get("/outbox", response_model=NotificationOutboxListResponse)
def list_notification_outbox(
    http_request: Request,
    actor: Annotated[TrustedActorContext, Depends(get_current_actor)],
    limit: int = 50,
) -> NotificationOutboxListResponse:
    """List durable notifications addressed exclusively to the authenticated actor."""
    settings = getattr(http_request.app.state, "settings", None) or load_settings()
    session_factory = getattr(http_request.app.state, "session_factory", None)
    if session_factory is not None:
        session = session_factory()
        try:
            return NotificationOutboxService(
                settings=settings,
                db_session=session,
                mock_store=None,
            ).list_outbox_for_actor(actor, limit=limit)
        finally:
            session.close()
    mock_store = get_or_create_v5_mock_store(http_request.app.state)
    return NotificationOutboxService(
        settings=settings,
        db_session=None,
        mock_store=mock_store,
    ).list_outbox_for_actor(actor, limit=limit)

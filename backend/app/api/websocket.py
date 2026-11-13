"""WebSocket endpoint and single-use ticket issuer for PauseGuard V2/V5.

Endpoints:
- POST /api/v2/ws/ticket: Issue short-lived single-use opaque ticket for WebSocket auth.
- WebSocket /api/v2/ws: Authenticated stream accepting ?ticket=... (or demo ?token= in mock mode).
"""

from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
import secrets
from typing import Annotated, Optional
from fastapi import APIRouter, Depends, Query, Request, WebSocket, WebSocketDisconnect, status

from app.auth.dependencies import get_current_actor
from app.auth.identities import is_demo_mode_allowed, resolve_synthetic_token
from app.auth.v5_schemas import WebSocketTicketResponse
from app.models.roles import UserRole
from app.services.events import get_connection_manager
from app.services.payment_guards import TrustedActorContext
from app.services.v5_store import (
    MockWebSocketTicketRecord,
    get_or_create_v5_mock_store,
)

router = APIRouter(prefix="/api/v2", tags=["websocket"])
logger = logging.getLogger("pauseguard.websocket")

WS_TICKET_TTL_SECONDS = 30


def _hash_ws_ticket(raw_ticket: str) -> str:
    return hashlib.sha256(raw_ticket.encode("utf-8")).hexdigest()


@router.post("/ws/ticket", response_model=WebSocketTicketResponse)
def issue_websocket_ticket(
    http_request: Request,
    actor: Annotated[TrustedActorContext, Depends(get_current_actor)],
) -> WebSocketTicketResponse:
    """Issue a short-lived single-use opaque ticket for authenticated WebSocket connection."""
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=WS_TICKET_TTL_SECONDS)
    raw_ticket = f"pg_ws_{secrets.token_urlsafe(24)}"
    ticket_hash = _hash_ws_ticket(raw_ticket)

    store = get_or_create_v5_mock_store(http_request.app.state)
    with store.lock:
        # Opportunistically prune expired tickets
        expired_keys = [
            key for key, rec in store.ws_tickets_by_hash.items()
            if rec.expires_at <= now
        ]
        for key in expired_keys:
            del store.ws_tickets_by_hash[key]

        store.ws_tickets_by_hash[ticket_hash] = MockWebSocketTicketRecord(
            ticket_hash=ticket_hash,
            user_id=actor.user_id,
            roles=tuple(r.value for r in actor.roles),
            expires_at=expires_at,
            consumed_at=None,
            created_at=now,
        )

    return WebSocketTicketResponse(
        ticket=raw_ticket,
        expires_in_seconds=WS_TICKET_TTL_SECONDS,
        expires_at=expires_at,
        single_use=True,
    )


def _consume_ws_ticket(websocket: WebSocket, raw_ticket: str) -> TrustedActorContext | None:
    cleaned = raw_ticket.strip()
    if not cleaned:
        return None
    now = datetime.now(timezone.utc)
    ticket_hash = _hash_ws_ticket(cleaned)
    store = get_or_create_v5_mock_store(websocket.app.state)
    with store.lock:
        record = store.ws_tickets_by_hash.get(ticket_hash)
        if record is None:
            return None
        if record.consumed_at is not None:
            return None
        if record.expires_at <= now:
            return None
        record.consumed_at = now
        return TrustedActorContext(
            user_id=record.user_id,
            roles=frozenset(UserRole(r) for r in record.roles),
        )


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    ticket: Optional[str] = Query(None),
    token: Optional[str] = Query(None),
) -> None:
    """Stream real-time payment status and guardian alerts.

    SECURITY INVARIANTS:
    1. Authenticated connections only: Single-use ticket or server-verified demo token.
    2. Plaintext V5 session tokens (pg_v5_*) are strictly rejected in WS URL query strings.
    3. Role-based message filtering: Payers receive full details; guardians receive redacted alerts.
    4. Graceful disconnect and leak prevention.
    """
    settings = getattr(websocket.app.state, "settings", None)
    actor: TrustedActorContext | None = None

    if ticket is not None:
        actor = _consume_ws_ticket(websocket, ticket)
        if actor is None:
            await websocket.close(
                code=status.WS_1008_POLICY_VIOLATION,
                reason="Invalid, expired, or already-used WebSocket ticket",
            )
            return
    elif token is not None:
        cleaned_token = token.strip()
        if cleaned_token.startswith("pg_v5_"):
            await websocket.close(
                code=status.WS_1008_POLICY_VIOLATION,
                reason="Plaintext session tokens are not allowed in WebSocket URL; use /api/v2/ws/ticket",
            )
            return
        if is_demo_mode_allowed(settings):
            actor = resolve_synthetic_token(cleaned_token, settings=settings)
        if actor is None:
            await websocket.close(
                code=status.WS_1008_POLICY_VIOLATION,
                reason="Invalid or expired authentication token",
            )
            return
    else:
        await websocket.close(
            code=status.WS_1008_POLICY_VIOLATION,
            reason="WebSocket authentication ticket or token is required",
        )
        return

    manager = get_connection_manager()
    await websocket.accept()
    manager.connect(actor.user_id, websocket)

    try:
        await websocket.send_text(
            json.dumps({
                "type": "CONNECTION_ESTABLISHED",
                "user_id": str(actor.user_id),
                "roles": [r.value for r in actor.roles],
            })
        )

        while True:
            text = await websocket.receive_text()
            try:
                data = json.loads(text)
                if data.get("type") == "PING":
                    await websocket.send_text(json.dumps({"type": "PONG"}))
            except Exception:
                pass
    except WebSocketDisconnect:
        logger.info(f"WebSocket client disconnected for user {actor.user_id}")
    finally:
        manager.disconnect(actor.user_id, websocket)

"""WebSocket endpoint for real-time payment status and guardian notification streaming.

Endpoint:
- WebSocket /ws: Authenticated stream providing instant payment transition updates.
"""

import json
import logging
from typing import Optional
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status

from app.auth.identities import resolve_synthetic_token
from app.services.events import get_connection_manager

router = APIRouter(prefix="/api/v2", tags=["websocket"])
logger = logging.getLogger("pauseguard.websocket")


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    token: Optional[str] = Query(None),
) -> None:
    """Stream real-time payment status and guardian alerts.

    SECURITY INVARIANTS:
    1. Authenticated connections only: Token must resolve to a server-verified actor.
    2. Role-based message filtering: Payers receive full details; guardians receive redacted alerts.
    3. Graceful disconnect and leak prevention.
    """
    if not token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Authentication token is required")
        return

    settings = getattr(websocket.app.state, "settings", None)
    actor = resolve_synthetic_token(token.strip(), settings=settings)
    if actor is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Invalid or expired authentication token")
        return

    manager = get_connection_manager()
    await websocket.accept()
    manager.connect(actor.user_id, websocket)

    try:
        # Send initial confirmation message
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


"""Real-time event broadcasting and WebSocket connection management for PauseGuard V2.

SECURITY INVARIANTS:
1. Authenticated connections only: Callers must authenticate via server-verified token.
2. Privacy redaction: Payer receives full payment event details; assigned guardian
   receives sanitized/redacted notifications without sensitive amounts or beneficiary details.
3. No false execution notifications: Notifications are emitted only after state transitions
   commit to durable persistence or mock state; events never imply executed payments prematurely.
"""

from datetime import datetime, timezone
import json
import logging
import threading
from typing import Any, Dict, List, Optional, Set
from uuid import UUID

from fastapi import WebSocket

logger = logging.getLogger("pauseguard.events")


class ConnectionManager:
    """Thread-safe WebSocket connection manager indexed by authenticated user_id."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._user_connections: Dict[UUID, Set[WebSocket]] = {}
        self._loop: Optional[Any] = None

    def set_loop(self, loop: Any) -> None:
        self._loop = loop

    def get_loop(self) -> Optional[Any]:
        if self._loop is not None and self._loop.is_running():
            return self._loop
        import asyncio
        try:
            loop = asyncio.get_running_loop()
            if loop.is_running():
                self._loop = loop
                return loop
        except RuntimeError:
            pass
        return self._loop

    def connect(self, user_id: UUID, websocket: WebSocket) -> None:
        with self._lock:
            if user_id not in self._user_connections:
                self._user_connections[user_id] = set()
            self._user_connections[user_id].add(websocket)
        import asyncio
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            pass

    def has_active_connections(self) -> bool:
        """Check whether any WebSocket clients are currently connected."""
        with self._lock:
            return bool(self._user_connections)

    def disconnect(self, user_id: UUID, websocket: WebSocket) -> None:
        with self._lock:
            if user_id in self._user_connections:
                self._user_connections[user_id].discard(websocket)
                if not self._user_connections[user_id]:
                    del self._user_connections[user_id]

    async def send_personal_message(self, user_id: UUID, message: dict) -> None:
        with self._lock:
            sockets = list(self._user_connections.get(user_id, []))

        text_msg = json.dumps(message)
        for ws in sockets:
            try:
                await ws.send_text(text_msg)
            except Exception as e:
                logger.warning(f"Error sending WebSocket message to user {user_id}: {e}")
                self.disconnect(user_id, ws)

    async def broadcast_payment_transition(
        self,
        *,
        payment_id: str,
        event_type: str,
        status: str,
        payer_id: UUID,
        assigned_guardian_id: Optional[UUID] = None,
        tier: int = 0,
        amount_paise: Optional[int] = None,
        guardian_deadline: Optional[str] = None,
        extra: Optional[dict] = None,
    ) -> None:
        """Broadcast payment lifecycle event with role-based privacy redaction."""
        now_str = datetime.now(timezone.utc).isoformat()

        # 1. Full view for owning payer
        payer_payload: Dict[str, Any] = {
            "event_type": event_type,
            "payment_id": payment_id,
            "status": status,
            "tier": tier,
            "amount_paise": amount_paise,
            "guardian_deadline": guardian_deadline,
            "timestamp": now_str,
        }
        if extra:
            payer_payload["extra"] = extra

        await self.send_personal_message(payer_id, payer_payload)

        # 2. Redacted view for assigned guardian
        if assigned_guardian_id is not None:
            guardian_payload: Dict[str, Any] = {
                "event_type": event_type,
                "payment_id": payment_id,
                "status": status,
                "tier": tier,
                "guardian_deadline": guardian_deadline,
                "timestamp": now_str,
                "message": "PauseGuard security review required: Please review this transaction.",
                "redacted": True,
            }
            await self.send_personal_message(assigned_guardian_id, guardian_payload)


_global_connection_manager = ConnectionManager()


def get_connection_manager() -> ConnectionManager:
    """Retrieve global ConnectionManager singleton."""
    return _global_connection_manager


def broadcast_event_sync(
    *,
    payment_id: str,
    event_type: str,
    status: str,
    payer_id: UUID,
    assigned_guardian_id: Optional[UUID] = None,
    tier: int = 0,
    amount_paise: Optional[int] = None,
    guardian_deadline: Optional[str] = None,
    extra: Optional[dict] = None,
) -> None:
    """Safely schedule event broadcast from synchronous execution context."""
    import asyncio
    manager = get_connection_manager()

    if not manager.has_active_connections():
        return

    # Check if current thread has a running loop
    try:
        current_loop = asyncio.get_running_loop()
        if current_loop.is_running():
            current_loop.create_task(
                manager.broadcast_payment_transition(
                    payment_id=payment_id,
                    event_type=event_type,
                    status=status,
                    payer_id=payer_id,
                    assigned_guardian_id=assigned_guardian_id,
                    tier=tier,
                    amount_paise=amount_paise,
                    guardian_deadline=guardian_deadline,
                    extra=extra,
                )
            )
            return
    except RuntimeError:
        pass

    loop = manager.get_loop()
    if loop is not None and loop.is_running():
        try:
            asyncio.run_coroutine_threadsafe(
                manager.broadcast_payment_transition(
                    payment_id=payment_id,
                    event_type=event_type,
                    status=status,
                    payer_id=payer_id,
                    assigned_guardian_id=assigned_guardian_id,
                    tier=tier,
                    amount_paise=amount_paise,
                    guardian_deadline=guardian_deadline,
                    extra=extra,
                ),
                loop,
            )
        except Exception as e:
            logger.warning(f"Failed to dispatch broadcast to running event loop: {e}")




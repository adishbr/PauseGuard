
"""In-memory Razorpay webhook replay protection.

Development/test utility only. Production deployments require
durable, shared, atomic event-ID storage.
"""

from collections import OrderedDict
from threading import RLock


class WebhookReplayGuard:
    """Thread-safe bounded registry of previously processed event IDs."""

    def __init__(self, max_events: int = 10_000) -> None:
        if (
            isinstance(max_events, bool)
            or not isinstance(max_events, int)
            or max_events < 1
        ):
            raise ValueError("max_events must be a positive integer")

        self._max_events = max_events
        self._processed: OrderedDict[str, None] = OrderedDict()
        self._lock = RLock()

    def record_if_new(self, event_id: str) -> bool:
        """Return True once per retained event ID; False for duplicates."""
        if (
            not isinstance(event_id, str)
            or not event_id
            or event_id != event_id.strip()
        ):
            return False

        with self._lock:
            if event_id in self._processed:
                return False

            self._processed[event_id] = None

            if len(self._processed) > self._max_events:
                self._processed.popitem(last=False)

            return True

    def contains(self, event_id: str) -> bool:
        """Check whether an event ID is currently retained."""
        if not isinstance(event_id, str):
            return False

        with self._lock:
            return event_id in self._processed

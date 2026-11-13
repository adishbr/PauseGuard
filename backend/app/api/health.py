"""Process health and lightweight thread-safe observability metrics."""

import threading
import time
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from app.auth.dependencies import get_current_actor
from app.models.roles import UserRole
from app.services.payment_guards import TrustedActorContext

router = APIRouter()


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    mode: Literal["mock"] = "mock"


class _MetricsStore:
    """Bounded in-memory observability tracker for local/mock latency and counters."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._started_at = time.monotonic()
        self._request_counts: dict[str, int] = {}
        self._status_counts: dict[str, int] = {}
        self._latencies_ms: list[float] = []

    def record(self, method: str, path: str, status_code: int, latency_ms: float) -> None:
        with self._lock:
            key = f"{method} {path}"
            self._request_counts[key] = self._request_counts.get(key, 0) + 1
            sc = str(status_code)
            self._status_counts[sc] = self._status_counts.get(sc, 0) + 1
            self._latencies_ms.append(round(latency_ms, 3))
            if len(self._latencies_ms) > 1000:
                self._latencies_ms = self._latencies_ms[-1000:]

    def snapshot(self, app_state: object) -> dict[str, Any]:
        with self._lock:
            samples = sorted(self._latencies_ms)
            total = len(samples)
            p50 = samples[int(0.50 * (total - 1))] if total else 0.0
            p95 = samples[int(0.95 * (total - 1))] if total else 0.0
            request_counts = dict(self._request_counts)
            status_counts = dict(self._status_counts)
            uptime_seconds = round(time.monotonic() - self._started_at, 2)

        v5_store = getattr(app_state, "v5_identity_store", None)
        v5_counters = {
            "registered_users": len(v5_store.users_by_id) if v5_store else 0,
            "guardian_invitations": len(v5_store.invitations_by_id) if v5_store else 0,
            "notification_outbox_items": len(v5_store.notification_outbox) if v5_store else 0,
            "bank_intents": len(v5_store.bank_intents_by_id) if v5_store else 0,
            "active_ws_tickets": len(v5_store.ws_tickets_by_hash) if v5_store else 0,
        }
        return {
            "status": "ok",
            "uptime_seconds": uptime_seconds,
            "http_requests_sampled": total,
            "latency_ms": {"p50": p50, "p95": p95},
            "status_counts": status_counts,
            "route_counts": request_counts,
            "v5_store_counters": v5_counters,
        }


_metrics = _MetricsStore()


def record_http_metric(method: str, path: str, status_code: int, latency_ms: float) -> None:
    _metrics.record(method, path, status_code, latency_ms)


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse()


@router.get("/metrics")
def get_observability_metrics(
    http_request: Request,
    actor: Annotated[TrustedActorContext, Depends(get_current_actor)],
) -> dict[str, Any]:
    """Expose operational latency and V5 telemetry metrics strictly to Analyst/Admin roles."""
    if UserRole.ANALYST not in actor.roles and UserRole.ADMIN not in actor.roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Operational metrics require Analyst or Admin role",
        )
    return _metrics.snapshot(http_request.app.state)

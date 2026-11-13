"""Run locally with: python -m uvicorn app.main:app --host 127.0.0.1"""

from uuid import uuid4
from fastapi import FastAPI, Request

from app.api.account import router as account_router
from app.api.guardian import router as guardian_router
from app.api.health import router as health_router
from app.api.notifications import router as notifications_router
from app.api.payments import router as payments_router
from app.api.policy_lab import router as policy_lab_router
from app.api.razorpay import router as razorpay_router
from app.api.risk import router as risk_router
from app.api.safety import (
    anchors_router,
    audit_router,
    recovery_router,
    safe_lock_router,
    safety_router,
)
from app.api.v5_auth import auth_v5_router, identity_router
from app.api.websocket import router as websocket_router
from app.auth.router import router as auth_router
from app.config import Settings, load_settings
from app.models.database import SessionFactory


def create_app(
    settings: Settings | None = None,
    *,
    session_factory: SessionFactory | None = None,
) -> FastAPI:
    """Build an isolated PauseGuard V2 app."""
    config = load_settings() if settings is None else settings
    application = FastAPI(
        title="PauseGuard V2 API",
        version="2.0.0",
        description="Durable mock-rail UPI APP-fraud intervention and advisory platform",
        debug=False,
    )
    application.state.settings = config
    application.state.session_factory = session_factory

    @application.middleware("http")
    async def correlation_id_middleware(request: Request, call_next):
        correlation_id = request.headers.get("X-Correlation-ID") or f"corr_{uuid4().hex[:16]}"
        response = await call_next(request)
        response.headers["X-Correlation-ID"] = correlation_id
        return response

    # Mount routers
    application.include_router(health_router, prefix="/api/v2")
    application.include_router(auth_router)
    application.include_router(auth_v5_router)
    application.include_router(identity_router)
    application.include_router(guardian_router)
    application.include_router(notifications_router)
    application.include_router(payments_router)
    application.include_router(account_router)
    application.include_router(safe_lock_router)
    application.include_router(safety_router)
    application.include_router(audit_router)
    application.include_router(anchors_router)
    application.include_router(recovery_router)
    application.include_router(risk_router)
    application.include_router(policy_lab_router)
    application.include_router(razorpay_router)
    application.include_router(websocket_router)

    return application


app = create_app()


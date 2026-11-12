"""Run locally with: python -m uvicorn app.main:app --host 127.0.0.1"""

from fastapi import FastAPI

from app.api.guardian import router as guardian_router
from app.api.health import router as health_router
from app.api.payments import router as payments_router
from app.auth.router import router as auth_router
from app.config import Settings, load_settings
from app.models.database import SessionFactory


def create_app(
    settings: Settings | None = None,
    *,
    session_factory: SessionFactory | None = None,
) -> FastAPI:
    """Build an isolated mock app; no database is created or contacted."""
    config = load_settings() if settings is None else settings
    application = FastAPI(title="PauseGuard", version="2.0.0", debug=False)
    application.state.settings = config
    application.state.session_factory = session_factory
    application.include_router(health_router, prefix="/api/v2")
    application.include_router(auth_router)
    application.include_router(guardian_router)
    application.include_router(payments_router)
    return application


app = create_app()

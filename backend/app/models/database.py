"""Lazy SQLAlchemy factories; no environment access, connection or schema DDL."""

import logging
from collections.abc import Callable, Iterator

from fastapi import HTTPException, Request, status
from pydantic import SecretStr
from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    """Empty registry reserved for a separately authorized persistence phase."""


class DatabaseConfigurationError(ValueError):
    """Safe database factory error that does not disclose connection settings."""


SessionFactory = Callable[[], Session]
logger = logging.getLogger(__name__)


class DatabaseSessionCleanupError(RuntimeError):
    """Cleanup failed without an existing request failure to preserve."""


def _cleanup_session(session: Session, *, rollback: bool) -> bool:
    """Attempt every cleanup step; never log driver errors or their context."""
    succeeded = True
    if rollback:
        try:
            session.rollback()
        except Exception:
            succeeded = False
            logger.warning("Database session rollback failed.", exc_info=False)
    try:
        session.close()
    except Exception:
        succeeded = False
        logger.warning("Database session close failed.", exc_info=False)
    return succeeded


def create_database_engine(database_url: SecretStr) -> Engine:
    """Construct an engine without connecting; require an explicit secret value.

    SQLAlchemy's default PostgreSQL driver varies by version, so this factory
    selects the installed synchronous psycopg2 driver explicitly. No caller in
    application startup invokes this function.
    """
    if not isinstance(database_url, SecretStr):
        raise DatabaseConfigurationError("Database configuration must be a secret value.")
    try:
        url = make_url(database_url.get_secret_value())
        if url.drivername not in {"postgresql", "postgresql+psycopg2"}:
            raise ValueError("Unsupported database driver.")
        if not url.host or not url.database:
            raise ValueError("Missing database target.")
        return create_engine(
            url.set(drivername="postgresql+psycopg2"),
            echo=False,
            hide_parameters=True,
            pool_pre_ping=True,
        )
    except Exception:
        raise DatabaseConfigurationError("Invalid or unavailable database configuration.") from None


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Binding a session factory performs no database I/O."""
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db(request: Request) -> Iterator[Session]:
    """Provide one session per request; the future service owns commit boundaries.

    No database is configured by default. Closing an unused/uncommitted real
    SQLAlchemy session releases resources and rolls back pending transactions.
    """
    factory: SessionFactory | None = request.app.state.session_factory
    if factory is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database access is not configured.",
        )
    try:
        session = factory()
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database session is unavailable.",
        ) from None
    try:
        yield session
    except BaseException:
        _cleanup_session(session, rollback=True)
        raise
    else:
        if not _cleanup_session(session, rollback=False):
            raise DatabaseSessionCleanupError("Database session cleanup failed.") from None

"""Canonical user roles for PauseGuard V2.

Pure StrEnum definition decoupled from SQLAlchemy ORM models, allowing
application routers, authorization guards, and auth dependencies to inspect
roles without eagerly loading database tables onto Base.metadata.
"""

from enum import StrEnum


class UserRole(StrEnum):
    PAYER = "payer"
    GUARDIAN = "guardian"
    ANALYST = "analyst"
    ADMIN = "admin"


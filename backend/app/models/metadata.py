"""Explicit offline model registration, separate from application startup."""

from app.models.account import MockAccount
from app.models.database import Base
from app.models.safe_lock import SafeLockState
from app.models.user import RoleBinding, SyntheticUser, UserRole

metadata = Base.metadata

__all__ = ["MockAccount", "RoleBinding", "SafeLockState", "SyntheticUser", "UserRole", "metadata"]

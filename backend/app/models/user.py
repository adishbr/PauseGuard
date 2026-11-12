"""Synthetic identities and server-managed grants; no authentication behavior."""

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum, ForeignKey, PrimaryKeyConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.database import Base

if TYPE_CHECKING:
    from app.models.account import MockAccount
    from app.models.safe_lock import SafeLockState


class UserRole(StrEnum):
    PAYER = "payer"
    GUARDIAN = "guardian"
    ANALYST = "analyst"
    ADMIN = "admin"


class SyntheticUser(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    role_bindings: Mapped[list["RoleBinding"]] = relationship(
        back_populates="user", passive_deletes="all", lazy="raise"
    )
    accounts: Mapped[list["MockAccount"]] = relationship(
        back_populates="owner", passive_deletes="all", lazy="raise"
    )
    safe_lock_state: Mapped["SafeLockState | None"] = relationship(
        back_populates="payer", passive_deletes="all", lazy="raise"
    )


class RoleBinding(Base):
    """A persisted grant, never proof that a caller is authenticated.

    Only a future authorized server workflow may write grants. No client input
    is interpreted here; the four V2 roles do not imply additional privileges.
    """

    __tablename__ = "role_bindings"
    __table_args__ = (PrimaryKeyConstraint("user_id", "role", name="pk_role_bindings"),)

    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", name="fk_role_bindings_user", ondelete="RESTRICT"),
        nullable=False,
    )
    role: Mapped[UserRole] = mapped_column(
        Enum(
            UserRole, values_callable=lambda roles: [role.value for role in roles],
            native_enum=False, create_constraint=True, validate_strings=True,
            name="ck_role_bindings_role",
        ),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    user: Mapped[SyntheticUser] = relationship(back_populates="role_bindings", lazy="raise")

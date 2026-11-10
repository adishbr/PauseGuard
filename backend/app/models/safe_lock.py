"""Binary Safe-Lock storage; no amount, category or execution exceptions."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.database import Base
from app.models.user import SyntheticUser


class SafeLockState(Base):
    __tablename__ = "safe_lock_states"
    __table_args__ = (
        CheckConstraint("version > 0", name="ck_safe_lock_states_positive_version"),
    )

    payer_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", name="fk_safe_lock_states_payer", ondelete="RESTRICT"),
        primary_key=True,
    )
    is_locked: Mapped[bool] = mapped_column(Boolean, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    payer: Mapped[SyntheticUser] = relationship(back_populates="safe_lock_state", lazy="raise")

    __mapper_args__ = {"version_id_col": version}

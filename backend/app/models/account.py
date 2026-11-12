"""Mock balances only; this mapping does not fund accounts or execute transfers."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, Integer, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.database import Base
from app.models.user import SyntheticUser


class MockAccount(Base):
    __tablename__ = "accounts"
    __table_args__ = (
        CheckConstraint("balance_paise >= 0", name="ck_accounts_nonnegative_balance"),
        CheckConstraint("version > 0", name="ck_accounts_positive_version"),
        Index("ix_accounts_owner_id", "owner_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", name="fk_accounts_owner", ondelete="RESTRICT"),
        nullable=False,
    )
    balance_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    owner: Mapped[SyntheticUser] = relationship(back_populates="accounts", lazy="raise")

    __mapper_args__ = {"version_id_col": version}

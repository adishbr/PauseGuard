"""Database-backed idempotency record ORM model."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    DateTime,
    Index,
    Integer,
    String,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.models.database import Base


class IdempotencyRecord(Base):
    """Persistent idempotency lock and cached response payload."""

    __tablename__ = "idempotency_records"
    __table_args__ = (
        Index("ix_idempotency_records_caller_endpoint", "caller_id", "endpoint"),
    )

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    caller_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    endpoint: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response_status: Mapped[int] = mapped_column(Integer, nullable=False)
    response_body: Mapped[dict] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


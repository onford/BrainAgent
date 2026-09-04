from datetime import datetime
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base, TimestampMixin


class UserToolIntegrationModel(TimestampMixin, Base):
    __tablename__ = "user_tool_integrations"
    __table_args__ = (
        UniqueConstraint("owner_id", "tool_id", name="uq_owner_tool_integration"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    owner_id: Mapped[str] = mapped_column(String(191), index=True, nullable=False)
    tool_id: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    credentials_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), default="unvalidated", nullable=False
    )
    last_validated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_validation_error: Mapped[str | None] = mapped_column(Text, nullable=True)

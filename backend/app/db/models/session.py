from uuid import uuid4

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.models.base import Base, TimestampMixin


class SessionModel(TimestampMixin, Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    messages: Mapped[list["MessageModel"]] = relationship(  # type: ignore[name-defined]
        back_populates="session",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="MessageModel.created_at",
    )
    agent_runs: Mapped[list["AgentRunModel"]] = relationship(  # type: ignore[name-defined]
        back_populates="session",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

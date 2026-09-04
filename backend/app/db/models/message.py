from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.models.base import Base, utcnow


class MessageModel(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    session_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    session: Mapped["SessionModel"] = relationship(back_populates="messages")  # type: ignore[name-defined]
    execution_events: Mapped[list["ExecutionEventModel"]] = relationship(  # type: ignore[name-defined]
        back_populates="assistant_message",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="ExecutionEventModel.sequence",
    )

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin, new_id


class ChatSession(TimestampMixin, Base):
    """问一问的一次会话。可以关联一道作业题或错题，模式决定 AI 能讲到什么程度。"""

    __tablename__ = "chat_session"
    __table_args__ = (Index("ix_chat_session_student", "tenant_id", "student_id", "updated_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.id"), index=True)
    student_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user_account.id", ondelete="CASCADE"))
    mode: Mapped[str] = mapped_column(String(12))  # learn / homework / correction
    subject: Mapped[str] = mapped_column(String(20), default="")
    title: Mapped[str] = mapped_column(String(100), default="新的提问")
    # 关联的题：{"type": "assignment_item" | "wrong_item", "id", "assignment_id", "question": {...}}
    context: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ChatMessage(TimestampMixin, Base):
    __tablename__ = "chat_message"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.id"), index=True)
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("chat_session.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(10))  # user / assistant
    content: Mapped[str] = mapped_column(Text, default="")
    images: Mapped[list[str]] = mapped_column(JSONB, default=list)
    style: Mapped[str | None] = mapped_column(String(12))  # 讲解方式：simpler / example / mnemonic
    # 安全标记：crisis 危机 / chat 闲聊拉回 / unsafe 不当内容 / leak 作业模式改写过
    flag: Mapped[str | None] = mapped_column(String(10))

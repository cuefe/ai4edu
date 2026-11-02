import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin, new_id


class AlertStatus(StrEnum):
    OPEN = "open"  # 待处理
    HANDLED = "handled"  # 已处理


class ModerationLog(TimestampMixin, Base):
    """内容安全记录：被拦下的闲聊、不当内容和危机信号。运营后台的"内容安全审核记录"从这里查。"""

    __tablename__ = "moderation_log"
    __table_args__ = (Index("ix_moderation_tenant_time", "tenant_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.id"), index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("user_account.id", ondelete="SET NULL"))
    source: Mapped[str] = mapped_column(String(20))  # tutor_input / tutor_output
    category: Mapped[str] = mapped_column(String(10))  # study / chat / unsafe
    crisis: Mapped[str] = mapped_column(String(10))  # none / low / high
    reason: Mapped[str] = mapped_column(String(200), default="")
    excerpt: Mapped[str] = mapped_column(Text, default="")


class CrisisAlert(TimestampMixin, Base):
    """危机预警工单。老师必须确认处理并填写记录；超过配置的时长没处理，在机构管理员那里标为超时。"""

    __tablename__ = "crisis_alert"
    __table_args__ = (Index("ix_crisis_alert_status", "tenant_id", "status", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.id"), index=True)
    student_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user_account.id", ondelete="CASCADE"))
    session_id: Mapped[uuid.UUID | None] = mapped_column()  # 问一问会话，老师查看上下文用
    level: Mapped[str] = mapped_column(String(10))  # low / high
    excerpt: Mapped[str] = mapped_column(Text)  # 学生的原话
    reason: Mapped[str] = mapped_column(String(200), default="")
    status: Mapped[str] = mapped_column(String(10), default=AlertStatus.OPEN)
    handled_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("user_account.id", ondelete="SET NULL"))
    handled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    note: Mapped[str] = mapped_column(Text, default="")  # 处理记录
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

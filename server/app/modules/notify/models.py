import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin, new_id


class Notification(TimestampMixin, Base):
    """站内信：作业布置、催交、危机预警等。P1 再加微信服务通知。"""

    __tablename__ = "notification"
    __table_args__ = (Index("ix_notification_user", "tenant_id", "user_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.id"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user_account.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(20))  # assignment / remind / crisis
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text, default="")
    link: Mapped[str | None] = mapped_column(String(300))  # 前端路由，点击跳转
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

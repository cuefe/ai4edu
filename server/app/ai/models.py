import uuid
from decimal import Decimal

from sqlalchemy import Boolean, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin, new_id


class AiUsage(TimestampMixin, Base):
    """每次模型调用一条，包括失败后切换备用模型的那次。"""

    __tablename__ = "ai_usage"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tenant.id"), index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("user_account.id"))
    skill: Mapped[str] = mapped_column(String(40), index=True)
    provider: Mapped[str] = mapped_column(String(20))
    model: Mapped[str] = mapped_column(String(80))
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_yuan: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))  # 没配置价格时为空
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    error: Mapped[str | None] = mapped_column(Text)

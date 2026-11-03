import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin, new_id


class Plan(TimestampMixin, Base):
    """套餐模板。开通、续费机构时选一个，名额和额度带到机构上（之后改套餐不影响已开通的机构）。"""

    __tablename__ = "plan"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(50), unique=True)
    student_quota: Mapped[int | None] = mapped_column(Integer)  # 为空表示不限
    teacher_quota: Mapped[int | None] = mapped_column(Integer)
    ai_budget_yuan: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))  # 每月
    months: Mapped[int] = mapped_column(Integer, default=12)  # 服务期，开通时据此算到期日
    note: Mapped[str] = mapped_column(Text, default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)  # 停售的套餐不出现在开通选项里


class AuditLog(TimestampMixin, Base):
    """敏感操作审计：登录、创建机构、导入学生、重置密码、改分、导出、删除等。"""

    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_log_time", "created_at"),)  # 运营后台按时间倒序翻看

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tenant.id"), index=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("user_account.id"))
    action: Mapped[str] = mapped_column(String(50))
    target_type: Mapped[str | None] = mapped_column(String(30))
    target_id: Mapped[str | None] = mapped_column(String(64))
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

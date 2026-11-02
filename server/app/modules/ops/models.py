import uuid
from typing import Any

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin, new_id


class AuditLog(TimestampMixin, Base):
    """敏感操作审计：创建机构、导入学生、重置密码等。"""

    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tenant.id"), index=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("user_account.id"))
    action: Mapped[str] = mapped_column(String(50))
    target_type: Mapped[str | None] = mapped_column(String(30))
    target_id: Mapped[str | None] = mapped_column(String(64))
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

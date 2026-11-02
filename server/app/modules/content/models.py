import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin, new_id


class DocType(StrEnum):
    LESSON_PLAN = "lesson_plan"


class DocStatus(StrEnum):
    GENERATING = "generating"
    READY = "ready"
    FAILED = "failed"


class Document(TimestampMixin, Base):
    """教案、讲义等可编辑文档。正文存 TipTap（ProseMirror）JSON，编辑器和 Word 导出共用。"""

    __tablename__ = "document"
    __table_args__ = (Index("ix_document_owner", "tenant_id", "owner_id", "updated_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.id"), index=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user_account.id", ondelete="CASCADE"))
    doc_type: Mapped[str] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(String(200))
    subject: Mapped[str | None] = mapped_column(String(20))
    grade: Mapped[str | None] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(12), default=DocStatus.READY)
    # 生成参数（含 prompt 版本），"重新生成"时回填表单
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    content: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # 模型的原始输出。生成中是已收到的部分；生成完保留下来，用来和老师改后的版本对比、做评测
    generated_md: Mapped[str | None] = mapped_column(Text)
    warnings: Mapped[list[str]] = mapped_column(JSONB, default=list)
    error: Mapped[str | None] = mapped_column(String(500))
    version: Mapped[int] = mapped_column(Integer, default=1)  # 每次保存加一，防止多个窗口互相覆盖
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

import uuid
from datetime import datetime
from enum import StrEnum

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.ai.gateway.gateway import EMBED_DIM
from app.core.db import Base, TimestampMixin, new_id


class ResourceStatus(StrEnum):
    PENDING = "pending"
    PARSING = "parsing"
    READY = "ready"
    FAILED = "failed"


class Resource(TimestampMixin, Base):
    """老师上传的资料文件（教案、课件、试卷等）。原文件在存储里，解析出的片段在 resource_chunk。"""

    __tablename__ = "resource_file"
    __table_args__ = (Index("ix_resource_owner", "tenant_id", "owner_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.id"), index=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user_account.id", ondelete="CASCADE"))
    filename: Mapped[str] = mapped_column(String(255))
    size: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    storage_key: Mapped[str] = mapped_column(String(255))
    subject: Mapped[str | None] = mapped_column(String(20))
    shared: Mapped[bool] = mapped_column(Boolean, default=False)  # 共享给本机构的老师
    status: Mapped[str] = mapped_column(String(12), default=ResourceStatus.PENDING)
    progress: Mapped[int] = mapped_column(Integer, default=0)  # 0～100
    error: Mapped[str | None] = mapped_column(String(500))
    pages: Mapped[int] = mapped_column(Integer, default=0)
    ocr_pages: Mapped[int] = mapped_column(Integer, default=0)  # 其中靠 OCR 识别的页 / 图片数
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    embedding_model: Mapped[str | None] = mapped_column(String(80))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ResourceChunk(TimestampMixin, Base):
    """资料片段：检索的最小单位。

    向量没有建 HNSW 索引：按机构和老师过滤后数据量不大，精确计算更准；资料量上来后再加索引。
    """

    __tablename__ = "resource_chunk"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.id"), index=True)
    resource_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("resource_file.id", ondelete="CASCADE"), index=True
    )
    seq: Mapped[int] = mapped_column(Integer)
    heading: Mapped[str] = mapped_column(String(500), default="")
    page_start: Mapped[int | None] = mapped_column(Integer)
    page_end: Mapped[int | None] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBED_DIM))
    embedding_model: Mapped[str] = mapped_column(String(80))

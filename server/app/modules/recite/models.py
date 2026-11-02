import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin, new_id


class ReciteDeck(TimestampMixin, Base):
    """一组背诵卡片，对应一节课或一个单元的必背内容。M2 布置背诵任务时按卡片组布置。"""

    __tablename__ = "recite_deck"
    __table_args__ = (Index("ix_recite_deck_owner", "tenant_id", "owner_id", "updated_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.id"), index=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user_account.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(200))
    subject: Mapped[str | None] = mapped_column(String(20))
    grade: Mapped[str | None] = mapped_column(String(20))
    # 从哪份讲义或教案抽取的；文档删了卡片组照样保留
    source_doc_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("document.id", ondelete="SET NULL"))
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)  # 生成参数（含 prompt 版本）
    # AI 生成的原始卡片，用来和老师改后的版本对比、做评测
    generated: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    card_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ReciteCard(TimestampMixin, Base):
    """背诵卡片。M2 的间隔重复（FSRS）按卡片记录复习状态。"""

    __tablename__ = "recite_card"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.id"), index=True)
    deck_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("recite_deck.id", ondelete="CASCADE"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(10))  # qa 问答 / cloze 挖空
    front: Mapped[str] = mapped_column(Text)
    back: Mapped[str] = mapped_column(Text, default="")

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin, new_id


class WrongStatus(StrEnum):
    PENDING = "pending"  # 待订正
    CORRECTED = "corrected"  # 已订正。P1 加相似题，做对才算"已消除"


class WrongItem(TimestampMixin, Base):
    """错题：作业里判错（含老师改为错）的题自动收进来。题目存快照，作业删了错题还在。"""

    __tablename__ = "wrong_item"
    __table_args__ = (
        UniqueConstraint("student_id", "item_id"),
        Index("ix_wrong_item_student", "tenant_id", "student_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.id"), index=True)
    student_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user_account.id", ondelete="CASCADE"))
    item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("assignment_item.id", ondelete="SET NULL"))
    assignment_title: Mapped[str] = mapped_column(String(200), default="")
    subject: Mapped[str] = mapped_column(String(20))
    # {qtype, stem, options, answer, analysis, knowledge_points, difficulty}
    question: Mapped[dict[str, Any]] = mapped_column(JSONB)
    wrong_response: Mapped[str] = mapped_column(Text, default="")  # 当时的作答
    status: Mapped[str] = mapped_column(String(12), default=WrongStatus.PENDING)
    wrong_count: Mapped[int] = mapped_column(Integer, default=1)  # 做错几次（含订正时重做做错）
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))  # 作业答案公布后才进错题本
    corrected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    guide: Mapped[dict[str, Any] | None] = mapped_column(JSONB)  # 四步订正引导，生成一次后缓存
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ReviewState(TimestampMixin, Base):
    """背诵卡片的复习状态（FSRS）。

    按“学生 + 作业里的背诵项 + 第几张卡”记录：作业里存的是卡片快照，编号不会变。
    """

    __tablename__ = "review_state"
    __table_args__ = (
        UniqueConstraint("student_id", "item_id", "card_key"),
        Index("ix_review_due", "tenant_id", "student_id", "due"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.id"), index=True)
    student_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user_account.id", ondelete="CASCADE"))
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assignment_item.id", ondelete="CASCADE"))
    card_key: Mapped[int] = mapped_column(Integer)
    card: Mapped[dict[str, Any]] = mapped_column(JSONB)  # fsrs.Card.to_dict()
    due: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reps: Mapped[int] = mapped_column(Integer, default=0)
    lapses: Mapped[int] = mapped_column(Integer, default=0)  # 忘记的次数
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ReviewLog(TimestampMixin, Base):
    __tablename__ = "review_log"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.id"), index=True)
    state_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("review_state.id", ondelete="CASCADE"), index=True)
    rating: Mapped[int] = mapped_column(Integer)  # 1 忘了 / 2 模糊 / 3 记得 / 4 很熟
    duration_ms: Mapped[int | None] = mapped_column(Integer)

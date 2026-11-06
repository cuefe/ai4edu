import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin, new_id


class ClassProgress(TimestampMixin, Base):
    """一个班一门课的教学进度：老师设置这周教哪几节。设置了才会发周测，停用后不再发。"""

    __tablename__ = "class_progress"
    __table_args__ = (UniqueConstraint("klass_id", "subject"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.id"), index=True)
    klass_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("klass.id", ondelete="CASCADE"), index=True)
    subject: Mapped[str] = mapped_column(String(20))
    book_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("textbook.id", ondelete="CASCADE"))
    # 设置进度的老师：周测的批改确认归这位老师
    teacher_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user_account.id", ondelete="CASCADE"))
    section_ids: Mapped[list[str]] = mapped_column(JSONB, default=list)  # 这周教的节
    week_start: Mapped[date] = mapped_column(Date)  # 进度是哪一周设置的（周一）
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class WeeklyPaper(TimestampMixin, Base):
    """学生一门课一周一份周测。题目和作答都在对应的 assignment 里，这里记组卷时的决定。"""

    __tablename__ = "weekly_paper"
    __table_args__ = (
        UniqueConstraint("student_id", "subject", "week_start"),
        Index("ix_weekly_paper_class", "tenant_id", "klass_id", "subject", "week_start"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.id"), index=True)
    student_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user_account.id", ondelete="CASCADE"))
    klass_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("klass.id", ondelete="SET NULL"))
    subject: Mapped[str] = mapped_column(String(20))
    book_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("textbook.id", ondelete="CASCADE"))
    week_start: Mapped[date] = mapped_column(Date)  # 这一周的周一
    assignment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assignment.id", ondelete="CASCADE"), index=True
    )
    level: Mapped[int] = mapped_column(Integer)  # 难度档：1 基础 / 2 标准 / 3 提高
    prev_ratio: Mapped[float | None] = mapped_column(Float)  # 上一份的得分比例，没有或没提交时为空
    reason: Mapped[str] = mapped_column(Text, default="")  # 这一档是怎么定的，给学生和老师看
    plan: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)  # 组卷结果：各来源的题数、缺几道题

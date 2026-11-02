import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    Boolean,
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


class ItemType(StrEnum):
    QUESTION = "question"  # 练习题
    DOCUMENT = "document"  # 阅读讲义
    RECITE = "recite"  # 背诵卡片


class AnswerRelease(StrEnum):
    SUBMIT = "submit"  # 学生提交后马上能看答案和解析
    DUE = "due"  # 截止后才公布


class SubmissionStatus(StrEnum):
    TODO = "todo"  # 未提交
    SUBMITTED = "submitted"  # 已提交，还有题在批改
    GRADED = "graded"  # 全部批改完


class AnswerStatus(StrEnum):
    DRAFT = "draft"  # 作答中
    AUTO = "auto"  # 客观题，提交时自动判分
    GRADING = "grading"  # AI 批改中
    AI_DONE = "ai_done"  # AI 已给分，等老师确认
    CONFIRMED = "confirmed"  # 老师确认（或改分）


class Assignment(TimestampMixin, Base):
    """一份作业或学习任务：可以包含练习题、讲义阅读、背诵卡片。布置时给每个学生建一条 submission。"""

    __tablename__ = "assignment"
    __table_args__ = (Index("ix_assignment_owner", "tenant_id", "owner_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.id"), index=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user_account.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(200))
    subject: Mapped[str] = mapped_column(String(20))
    note: Mapped[str] = mapped_column(Text, default="")  # 给学生的要求
    class_ids: Mapped[list[str]] = mapped_column(JSONB, default=list)  # 布置给的班级（展示、统计用）
    publish_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    answer_release: Mapped[str] = mapped_column(String(10), default=AnswerRelease.SUBMIT)
    allow_ai: Mapped[bool] = mapped_column(Boolean, default=True)  # 作业期间能不能问 AI（只给提示）
    total_score: Mapped[float] = mapped_column(Float, default=0)
    student_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AssignmentItem(TimestampMixin, Base):
    """作业里的一项。content 是布置时的快照：之后题库、讲义再改，已布置的作业不变。

    - question：{qtype, stem, options, answer, analysis, knowledge_points, difficulty}
    - document：{title, markdown}
    - recite：{title, cards: [{kind, front, back}]}
    """

    __tablename__ = "assignment_item"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.id"), index=True)
    assignment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assignment.id", ondelete="CASCADE"), index=True
    )
    seq: Mapped[int] = mapped_column(Integer)
    item_type: Mapped[str] = mapped_column(String(12))
    ref_id: Mapped[uuid.UUID | None] = mapped_column()  # 来源（题目、讲义、卡片组）的 ID，只做追溯
    score: Mapped[float] = mapped_column(Float, default=0)  # 题目分值；阅读、背诵为 0
    content: Mapped[dict[str, Any]] = mapped_column(JSONB)


class Submission(TimestampMixin, Base):
    __tablename__ = "submission"
    __table_args__ = (
        UniqueConstraint("assignment_id", "student_id"),
        Index("ix_submission_student", "tenant_id", "student_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.id"), index=True)
    assignment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assignment.id", ondelete="CASCADE"), index=True
    )
    student_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user_account.id", ondelete="CASCADE"))
    klass_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("klass.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(12), default=SubmissionStatus.TODO)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    score: Mapped[float | None] = mapped_column(Float)  # 已出分的题的得分合计
    pending_count: Mapped[int] = mapped_column(Integer, default=0)  # 还在批改、等老师确认的题数
    # 阅读、背诵类任务的完成情况：{item_id: true}
    progress: Mapped[dict[str, bool]] = mapped_column(JSONB, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Answer(TimestampMixin, Base):
    """学生对一道题的作答。客观题提交时自动判分；主观题（和判断不了的填空）AI 批改后由老师确认。"""

    __tablename__ = "answer"
    __table_args__ = (UniqueConstraint("submission_id", "item_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.id"), index=True)
    submission_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("submission.id", ondelete="CASCADE"), index=True
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assignment_item.id", ondelete="CASCADE"), index=True
    )
    student_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user_account.id", ondelete="CASCADE"))
    response: Mapped[str] = mapped_column(Text, default="")  # 填空题多个空用“；”隔开
    images: Mapped[list[str]] = mapped_column(JSONB, default=list)  # 拍照作答的存储键
    status: Mapped[str] = mapped_column(String(12), default=AnswerStatus.DRAFT)
    correct: Mapped[bool | None] = mapped_column(Boolean)  # 得满分为对
    score: Mapped[float | None] = mapped_column(Float)  # 最终得分
    ai_score: Mapped[float | None] = mapped_column(Float)
    ai_confidence: Mapped[float | None] = mapped_column(Float)  # 0～1，老师确认页按它从低到高排
    ai_comment: Mapped[str] = mapped_column(Text, default="")
    ai_points: Mapped[list[str]] = mapped_column(JSONB, default=list)  # 扣分点
    teacher_comment: Mapped[str] = mapped_column(Text, default="")
    graded_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("user_account.id", ondelete="SET NULL"))
    graded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

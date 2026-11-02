import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin, new_id


class BatchStatus(StrEnum):
    GENERATING = "generating"  # 正在出题
    CHECKING = "checking"  # 题目出好了，正在校验
    DONE = "done"
    FAILED = "failed"


class QuestionStatus(StrEnum):
    CHECKING = "checking"  # 校验中
    CHECKED = "checked"  # 校验一致，待审核
    DISPUTED = "disputed"  # 校验不一致，待审核（老师重点看）
    UNCHECKED = "unchecked"  # 没能自动校验，待审核
    APPROVED = "approved"  # 审核通过，已入库
    REJECTED = "rejected"  # 驳回


PENDING_REVIEW = (
    QuestionStatus.CHECKING,
    QuestionStatus.CHECKED,
    QuestionStatus.DISPUTED,
    QuestionStatus.UNCHECKED,
)


class QuestionBatch(TimestampMixin, Base):
    """一次 AI 出题：出题和校验在后台任务里跑，前端轮询进度。"""

    __tablename__ = "question_batch"
    __table_args__ = (Index("ix_question_batch_owner", "tenant_id", "owner_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.id"), index=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user_account.id", ondelete="CASCADE"))
    topic: Mapped[str] = mapped_column(String(200))
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)  # 出题参数（含 prompt 版本）
    status: Mapped[str] = mapped_column(String(12), default=BatchStatus.GENERATING)
    progress: Mapped[int] = mapped_column(Integer, default=0)  # 0～100
    error: Mapped[str | None] = mapped_column(String(500))
    warnings: Mapped[list[str]] = mapped_column(JSONB, default=list)
    # 参考了资料库的哪些片段：[{"label", "resource_id", "chunk_id"}]
    sources: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Question(TimestampMixin, Base):
    """题目。AI 出的题经过校验、老师审核通过后入库；老师手动录入的题直接入库。

    入库的题本机构老师都能看到和选用，只有出题的老师能修改、删除；待审核和驳回的题只有自己能看到。
    知识点暂时存文字标签，知识点树（curriculum 模块）做好后改成关联表。
    """

    __tablename__ = "question"
    __table_args__ = (
        Index("ix_question_bank", "tenant_id", "status", "subject"),
        Index("ix_question_owner", "tenant_id", "owner_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.id"), index=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user_account.id", ondelete="CASCADE"))
    batch_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("question_batch.id", ondelete="SET NULL"), index=True
    )
    seq: Mapped[int] = mapped_column(Integer, default=0)  # 在这批题里的顺序
    subject: Mapped[str] = mapped_column(String(20))
    grade: Mapped[str | None] = mapped_column(String(20))
    qtype: Mapped[str] = mapped_column(String(10))
    difficulty: Mapped[str] = mapped_column(String(10))
    stem: Mapped[str] = mapped_column(Text)
    options: Mapped[list[str]] = mapped_column(JSONB, default=list)
    answer: Mapped[str] = mapped_column(Text)
    analysis: Mapped[str] = mapped_column(Text, default="")
    knowledge_points: Mapped[list[str]] = mapped_column(JSONB, default=list)
    source: Mapped[str] = mapped_column(String(10))  # ai / manual
    status: Mapped[str] = mapped_column(String(12))
    # AI 出的原题和老师是否改过：统计审核通过率、改进 prompt 用
    generated: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    edited: Mapped[bool] = mapped_column(Boolean, default=False)
    warnings: Mapped[list[str]] = mapped_column(JSONB, default=list)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("user_account.id", ondelete="SET NULL"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class QuestionCheck(TimestampMixin, Base):
    """一次答案校验的记录。重新校验会新增一条，界面上显示最新的。"""

    __tablename__ = "question_check"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.id"), index=True)
    question_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("question.id", ondelete="CASCADE"), index=True)
    verdict: Mapped[str] = mapped_column(String(12))  # agree / disagree / unsure / error
    method: Mapped[str] = mapped_column(String(10))  # rule / numeric / judge
    solver_model: Mapped[str | None] = mapped_column(String(80))
    solver_answer: Mapped[str | None] = mapped_column(Text)
    solver_work: Mapped[str] = mapped_column(Text, default="")  # 独立求解的过程，分歧时给老师看
    reason: Mapped[str] = mapped_column(Text, default="")

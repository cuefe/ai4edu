"""教材、章节、知识点、课件。平台维护的公共内容：不带 tenant_id，所有机构只读，没有行级安全。

内容经“内容包”离线生成后用命令行导入（见 curriculum/pack.py、devtools/content_gen.py）。
"""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
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


class BookStatus(StrEnum):
    DRAFT = "draft"  # 只有平台运营能看到，用来抽检
    PUBLISHED = "published"


class Textbook(TimestampMixin, Base):
    """一册教材。初中按上下册，高中按必修、选择性必修分册。"""

    __tablename__ = "textbook"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    key: Mapped[str] = mapped_column(String(60), unique=True)  # 内容包里的稳定标识，如 rj-math-9a
    stage: Mapped[str] = mapped_column(String(10))  # 初中 / 高中
    subject: Mapped[str] = mapped_column(String(20))
    edition: Mapped[str] = mapped_column(String(40))  # 如：人教版（2024 起新版）
    grade: Mapped[str] = mapped_column(String(10))  # 初一～高三，和班级的年级对应
    title: Mapped[str] = mapped_column(String(60))  # 如：九年级上册、必修第一册
    seq: Mapped[int] = mapped_column(Integer, default=0)  # 同一学科里的排序
    status: Mapped[str] = mapped_column(String(12), default=BookStatus.DRAFT)
    # 内容来源：生成工具、模型、prompt 版本、参考资料。需要时可以按来源整册下架
    provenance: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Chapter(TimestampMixin, Base):
    """章或节：parent_id 为空的是章，否则是章下面的节。"""

    __tablename__ = "chapter"
    __table_args__ = (UniqueConstraint("book_id", "no"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    book_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("textbook.id", ondelete="CASCADE"), index=True)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("chapter.id", ondelete="CASCADE"), index=True
    )
    no: Mapped[str] = mapped_column(String(20))  # 编号，如 25、25.1
    seq: Mapped[int] = mapped_column(Integer, default=0)
    title: Mapped[str] = mapped_column(String(120))
    summary: Mapped[str] = mapped_column(Text, default="")
    mind_map: Mapped[dict[str, Any] | None] = mapped_column(JSONB)  # {"text": "...", "children": [...]}


class KnowledgePoint(TimestampMixin, Base):
    """知识点，挂在节上。重新导入时按（节，名称）更新，ID 不变，以后题目可以放心关联。"""

    __tablename__ = "knowledge_point"
    __table_args__ = (UniqueConstraint("chapter_id", "name"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    book_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("textbook.id", ondelete="CASCADE"), index=True)
    chapter_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("chapter.id", ondelete="CASCADE"), index=True)
    seq: Mapped[int] = mapped_column(Integer, default=0)
    name: Mapped[str] = mapped_column(String(80))
    content: Mapped[str] = mapped_column(Text)  # Markdown，公式用 $...$
    kind: Mapped[str] = mapped_column(String(10))  # 概念 / 公式 / 定理 / 方法 / 易错
    importance: Mapped[str] = mapped_column(String(10))  # 核心 / 重点 / 了解
    recite: Mapped[bool] = mapped_column(Boolean, default=False)  # 需要背诵


class CourseFile(TimestampMixin, Base):
    """课本、课件文件。网页上只能显示 PDF，PPT 要先转成 PDF 再放进内容包。"""

    __tablename__ = "course_file"
    __table_args__ = (UniqueConstraint("book_id", "sha256"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    book_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("textbook.id", ondelete="CASCADE"), index=True)
    chapter_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("chapter.id", ondelete="SET NULL"), index=True
    )
    kind: Mapped[str] = mapped_column(String(12))  # textbook 课本 / courseware 课件
    title: Mapped[str] = mapped_column(String(200))
    filename: Mapped[str] = mapped_column(String(200))
    storage_key: Mapped[str] = mapped_column(String(200))
    mime: Mapped[str] = mapped_column(String(100))
    size: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))
    seq: Mapped[int] = mapped_column(Integer, default=0)
    source: Mapped[str] = mapped_column(String(200), default="")  # 文件从哪里来


class PoolStatus(StrEnum):
    CHECKED = "checked"  # 独立解答和参考答案一致，待审核
    DISPUTED = "disputed"  # 不一致，待审核（重点看）
    UNCHECKED = "unchecked"  # 没能自动校验，待审核
    APPROVED = "approved"  # 审核通过，可以进周测
    REJECTED = "rejected"  # 驳回


class PoolQuestion(TimestampMixin, Base):
    """平台题库：周测从这里抽题。和教材一样是公共内容，只有审核通过的题才会进卷。

    离线生成后用命令行导入（见 curriculum/pool.py、devtools/pool_gen.py）。按 key 更新，
    审核过或改过的题重新导入时不会被覆盖。
    """

    __tablename__ = "pool_question"
    __table_args__ = (
        UniqueConstraint("book_id", "key"),
        Index("ix_pool_question_section", "section_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    book_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("textbook.id", ondelete="CASCADE"), index=True)
    section_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("chapter.id", ondelete="CASCADE"))
    key: Mapped[str] = mapped_column(String(40))  # 节编号 + 题干的摘要
    seq: Mapped[int] = mapped_column(Integer, default=0)
    qtype: Mapped[str] = mapped_column(String(10))
    difficulty: Mapped[str] = mapped_column(String(10))  # 容易 / 中等 / 较难
    stem: Mapped[str] = mapped_column(Text)
    options: Mapped[list[str]] = mapped_column(JSONB, default=list)
    answer: Mapped[str] = mapped_column(Text)
    analysis: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(12))  # textbook 改编自课本 / generated 原创
    source_ref: Mapped[str] = mapped_column(String(120), default="")  # 如：课本第 23 页习题 25.2 第 3 题
    status: Mapped[str] = mapped_column(String(12))
    # 自动校验的结果：{verdict, method, solver_answer, solver_work, reason}
    check_result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    warnings: Mapped[list[str]] = mapped_column(JSONB, default=list)
    edited: Mapped[bool] = mapped_column(Boolean, default=False)  # 人工改过
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("user_account.id", ondelete="SET NULL"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class PoolQuestionKp(Base):
    """题目考查哪些知识点。"""

    __tablename__ = "pool_question_kp"

    question_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pool_question.id", ondelete="CASCADE"), primary_key=True
    )
    kp_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("knowledge_point.id", ondelete="CASCADE"), primary_key=True, index=True
    )

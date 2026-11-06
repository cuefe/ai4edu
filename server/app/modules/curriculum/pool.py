"""平台题库：离线生成的题包导入、运营审核。只有审核通过（approved）的题才会进周测。

- 按 key（节编号 + 题干的摘要）更新，可以重复导入。
- 审核过或人工改过的题，重新导入时不动；还没审核、这次题包里又没有的题会删掉。
"""

import hashlib
import re
import unicodedata
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.ai.skills.question_gen import Difficulty, QType, QuestionData, normalize
from app.core.errors import AppError, NotFound
from app.modules.curriculum.models import (
    Chapter,
    KnowledgePoint,
    PoolQuestion,
    PoolQuestionKp,
    PoolStatus,
    Textbook,
)

PENDING = (PoolStatus.CHECKED, PoolStatus.DISPUTED, PoolStatus.UNCHECKED)
MAX_PAGE = 100


class PoolItemPack(BaseModel):
    """题包里的一道题。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    section_no: str = Field(min_length=1, max_length=20)
    qtype: QType
    difficulty: Difficulty
    stem: str = Field(min_length=1, max_length=5000)
    options: list[str] = Field(default_factory=list, max_length=6)
    answer: str = Field(min_length=1, max_length=2000)
    analysis: str = Field(default="", max_length=5000)
    knowledge_points: list[str] = Field(min_length=1, max_length=5, description="这一节的知识点名称")
    source: Literal["textbook", "generated"]
    source_ref: str = Field(default="", max_length=120)
    status: Literal["checked", "disputed", "unchecked"] = "unchecked"
    check_result: dict[str, Any] | None = None
    warnings: list[str] = Field(default_factory=list)


class PoolPack(BaseModel):
    book_key: str
    provenance: dict[str, Any] = Field(default_factory=dict)
    questions: list[PoolItemPack]


class PoolQuestionOut(BaseModel):
    id: uuid.UUID
    section_id: uuid.UUID
    section_no: str
    section_title: str
    qtype: str
    difficulty: str
    stem: str
    options: list[str]
    answer: str
    analysis: str
    source: str = Field(description="textbook 改编自课本 / generated 原创")
    source_ref: str
    status: str = Field(description="checked、disputed、unchecked 待审核 / approved 已通过 / rejected 驳回")
    check_result: dict[str, Any] | None
    warnings: list[str]
    edited: bool
    knowledge_points: list[str]
    reviewed_at: datetime | None


class PoolPage(BaseModel):
    items: list[PoolQuestionOut]
    total: int = Field(description="符合筛选条件的总数")
    counts: dict[str, int] = Field(description="这册书各状态的题数")


class PoolQuestionIn(QuestionData):
    """运营修改题目。"""

    difficulty: Difficulty


class ApproveCheckedIn(BaseModel):
    section_id: uuid.UUID | None = Field(default=None, description="只通过这一节的；为空表示整册")


def question_key(section_no: str, stem: str, options: list[str]) -> str:
    text = unicodedata.normalize("NFKC", f"{section_no}|{stem}|{'|'.join(options)}")
    return hashlib.sha1(re.sub(r"\s", "", text).encode()).hexdigest()


@dataclass
class PoolImportResult:
    created: int = 0
    updated: int = 0
    kept: int = 0  # 审核过或改过，没有动
    removed: int = 0
    dropped: list[str] = field(default_factory=list)  # 没能导入的题和原因


def load_pack(path: Path) -> PoolPack:
    return PoolPack.model_validate_json(path.read_text(encoding="utf-8"))


def import_pool(db: Session, pack: PoolPack) -> PoolImportResult:
    book = db.scalar(select(Textbook).where(Textbook.key == pack.book_key))
    if book is None:
        raise NotFound(f"教材 {pack.book_key} 不存在，先导入内容包")
    sections = {
        c.no: c
        for c in db.scalars(select(Chapter).where(Chapter.book_id == book.id, Chapter.parent_id.is_not(None)))
    }
    points = {
        (chapter_id, name): kid
        for kid, chapter_id, name in db.execute(
            select(KnowledgePoint.id, KnowledgePoint.chapter_id, KnowledgePoint.name).where(
                KnowledgePoint.book_id == book.id
            )
        )
    }
    existing = {q.key: q for q in db.scalars(select(PoolQuestion).where(PoolQuestion.book_id == book.id))}
    result = PoolImportResult()
    seen: set[str] = set()
    for seq, item in enumerate(pack.questions):
        label = f"{item.section_no}「{item.stem[:20]}」"
        section = sections.get(item.section_no)
        if section is None:
            result.dropped.append(f"{label}：没有这一节")
            continue
        kp_ids = [
            points[(section.id, name)] for name in item.knowledge_points if (section.id, name) in points
        ]
        if not kp_ids:
            result.dropped.append(f"{label}：知识点和这一节对不上")
            continue
        key = question_key(item.section_no, item.stem, item.options)
        if key in seen:
            continue
        seen.add(key)
        row = existing.get(key)
        if row is not None and (row.edited or row.status in (PoolStatus.APPROVED, PoolStatus.REJECTED)):
            result.kept += 1
            continue
        if row is None:
            row = PoolQuestion(book_id=book.id, key=key)
            db.add(row)
            result.created += 1
        else:
            result.updated += 1
        row.section_id, row.seq = section.id, seq
        row.qtype, row.difficulty = item.qtype, item.difficulty
        row.stem, row.options, row.answer, row.analysis = item.stem, item.options, item.answer, item.analysis
        row.source, row.source_ref = item.source, item.source_ref
        row.status, row.check_result, row.warnings = item.status, item.check_result, item.warnings
        db.flush()
        db.execute(delete(PoolQuestionKp).where(PoolQuestionKp.question_id == row.id))
        db.add_all(PoolQuestionKp(question_id=row.id, kp_id=kid) for kid in dict.fromkeys(kp_ids))
    stale = [q.id for key, q in existing.items() if key not in seen and q.status in PENDING and not q.edited]
    if stale:
        db.execute(delete(PoolQuestion).where(PoolQuestion.id.in_(stale)))
        result.removed = len(stale)
    db.flush()
    return result


# —— 审核 ——


def _to_out(db: Session, rows: list[PoolQuestion]) -> list[PoolQuestionOut]:
    ids = [q.id for q in rows]
    names: dict[uuid.UUID, list[str]] = {}
    for qid, name in db.execute(
        select(PoolQuestionKp.question_id, KnowledgePoint.name)
        .join(KnowledgePoint, KnowledgePoint.id == PoolQuestionKp.kp_id)
        .where(PoolQuestionKp.question_id.in_(ids))
        .order_by(KnowledgePoint.seq)
    ):
        names.setdefault(qid, []).append(name)
    sections = {
        c.id: c for c in db.scalars(select(Chapter).where(Chapter.id.in_({q.section_id for q in rows})))
    }
    return [
        PoolQuestionOut(
            id=q.id,
            section_id=q.section_id,
            section_no=sections[q.section_id].no,
            section_title=sections[q.section_id].title,
            qtype=q.qtype,
            difficulty=q.difficulty,
            stem=q.stem,
            options=q.options,
            answer=q.answer,
            analysis=q.analysis,
            source=q.source,
            source_ref=q.source_ref,
            status=q.status,
            check_result=q.check_result,
            warnings=q.warnings,
            edited=q.edited,
            knowledge_points=names.get(q.id, []),
            reviewed_at=q.reviewed_at,
        )
        for q in rows
    ]


def list_questions(
    db: Session,
    book_id: uuid.UUID,
    *,
    status: str | None = None,
    section_id: uuid.UUID | None = None,
    limit: int = 20,
    offset: int = 0,
) -> PoolPage:
    if db.get(Textbook, book_id) is None:
        raise NotFound("这册教材不存在")
    where = [PoolQuestion.book_id == book_id]
    if section_id:
        where.append(PoolQuestion.section_id == section_id)
    counts = {
        s: n
        for s, n in db.execute(
            select(PoolQuestion.status, func.count()).where(*where).group_by(PoolQuestion.status)
        )
    }
    if status == "pending":
        where.append(PoolQuestion.status.in_(PENDING))
    elif status:
        where.append(PoolQuestion.status == status)
    # 待审核的题里，有分歧的排最前面，老师先看这些
    order = {PoolStatus.DISPUTED: 0, PoolStatus.UNCHECKED: 1, PoolStatus.CHECKED: 2}
    rows = list(db.scalars(select(PoolQuestion).where(*where)))
    rows.sort(key=lambda q: (order.get(q.status, 3), q.seq))  # type: ignore[call-overload]
    page = rows[offset : offset + min(limit, MAX_PAGE)]
    return PoolPage(items=_to_out(db, page), total=len(rows), counts=counts)


def get_question(db: Session, qid: uuid.UUID) -> PoolQuestion:
    q = db.get(PoolQuestion, qid)
    if q is None:
        raise NotFound("题目不存在")
    return q


def update_question(db: Session, q: PoolQuestion, body: PoolQuestionIn) -> PoolQuestionOut:
    fixed, fatal, warnings = normalize(QuestionData.model_validate(body.model_dump(exclude={"difficulty"})))
    if fatal:
        raise AppError(fatal)
    q.qtype, q.stem, q.options = fixed.qtype, fixed.stem, fixed.options
    q.answer, q.analysis = fixed.answer, fixed.analysis
    q.difficulty, q.warnings, q.edited = body.difficulty, warnings, True
    db.flush()
    return _to_out(db, [q])[0]


def review(db: Session, q: PoolQuestion, user_id: uuid.UUID, *, approved: bool) -> PoolQuestionOut:
    q.status = PoolStatus.APPROVED if approved else PoolStatus.REJECTED
    q.reviewed_by, q.reviewed_at = user_id, datetime.now(UTC)
    db.flush()
    return _to_out(db, [q])[0]


def approve_checked(db: Session, book_id: uuid.UUID, section_id: uuid.UUID | None, user_id: uuid.UUID) -> int:
    """把自动校验一致的题一次通过。有分歧、没校验的题还是要逐题看。"""
    where = [PoolQuestion.book_id == book_id, PoolQuestion.status == PoolStatus.CHECKED]
    if section_id:
        where.append(PoolQuestion.section_id == section_id)
    done = db.execute(
        update(PoolQuestion)
        .where(*where)
        .values(status=PoolStatus.APPROVED, reviewed_by=user_id, reviewed_at=datetime.now(UTC))
    )
    return done.rowcount

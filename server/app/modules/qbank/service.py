"""题库：AI 出题 → 自动校验答案 → 老师审核入库；老师也可以手动录题。出题和校验在 tasks.py 里异步进行。

可见范围：入库的题本机构老师都能看到；待审核、驳回的题只有出题的老师能看到。只有出题的老师能修改、审核、删除。
"""

import uuid
from datetime import UTC, datetime, timedelta

from pydantic import ValidationError
from sqlalchemy import ColumnElement, Text, and_, case, func, or_, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session

from app.ai.skills import question_gen
from app.core.errors import AppError, Forbidden, NotFound
from app.modules.iam.models import User
from app.modules.qbank.models import (
    PENDING_REVIEW,
    BatchStatus,
    Question,
    QuestionBatch,
    QuestionCheck,
    QuestionStatus,
)
from app.modules.qbank.schemas import (
    BatchOut,
    CheckOut,
    QuestionCounts,
    QuestionIn,
    QuestionOut,
    QuestionView,
)

# 出题、校验中每完成一步就更新进度；超过这个时间没进度，说明任务中断了（例如服务重启）
STALE_AFTER = timedelta(minutes=10)
MAX_BATCHES_PER_USER = 2
CONTENT_FIELDS = ("qtype", "stem", "options", "answer", "analysis", "knowledge_points")

# 待审核列表的顺序：有分歧的最先看，其次是没能校验的。校验中的和有分歧的排在一起：
# 老师点"重新校验"后题目留在原处，不会突然跳到列表末尾
_REVIEW_ORDER = case(
    (Question.status.in_((QuestionStatus.DISPUTED, QuestionStatus.CHECKING)), 0),
    (Question.status == QuestionStatus.UNCHECKED, 1),
    else_=2,
)


def _visible(tenant_id: uuid.UUID, user_id: uuid.UUID) -> ColumnElement[bool]:
    return and_(
        Question.tenant_id == tenant_id,
        or_(Question.owner_id == user_id, Question.status == QuestionStatus.APPROVED),
    )


def _stale(updated_at: datetime) -> bool:
    return updated_at < datetime.now(UTC) - STALE_AFTER


def _expire_question(q: Question) -> None:
    if q.status == QuestionStatus.CHECKING and _stale(q.updated_at):
        q.status = QuestionStatus.UNCHECKED


def _expire_batch(b: QuestionBatch) -> None:
    if b.status in (BatchStatus.GENERATING, BatchStatus.CHECKING) and _stale(b.updated_at):
        b.status = BatchStatus.FAILED
        b.error = "出题中断了，请重新出题"


# —— 查询 ——


def to_outs(db: Session, questions: list[Question], user_id: uuid.UUID) -> list[QuestionOut]:
    ids = [q.id for q in questions]
    checks = {
        c.question_id: c
        for c in db.scalars(
            select(QuestionCheck)
            .where(QuestionCheck.question_id.in_(ids))
            .order_by(QuestionCheck.question_id, QuestionCheck.created_at.desc())
            .ext(distinct_on(QuestionCheck.question_id))  # 每道题只取最新一次
        )
    }
    owners = {q.owner_id for q in questions}
    names: dict[uuid.UUID, str] = {
        uid: name for uid, name in db.execute(select(User.id, User.name).where(User.id.in_(owners)))
    }
    out = []
    for q in questions:
        _expire_question(q)
        check = checks.get(q.id)
        out.append(
            QuestionOut(
                id=q.id,
                subject=q.subject,
                grade=q.grade,
                qtype=q.qtype,
                difficulty=q.difficulty,
                stem=q.stem,
                options=q.options,
                answer=q.answer,
                analysis=q.analysis,
                knowledge_points=q.knowledge_points,
                source=q.source,
                status=q.status,
                edited=q.edited,
                warnings=q.warnings,
                batch_id=q.batch_id,
                owner_name=names.get(q.owner_id, ""),
                mine=q.owner_id == user_id,
                check=CheckOut.model_validate(check, from_attributes=True) if check else None,
                created_at=q.created_at,
                updated_at=q.updated_at,
            )
        )
    return out


def list_questions(
    db: Session,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    view: QuestionView,
    subject: str | None = None,
    grade: str | None = None,
    qtype: str | None = None,
    difficulty: str | None = None,
    keyword: str | None = None,
    mine: bool = False,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[QuestionOut], int]:
    filters: list[ColumnElement[bool]] = [Question.tenant_id == tenant_id]
    if view == "bank":
        filters.append(Question.status == QuestionStatus.APPROVED)
        if mine:
            filters.append(Question.owner_id == user_id)
        order = [Question.created_at.desc(), Question.seq]
    else:
        filters.append(Question.owner_id == user_id)
        if view == "review":
            filters.append(Question.status.in_(PENDING_REVIEW))
            order = [_REVIEW_ORDER, Question.created_at.desc(), Question.seq]
        else:
            filters.append(Question.status == QuestionStatus.REJECTED)
            order = [Question.updated_at.desc()]
    for column, value in ((Question.subject, subject), (Question.grade, grade), (Question.qtype, qtype)):
        if value:
            filters.append(column == value)
    if difficulty:
        filters.append(Question.difficulty == difficulty)
    if keyword:
        escaped = keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        filters.append(or_(Question.stem.ilike(pattern), Question.knowledge_points.cast(Text).ilike(pattern)))

    total = db.scalar(select(func.count()).select_from(Question).where(*filters)) or 0
    rows = db.scalars(
        select(Question).where(*filters).order_by(*order).offset((page - 1) * page_size).limit(page_size)
    ).all()
    return to_outs(db, list(rows), user_id), total


def counts(db: Session, tenant_id: uuid.UUID, user_id: uuid.UUID) -> QuestionCounts:
    def count(*where: ColumnElement[bool]) -> int:
        return (
            db.scalar(
                select(func.count()).select_from(Question).where(Question.tenant_id == tenant_id, *where)
            )
            or 0
        )

    return QuestionCounts(
        review=count(Question.owner_id == user_id, Question.status.in_(PENDING_REVIEW)),
        bank=count(Question.status == QuestionStatus.APPROVED),
        rejected=count(Question.owner_id == user_id, Question.status == QuestionStatus.REJECTED),
    )


def get_visible(db: Session, tenant_id: uuid.UUID, user_id: uuid.UUID, qid: uuid.UUID) -> Question:
    q = db.scalar(select(Question).where(Question.id == qid, _visible(tenant_id, user_id)))
    if q is None:
        raise NotFound("题目不存在")
    _expire_question(q)
    return q


def get_owned(db: Session, tenant_id: uuid.UUID, user_id: uuid.UUID, qid: uuid.UUID) -> Question:
    q = get_visible(db, tenant_id, user_id, qid)
    if q.owner_id != user_id:
        raise Forbidden("这是别的老师出的题，只有出题的老师可以修改")
    return q


# —— 录题、修改、审核 ——


def _normalized(data: QuestionIn) -> tuple[dict, list[str]]:
    """检查题目结构，返回（题目内容字段，提示）。"""
    fixed, problem, warnings = question_gen.normalize(data)
    if problem:
        raise AppError(problem)
    return fixed.model_dump(include=set(CONTENT_FIELDS)), warnings


def create_manual(db: Session, tenant_id: uuid.UUID, user_id: uuid.UUID, data: QuestionIn) -> Question:
    """老师自己录的题不用校验，直接入库。"""
    values, warnings = _normalized(data)
    q = Question(
        tenant_id=tenant_id,
        owner_id=user_id,
        subject=data.subject,
        grade=data.grade,
        difficulty=data.difficulty,
        **values,
        source="manual",
        status=QuestionStatus.APPROVED,
        warnings=warnings,
        reviewed_by=user_id,
        reviewed_at=datetime.now(UTC),
    )
    db.add(q)
    db.flush()
    return q


def update_question(db: Session, q: Question, data: QuestionIn) -> None:
    if q.status == QuestionStatus.CHECKING:
        raise AppError("正在校验答案，请等校验完再修改", code="checking", status=409)
    values, warnings = _normalized(data)
    if q.source == "ai" and any(getattr(q, f) != values[f] for f in CONTENT_FIELDS):
        q.edited = True
    for name, value in values.items():
        setattr(q, name, value)
    q.subject, q.grade, q.difficulty, q.warnings = data.subject, data.grade, data.difficulty, warnings


def review(q: Question, user_id: uuid.UUID, approve: bool) -> None:
    if q.status == QuestionStatus.CHECKING:
        raise AppError("正在校验答案，请等校验完再审核", code="checking", status=409)
    q.status = QuestionStatus.APPROVED if approve else QuestionStatus.REJECTED
    q.reviewed_by = user_id
    q.reviewed_at = datetime.now(UTC)


def mark_for_recheck(q: Question) -> None:
    if q.status == QuestionStatus.CHECKING:
        raise AppError("正在校验答案", code="checking", status=409)
    if q.status == QuestionStatus.APPROVED:
        raise AppError("已入库的题不能重新校验")
    q.status = QuestionStatus.CHECKING


# —— 出题批次 ——


def start_batch(
    db: Session, tenant_id: uuid.UUID, user_id: uuid.UUID, p: question_gen.QuestionGenIn
) -> QuestionBatch:
    running = db.scalar(
        select(func.count())
        .select_from(QuestionBatch)
        .where(
            QuestionBatch.tenant_id == tenant_id,
            QuestionBatch.owner_id == user_id,
            QuestionBatch.status.in_((BatchStatus.GENERATING, BatchStatus.CHECKING)),
            QuestionBatch.updated_at >= datetime.now(UTC) - STALE_AFTER,
        )
    )
    if running >= MAX_BATCHES_PER_USER:
        raise AppError(f"已有 {running} 批题正在出，请等出完再试", code="too_many_generating", status=429)
    batch = QuestionBatch(
        tenant_id=tenant_id,
        owner_id=user_id,
        topic=p.topic,
        params={**p.model_dump(mode="json"), "prompt_version": question_gen.PROMPT_VERSION},
        status=BatchStatus.GENERATING,
    )
    db.add(batch)
    db.flush()
    return batch


def get_batch(db: Session, tenant_id: uuid.UUID, user_id: uuid.UUID, batch_id: uuid.UUID) -> QuestionBatch:
    batch = db.scalar(
        select(QuestionBatch).where(
            QuestionBatch.id == batch_id,
            QuestionBatch.tenant_id == tenant_id,
            QuestionBatch.owner_id == user_id,
        )
    )
    if batch is None:
        raise NotFound("出题记录不存在")
    _expire_batch(batch)
    return batch


def batch_out(db: Session, batch: QuestionBatch, user_id: uuid.UUID) -> BatchOut:
    questions = db.scalars(select(Question).where(Question.batch_id == batch.id).order_by(Question.seq)).all()
    try:
        params = question_gen.QuestionGenIn.model_validate(batch.params)
    except ValidationError:
        params = None
    return BatchOut(
        id=batch.id,
        topic=batch.topic,
        params=params,
        status=batch.status,
        progress=batch.progress,
        error=batch.error,
        warnings=batch.warnings,
        sources=batch.sources,
        created_at=batch.created_at,
        questions=to_outs(db, list(questions), user_id),
    )

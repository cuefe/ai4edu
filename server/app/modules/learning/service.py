"""学生的学习记录：错题本（自动收录、订正）。背诵复习在 review.py。"""

import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

import anyio
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.ai.gateway.gateway import CallContext, get_gateway
from app.ai.skills import correction_guide
from app.ai.skills.common import parse_json
from app.core.db import new_id, session_scope
from app.core.errors import AppError, NotFound
from app.modules.assignment.grading import objective_ratio
from app.modules.learning.models import KpEvidence, ReviewState, WrongItem, WrongStatus

MASTERY_DECAY = 0.8  # 掌握度里成绩的权重每过一周乘这个数


class WrongItemOut(BaseModel):
    id: uuid.UUID
    subject: str
    assignment_title: str
    question: dict[str, Any] = Field(description="题目快照，含答案和解析（前端订正时先隐藏）")
    wrong_response: str
    status: str
    wrong_count: int
    created_at: datetime
    corrected_at: datetime | None
    guide: dict[str, Any] | None


class WrongBook(BaseModel):
    items: list[WrongItemOut]
    pending: int
    corrected: int
    knowledge_points: list[str] = Field(description="错题涉及的知识点，用来筛选")


class RedoOut(BaseModel):
    correct: bool | None = Field(description="为空表示要对照答案自己判断（解答题等）")
    item: WrongItemOut


def record_wrong(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    student_id: uuid.UUID,
    item_id: uuid.UUID,
    assignment_title: str,
    subject: str,
    question: dict[str, Any],
    response: str,
    available_at: datetime,
) -> None:
    """作业里做错的题收进错题本。同一道题只收一次。"""
    existing = db.scalar(
        select(WrongItem).where(WrongItem.student_id == student_id, WrongItem.item_id == item_id)
    )
    if existing:
        existing.wrong_response = response
        return
    db.add(
        WrongItem(
            tenant_id=tenant_id,
            student_id=student_id,
            item_id=item_id,
            assignment_title=assignment_title,
            subject=subject,
            question=question,
            wrong_response=response,
            available_at=available_at,
        )
    )


def remove_wrong(db: Session, student_id: uuid.UUID, item_id: uuid.UUID) -> None:
    """老师把判错改成对：还没订正的错题从错题本里拿掉。"""
    db.execute(
        delete(WrongItem).where(
            WrongItem.student_id == student_id,
            WrongItem.item_id == item_id,
            WrongItem.status == WrongStatus.PENDING,
        )
    )


def record_evidence(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    student_id: uuid.UUID,
    subject: str,
    item_id: uuid.UUID,
    kp_ids: list[str],
    ratio: float,
    at: datetime,
) -> None:
    """记下一道题对这些知识点的得分。同一道题再记一次（老师改分）时覆盖，不会重复计入。"""
    if not kp_ids:
        return
    stmt = insert(KpEvidence).values(
        [
            {
                "id": new_id(),
                "tenant_id": tenant_id,
                "student_id": student_id,
                "subject": subject,
                "kp_id": uuid.UUID(k),
                "item_id": item_id,
                "ratio": ratio,
                "answered_at": at,
            }
            for k in kp_ids
        ]
    )
    db.execute(
        stmt.on_conflict_do_update(
            index_elements=[KpEvidence.student_id, KpEvidence.item_id, KpEvidence.kp_id],
            set_={"ratio": stmt.excluded.ratio, "answered_at": stmt.excluded.answered_at},
        )
    )


def compute_mastery(
    rows: Iterable[tuple[uuid.UUID, float, datetime]], at: datetime
) -> dict[uuid.UUID, float]:
    """按知识点、按时间衰减的加权正确率（技术方案里的掌握度）。rows 是（知识点，得分比例，作答时间）。

    越近的成绩权重越大，每过一周权重乘 MASTERY_DECAY。再加一个权重为 1、取值 0.5 的先验：
    只做过一道题时不会直接判成 0 或 1，答错一道题的掌握度是 0.25，答对一道是 0.75。
    """
    weighted: dict[uuid.UUID, float] = {}
    weights: dict[uuid.UUID, float] = {}
    for kp_id, ratio, answered_at in rows:
        weeks = max((at - answered_at).total_seconds(), 0) / (7 * 24 * 3600)
        w = MASTERY_DECAY**weeks
        weighted[kp_id] = weighted.get(kp_id, 0) + w * ratio
        weights[kp_id] = weights.get(kp_id, 0) + w
    return {k: (weighted[k] + 0.5) / (weights[k] + 1) for k in weights}


def mastery(
    db: Session, tenant_id: uuid.UUID, student_id: uuid.UUID, subject: str, at: datetime | None = None
) -> dict[uuid.UUID, float]:
    """这个学生这门课各知识点的掌握度（0～1）。没考过的知识点不在结果里。"""
    rows = db.execute(
        select(KpEvidence.kp_id, KpEvidence.ratio, KpEvidence.answered_at).where(
            KpEvidence.tenant_id == tenant_id,
            KpEvidence.student_id == student_id,
            KpEvidence.subject == subject,
        )
    )
    return compute_mastery([tuple(r) for r in rows], at or datetime.now(UTC))


def learned_counts(db: Session, student_id: uuid.UUID, item_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    """每个背诵项学过（复习过至少一次）的卡片数。"""
    if not item_ids:
        return {}
    rows = db.execute(
        select(ReviewState.item_id, func.count())
        .where(ReviewState.student_id == student_id, ReviewState.item_id.in_(item_ids))
        .group_by(ReviewState.item_id)
    )
    return {iid: n for iid, n in rows}


# —— 错题本 ——


def _out(w: WrongItem) -> WrongItemOut:
    return WrongItemOut.model_validate(w, from_attributes=True)


def wrong_book(
    db: Session,
    tenant_id: uuid.UUID,
    student_id: uuid.UUID,
    *,
    status: str | None = None,
    subject: str | None = None,
    knowledge_point: str | None = None,
) -> WrongBook:
    now = datetime.now(UTC)
    visible = (
        WrongItem.tenant_id == tenant_id,
        WrongItem.student_id == student_id,
        WrongItem.available_at <= now,
    )
    rows = list(db.scalars(select(WrongItem).where(*visible).order_by(WrongItem.created_at.desc())))
    points = sorted({k for w in rows for k in w.question.get("knowledge_points") or []})
    pending = sum(1 for w in rows if w.status == WrongStatus.PENDING)
    corrected = len(rows) - pending
    if status:
        rows = [w for w in rows if w.status == status]
    if subject:
        rows = [w for w in rows if w.subject == subject]
    if knowledge_point:
        rows = [w for w in rows if knowledge_point in (w.question.get("knowledge_points") or [])]
    return WrongBook(
        items=[_out(w) for w in rows[:200]],
        pending=pending,
        corrected=corrected,
        knowledge_points=points,
    )


def get_wrong(db: Session, tenant_id: uuid.UUID, student_id: uuid.UUID, wid: uuid.UUID) -> WrongItem:
    w = db.scalar(
        select(WrongItem).where(
            WrongItem.id == wid,
            WrongItem.tenant_id == tenant_id,
            WrongItem.student_id == student_id,
            WrongItem.available_at <= datetime.now(UTC),
        )
    )
    if w is None:
        raise NotFound("错题不存在")
    return w


def _corrected(w: WrongItem, ok: bool) -> None:
    if ok:
        w.status = WrongStatus.CORRECTED
        w.corrected_at = datetime.now(UTC)
    else:
        w.wrong_count += 1


def redo(w: WrongItem, response: str) -> RedoOut:
    """订正时重做：客观题马上判对错；解答题等判断不了的，返回答案让学生自己对照（self_check）。"""
    if not response.strip():
        raise AppError("请先写出你的答案")
    q = w.question
    ratio = objective_ratio(q["qtype"], q["answer"], response)
    if ratio is None:
        return RedoOut(correct=None, item=_out(w))
    _corrected(w, ratio == 1)
    return RedoOut(correct=ratio == 1, item=_out(w))


def self_check(w: WrongItem, correct: bool) -> WrongItemOut:
    _corrected(w, correct)
    return _out(w)


def remove(db: Session, w: WrongItem) -> None:
    db.delete(w)


async def guide(ctx: CallContext, tenant_id: uuid.UUID, wid: uuid.UUID) -> dict[str, Any]:
    """四步订正引导。生成一次后存起来，再看不用重新调用模型。"""

    def load() -> tuple[dict | None, str, dict, str]:
        with session_scope(tenant_id=tenant_id) as db:
            w = get_wrong(db, tenant_id, ctx.user_id, wid)  # type: ignore[arg-type]
            return w.guide, w.subject, dict(w.question), w.wrong_response

    cached, subject, question, wrong_response = await anyio.to_thread.run_sync(load)
    if cached:
        return cached
    result = await get_gateway().chat(
        correction_guide.SKILL,
        correction_guide.build_messages(subject, question, wrong_response),
        ctx=ctx,
        temperature=0.3,
        max_tokens=3000,
        response_format={"type": "json_object"},
    )
    data = correction_guide.parse_guide(parse_json(result.text))
    if data is None:
        raise AppError("AI 返回的内容格式不对，请重试", code="ai_bad_output", status=502)

    def save() -> None:
        with session_scope(tenant_id=tenant_id) as db:
            w = db.get(WrongItem, wid)
            if w is not None:
                w.guide = data

    await anyio.to_thread.run_sync(save)
    return data

"""作业（老师端）：布置、列表、作业报告、批改确认。学生端在 student.py。

布置时把题目、讲义、卡片存成快照，给每个学生建一条 submission。
作业报告在读取时汇总：数据量在单份作业内，查询很小，不需要单独的汇总表。
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError, Forbidden, NotFound
from app.modules.assignment.grading import DEFAULT_SCORE
from app.modules.assignment.models import (
    Answer,
    AnswerStatus,
    Assignment,
    AssignmentItem,
    ItemType,
    Submission,
    SubmissionStatus,
)
from app.modules.assignment.schemas import (
    AnswerOut,
    AssignmentBrief,
    AssignmentIn,
    AssignmentReport,
    GradingRow,
    ItemIn,
    ItemOut,
    ItemStat,
    SubmissionRow,
)
from app.modules.content import service as content
from app.modules.content.markdown import doc_to_markdown
from app.modules.iam.models import User
from app.modules.learning import service as learning
from app.modules.notify.service import notify
from app.modules.ops.service import audit
from app.modules.org import service as org
from app.modules.org.models import MemberRole
from app.modules.qbank import service as qbank
from app.modules.qbank.models import QuestionStatus
from app.modules.recite import service as recite

COMMON_WRONG_RATE = 0.4  # 错误率达到这个比例算共性错题
PENDING = (AnswerStatus.GRADING, AnswerStatus.AI_DONE)
QUESTION_FIELDS = ("qtype", "stem", "options", "answer", "analysis", "knowledge_points", "difficulty")


def now() -> datetime:
    return datetime.now(UTC)


def teacher_label(name: str) -> str:
    """“王”→“王老师”；名字本身就是“李老师”的不再重复加。"""
    return name if name.endswith("老师") else f"{name}老师"


# —— 布置 ——


def _snapshot(
    db: Session, tenant_id: uuid.UUID, teacher_id: uuid.UUID, item: ItemIn
) -> tuple[dict[str, Any], float]:
    if item.item_type == ItemType.QUESTION:
        q = qbank.get_visible(db, tenant_id, teacher_id, item.ref_id)
        if q.status != QuestionStatus.APPROVED:
            raise AppError(f"只能布置已入库的题，「{q.stem[:20]}」还没审核通过")
        return {f: getattr(q, f) for f in QUESTION_FIELDS}, item.score or DEFAULT_SCORE[q.qtype]
    if item.item_type == ItemType.DOCUMENT:
        doc = content.get_ready_document(db, tenant_id, teacher_id, item.ref_id)
        return {
            "title": doc.title,
            "doc_type": doc.doc_type,
            "markdown": doc_to_markdown(doc.content or {}),
        }, 0
    deck = recite.to_out(db, recite.get_deck(db, tenant_id, teacher_id, item.ref_id))
    if not deck.cards:
        raise AppError(f"卡片组「{deck.title}」里还没有卡片")
    return {
        "title": deck.title,
        "cards": [c.model_dump(include={"kind", "front", "back"}) for c in deck.cards],
    }, 0


def create(db: Session, tenant_id: uuid.UUID, teacher: User, body: AssignmentIn) -> Assignment:
    my_classes = org.class_ids_of(db, tenant_id, teacher.id, MemberRole.TEACHER)
    if set(body.class_ids) - set(my_classes):
        raise AppError("只能布置给自己任教的班级")
    in_my_classes: dict[uuid.UUID, uuid.UUID] = {}
    for sid, cid in org.students_in_classes(db, tenant_id, my_classes):
        in_my_classes.setdefault(sid, cid)
    recipients: dict[uuid.UUID, uuid.UUID] = {}
    for sid, cid in org.students_in_classes(db, tenant_id, body.class_ids):
        recipients.setdefault(sid, cid)
    for sid in body.student_ids:
        if sid not in in_my_classes:
            raise AppError("只能布置给自己班上的学生")
        recipients.setdefault(sid, in_my_classes[sid])
    if not recipients:
        raise AppError("请选择班级或学生；所选班级里还没有学生")

    publish_at = body.publish_at or now()
    if body.due_at and body.due_at <= max(publish_at, now()):
        raise AppError("截止时间要晚于发布时间")
    snapshots = [_snapshot(db, tenant_id, teacher.id, item) for item in body.items]

    a = Assignment(
        tenant_id=tenant_id,
        owner_id=teacher.id,
        title=body.title,
        subject=body.subject,
        note=body.note,
        class_ids=[str(c) for c in body.class_ids],
        publish_at=publish_at,
        due_at=body.due_at,
        answer_release=body.answer_release,
        allow_ai=body.allow_ai,
        total_score=sum(score for _, score in snapshots),
        student_count=len(recipients),
    )
    db.add(a)
    db.flush()
    db.add_all(
        AssignmentItem(
            tenant_id=tenant_id,
            assignment_id=a.id,
            seq=i,
            item_type=item.item_type,
            ref_id=item.ref_id,
            score=score,
            content=snapshot,
        )
        for i, (item, (snapshot, score)) in enumerate(zip(body.items, snapshots, strict=True))
    )
    db.add_all(
        Submission(tenant_id=tenant_id, assignment_id=a.id, student_id=sid, klass_id=cid)
        for sid, cid in recipients.items()
    )
    if publish_at <= now():  # 定时发布的作业到时间后学生在列表里能看到，暂不单独发通知
        notify(
            db,
            tenant_id,
            recipients,
            kind="assignment",
            title=f"新作业：{body.title}",
            body=f"{teacher_label(teacher.name)}布置了作业"
            + (f"，{body.due_at:%m-%d %H:%M} 截止" if body.due_at else ""),
            link=f"/student/assignments/{a.id}",
        )
    db.flush()
    return a


def get_owned(db: Session, tenant_id: uuid.UUID, teacher_id: uuid.UUID, aid: uuid.UUID) -> Assignment:
    a = db.scalar(select(Assignment).where(Assignment.id == aid, Assignment.tenant_id == tenant_id))
    if a is None:
        raise NotFound("作业不存在")
    if a.owner_id != teacher_id:
        raise Forbidden("只有布置作业的老师可以查看和批改")
    return a


def items_of(db: Session, aid: uuid.UUID) -> list[AssignmentItem]:
    return list(
        db.scalars(
            select(AssignmentItem).where(AssignmentItem.assignment_id == aid).order_by(AssignmentItem.seq)
        )
    )


# —— 列表和报告 ——


def _brief(a: Assignment, names: dict[uuid.UUID, str], stats: dict[uuid.UUID, tuple]) -> AssignmentBrief:
    submitted, avg, pending = stats.get(a.id, (0, None, 0))
    return AssignmentBrief(
        id=a.id,
        title=a.title,
        subject=a.subject,
        class_names=[names.get(uuid.UUID(c), "") for c in a.class_ids],
        publish_at=a.publish_at,
        due_at=a.due_at,
        answer_release=a.answer_release,
        allow_ai=a.allow_ai,
        total_score=a.total_score,
        student_count=a.student_count,
        submitted_count=submitted,
        pending_review=pending,
        avg_score=round(avg, 1) if avg is not None else None,
        created_at=a.created_at,
    )


def _stats(db: Session, ids: list[uuid.UUID]) -> dict[uuid.UUID, tuple]:
    if not ids:
        return {}
    graded = Submission.status == SubmissionStatus.GRADED
    rows = db.execute(
        select(
            Submission.assignment_id,
            func.count().filter(Submission.status != SubmissionStatus.TODO),
            func.avg(case((graded, Submission.score))),
            func.coalesce(func.sum(Submission.pending_count), 0),
        )
        .where(Submission.assignment_id.in_(ids))
        .group_by(Submission.assignment_id)
    )
    return {aid: (n, avg, pending) for aid, n, avg, pending in rows}


def list_for_teacher(db: Session, tenant_id: uuid.UUID, teacher_id: uuid.UUID) -> list[AssignmentBrief]:
    rows = list(
        db.scalars(
            select(Assignment)
            .where(Assignment.tenant_id == tenant_id, Assignment.owner_id == teacher_id)
            .order_by(Assignment.created_at.desc())
            .limit(200)
        )
    )
    names = org.class_names(db, tenant_id, list({uuid.UUID(c) for a in rows for c in a.class_ids}))
    stats = _stats(db, [a.id for a in rows])
    return [_brief(a, names, stats) for a in rows]


def item_out(item: AssignmentItem, *, reveal: bool = True) -> ItemOut:
    data = dict(item.content)
    if not reveal and item.item_type == ItemType.QUESTION:
        data.pop("answer", None)
        data.pop("analysis", None)
    return ItemOut(id=item.id, seq=item.seq, item_type=item.item_type, score=item.score, content=data)


def answer_out(a: Answer, *, show_ai: bool = True) -> AnswerOut:
    """show_ai=False：学生端在老师确认前看不到 AI 给的分和评语。"""
    visible = show_ai or a.status == AnswerStatus.CONFIRMED
    return AnswerOut(
        id=a.id,
        item_id=a.item_id,
        response=a.response,
        image_count=len(a.images),
        status=a.status,
        correct=a.correct,
        score=a.score,
        ai_score=a.ai_score if visible else None,
        ai_confidence=a.ai_confidence if show_ai else None,
        ai_comment=a.ai_comment if visible else "",
        ai_points=a.ai_points if visible else [],
        teacher_comment=a.teacher_comment,
    )


def submission_rows(db: Session, tenant_id: uuid.UUID, a: Assignment) -> list[SubmissionRow]:
    rows = db.execute(
        select(Submission, User.name, User.username)
        .join(User, User.id == Submission.student_id)
        .where(Submission.assignment_id == a.id)
        .order_by(User.username, User.name)
    ).all()
    names = org.class_names(db, tenant_id, [s.klass_id for s, _, _ in rows if s.klass_id])
    return [
        SubmissionRow(
            id=s.id,
            student_id=s.student_id,
            student_name=name,
            username=username,
            class_name=names.get(s.klass_id) if s.klass_id else None,
            status=s.status,
            submitted_at=s.submitted_at,
            late=bool(s.submitted_at and a.due_at and s.submitted_at > a.due_at),
            score=s.score if s.status != SubmissionStatus.TODO else None,
            pending_count=s.pending_count,
            progress_done=sum(1 for v in s.progress.values() if v),
        )
        for s, name, username in rows
    ]


def report(db: Session, tenant_id: uuid.UUID, a: Assignment) -> AssignmentReport:
    items = items_of(db, a.id)
    final = Answer.score.is_not(None)
    rows = db.execute(
        select(
            Answer.item_id,
            func.count().filter(final),
            func.count().filter(Answer.correct.is_(True)),
            func.avg(Answer.score),
        )
        .join(Submission, Submission.id == Answer.submission_id)
        .where(Submission.assignment_id == a.id, Submission.status != SubmissionStatus.TODO)
        .group_by(Answer.item_id)
    )
    per_item = {iid: (n, correct, avg) for iid, n, correct, avg in rows}
    item_stats = []
    for item in items:
        if item.item_type != ItemType.QUESTION:
            continue
        n, correct, avg = per_item.get(item.id, (0, 0, None))
        accuracy = correct / n if n else None
        item_stats.append(
            ItemStat(
                item_id=item.id,
                seq=item.seq,
                answered=n,
                correct=correct,
                avg_score=round(avg, 1) if avg is not None else None,
                accuracy=round(accuracy, 3) if accuracy is not None else None,
                common_wrong=accuracy is not None and 1 - accuracy >= COMMON_WRONG_RATE,
            )
        )
    names = org.class_names(db, tenant_id, [uuid.UUID(c) for c in a.class_ids])
    brief = _brief(a, names, _stats(db, [a.id]))
    subs = submission_rows(db, tenant_id, a)
    return AssignmentReport(
        **brief.model_dump(),
        note=a.note,
        items=[item_out(i) for i in items],
        graded_count=sum(1 for s in subs if s.status == SubmissionStatus.GRADED),
        item_stats=item_stats,
        submissions=subs,
    )


def remind(db: Session, tenant_id: uuid.UUID, a: Assignment, teacher: User) -> int:
    """一键催交：给还没提交的学生发站内信。"""
    todo = db.scalars(
        select(Submission.student_id).where(
            Submission.assignment_id == a.id, Submission.status == SubmissionStatus.TODO
        )
    ).all()
    due = f"，{a.due_at:%m-%d %H:%M} 截止" if a.due_at else ""
    return notify(
        db,
        tenant_id,
        todo,
        kind="remind",
        title=f"{teacher_label(teacher.name)}提醒你完成作业：{a.title}",
        body=f"作业还没有提交{due}，抓紧时间完成吧。",
        link=f"/student/assignments/{a.id}",
    )


# —— 批改确认 ——


def refresh_submission(db: Session, sub: Submission) -> None:
    """重新汇总得分和待批改数。"""
    db.flush()
    answers = db.scalars(select(Answer).where(Answer.submission_id == sub.id)).all()
    sub.score = sum(x.score for x in answers if x.score is not None)
    sub.pending_count = sum(1 for x in answers if x.status in PENDING)
    if sub.status != SubmissionStatus.TODO:
        sub.status = SubmissionStatus.SUBMITTED if sub.pending_count else SubmissionStatus.GRADED


def record_result(db: Session, a: Assignment, sub: Submission, item: AssignmentItem, answer: Answer) -> None:
    """一道题出了最终分：做错的进错题本，老师改成对的从错题本拿掉。"""
    if answer.correct:
        learning.remove_wrong(db, sub.student_id, item.id)
        return
    release = a.due_at if a.answer_release == "due" and a.due_at else (sub.submitted_at or now())
    learning.record_wrong(
        db,
        tenant_id=a.tenant_id,
        student_id=sub.student_id,
        item_id=item.id,
        assignment_title=a.title,
        subject=a.subject,
        question=dict(item.content),
        response=answer.response or ("（拍照作答）" if answer.images else ""),
        available_at=release,
    )


def grading_rows(db: Session, a: Assignment) -> list[GradingRow]:
    """等老师确认的题：AI 没把握的排前面，批改中的排最后。"""
    rows = db.execute(
        select(Answer, User.name, AssignmentItem)
        .join(Submission, Submission.id == Answer.submission_id)
        .join(User, User.id == Answer.student_id)
        .join(AssignmentItem, AssignmentItem.id == Answer.item_id)
        .where(Submission.assignment_id == a.id, Answer.status.in_(PENDING))
        .order_by(
            case((Answer.status == AnswerStatus.GRADING, 1), else_=0),
            Answer.ai_confidence.asc().nulls_first(),
            AssignmentItem.seq,
        )
    ).all()
    return [
        GradingRow(
            **answer_out(ans).model_dump(),
            student_name=name,
            item_seq=item.seq,
            item_score=item.score,
            question=dict(item.content),
        )
        for ans, name, item in rows
    ]


def get_answer_for_teacher(
    db: Session, tenant_id: uuid.UUID, teacher_id: uuid.UUID, answer_id: uuid.UUID
) -> tuple[Answer, Submission, Assignment, AssignmentItem]:
    row = db.execute(
        select(Answer, Submission, Assignment, AssignmentItem)
        .join(Submission, Submission.id == Answer.submission_id)
        .join(Assignment, Assignment.id == Submission.assignment_id)
        .join(AssignmentItem, AssignmentItem.id == Answer.item_id)
        .where(Answer.id == answer_id, Answer.tenant_id == tenant_id)
    ).first()
    if row is None:
        raise NotFound("作答不存在")
    if row[2].owner_id != teacher_id:
        raise Forbidden("只有布置作业的老师可以批改")
    return row[0], row[1], row[2], row[3]


def confirm(
    db: Session,
    teacher: User,
    answer: Answer,
    sub: Submission,
    a: Assignment,
    item: AssignmentItem,
    score: float | None,
    comment: str | None,
) -> None:
    """老师确认 AI 给的分，或者改分（客观题也可以改）。"""
    if answer.status == AnswerStatus.GRADING:
        raise AppError("AI 还在批改这道题，请稍等", code="grading", status=409)
    if answer.status == AnswerStatus.DRAFT:
        raise AppError("学生还没有提交")
    if score is None:
        score = answer.ai_score
    if score is None:
        raise AppError("AI 没能批改这道题，请填写分数")
    if score > item.score:
        raise AppError(f"得分不能超过满分 {item.score:g} 分")
    previous = answer.score if answer.score is not None else answer.ai_score
    if answer.status in (AnswerStatus.AUTO, AnswerStatus.CONFIRMED) and previous != score:
        audit(
            db,
            tenant_id=a.tenant_id,
            actor_id=teacher.id,
            action="change_score",
            target_type="answer",
            target_id=answer.id,
            before=previous,
            after=score,
        )
    answer.score = round(score * 2) / 2
    answer.correct = answer.score >= item.score
    answer.status = AnswerStatus.CONFIRMED
    if comment is not None:
        answer.teacher_comment = comment
    answer.graded_by = teacher.id
    answer.graded_at = now()
    record_result(db, a, sub, item, answer)
    refresh_submission(db, sub)

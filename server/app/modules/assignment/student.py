"""作业（学生端）：查看、作答（文字或拍照）、提交。提交时客观题马上出分，主观题交给 AI 批改、老师确认。"""

import uuid
from datetime import datetime
from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import storage
from app.core.errors import AppError, NotFound
from app.modules.assignment.grading import objective_ratio, points
from app.modules.assignment.models import (
    Answer,
    AnswerRelease,
    AnswerStatus,
    Assignment,
    AssignmentItem,
    ItemType,
    Submission,
    SubmissionStatus,
)
from app.modules.assignment.schemas import StudentAssignment, StudentAssignmentBrief
from app.modules.assignment.service import (
    answer_out,
    item_out,
    items_of,
    now,
    record_result,
    refresh_submission,
)
from app.modules.iam.models import User
from app.modules.learning import service as learning

MAX_IMAGES = 3
MAX_IMAGE_BYTES = 10 * 1024 * 1024
IMAGE_EDGE = 1600  # 拍照作答压到这个长边，够看清字迹，也省 token


def revealed(a: Assignment, sub: Submission, at: datetime | None = None) -> bool:
    """答案和解析是否已经公布给这个学生。"""
    if sub.status == SubmissionStatus.TODO:
        return False
    if a.answer_release == AnswerRelease.DUE and a.due_at:
        return (at or now()) >= a.due_at
    return True


def get(
    db: Session, tenant_id: uuid.UUID, student_id: uuid.UUID, aid: uuid.UUID
) -> tuple[Assignment, Submission]:
    row = db.execute(
        select(Assignment, Submission)
        .join(Submission, Submission.assignment_id == Assignment.id)
        .where(
            Assignment.id == aid,
            Assignment.tenant_id == tenant_id,
            Submission.student_id == student_id,
            Assignment.publish_at <= now(),
        )
    ).first()
    if row is None:
        raise NotFound("作业不存在")
    return row[0], row[1]


def _counts(items: list[AssignmentItem]) -> tuple[int, int]:
    questions = sum(1 for i in items if i.item_type == ItemType.QUESTION)
    return questions, len(items) - questions


def list_for_student(
    db: Session, tenant_id: uuid.UUID, student_id: uuid.UUID
) -> list[StudentAssignmentBrief]:
    rows = db.execute(
        select(Assignment, Submission, User.name)
        .join(Submission, Submission.assignment_id == Assignment.id)
        .join(User, User.id == Assignment.owner_id)
        .where(
            Assignment.tenant_id == tenant_id,
            Submission.student_id == student_id,
            Assignment.publish_at <= now(),
        )
        .order_by(Assignment.publish_at.desc())
        .limit(100)
    ).all()
    ids = [a.id for a, _, _ in rows]
    kinds = db.execute(
        select(AssignmentItem.assignment_id, AssignmentItem.item_type, func.count())
        .where(AssignmentItem.assignment_id.in_(ids))
        .group_by(AssignmentItem.assignment_id, AssignmentItem.item_type)
    ).all()
    questions = {aid: n for aid, kind, n in kinds if kind == ItemType.QUESTION}
    tasks: dict[uuid.UUID, int] = {}
    for aid, kind, n in kinds:
        if kind != ItemType.QUESTION:
            tasks[aid] = tasks.get(aid, 0) + n
    return [
        StudentAssignmentBrief(
            id=a.id,
            title=a.title,
            subject=a.subject,
            teacher_name=teacher,
            publish_at=a.publish_at,
            due_at=a.due_at,
            status=s.status,
            score=s.score if s.status == SubmissionStatus.GRADED else None,
            total_score=a.total_score,
            question_count=questions.get(a.id, 0),
            task_count=tasks.get(a.id, 0),
            progress_done=sum(1 for v in s.progress.values() if v),
        )
        for a, s, teacher in rows
    ]


def detail(db: Session, a: Assignment, sub: Submission) -> StudentAssignment:
    items = items_of(db, a.id)
    reveal = revealed(a, sub)
    answers = db.scalars(select(Answer).where(Answer.submission_id == sub.id)).all()
    questions, tasks = _counts(items)
    teacher = db.scalar(select(User.name).where(User.id == a.owner_id)) or ""
    recite_items = [i.id for i in items if i.item_type == ItemType.RECITE]
    return StudentAssignment(
        id=a.id,
        title=a.title,
        subject=a.subject,
        teacher_name=teacher,
        publish_at=a.publish_at,
        due_at=a.due_at,
        status=sub.status,
        score=sub.score if sub.status == SubmissionStatus.GRADED else None,
        total_score=a.total_score,
        question_count=questions,
        task_count=tasks,
        progress_done=sum(1 for v in sub.progress.values() if v),
        note=a.note,
        allow_ai=a.allow_ai,
        revealed=reveal,
        submitted_at=sub.submitted_at,
        pending_count=sub.pending_count,
        items=[item_out(i, reveal=reveal) for i in items],
        # 提交前不返回判分结果（也没有），提交后客观题马上能看到对错
        answers=[answer_out(x, show_ai=False) for x in answers],
        recite_progress={
            str(k): v for k, v in learning.learned_counts(db, sub.student_id, recite_items).items()
        },
        progress=sub.progress,
    )


def _item(
    db: Session, a: Assignment, item_id: uuid.UUID, item_type: ItemType | None = None
) -> AssignmentItem:
    item = db.scalar(
        select(AssignmentItem).where(AssignmentItem.id == item_id, AssignmentItem.assignment_id == a.id)
    )
    if item is None or (item_type and item.item_type != item_type):
        raise NotFound("题目不存在")
    return item


def _editable(sub: Submission) -> None:
    if sub.status != SubmissionStatus.TODO:
        raise AppError("作业已经提交，不能再修改", code="submitted", status=409)


def _answer(db: Session, sub: Submission, item: AssignmentItem) -> Answer:
    answer = db.scalar(select(Answer).where(Answer.submission_id == sub.id, Answer.item_id == item.id))
    if answer is None:
        answer = Answer(
            tenant_id=sub.tenant_id, submission_id=sub.id, item_id=item.id, student_id=sub.student_id
        )
        db.add(answer)
        db.flush()
    return answer


def save_response(db: Session, a: Assignment, sub: Submission, item_id: uuid.UUID, response: str) -> Answer:
    _editable(sub)
    answer = _answer(db, sub, _item(db, a, item_id, ItemType.QUESTION))
    answer.response = response
    return answer


def ai_blocked(db: Session, tenant_id: uuid.UUID, student_id: uuid.UUID) -> Assignment | None:
    """正在做的作业里有老师设置了“不能问 AI”的，作业期间问一问整体关闭。"""
    t = now()
    return db.scalar(
        select(Assignment)
        .join(Submission, Submission.assignment_id == Assignment.id)
        .where(
            Assignment.tenant_id == tenant_id,
            Submission.student_id == student_id,
            Submission.status == SubmissionStatus.TODO,
            Assignment.allow_ai.is_(False),
            Assignment.publish_at <= t,
            (Assignment.due_at.is_(None)) | (Assignment.due_at > t),
        )
        .limit(1)
    )


def normalize_image(data: bytes) -> bytes:
    """拍照上传的图片：转正方向、压到 IMAGE_EDGE、存成 JPEG。"""
    if len(data) > MAX_IMAGE_BYTES:
        raise AppError("图片不能超过 10MB")
    try:
        img = Image.open(BytesIO(data))
        img = ImageOps.exif_transpose(img).convert("RGB")
    except (UnidentifiedImageError, OSError) as exc:
        raise AppError("图片打不开，请重新拍一张") from exc
    img.thumbnail((IMAGE_EDGE, IMAGE_EDGE))
    buf = BytesIO()
    img.save(buf, "JPEG", quality=85)
    return buf.getvalue()


def add_image(db: Session, a: Assignment, sub: Submission, item_id: uuid.UUID, data: bytes) -> Answer:
    _editable(sub)
    answer = _answer(db, sub, _item(db, a, item_id, ItemType.QUESTION))
    if len(answer.images) >= MAX_IMAGES:
        raise AppError(f"每道题最多上传 {MAX_IMAGES} 张照片")
    key = storage.new_key(sub.tenant_id, "answer.jpg")
    storage.put(key, normalize_image(data))
    answer.images = [*answer.images, key]
    return answer


def remove_image(db: Session, a: Assignment, sub: Submission, item_id: uuid.UUID, index: int) -> Answer:
    _editable(sub)
    answer = _answer(db, sub, _item(db, a, item_id, ItemType.QUESTION))
    if not 0 <= index < len(answer.images):
        raise NotFound("照片不存在")
    key = answer.images[index]
    answer.images = [k for i, k in enumerate(answer.images) if i != index]
    storage.delete(key)
    return answer


def image_bytes(answer: Answer, index: int) -> bytes:
    if not 0 <= index < len(answer.images):
        raise NotFound("照片不存在")
    try:
        return storage.get(answer.images[index])
    except FileNotFoundError as exc:
        raise NotFound("照片找不到了") from exc


def answer_of(db: Session, sub: Submission, item_id: uuid.UUID) -> Answer:
    answer = db.scalar(select(Answer).where(Answer.submission_id == sub.id, Answer.item_id == item_id))
    if answer is None:
        raise NotFound("还没有作答")
    return answer


def mark_done(db: Session, a: Assignment, sub: Submission, item_id: uuid.UUID) -> None:
    """讲义读完、背诵完成。"""
    item = _item(db, a, item_id)
    if item.item_type == ItemType.QUESTION:
        raise AppError("题目要作答提交")
    sub.progress = {**sub.progress, str(item.id): True}


def recite_items(
    db: Session, tenant_id: uuid.UUID, student_id: uuid.UUID
) -> list[tuple[AssignmentItem, Assignment, Submission]]:
    """布置给这个学生、已经发布的背诵项。"""
    rows = db.execute(
        select(AssignmentItem, Assignment, Submission)
        .join(Assignment, Assignment.id == AssignmentItem.assignment_id)
        .join(Submission, Submission.assignment_id == Assignment.id)
        .where(
            Assignment.tenant_id == tenant_id,
            Submission.student_id == student_id,
            Assignment.publish_at <= now(),
            AssignmentItem.item_type == ItemType.RECITE,
        )
        .order_by(Assignment.publish_at, AssignmentItem.seq)
    ).all()
    return [(i, a, s) for i, a, s in rows]


def submit(db: Session, a: Assignment, sub: Submission) -> bool:
    """提交并自动判分，返回是否有题需要 AI 批改。"""
    _editable(sub)
    sub.status = SubmissionStatus.SUBMITTED
    sub.submitted_at = now()
    need_ai = False
    # 一次查出全部作答，循环里不自动写库：逐题查询、写库在全班同时提交时会明显变慢（压测）
    answers = {x.item_id: x for x in db.scalars(select(Answer).where(Answer.submission_id == sub.id))}
    with db.no_autoflush:
        for item in items_of(db, a.id):
            if item.item_type != ItemType.QUESTION:
                continue
            answer = answers.get(item.id)
            if answer is None:  # 没作答过的题
                answer = Answer(
                    tenant_id=sub.tenant_id, submission_id=sub.id, item_id=item.id, student_id=sub.student_id
                )
                db.add(answer)
            q = item.content
            blank = not (answer.response or "").strip() and not answer.images
            ratio = 0.0 if blank else objective_ratio(q["qtype"], q["answer"], answer.response)
            if ratio is None:  # 解答题、判断不了的填空：AI 批改后老师确认
                answer.status = AnswerStatus.GRADING
                need_ai = True
                continue
            answer.status = AnswerStatus.AUTO
            answer.score = points(ratio, item.score)
            answer.correct = ratio == 1
            record_result(db, a, sub, item, answer)
    refresh_submission(db, sub)
    return need_ai

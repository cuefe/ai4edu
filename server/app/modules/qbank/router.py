import uuid

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.skills.question_gen import QuestionGenIn
from app.core.db import get_db
from app.core.deps import require_roles, tenant_of
from app.modules.iam.models import Role, User
from app.modules.iam.schemas import OkOut
from app.modules.ops.service import audit
from app.modules.qbank import service, tasks
from app.modules.qbank.models import PENDING_REVIEW, Question, QuestionStatus
from app.modules.qbank.schemas import (
    BatchOut,
    QuestionCounts,
    QuestionIn,
    QuestionOut,
    QuestionPage,
    QuestionView,
)
from app.workers import dispatch

router = APIRouter(prefix="/teacher", tags=["题库"])

Teacher = Depends(require_roles(Role.TEACHER))


class BulkReviewIn(BaseModel):
    ids: list[uuid.UUID] = Field(min_length=1, max_length=100)
    approve: bool = True


class BulkReviewOut(BaseModel):
    count: int = Field(description="实际审核的道数（校验中的、别人的题会跳过）")


def _out(db: Session, q: Question, user: User) -> QuestionOut:
    return service.to_outs(db, [q], user.id)[0]


@router.post(
    "/questions/generate",
    response_model=BatchOut,
    summary="AI 出题",
    description="出题和校验在后台进行，用返回的 ID 查询进度",
)
def generate(body: QuestionGenIn, user: User = Teacher, db: Session = Depends(get_db)):
    batch = service.start_batch(db, tenant_of(user), user.id, body)
    db.commit()
    dispatch.submit(tasks.generate_batch, str(batch.id))
    return service.batch_out(db, batch, user.id)


@router.get("/question-batches/{batch_id}", response_model=BatchOut, summary="出题进度和结果")
def get_batch(batch_id: uuid.UUID, user: User = Teacher, db: Session = Depends(get_db)):
    return service.batch_out(db, service.get_batch(db, tenant_of(user), user.id, batch_id), user.id)


@router.get("/questions", response_model=QuestionPage, summary="题目列表")
def list_questions(
    view: QuestionView = Query("bank", description="review 我的待审核 / bank 机构题库 / rejected 我驳回的"),
    subject: str | None = None,
    grade: str | None = None,
    qtype: str | None = None,
    difficulty: str | None = None,
    keyword: str | None = Query(None, max_length=50, description="搜题干和知识点"),
    mine: bool = Query(False, description="题库里只看我出的"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=50),
    user: User = Teacher,
    db: Session = Depends(get_db),
):
    items, total = service.list_questions(
        db,
        tenant_of(user),
        user.id,
        view=view,
        subject=subject,
        grade=grade,
        qtype=qtype,
        difficulty=difficulty,
        keyword=keyword.strip() if keyword else None,
        mine=mine,
        page=page,
        page_size=page_size,
    )
    return QuestionPage(items=items, total=total)


@router.get("/questions/counts", response_model=QuestionCounts, summary="各列表的题目数")
def counts(user: User = Teacher, db: Session = Depends(get_db)):
    return service.counts(db, tenant_of(user), user.id)


@router.post("/questions", response_model=QuestionOut, summary="手动录题（直接入库）")
def create_question(body: QuestionIn, user: User = Teacher, db: Session = Depends(get_db)):
    q = service.create_manual(db, tenant_of(user), user.id, body)
    db.commit()
    return _out(db, q, user)


@router.post("/questions/bulk-review", response_model=BulkReviewOut, summary="批量通过或驳回")
def bulk_review(body: BulkReviewIn, user: User = Teacher, db: Session = Depends(get_db)):
    questions = db.scalars(
        select(Question).where(
            Question.tenant_id == tenant_of(user),
            Question.owner_id == user.id,
            Question.id.in_(body.ids),
            Question.status.in_(PENDING_REVIEW),
            Question.status != QuestionStatus.CHECKING,
        )
    ).all()
    for q in questions:
        service.review(q, user.id, body.approve)
    db.commit()
    return BulkReviewOut(count=len(questions))


@router.get("/questions/{qid}", response_model=QuestionOut)
def get_question(qid: uuid.UUID, user: User = Teacher, db: Session = Depends(get_db)):
    return _out(db, service.get_visible(db, tenant_of(user), user.id, qid), user)


@router.put("/questions/{qid}", response_model=QuestionOut, summary="修改题目")
def update_question(qid: uuid.UUID, body: QuestionIn, user: User = Teacher, db: Session = Depends(get_db)):
    q = service.get_owned(db, tenant_of(user), user.id, qid)
    service.update_question(db, q, body)
    db.commit()
    return _out(db, q, user)


@router.post("/questions/{qid}/approve", response_model=QuestionOut, summary="审核通过，入库")
def approve(qid: uuid.UUID, user: User = Teacher, db: Session = Depends(get_db)):
    q = service.get_owned(db, tenant_of(user), user.id, qid)
    service.review(q, user.id, approve=True)
    db.commit()
    return _out(db, q, user)


@router.post("/questions/{qid}/reject", response_model=QuestionOut, summary="驳回")
def reject(qid: uuid.UUID, user: User = Teacher, db: Session = Depends(get_db)):
    q = service.get_owned(db, tenant_of(user), user.id, qid)
    service.review(q, user.id, approve=False)
    db.commit()
    return _out(db, q, user)


@router.post("/questions/{qid}/recheck", response_model=QuestionOut, summary="重新校验答案")
def recheck(qid: uuid.UUID, user: User = Teacher, db: Session = Depends(get_db)):
    q = service.get_owned(db, tenant_of(user), user.id, qid)
    service.mark_for_recheck(q)
    db.commit()
    dispatch.submit(tasks.check_question, str(q.id))
    return _out(db, q, user)


@router.delete("/questions/{qid}", response_model=OkOut)
def delete_question(qid: uuid.UUID, user: User = Teacher, db: Session = Depends(get_db)):
    q = service.get_owned(db, tenant_of(user), user.id, qid)
    audit(
        db,
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action="delete_question",
        target_type="question",
        target_id=q.id,
        stem=q.stem[:100],
    )
    db.delete(q)
    db.commit()
    return OkOut()

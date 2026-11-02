import uuid

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import require_roles, tenant_of
from app.core.errors import NotFound
from app.modules.assignment import service, student, tasks
from app.modules.assignment.models import Answer, AnswerStatus, AssignmentItem, Submission
from app.modules.assignment.schemas import (
    AnswerOut,
    AssignmentBrief,
    AssignmentIn,
    AssignmentReport,
    ConfirmIn,
    GradingRow,
    ResponseIn,
    StudentAssignment,
    StudentAssignmentBrief,
    SubmissionDetail,
)
from app.modules.iam.models import Role, User
from app.modules.iam.schemas import OkOut
from app.modules.ops.service import audit
from app.workers import dispatch

teacher_router = APIRouter(prefix="/teacher", tags=["作业"])
student_router = APIRouter(prefix="/student/assignments", tags=["学生作业"])

Teacher = Depends(require_roles(Role.TEACHER))
Student = Depends(require_roles(Role.STUDENT))


class CountOut(BaseModel):
    count: int = Field(description="处理了几条")


def _jpeg(data: bytes) -> Response:
    return Response(content=data, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})


# —— 老师端 ——


@teacher_router.get("/assignments", response_model=list[AssignmentBrief], summary="我布置的作业")
def list_assignments(user: User = Teacher, db: Session = Depends(get_db)):
    return service.list_for_teacher(db, tenant_of(user), user.id)


@teacher_router.post("/assignments", response_model=AssignmentBrief, summary="布置作业")
def create_assignment(body: AssignmentIn, user: User = Teacher, db: Session = Depends(get_db)):
    tenant_id = tenant_of(user)
    a = service.create(db, tenant_id, user, body)
    db.commit()
    return service.report(db, tenant_id, a)


@teacher_router.get("/assignments/{aid}", response_model=AssignmentReport, summary="作业报告")
def get_assignment(aid: uuid.UUID, user: User = Teacher, db: Session = Depends(get_db)):
    tenant_id = tenant_of(user)
    return service.report(db, tenant_id, service.get_owned(db, tenant_id, user.id, aid))


@teacher_router.delete("/assignments/{aid}", response_model=OkOut)
def delete_assignment(aid: uuid.UUID, user: User = Teacher, db: Session = Depends(get_db)):
    a = service.get_owned(db, tenant_of(user), user.id, aid)
    audit(
        db,
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action="delete_assignment",
        target_type="assignment",
        target_id=a.id,
        title=a.title,
    )
    db.delete(a)
    db.commit()
    return OkOut()


@teacher_router.post("/assignments/{aid}/remind", response_model=CountOut, summary="一键催交")
def remind(aid: uuid.UUID, user: User = Teacher, db: Session = Depends(get_db)):
    tenant_id = tenant_of(user)
    count = service.remind(db, tenant_id, service.get_owned(db, tenant_id, user.id, aid), user)
    db.commit()
    return CountOut(count=count)


@teacher_router.get("/assignments/{aid}/grading", response_model=list[GradingRow], summary="待确认的批改")
def grading(aid: uuid.UUID, user: User = Teacher, db: Session = Depends(get_db)):
    return service.grading_rows(db, service.get_owned(db, tenant_of(user), user.id, aid))


@teacher_router.post(
    "/assignments/{aid}/confirm-all", response_model=CountOut, summary="AI 已批改的全部按 AI 给分确认"
)
def confirm_all(aid: uuid.UUID, user: User = Teacher, db: Session = Depends(get_db)):
    tenant_id = tenant_of(user)
    a = service.get_owned(db, tenant_id, user.id, aid)
    rows = db.execute(
        select(Answer, Submission, AssignmentItem)
        .join(Submission, Submission.id == Answer.submission_id)
        .join(AssignmentItem, AssignmentItem.id == Answer.item_id)
        .where(
            Submission.assignment_id == a.id,
            Answer.status == AnswerStatus.AI_DONE,
            Answer.ai_score.is_not(None),
        )
    ).all()
    for answer, sub, item in rows:
        service.confirm(db, user, answer, sub, a, item, None, None)
    db.commit()
    return CountOut(count=len(rows))


@teacher_router.get(
    "/assignments/{aid}/submissions/{sid}", response_model=SubmissionDetail, summary="某个学生的作答"
)
def submission_detail(aid: uuid.UUID, sid: uuid.UUID, user: User = Teacher, db: Session = Depends(get_db)):
    tenant_id = tenant_of(user)
    a = service.get_owned(db, tenant_id, user.id, aid)
    row = next((s for s in service.submission_rows(db, tenant_id, a) if s.id == sid), None)
    if row is None:
        raise NotFound("没有这个学生的作答")
    answers = db.scalars(select(Answer).where(Answer.submission_id == sid)).all()
    return SubmissionDetail(submission=row, answers=[service.answer_out(x) for x in answers])


@teacher_router.post("/answers/{answer_id}/confirm", response_model=AnswerOut, summary="确认或修改得分")
def confirm(answer_id: uuid.UUID, body: ConfirmIn, user: User = Teacher, db: Session = Depends(get_db)):
    answer, sub, a, item = service.get_answer_for_teacher(db, tenant_of(user), user.id, answer_id)
    service.confirm(db, user, answer, sub, a, item, body.score, body.comment)
    db.commit()
    return service.answer_out(answer)


@teacher_router.get("/answers/{answer_id}/images/{index}", summary="学生拍照作答的图片")
def teacher_image(answer_id: uuid.UUID, index: int, user: User = Teacher, db: Session = Depends(get_db)):
    answer, *_ = service.get_answer_for_teacher(db, tenant_of(user), user.id, answer_id)
    return _jpeg(student.image_bytes(answer, index))


# —— 学生端 ——


@student_router.get("", response_model=list[StudentAssignmentBrief], summary="我的作业")
def my_assignments(user: User = Student, db: Session = Depends(get_db)):
    return student.list_for_student(db, tenant_of(user), user.id)


@student_router.get("/{aid}", response_model=StudentAssignment)
def my_assignment(aid: uuid.UUID, user: User = Student, db: Session = Depends(get_db)):
    a, sub = student.get(db, tenant_of(user), user.id, aid)
    return student.detail(db, a, sub)


@student_router.put("/{aid}/answers/{item_id}", response_model=AnswerOut, summary="保存作答（自动保存）")
def save_answer(
    aid: uuid.UUID, item_id: uuid.UUID, body: ResponseIn, user: User = Student, db: Session = Depends(get_db)
):
    a, sub = student.get(db, tenant_of(user), user.id, aid)
    answer = student.save_response(db, a, sub, item_id, body.response)
    db.commit()
    return service.answer_out(answer, show_ai=False)


@student_router.post(
    "/{aid}/answers/{item_id}/images", response_model=AnswerOut, summary="拍照作答：上传一张照片"
)
def upload_image(
    aid: uuid.UUID,
    item_id: uuid.UUID,
    file: UploadFile = File(...),
    user: User = Student,
    db: Session = Depends(get_db),
):
    a, sub = student.get(db, tenant_of(user), user.id, aid)
    answer = student.add_image(db, a, sub, item_id, file.file.read(student.MAX_IMAGE_BYTES + 1))
    db.commit()
    return service.answer_out(answer, show_ai=False)


@student_router.delete("/{aid}/answers/{item_id}/images/{index}", response_model=AnswerOut)
def delete_image(
    aid: uuid.UUID, item_id: uuid.UUID, index: int, user: User = Student, db: Session = Depends(get_db)
):
    a, sub = student.get(db, tenant_of(user), user.id, aid)
    answer = student.remove_image(db, a, sub, item_id, index)
    db.commit()
    return service.answer_out(answer, show_ai=False)


@student_router.get("/{aid}/answers/{item_id}/images/{index}", summary="我上传的照片")
def my_image(
    aid: uuid.UUID, item_id: uuid.UUID, index: int, user: User = Student, db: Session = Depends(get_db)
):
    _, sub = student.get(db, tenant_of(user), user.id, aid)
    return _jpeg(student.image_bytes(student.answer_of(db, sub, item_id), index))


@student_router.post("/{aid}/items/{item_id}/done", response_model=OkOut, summary="讲义读完、背诵完成")
def mark_done(aid: uuid.UUID, item_id: uuid.UUID, user: User = Student, db: Session = Depends(get_db)):
    a, sub = student.get(db, tenant_of(user), user.id, aid)
    student.mark_done(db, a, sub, item_id)
    db.commit()
    return OkOut()


@student_router.post("/{aid}/submit", response_model=StudentAssignment, summary="提交作业")
def submit(aid: uuid.UUID, user: User = Student, db: Session = Depends(get_db)):
    a, sub = student.get(db, tenant_of(user), user.id, aid)
    need_ai = student.submit(db, a, sub)
    db.commit()
    if need_ai:
        dispatch.submit(tasks.grade_submission, str(sub.id))
    db.refresh(sub)
    return student.detail(db, a, sub)

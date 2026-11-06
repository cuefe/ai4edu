import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import require_roles, tenant_of
from app.core.routing import DbRoute
from app.modules.assignment import service as assignments
from app.modules.assignment.schemas import GradingRow
from app.modules.iam.models import Role, User
from app.modules.weekly import service
from app.modules.weekly.schemas import (
    ClassWeeklyOut,
    ClassWeekReport,
    IssueResult,
    ProgressIn,
    SectionOut,
    SubjectWeekly,
)

teacher_router = APIRouter(route_class=DbRoute, prefix="/teacher/weekly", tags=["周测"])
student_router = APIRouter(route_class=DbRoute, prefix="/student/weekly", tags=["周测"])

Teacher = Depends(require_roles(Role.TEACHER))
Student = Depends(require_roles(Role.STUDENT))


class CountOut(BaseModel):
    count: int


@teacher_router.get("", response_model=list[ClassWeeklyOut], summary="我任教的班级的周测情况")
def my_classes(user: User = Teacher, db: Session = Depends(get_db)):
    return service.list_for_teacher(db, tenant_of(user), user.id)


@teacher_router.get(
    "/books/{book_id}/sections", response_model=list[SectionOut], summary="一册教材的节和每节可用的题数"
)
def sections(book_id: uuid.UUID, _: User = Teacher, db: Session = Depends(get_db)):
    return service.book_sections(db, book_id)


@teacher_router.put("/classes/{klass_id}/progress", response_model=ClassWeeklyOut, summary="设置这周教到哪里")
def set_progress(klass_id: uuid.UUID, body: ProgressIn, user: User = Teacher, db: Session = Depends(get_db)):
    tenant_id = tenant_of(user)
    row = service.set_progress(db, tenant_id, user.id, klass_id, body)
    db.commit()
    return next(
        c
        for c in service.list_for_teacher(db, tenant_id, user.id)
        if c.klass_id == klass_id and c.subject == row.subject
    )


@teacher_router.post("/classes/{klass_id}/issue", response_model=IssueResult, summary="现在发这周的周测")
def issue(klass_id: uuid.UUID, subject: str = Query(), user: User = Teacher, db: Session = Depends(get_db)):
    progress = service.get_progress(db, tenant_of(user), user.id, klass_id, subject)
    result = service.issue_class(db, progress)
    db.commit()
    return result


@teacher_router.get(
    "/classes/{klass_id}/report", response_model=ClassWeekReport, summary="全班某一周的周测成绩"
)
def report(
    klass_id: uuid.UUID,
    subject: str = Query(),
    week: date | None = Query(default=None, description="这一周的周一；为空表示最近一周"),
    user: User = Teacher,
    db: Session = Depends(get_db),
):
    return service.class_report(db, tenant_of(user), user.id, klass_id, subject, week)


@teacher_router.get(
    "/classes/{klass_id}/grading", response_model=list[GradingRow], summary="全班周测待确认的批改"
)
def grading(klass_id: uuid.UUID, subject: str = Query(), user: User = Teacher, db: Session = Depends(get_db)):
    ids = service.week_assignment_ids(db, tenant_of(user), user.id, klass_id, subject)
    return assignments.grading_rows_of(db, ids)


@teacher_router.post(
    "/classes/{klass_id}/confirm-all", response_model=CountOut, summary="全班周测 AI 已批改的题按 AI 给分确认"
)
def confirm_all(
    klass_id: uuid.UUID, subject: str = Query(), user: User = Teacher, db: Session = Depends(get_db)
):
    ids = service.week_assignment_ids(db, tenant_of(user), user.id, klass_id, subject)
    count = service.confirm_all(db, user, ids)
    db.commit()
    return CountOut(count=count)


@student_router.get("", response_model=list[SubjectWeekly], summary="我的周测：各科成绩、难度和薄弱知识点")
def my_weekly(user: User = Student, db: Session = Depends(get_db)):
    return service.for_student(db, tenant_of(user), user.id)

import uuid

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core import storage
from app.core.db import get_db
from app.core.deps import get_current_user, require_roles
from app.core.errors import NotFound
from app.core.routing import DbRoute
from app.modules.curriculum import pool, service
from app.modules.curriculum.pool import ApproveCheckedIn, PoolPage, PoolQuestionIn, PoolQuestionOut
from app.modules.curriculum.schemas import BookBrief, BookDetail, Catalog, ChapterDetail, StatusIn
from app.modules.iam.models import Role, User
from app.modules.ops.service import audit

router = APIRouter(route_class=DbRoute, prefix="/courses", tags=["课程内容"])

CurrentUser = Depends(get_current_user)


@router.get("", response_model=Catalog, summary="教材目录：学生、老师看已发布的，运营还能看到草稿")
def catalog(user: User = CurrentUser, db: Session = Depends(get_db)):
    return service.catalog(db, user)


@router.get(
    "/chapters/{chapter_id}", response_model=ChapterDetail, summary="一章或一节的知识点、思维导图、课件"
)
def chapter(chapter_id: uuid.UUID, user: User = CurrentUser, db: Session = Depends(get_db)):
    return service.chapter_detail(db, user, chapter_id)


@router.get("/files/{file_id}", summary="课本、课件文件（支持 Range 分段读取）")
def course_file(file_id: uuid.UUID, user: User = CurrentUser, db: Session = Depends(get_db)):
    row = service.get_file(db, user, file_id)
    path = storage.local_path(row.storage_key)
    if not path.is_file():
        raise NotFound("文件不存在")
    return FileResponse(
        path,
        media_type=row.mime,
        filename=row.filename,
        content_disposition_type="inline",
        headers={"Cache-Control": "private, max-age=3600"},
    )


# —— 平台题库（平台运营）——

Admin = Depends(require_roles(Role.PLATFORM_ADMIN))


class CountOut(BaseModel):
    count: int


def _audit_review(db: Session, user: User, action: str, target_id: uuid.UUID, **extra) -> None:
    audit(
        db,
        tenant_id=None,
        actor_id=user.id,
        action=action,
        target_type="pool_question",
        target_id=target_id,
        **extra,
    )


@router.put("/questions/{qid}", response_model=PoolQuestionOut, summary="修改题库里的题")
def update_pool_question(
    qid: uuid.UUID, body: PoolQuestionIn, user: User = Admin, db: Session = Depends(get_db)
):
    out = pool.update_question(db, pool.get_question(db, qid), body)
    _audit_review(db, user, "pool.edit", qid)
    db.commit()
    return out


@router.post("/questions/{qid}/approve", response_model=PoolQuestionOut, summary="审核通过：可以进周测")
def approve_pool_question(qid: uuid.UUID, user: User = Admin, db: Session = Depends(get_db)):
    out = pool.review(db, pool.get_question(db, qid), user.id, approved=True)
    _audit_review(db, user, "pool.approve", qid)
    db.commit()
    return out


@router.post("/questions/{qid}/reject", response_model=PoolQuestionOut, summary="驳回")
def reject_pool_question(qid: uuid.UUID, user: User = Admin, db: Session = Depends(get_db)):
    out = pool.review(db, pool.get_question(db, qid), user.id, approved=False)
    _audit_review(db, user, "pool.reject", qid)
    db.commit()
    return out


@router.get("/{book_id}/questions", response_model=PoolPage, summary="题库审核列表，有分歧的排最前面")
def pool_questions(
    book_id: uuid.UUID,
    status: str | None = Query(default=None, description="pending 待审核 / approved / rejected / 具体状态"),
    section_id: uuid.UUID | None = None,
    limit: int = Query(default=20, ge=1, le=pool.MAX_PAGE),
    offset: int = Query(default=0, ge=0),
    _: User = Admin,
    db: Session = Depends(get_db),
):
    return pool.list_questions(db, book_id, status=status, section_id=section_id, limit=limit, offset=offset)


@router.post(
    "/{book_id}/questions/approve-checked",
    response_model=CountOut,
    summary="把自动校验一致的题一次通过（有分歧的还要逐题看）",
)
def approve_checked(
    book_id: uuid.UUID, body: ApproveCheckedIn, user: User = Admin, db: Session = Depends(get_db)
):
    count = pool.approve_checked(db, book_id, body.section_id, user.id)
    _audit_review(db, user, "pool.approve_checked", book_id, count=count)
    db.commit()
    return CountOut(count=count)


@router.get("/{book_id}", response_model=BookDetail, summary="一册教材的章节目录和文件")
def book(book_id: uuid.UUID, user: User = CurrentUser, db: Session = Depends(get_db)):
    return service.book_detail(db, user, book_id)


@router.put("/{book_id}/status", response_model=BookBrief, summary="发布或下架一册教材（平台运营）")
def set_status(
    book_id: uuid.UUID,
    body: StatusIn,
    user: User = Depends(require_roles(Role.PLATFORM_ADMIN)),
    db: Session = Depends(get_db),
):
    out = service.set_published(db, user, book_id, body.published)
    audit(
        db,
        tenant_id=None,
        actor_id=user.id,
        action="course.publish" if body.published else "course.unpublish",
        target_type="textbook",
        target_id=book_id,
        key=out.key,
    )
    db.commit()
    return out

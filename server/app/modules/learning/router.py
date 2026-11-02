import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.ai.gateway.gateway import CallContext
from app.core.db import get_db
from app.core.deps import require_roles, tenant_of
from app.modules.iam.models import Role, User
from app.modules.iam.schemas import OkOut
from app.modules.learning import review, service
from app.modules.learning.review import RateIn, RateOut, ReviewToday
from app.modules.learning.service import RedoOut, WrongBook, WrongItemOut

router = APIRouter(prefix="/student", tags=["错题本与背诵"])

Student = Depends(require_roles(Role.STUDENT))


class RedoIn(BaseModel):
    response: str


class SelfCheckIn(BaseModel):
    correct: bool


class GuideOut(BaseModel):
    analysis: str  # 题目解析
    knowledge: str  # 考点分析
    steps: list[str]  # 逐步讲解
    summary: str  # 思路总结


@router.get("/wrong-items", response_model=WrongBook, summary="错题本")
def wrong_book(
    status: str | None = None,
    subject: str | None = None,
    knowledge_point: str | None = None,
    user: User = Student,
    db: Session = Depends(get_db),
):
    return service.wrong_book(
        db, tenant_of(user), user.id, status=status, subject=subject, knowledge_point=knowledge_point
    )


@router.get("/wrong-items/{wid}", response_model=WrongItemOut)
def wrong_item(wid: uuid.UUID, user: User = Student, db: Session = Depends(get_db)):
    return service.WrongItemOut.model_validate(
        service.get_wrong(db, tenant_of(user), user.id, wid), from_attributes=True
    )


@router.post("/wrong-items/{wid}/redo", response_model=RedoOut, summary="订正：重做")
def redo(wid: uuid.UUID, body: RedoIn, user: User = Student, db: Session = Depends(get_db)):
    out = service.redo(service.get_wrong(db, tenant_of(user), user.id, wid), body.response)
    db.commit()
    return out


@router.post(
    "/wrong-items/{wid}/self-check", response_model=WrongItemOut, summary="订正：对照答案后自己判断做对没有"
)
def self_check(wid: uuid.UUID, body: SelfCheckIn, user: User = Student, db: Session = Depends(get_db)):
    out = service.self_check(service.get_wrong(db, tenant_of(user), user.id, wid), body.correct)
    db.commit()
    return out


@router.post(
    "/wrong-items/{wid}/guide", response_model=GuideOut, summary="订正：四步引导（AI 生成，生成过的直接返回）"
)
async def guide(wid: uuid.UUID, user: User = Student):
    tenant_id = tenant_of(user)
    return GuideOut(**await service.guide(CallContext(tenant_id=tenant_id, user_id=user.id), tenant_id, wid))


@router.delete("/wrong-items/{wid}", response_model=OkOut, summary="从错题本移除")
def remove(wid: uuid.UUID, user: User = Student, db: Session = Depends(get_db)):
    service.remove(db, service.get_wrong(db, tenant_of(user), user.id, wid))
    db.commit()
    return OkOut()


@router.get("/review/today", response_model=ReviewToday, summary="今日背诵：到期复习的和新学的卡片")
def review_today(item_id: uuid.UUID | None = None, user: User = Student, db: Session = Depends(get_db)):
    return review.today(db, tenant_of(user), user.id, item_id)


@router.post("/review/{item_id}/{card_key}", response_model=RateOut, summary="背完一张卡：自评记忆程度")
def rate(
    item_id: uuid.UUID, card_key: int, body: RateIn, user: User = Student, db: Session = Depends(get_db)
):
    out = review.rate(db, tenant_of(user), user.id, item_id, card_key, body)
    db.commit()
    return out

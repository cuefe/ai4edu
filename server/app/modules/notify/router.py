import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user, tenant_of
from app.modules.iam.models import User
from app.modules.iam.schemas import OkOut
from app.modules.notify import service
from app.modules.notify.service import NotificationList

router = APIRouter(prefix="/me/notifications", tags=["站内信"])


class ReadIn(BaseModel):
    ids: list[uuid.UUID] = Field(default_factory=list, max_length=100, description="为空表示全部已读")


@router.get("", response_model=NotificationList, summary="我的站内信（最近 50 条）")
def list_notifications(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return service.list_for(db, tenant_of(user), user.id)


@router.post("/read", response_model=OkOut, summary="标记已读")
def mark_read(body: ReadIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    service.mark_read(db, tenant_of(user), user.id, body.ids or None)
    db.commit()
    return OkOut()

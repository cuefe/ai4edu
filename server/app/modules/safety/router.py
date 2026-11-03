import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import require_roles
from app.core.routing import DbRoute
from app.modules.iam.models import Role, User
from app.modules.safety import service
from app.modules.safety.service import AlertOut
from app.modules.tutor import service as tutor
from app.modules.tutor.service import MessageOut

router = APIRouter(route_class=DbRoute, prefix="/alerts", tags=["心理预警"])

Staff = Depends(require_roles(Role.TEACHER, Role.ORG_ADMIN))


class HandleIn(BaseModel):
    note: str = Field(min_length=2, max_length=2000, description="处理记录：和学生、家长沟通的情况，后续安排")


@router.get("", response_model=list[AlertOut], summary="心理预警（老师看自己班的，机构管理员看全部）")
def list_alerts(status: str | None = None, user: User = Staff, db: Session = Depends(get_db)):
    return service.list_alerts(db, user, status)


@router.get("/{alert_id}/messages", response_model=list[MessageOut], summary="预警前后的对话，了解情况用")
def alert_messages(alert_id: uuid.UUID, user: User = Staff, db: Session = Depends(get_db)):
    alert = service.get_alert(db, user, alert_id)
    if alert.session_id is None:
        return []
    return [tutor.message_out(m) for m in tutor.messages(db, alert.session_id, 30)]


@router.post("/{alert_id}/handle", response_model=AlertOut, summary="确认处理并填写记录")
def handle(alert_id: uuid.UUID, body: HandleIn, user: User = Staff, db: Session = Depends(get_db)):
    alert = service.get_alert(db, user, alert_id)
    service.handle(alert, user, body.note.strip())
    db.commit()
    return next(a for a in service.list_alerts(db, user) if a.id == alert.id)

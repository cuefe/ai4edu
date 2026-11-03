import json
import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import require_roles, tenant_of
from app.core.routing import DbRoute
from app.modules.assignment import student as assignments
from app.modules.iam.models import Role, User
from app.modules.tutor import service
from app.modules.tutor.service import MessageIn, SessionDetail, SessionIn, SessionOut

router = APIRouter(route_class=DbRoute, prefix="/student/tutor", tags=["问一问"])

Student = Depends(require_roles(Role.STUDENT))

_SSE_DOC = """以 Server-Sent Events 流式返回：
- `notice`：`{"kind": "crisis", "hotlines": [...]}`，学生流露危机信号时先发，前端醒目显示求助电话
- `delta`：`{"text": 回复片段}`
- `done`：`{"id": 回复的消息 ID, "flag": 安全标记}`
- `error`：`{"message": 错误说明}`"""


class ImageOut(BaseModel):
    key: str


class StatusOut(BaseModel):
    blocked_by: str | None = None  # 正在做的、不允许问 AI 的作业标题


@router.get("/status", response_model=StatusOut, summary="现在能不能用问一问")
def status(user: User = Student, db: Session = Depends(get_db)):
    blocked = assignments.ai_blocked(db, tenant_of(user), user.id)
    return StatusOut(blocked_by=blocked.title if blocked else None)


@router.get("/sessions", response_model=list[SessionOut], summary="最近的提问")
def list_sessions(user: User = Student, db: Session = Depends(get_db)):
    return service.list_sessions(db, tenant_of(user), user.id)


@router.post("/sessions", response_model=SessionDetail, summary="开始一次提问（可以关联作业题或错题）")
def create_session(body: SessionIn, user: User = Student, db: Session = Depends(get_db)):
    s = service.create_session(db, tenant_of(user), user.id, body)
    db.commit()
    return service.detail(db, s)


@router.get("/sessions/{sid}", response_model=SessionDetail)
def get_session(sid: uuid.UUID, user: User = Student, db: Session = Depends(get_db)):
    return service.detail(db, service.get_session(db, tenant_of(user), user.id, sid))


@router.post("/images", response_model=ImageOut, summary="拍照提问：先上传图片")
def upload_image(file: UploadFile = File(...), user: User = Student):
    return ImageOut(
        key=service.save_image(tenant_of(user), user.id, file.file.read(assignments.MAX_IMAGE_BYTES + 1))
    )


@router.get("/messages/{mid}/images/{index}", summary="消息里的图片")
def message_image(mid: uuid.UUID, index: int, user: User = Student, db: Session = Depends(get_db)):
    data = service.message_image(db, tenant_of(user), user.id, mid, index)
    return Response(content=data, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})


async def _sse(events: AsyncIterator[tuple[str, dict]]) -> AsyncIterator[str]:
    async for name, data in events:
        yield f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post(
    "/sessions/{sid}/messages",
    summary="发消息",
    description=_SSE_DOC,
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {"schema": {"type": "string"}}}}},
)
async def send(sid: uuid.UUID, body: MessageIn, user: User = Student):
    tenant_id = tenant_of(user)
    events = await service.send(tenant_id, user.id, sid, body)
    return StreamingResponse(
        _sse(events),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

import json
import re
import uuid
from collections.abc import AsyncIterator
from urllib.parse import quote

from fastapi import APIRouter, Depends
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.orm import Session

from app.ai.gateway.gateway import CallContext
from app.ai.skills.lesson_plan import LessonPlanIn
from app.core.db import get_db
from app.core.deps import require_roles, tenant_of
from app.core.errors import AppError
from app.modules.content import generation, service
from app.modules.content.docx_export import doc_to_docx
from app.modules.content.models import DocStatus, DocType
from app.modules.content.schemas import DocumentBrief, DocumentOut, DocumentUpdate
from app.modules.iam.models import Role, User
from app.modules.iam.schemas import OkOut
from app.modules.ops.service import audit

router = APIRouter(prefix="/teacher", tags=["备课"])

Teacher = Depends(require_roles(Role.TEACHER))

_SSE_DOC = """以 Server-Sent Events 流式返回，事件依次为：
- `created`：`{"id": 文档 ID}`，文档已创建（状态为生成中）
- `delta`：`{"text": 新生成的一段 Markdown}`，可能有很多个
- `done`：`{"id": 文档 ID, "warnings": [自动检查发现的问题]}`
- `error`：`{"message": 错误说明}`

老师中途断开连接，生成也会继续并保存。"""


def _sse(name: str, data: dict) -> str:
    return f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _stream(events: AsyncIterator[tuple[str, dict]]) -> AsyncIterator[str]:
    async for name, data in events:
        yield _sse(name, data)


@router.post(
    "/lesson-plans/generate",
    summary="AI 生成教案",
    description=_SSE_DOC,
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {"schema": {"type": "string"}}}}},
)
async def generate_lesson_plan(body: LessonPlanIn, user: User = Teacher, db: Session = Depends(get_db)):
    tenant_id = tenant_of(user)

    def create() -> uuid.UUID:
        doc = service.start_lesson_plan(db, tenant_id, user.id, body)
        db.commit()
        return doc.id

    doc_id = await run_in_threadpool(create)
    events = generation.start_lesson_plan(doc_id, CallContext(tenant_id=tenant_id, user_id=user.id), body)
    return StreamingResponse(
        _stream(events),
        media_type="text/event-stream",
        # 关掉 Nginx 的响应缓冲，否则内容会攒够一批才发出去
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/documents", response_model=list[DocumentBrief], summary="我的文档")
def list_documents(
    doc_type: DocType = DocType.LESSON_PLAN, user: User = Teacher, db: Session = Depends(get_db)
):
    docs = service.list_documents(db, tenant_of(user), user.id, doc_type)
    return [service.to_brief(d) for d in docs]


@router.get("/documents/{doc_id}", response_model=DocumentOut)
def get_document(doc_id: uuid.UUID, user: User = Teacher, db: Session = Depends(get_db)):
    return service.to_out(service.get_document(db, tenant_of(user), user.id, doc_id))


@router.put("/documents/{doc_id}", response_model=DocumentOut, summary="保存文档")
def update_document(
    doc_id: uuid.UUID, body: DocumentUpdate, user: User = Teacher, db: Session = Depends(get_db)
):
    doc = service.get_document(db, tenant_of(user), user.id, doc_id)
    service.update_document(db, doc, body.title, body.content, body.version)
    db.commit()
    return service.to_out(doc)


@router.delete("/documents/{doc_id}", response_model=OkOut)
def delete_document(doc_id: uuid.UUID, user: User = Teacher, db: Session = Depends(get_db)):
    doc = service.get_document(db, tenant_of(user), user.id, doc_id)
    audit(
        db,
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action="delete_document",
        target_type="document",
        target_id=doc.id,
        title=doc.title,
    )
    db.delete(doc)
    db.commit()
    return OkOut()


@router.get("/documents/{doc_id}/docx", summary="导出 Word")
def export_docx(doc_id: uuid.UUID, user: User = Teacher, db: Session = Depends(get_db)):
    doc = service.get_document(db, tenant_of(user), user.id, doc_id)
    if doc.status != DocStatus.READY or doc.content is None:
        raise AppError("文档还没有生成完成，不能导出")
    data = doc_to_docx(doc.title, doc.content, author=user.name)
    audit(
        db,
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action="export_document",
        target_type="document",
        target_id=doc.id,
    )
    db.commit()
    filename = re.sub(r'[\\/:*?"<>|\s]+', "_", doc.title).strip("_")[:80] or "教案"
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename + '.docx')}"},
    )

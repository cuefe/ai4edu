import uuid
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.ai.gateway.gateway import CallContext
from app.core import storage
from app.core.config import get_settings
from app.core.db import get_db
from app.core.deps import require_roles, tenant_of
from app.core.errors import AppError
from app.modules.iam.models import Role, User
from app.modules.iam.schemas import OkOut
from app.modules.library import service, tasks
from app.modules.library.schemas import ChunkOut, ResourceOut, ResourcePatch, SearchHit, SearchIn
from app.modules.ops.service import audit
from app.workers import dispatch

router = APIRouter(prefix="/teacher/resources", tags=["资料库"])

Teacher = Depends(require_roles(Role.TEACHER))


@router.get("", response_model=list[ResourceOut], summary="我的资料（含本机构共享的）")
def list_resources(user: User = Teacher, db: Session = Depends(get_db)):
    return service.list_resources(db, tenant_of(user), user.id)


@router.post("", response_model=ResourceOut, summary="上传资料，上传后自动解析")
def upload(
    file: UploadFile = File(...),
    subject: str | None = Form(default=None, max_length=20),
    shared: bool = Form(default=False),
    user: User = Teacher,
    db: Session = Depends(get_db),
):
    limit = get_settings().max_upload_mb * 1024 * 1024
    data = file.file.read(limit + 1)
    r = service.create_resource(
        db, tenant_of(user), user.id, file.filename or "", data, subject=subject, shared=shared
    )
    db.commit()
    dispatch.submit(tasks.parse_resource, str(r.id))
    return service.to_out(r, user.name, user.id)


@router.post("/search", response_model=list[SearchHit], summary="在资料库里检索")
async def search(body: SearchIn, user: User = Teacher):
    ctx = CallContext(tenant_id=tenant_of(user), user_id=user.id)
    return await service.search(
        ctx, body.query, resource_ids=body.resource_ids or None, subject=body.subject, k=body.k
    )


@router.get("/{rid}", response_model=ResourceOut)
def get_resource(rid: uuid.UUID, user: User = Teacher, db: Session = Depends(get_db)):
    r = service.get_visible(db, tenant_of(user), user.id, rid)
    return service.to_out(r, service.owner_name(db, r), user.id)


@router.patch("/{rid}", response_model=ResourceOut, summary="修改学科、共享设置")
def update_resource(rid: uuid.UUID, body: ResourcePatch, user: User = Teacher, db: Session = Depends(get_db)):
    r = service.get_owned(db, tenant_of(user), user.id, rid)
    if "subject" in body.model_fields_set:
        r.subject = body.subject or None
    if body.shared is not None:
        r.shared = body.shared
    db.commit()
    return service.to_out(r, user.name, user.id)


@router.post("/{rid}/reparse", response_model=ResourceOut, summary="重新解析")
def reparse(rid: uuid.UUID, user: User = Teacher, db: Session = Depends(get_db)):
    r = service.get_owned(db, tenant_of(user), user.id, rid)
    service.mark_for_reparse(r)
    db.commit()
    dispatch.submit(tasks.parse_resource, str(r.id))
    return service.to_out(r, user.name, user.id)


@router.delete("/{rid}", response_model=OkOut)
def delete_resource(rid: uuid.UUID, user: User = Teacher, db: Session = Depends(get_db)):
    r = service.get_owned(db, tenant_of(user), user.id, rid)
    key = r.storage_key
    audit(
        db,
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action="delete_resource",
        target_type="resource",
        target_id=r.id,
        filename=r.filename,
    )
    db.delete(r)
    db.commit()
    storage.delete(key)  # 数据库删除成功后再删文件
    return OkOut()


@router.get("/{rid}/chunks", response_model=list[ChunkOut], summary="解析出的片段")
def list_chunks(rid: uuid.UUID, user: User = Teacher, db: Session = Depends(get_db)):
    return service.list_chunks(db, service.get_visible(db, tenant_of(user), user.id, rid))


@router.get("/{rid}/file", summary="下载原文件")
def download(rid: uuid.UUID, user: User = Teacher, db: Session = Depends(get_db)):
    r = service.get_visible(db, tenant_of(user), user.id, rid)
    try:
        data = storage.get(r.storage_key)
    except FileNotFoundError as exc:
        raise AppError("原文件找不到了", code="file_missing", status=404) from exc
    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(r.filename)}"},
    )

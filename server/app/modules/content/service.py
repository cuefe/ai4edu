import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import ValidationError
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.db import session_scope
from app.core.errors import AppError, NotFound
from app.modules.content.markdown import markdown_to_doc
from app.modules.content.models import DocStatus, Document
from app.modules.content.schemas import DocumentBrief, DocumentOut
from app.modules.content.skills import DOC_SKILLS, DocInput

# 生成中的文档每隔几秒写一次进度；超过这个时间没有进度，说明生成已中断（例如服务重启）
STALE_AFTER = timedelta(minutes=2)
MAX_GENERATING_PER_USER = 2
MAX_CONTENT_BYTES = 2 * 1024 * 1024


def _expire_if_stale(doc: Document) -> None:
    if doc.status == DocStatus.GENERATING and doc.updated_at < datetime.now(UTC) - STALE_AFTER:
        doc.status = DocStatus.FAILED
        doc.error = "生成中断了，请重新生成"


def list_documents(db: Session, tenant_id: uuid.UUID, owner_id: uuid.UUID, doc_type: str) -> list[Document]:
    docs = db.scalars(
        select(Document)
        .where(Document.tenant_id == tenant_id, Document.owner_id == owner_id, Document.doc_type == doc_type)
        .order_by(Document.updated_at.desc())
    ).all()
    for doc in docs:
        _expire_if_stale(doc)
    return list(docs)


def get_document(db: Session, tenant_id: uuid.UUID, owner_id: uuid.UUID, doc_id: uuid.UUID) -> Document:
    """只能访问自己的文档。别人的文档和不存在一样返回 404，不暴露是否存在。"""
    doc = db.scalar(
        select(Document).where(
            Document.id == doc_id, Document.tenant_id == tenant_id, Document.owner_id == owner_id
        )
    )
    if doc is None:
        raise NotFound("文档不存在")
    _expire_if_stale(doc)
    return doc


def get_ready_document(db: Session, tenant_id: uuid.UUID, owner_id: uuid.UUID, doc_id: uuid.UUID) -> Document:
    """取一份已生成好的文档，供其他功能读取正文（如抽背诵点）。正文用 markdown.doc_to_markdown 转。"""
    doc = get_document(db, tenant_id, owner_id, doc_id)
    if doc.status != DocStatus.READY or doc.content is None:
        raise AppError("这份文档还没有生成完成")
    return doc


def to_brief(doc: Document) -> DocumentBrief:
    return DocumentBrief.model_validate(doc, from_attributes=True)


def to_out(doc: Document) -> DocumentOut:
    spec = DOC_SKILLS.get(doc.doc_type)
    try:
        params = spec.input_type.model_validate(doc.params) if spec and doc.params else None
    except ValidationError:  # 参数结构改过，旧文档回填不了表单，不影响查看
        params = None
    return DocumentOut(
        **to_brief(doc).model_dump(),
        params=params,
        content=doc.content,
        generated_md=doc.generated_md if doc.status == DocStatus.GENERATING else None,
        warnings=doc.warnings,
        error=doc.error,
        version=doc.version,
    )


def start_generation(
    db: Session, tenant_id: uuid.UUID, owner_id: uuid.UUID, doc_type: str, p: DocInput
) -> Document:
    """建一份"生成中"的文档。同一个老师同时在生成的文档有上限，防止误点多次。"""
    spec = DOC_SKILLS[doc_type]
    generating = db.scalar(
        select(func.count())
        .select_from(Document)
        .where(
            Document.tenant_id == tenant_id,
            Document.owner_id == owner_id,
            Document.status == DocStatus.GENERATING,
            Document.updated_at >= datetime.now(UTC) - STALE_AFTER,
        )
    )
    if generating >= MAX_GENERATING_PER_USER:
        raise AppError(
            f"已有 {generating} 份文档正在生成，请等生成完再试", code="too_many_generating", status=429
        )
    doc = Document(
        tenant_id=tenant_id,
        owner_id=owner_id,
        doc_type=doc_type,
        title=p.topic,
        subject=p.subject,
        grade=p.grade,
        status=DocStatus.GENERATING,
        # mode="json"：resource_ids 是 UUID，原样存 JSONB 会序列化失败
        params={**p.model_dump(mode="json"), "prompt_version": spec.prompt_version},
    )
    db.add(doc)
    db.flush()
    return doc


def update_document(db: Session, doc: Document, title: str, content: dict[str, Any], version: int) -> None:
    if doc.status == DocStatus.GENERATING:
        raise AppError("文档还在生成中，生成完才能编辑", code="generating", status=409)
    if content.get("type") != "doc":
        raise AppError("文档格式不正确")
    if len(json.dumps(content, ensure_ascii=False).encode()) > MAX_CONTENT_BYTES:
        raise AppError("文档太大了，请删减部分内容")
    result = db.execute(
        update(Document)
        .where(Document.id == doc.id, Document.version == version)
        .values(title=title, content=content, version=version + 1, updated_at=func.now())
    )
    if result.rowcount == 0:
        raise AppError("文档已在别的窗口修改过，请刷新后再编辑", code="version_conflict", status=409)
    db.refresh(doc)


# —— 后台生成任务用：每次单独开会话，和请求的事务无关 ——


def save_draft(tenant_id: uuid.UUID, doc_id: uuid.UUID, md: str) -> None:
    with session_scope(tenant_id=tenant_id) as db:
        db.execute(
            update(Document)
            .where(Document.id == doc_id, Document.status == DocStatus.GENERATING)
            .values(generated_md=md, updated_at=func.now())
        )


def finish_generation(
    tenant_id: uuid.UUID,
    doc_id: uuid.UUID,
    md: str,
    warnings: list[str],
    sources: list[dict[str, Any]] | None = None,
) -> None:
    # 不限定状态：生成慢、已被判定为中断的文档，最后完成了也照样保存
    with session_scope(tenant_id=tenant_id) as db:
        doc = db.get(Document, doc_id)
        if doc is None:  # 生成过程中被删除了
            return
        doc.status = DocStatus.READY
        doc.generated_md = md
        doc.content = markdown_to_doc(md)
        doc.warnings = warnings
        doc.error = None
        if sources:
            doc.params = {**doc.params, "sources": sources}  # 记下引用了哪些片段，方便追溯


def fail_generation(tenant_id: uuid.UUID, doc_id: uuid.UUID, error: str, md: str | None) -> None:
    with session_scope(tenant_id=tenant_id) as db:
        db.execute(
            update(Document)
            .where(Document.id == doc_id, Document.status == DocStatus.GENERATING)
            .values(status=DocStatus.FAILED, error=error[:500], generated_md=md, updated_at=func.now())
        )

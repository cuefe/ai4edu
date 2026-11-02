"""资料库：上传、查看、共享、检索。解析在 tasks.py 里异步进行。

可见范围：自己上传的，加上本机构其他老师共享的。只有上传者能修改、删除、重新解析。
"""

import hashlib
import re
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import anyio
from sqlalchemy import ColumnElement, and_, func, or_, select
from sqlalchemy.orm import Session

from app.ai.gateway.gateway import AIGateway, CallContext, get_gateway
from app.ai.parsing import SUPPORTED_EXTS
from app.core import storage
from app.core.config import get_settings
from app.core.db import session_scope
from app.core.errors import AppError, Forbidden, NotFound
from app.modules.iam.models import User
from app.modules.library.models import Resource, ResourceChunk, ResourceStatus
from app.modules.library.schemas import ChunkOut, ResourceOut, SearchHit

EMBED_SKILL = "embed"
# 解析中的资料每识别一页就更新一次；超过这个时间没进度，说明解析中断了（例如服务重启）
STALE_AFTER = timedelta(minutes=10)
# 相关度门槛，宁缺毋滥。text-embedding-v4 实测（2026-11）：相关片段 0.55～0.85，无关的 0.2～0.35
MIN_SCORE = 0.4
MAX_GAP = 0.15  # 比最相关的片段低太多的不要，避免拿"沾点边"的内容凑数
_ACCEPTED = {*SUPPORTED_EXTS, ".jpeg", ".webp"}


def _visible(tenant_id: uuid.UUID, user_id: uuid.UUID) -> ColumnElement[bool]:
    return and_(Resource.tenant_id == tenant_id, or_(Resource.owner_id == user_id, Resource.shared.is_(True)))


def _expire_if_stale(r: Resource) -> None:
    busy = (ResourceStatus.PENDING, ResourceStatus.PARSING)
    if r.status in busy and r.updated_at < datetime.now(UTC) - STALE_AFTER:
        r.status = ResourceStatus.FAILED
        r.error = "解析中断了，请重新解析"


def list_resources(db: Session, tenant_id: uuid.UUID, user_id: uuid.UUID) -> list[ResourceOut]:
    rows = db.execute(
        select(Resource, User.name)
        .join(User, User.id == Resource.owner_id)
        .where(_visible(tenant_id, user_id))
        .order_by(Resource.created_at.desc())
    ).all()
    for r, _ in rows:
        _expire_if_stale(r)
    return [to_out(r, name, user_id) for r, name in rows]


def get_visible(db: Session, tenant_id: uuid.UUID, user_id: uuid.UUID, rid: uuid.UUID) -> Resource:
    r = db.scalar(select(Resource).where(Resource.id == rid, _visible(tenant_id, user_id)))
    if r is None:
        raise NotFound("资料不存在")
    _expire_if_stale(r)
    return r


def get_owned(db: Session, tenant_id: uuid.UUID, user_id: uuid.UUID, rid: uuid.UUID) -> Resource:
    r = get_visible(db, tenant_id, user_id, rid)
    if r.owner_id != user_id:
        raise Forbidden("这是别的老师共享的资料，只有上传的老师可以修改")
    return r


def to_out(r: Resource, owner_name: str, user_id: uuid.UUID) -> ResourceOut:
    return ResourceOut(
        id=r.id,
        filename=r.filename,
        size=r.size,
        subject=r.subject,
        shared=r.shared,
        status=r.status,
        progress=r.progress,
        error=r.error,
        pages=r.pages,
        ocr_pages=r.ocr_pages,
        chunk_count=r.chunk_count,
        owner_name=owner_name,
        mine=r.owner_id == user_id,
        created_at=r.created_at,
        updated_at=r.updated_at,
    )


def owner_name(db: Session, r: Resource) -> str:
    return db.scalar(select(User.name).where(User.id == r.owner_id)) or ""


def create_resource(
    db: Session,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    filename: str,
    data: bytes,
    *,
    subject: str | None,
    shared: bool,
) -> Resource:
    filename = Path(filename).name.strip()[:255] or "未命名"
    ext = Path(filename).suffix.lower()
    if ext in (".doc", ".ppt"):
        raise AppError(f"暂不支持老版本的 {ext} 文件，请用 Office 或 WPS 另存为 {ext}x 后再上传")
    if ext not in _ACCEPTED:
        raise AppError(f"不支持 {ext or '没有扩展名的'} 文件，支持：{'、'.join(SUPPORTED_EXTS)}")
    if not data:
        raise AppError("文件是空的")
    if len(data) > get_settings().max_upload_mb * 1024 * 1024:
        raise AppError(f"文件不能超过 {get_settings().max_upload_mb}MB")

    sha256 = hashlib.sha256(data).hexdigest()
    existing = db.scalar(
        select(Resource.filename).where(
            Resource.tenant_id == tenant_id, Resource.owner_id == user_id, Resource.sha256 == sha256
        )
    )
    if existing:
        raise AppError(f"这份文件已经上传过了（{existing}）", code="duplicate", status=409)

    key = storage.new_key(tenant_id, filename)
    storage.put(key, data)
    r = Resource(
        tenant_id=tenant_id,
        owner_id=user_id,
        filename=filename,
        size=len(data),
        sha256=sha256,
        storage_key=key,
        subject=subject or None,
        shared=shared,
        status=ResourceStatus.PENDING,
    )
    db.add(r)
    db.flush()
    return r


def mark_for_reparse(r: Resource) -> None:
    if r.status in (ResourceStatus.PENDING, ResourceStatus.PARSING):
        raise AppError("资料正在解析，请等解析完再试", code="parsing", status=409)
    r.status = ResourceStatus.PENDING
    r.progress = 0
    r.error = None


def list_chunks(db: Session, r: Resource) -> list[ChunkOut]:
    chunks = db.scalars(
        select(ResourceChunk).where(ResourceChunk.resource_id == r.id).order_by(ResourceChunk.seq).limit(1000)
    )
    return [
        ChunkOut(seq=c.seq, heading=c.heading, page_start=c.page_start, page_end=c.page_end, text=c.text)
        for c in chunks
    ]


# —— 检索 ——


async def search(
    ctx: CallContext,
    query: str,
    *,
    resource_ids: list[uuid.UUID] | None = None,
    subject: str | None = None,
    k: int = 6,
    gateway: AIGateway | None = None,
) -> list[SearchHit]:
    """在老师可见的资料里找和 query 最相关的片段。没有可检索的资料时不调用向量模型。

    后台任务在自己的事件循环里运行，要传入自己的网关实例（见 gateway.build_gateway）。
    """
    assert ctx.tenant_id is not None and ctx.user_id is not None
    gateway = gateway or get_gateway()
    model = gateway.embed_model(EMBED_SKILL)
    if model is None:
        return []
    filters = _search_filters(ctx.tenant_id, ctx.user_id, model, resource_ids, subject)
    if not await anyio.to_thread.run_sync(_has_chunks, ctx.tenant_id, filters):
        return []
    _, [vector] = await gateway.embed(EMBED_SKILL, [query], ctx=ctx)
    rows = await anyio.to_thread.run_sync(_nearest, ctx.tenant_id, filters, vector, k * 3)

    terms = _bigrams(query)
    min_score = 0 if model.startswith("mock/") else MIN_SCORE  # mock 向量的相似度没有标定，不设门槛
    hits = []
    for chunk, filename, distance in rows:
        score = 1 - float(distance)
        if score < min_score:
            continue
        # 字面重合做一点加分：专有名词、课题名完全对上的片段往前排
        overlap = len(terms & _bigrams(chunk.text)) / len(terms) if terms else 0
        hits.append(
            SearchHit(
                chunk_id=chunk.id,
                resource_id=chunk.resource_id,
                filename=filename,
                heading=chunk.heading,
                page_start=chunk.page_start,
                page_end=chunk.page_end,
                text=chunk.text,
                score=round(min(score + 0.05 * overlap, 1.0), 3),
            )
        )
    hits.sort(key=lambda h: h.score, reverse=True)
    if hits and min_score:
        hits = [h for h in hits if h.score >= hits[0].score - MAX_GAP]
    return hits[:k]


def hit_label(hit: SearchHit) -> str:
    """引用时显示的出处，如：《有理数.pptx》第 3 页。"""
    text = f"《{hit.filename}》"
    if hit.page_start is not None:
        same = hit.page_end in (None, hit.page_start)
        text += f"第 {hit.page_start} 页" if same else f"第 {hit.page_start}～{hit.page_end} 页"
    return text


def _search_filters(
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    model: str,
    resource_ids: list[uuid.UUID] | None,
    subject: str | None,
) -> list[ColumnElement[bool]]:
    filters = [
        _visible(tenant_id, user_id),
        Resource.status == ResourceStatus.READY,
        ResourceChunk.tenant_id == tenant_id,
        ResourceChunk.embedding_model == model,  # 不同向量模型的向量不能比较
    ]
    if resource_ids:
        filters.append(Resource.id.in_(resource_ids))
    if subject:
        filters.append(or_(Resource.subject == subject, Resource.subject.is_(None)))
    return filters


def _has_chunks(tenant_id: uuid.UUID, filters: list[ColumnElement[bool]]) -> bool:
    with session_scope(tenant_id=tenant_id) as db:
        stmt = (
            select(func.count())
            .select_from(ResourceChunk)
            .join(Resource, Resource.id == ResourceChunk.resource_id)
            .where(*filters)
        )
        return bool(db.scalar(stmt))


def _nearest(tenant_id: uuid.UUID, filters: list[ColumnElement[bool]], vector: list[float], limit: int):
    distance = ResourceChunk.embedding.cosine_distance(vector)
    with session_scope(tenant_id=tenant_id) as db:
        rows = db.execute(
            select(ResourceChunk, Resource.filename, distance)
            .join(Resource, Resource.id == ResourceChunk.resource_id)
            .where(*filters)
            .order_by(distance)
            .limit(limit)
        ).all()
        db.expunge_all()
        return [tuple(r) for r in rows]


_NON_WORD = re.compile(r"[\s\W_]+")


def _bigrams(text: str) -> set[str]:
    s = _NON_WORD.sub("", text.lower())
    return {s[i : i + 2] for i in range(len(s) - 1)}

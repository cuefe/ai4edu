"""资料解析任务：取文字（扫描页、图片走 OCR）→ 去页眉页脚 → 切片段 → 向量化 → 入库。"""

import asyncio
import logging
import uuid

from sqlalchemy import delete

from app.ai.gateway.gateway import AIGateway, CallContext, build_gateway
from app.ai.parsing import ParseError, drop_repeated_lines, make_chunks, parse_file
from app.ai.parsing.ocr import ocr_image
from app.core import storage
from app.core.db import session_scope
from app.core.errors import AppError
from app.modules.library.models import Resource, ResourceChunk, ResourceStatus
from app.modules.library.service import EMBED_SKILL
from app.workers.celery_app import celery_app

log = logging.getLogger(__name__)

OCR_CONCURRENCY = 4
OCR_SHARE = 90  # 进度条里 OCR 占的百分比，剩下的是向量化


@celery_app.task(name="library.parse_resource")
def parse_resource(resource_id: str) -> None:
    asyncio.run(run_parse(uuid.UUID(resource_id), build_gateway()))


def _update(tenant_id: uuid.UUID, resource_id: uuid.UUID, **values) -> None:
    with session_scope(tenant_id=tenant_id) as db:
        r = db.get(Resource, resource_id)
        if r is not None:
            for name, value in values.items():
                setattr(r, name, value)


async def run_parse(resource_id: uuid.UUID, gateway: AIGateway) -> None:
    with session_scope(bypass=True) as db:
        r = db.get(Resource, resource_id)
        if r is None:  # 解析开始前已被删除
            return
        tenant_id, owner_id, key, filename = r.tenant_id, r.owner_id, r.storage_key, r.filename
        r.status, r.progress, r.error = ResourceStatus.PARSING, 0, None

    ctx = CallContext(tenant_id=tenant_id, user_id=owner_id)
    try:
        parsed = parse_file(filename, storage.get(key))
        pending = parsed.ocr_blocks
        failed = 0
        done = 0
        sem = asyncio.Semaphore(OCR_CONCURRENCY)

        async def recognize(block) -> None:
            nonlocal done, failed
            async with sem:
                try:
                    block.text = await ocr_image(gateway, block.image, ctx)
                except AppError:  # 单页识别失败不影响其他页
                    failed += 1
                block.image = None
                done += 1
                _update(tenant_id, resource_id, progress=OCR_SHARE * done // len(pending))

        await asyncio.gather(*(recognize(b) for b in pending))
        if pending and failed == len(pending):
            raise ParseError("文字识别失败，请稍后重新解析")

        drop_repeated_lines(parsed)
        chunks = make_chunks(parsed)
        if not chunks:
            raise ParseError("没有识别到文字内容。如果是图片或扫描件，请确认内容清晰")
        model, vectors = await gateway.embed(EMBED_SKILL, [c.embedding_text() for c in chunks], ctx=ctx)

        with session_scope(tenant_id=tenant_id) as db:
            r = db.get(Resource, resource_id)
            if r is None:
                return
            db.execute(delete(ResourceChunk).where(ResourceChunk.resource_id == resource_id))
            db.add_all(
                ResourceChunk(
                    tenant_id=tenant_id,
                    resource_id=resource_id,
                    seq=i,
                    heading=c.heading[:500],
                    page_start=c.page_start,
                    page_end=c.page_end,
                    text=c.text,
                    embedding=v,
                    embedding_model=model,
                )
                for i, (c, v) in enumerate(zip(chunks, vectors, strict=True))
            )
            r.status = ResourceStatus.READY
            r.progress = 100
            r.pages = sum(1 for p in parsed.pages if p.number is not None)  # Word、纯文本没有页的概念，记 0
            r.ocr_pages = len(pending)
            r.chunk_count = len(chunks)
            r.embedding_model = model
            r.error = f"有 {failed} 页（张）图片没能识别出文字" if failed else None
    except (ParseError, AppError) as exc:
        message = exc.message if isinstance(exc, AppError) else str(exc)
        _update(tenant_id, resource_id, status=ResourceStatus.FAILED, error=message[:500])
    except Exception:
        log.exception("资料解析失败：%s", resource_id)
        _update(tenant_id, resource_id, status=ResourceStatus.FAILED, error="解析失败，请稍后重新解析")

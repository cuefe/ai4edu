"""教案、讲义的流式生成。

生成在后台 asyncio 任务里跑，和 HTTP 连接解耦：老师中途关掉页面，生成照样完成并保存。
进度每隔几秒写一次库，重新打开文档能看到已生成的部分。
服务重启会中断正在进行的生成，这类文档超过 service.STALE_AFTER 没有进度就显示为失败。
TODO：并发量上来后改成 Celery 任务，进度通过 Redis 推给 SSE 连接。
"""

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

import anyio

from app.ai.gateway.gateway import CallContext, get_gateway
from app.ai.skills.common import Source, cited_numbers, sources_markdown
from app.core.errors import AppError
from app.modules.content import service
from app.modules.content.skills import DOC_SKILLS, DocInput
from app.modules.library import service as library
from app.modules.library.schemas import SearchHit

log = logging.getLogger(__name__)

Event = tuple[str, dict[str, Any]]

FLUSH_SECONDS = 2.0
MAX_SOURCES = 6  # 最多参考几个资料片段：太多会冲淡重点，也更费 token
_tasks: set[asyncio.Task[None]] = set()  # 保持引用，避免任务被垃圾回收


def start(doc_type: str, doc_id: uuid.UUID, ctx: CallContext, p: DocInput) -> AsyncIterator[Event]:
    """启动生成，返回事件流：created →（sources）→ delta…… → done 或 error。必须在事件循环里调用。"""
    queue: asyncio.Queue[Event] = asyncio.Queue()
    task = asyncio.create_task(_run(doc_type, doc_id, ctx, p, queue))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return _events(doc_id, queue)


async def _events(doc_id: uuid.UUID, queue: asyncio.Queue[Event]) -> AsyncIterator[Event]:
    yield "created", {"id": str(doc_id)}
    while True:
        name, data = await queue.get()
        yield name, data
        if name in ("done", "error"):
            return


async def _retrieve(ctx: CallContext, p: DocInput) -> tuple[list[SearchHit], list[str]]:
    """按课题从资料库检索参考片段。检索失败不影响生成，只提示老师。"""
    if not (p.use_library or p.resource_ids):
        return [], []
    query = f"{p.topic} {p.requirements or ''}".strip()
    try:
        hits = await library.search(
            ctx, query, resource_ids=p.resource_ids or None, subject=p.subject, k=MAX_SOURCES
        )
    except AppError:
        log.exception("资料库检索失败")
        return [], ["资料库检索失败，这次没有参考资料库"]
    return hits, []


async def _run(
    doc_type: str, doc_id: uuid.UUID, ctx: CallContext, p: DocInput, queue: asyncio.Queue[Event]
) -> None:
    assert ctx.tenant_id is not None
    tenant_id = ctx.tenant_id
    spec = DOC_SKILLS[doc_type]
    parts = [spec.header(p)]
    queue.put_nowait(("delta", {"text": parts[0]}))
    last_flush = time.monotonic()
    try:
        hits, warnings = await _retrieve(ctx, p)
        sources = [Source(label=library.hit_label(h), text=h.text) for h in hits]
        items = [
            {"n": i, "resource_id": str(h.resource_id), "chunk_id": str(h.chunk_id), "label": s.label}
            for i, (h, s) in enumerate(zip(hits, sources, strict=True), start=1)
        ]
        if items:
            queue.put_nowait(("sources", {"items": items}))

        stream = get_gateway().stream(
            spec.skill, spec.messages(p, sources), ctx=ctx, temperature=0.7, max_tokens=8000
        )
        async for delta in stream:
            parts.append(delta)
            queue.put_nowait(("delta", {"text": delta}))
            if time.monotonic() - last_flush >= FLUSH_SECONDS:
                await anyio.to_thread.run_sync(service.save_draft, tenant_id, doc_id, "".join(parts))
                last_flush = time.monotonic()
        cited = cited_numbers("".join(parts), len(sources))
        tail = sources_markdown(sources, cited)
        if tail:
            parts.append(tail)
            queue.put_nowait(("delta", {"text": tail}))
        md = "".join(parts)
        warnings += spec.check(md, p, len(sources))
        for item in items:
            item["cited"] = item["n"] in cited
        await anyio.to_thread.run_sync(service.finish_generation, tenant_id, doc_id, md, warnings, items)
        queue.put_nowait(("done", {"id": str(doc_id), "warnings": warnings}))
    except Exception as exc:
        message = exc.message if isinstance(exc, AppError) else "生成失败，请稍后重试"
        log.exception("%s生成失败：doc=%s", spec.label, doc_id)
        try:
            await anyio.to_thread.run_sync(
                service.fail_generation, tenant_id, doc_id, message, "".join(parts)
            )
        finally:
            queue.put_nowait(("error", {"message": message}))

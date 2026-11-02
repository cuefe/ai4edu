"""教案的流式生成。

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
from app.ai.skills import lesson_plan
from app.core.errors import AppError
from app.modules.content import service
from app.modules.library import service as library
from app.modules.library.schemas import SearchHit

log = logging.getLogger(__name__)

Event = tuple[str, dict[str, Any]]

FLUSH_SECONDS = 2.0
MAX_SOURCES = 6  # 最多参考几个资料片段：太多会冲淡重点，也更费 token
_tasks: set[asyncio.Task[None]] = set()  # 保持引用，避免任务被垃圾回收


def start_lesson_plan(
    doc_id: uuid.UUID, ctx: CallContext, p: lesson_plan.LessonPlanIn
) -> AsyncIterator[Event]:
    """启动生成，返回事件流：created →（sources）→ delta…… → done 或 error。必须在事件循环里调用。"""
    queue: asyncio.Queue[Event] = asyncio.Queue()
    task = asyncio.create_task(_run(doc_id, ctx, p, queue))
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


async def _retrieve(ctx: CallContext, p: lesson_plan.LessonPlanIn) -> tuple[list[SearchHit], list[str]]:
    """从资料库检索参考片段。检索失败不影响生成，只提示老师。"""
    if not (p.use_library or p.resource_ids):
        return [], []
    query = f"{p.topic} {p.requirements or ''}".strip()
    try:
        hits = await library.search(
            ctx, query, resource_ids=p.resource_ids or None, subject=p.subject, k=MAX_SOURCES
        )
    except AppError:
        log.exception("教案生成时资料库检索失败")
        return [], ["资料库检索失败，这份教案没有参考资料库"]
    return hits, []


def _label(hit: SearchHit) -> str:
    label = f"《{hit.filename}》"
    if hit.page_start is not None:
        same = hit.page_end in (None, hit.page_start)
        label += f"第 {hit.page_start} 页" if same else f"第 {hit.page_start}～{hit.page_end} 页"
    return label


async def _run(doc_id: uuid.UUID, ctx: CallContext, p: lesson_plan.LessonPlanIn, queue: asyncio.Queue[Event]):
    assert ctx.tenant_id is not None
    tenant_id = ctx.tenant_id
    parts = [lesson_plan.header_markdown(p)]
    queue.put_nowait(("delta", {"text": parts[0]}))
    last_flush = time.monotonic()
    try:
        hits, warnings = await _retrieve(ctx, p)
        sources = [lesson_plan.Source(label=_label(h), text=h.text) for h in hits]
        items = [
            {"n": i, "resource_id": str(h.resource_id), "chunk_id": str(h.chunk_id), "label": s.label}
            for i, (h, s) in enumerate(zip(hits, sources, strict=True), start=1)
        ]
        if items:
            queue.put_nowait(("sources", {"items": items}))

        stream = get_gateway().stream(
            lesson_plan.SKILL,
            lesson_plan.build_messages(p, sources),
            ctx=ctx,
            temperature=0.7,
            max_tokens=8000,
        )
        async for delta in stream:
            parts.append(delta)
            queue.put_nowait(("delta", {"text": delta}))
            if time.monotonic() - last_flush >= FLUSH_SECONDS:
                await anyio.to_thread.run_sync(service.save_draft, tenant_id, doc_id, "".join(parts))
                last_flush = time.monotonic()
        cited = lesson_plan.cited_numbers("".join(parts), len(sources))
        tail = lesson_plan.sources_markdown(sources, cited)
        if tail:
            parts.append(tail)
            queue.put_nowait(("delta", {"text": tail}))
        md = "".join(parts)
        warnings += lesson_plan.check_output(md, p, len(sources))
        for item in items:
            item["cited"] = item["n"] in cited
        await anyio.to_thread.run_sync(service.finish_generation, tenant_id, doc_id, md, warnings, items)
        queue.put_nowait(("done", {"id": str(doc_id), "warnings": warnings}))
    except Exception as exc:
        message = exc.message if isinstance(exc, AppError) else "生成失败，请稍后重试"
        log.exception("教案生成失败：doc=%s", doc_id)
        try:
            await anyio.to_thread.run_sync(
                service.fail_generation, tenant_id, doc_id, message, "".join(parts)
            )
        finally:
            queue.put_nowait(("error", {"message": message}))

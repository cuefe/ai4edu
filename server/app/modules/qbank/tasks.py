"""出题任务：检索资料库 → 出题 → 检查格式 → 逐题校验答案（并发）→ 等老师审核。"""

import asyncio
import logging
import re
import uuid

from app.ai.gateway.gateway import AIGateway, CallContext, build_gateway
from app.ai.skills import answer_check, question_gen
from app.ai.skills.common import Source, parse_json
from app.core.db import session_scope
from app.core.errors import AppError
from app.modules.library import service as library
from app.modules.qbank.models import BatchStatus, Question, QuestionBatch, QuestionCheck, QuestionStatus
from app.workers.celery_app import celery_app

log = logging.getLogger(__name__)

CHECK_CONCURRENCY = 3
GEN_SHARE = 30  # 进度条里出题占的百分比，剩下的是校验
MAX_SOURCES = 4
_STATUS = {"agree": QuestionStatus.CHECKED, "disagree": QuestionStatus.DISPUTED}


@celery_app.task(name="qbank.generate_batch")
def generate_batch(batch_id: str) -> None:
    asyncio.run(run_batch(uuid.UUID(batch_id), build_gateway()))


@celery_app.task(name="qbank.check_question")
def check_question(question_id: str) -> None:
    asyncio.run(run_check(uuid.UUID(question_id), build_gateway()))


def _update_batch(tenant_id: uuid.UUID, batch_id: uuid.UUID, **values) -> None:
    with session_scope(tenant_id=tenant_id) as db:
        batch = db.get(QuestionBatch, batch_id)
        if batch is not None:
            for name, value in values.items():
                setattr(batch, name, value)


async def _sources(
    gateway: AIGateway, ctx: CallContext, p: question_gen.QuestionGenIn
) -> tuple[list[Source], list[dict], list[str]]:
    if not (p.use_library or p.resource_ids):
        return [], [], []
    query = f"{p.topic} {p.requirements or ''}".strip()
    try:
        hits = await library.search(
            ctx, query, resource_ids=p.resource_ids or None, subject=p.subject, k=MAX_SOURCES, gateway=gateway
        )
    except AppError:
        log.exception("出题时资料库检索失败")
        return [], [], ["资料库检索失败，这批题没有参考资料库"]
    sources = [Source(label=library.hit_label(h), text=h.text) for h in hits]
    meta = [
        {"label": s.label, "resource_id": str(h.resource_id), "chunk_id": str(h.chunk_id)}
        for h, s in zip(hits, sources, strict=True)
    ]
    return sources, meta, []


async def run_batch(batch_id: uuid.UUID, gateway: AIGateway) -> None:
    with session_scope(bypass=True) as db:
        batch = db.get(QuestionBatch, batch_id)
        if batch is None:
            return
        tenant_id, owner_id, params = batch.tenant_id, batch.owner_id, dict(batch.params)
        batch.status, batch.progress = BatchStatus.GENERATING, 5

    ctx = CallContext(tenant_id=tenant_id, user_id=owner_id)
    try:
        p = question_gen.QuestionGenIn.model_validate(params)
        sources, meta, warnings = await _sources(gateway, ctx, p)
        result = await gateway.chat(
            question_gen.SKILL,
            question_gen.build_messages(p, sources),
            ctx=ctx,
            temperature=0.8,
            max_tokens=8000,
            response_format={"type": "json_object"},
        )
        raw, incomplete = question_gen.parse_questions(parse_json(result.text), p.qtype)
        reasons = ["内容不完整"] * incomplete  # 丢掉的题和原因，告诉老师为什么少了
        accepted: list[tuple[question_gen.QuestionData, list[str]]] = []
        seen: set[str] = set()
        for q in raw:
            fixed, problem, notes = question_gen.normalize(q)
            key = re.sub(r"\s+", "", fixed.stem)
            if problem or key in seen:
                reasons.append(problem or "和前面的题重复")
                continue
            seen.add(key)
            accepted.append((fixed, notes))
        accepted = accepted[: p.count]
        if not accepted:
            raise AppError("AI 出的题格式都不对，请重新出题")
        if reasons:
            warnings.append(f"去掉了 {len(reasons)} 道有问题的题：{'；'.join(dict.fromkeys(reasons))}")
        if len(accepted) < p.count:
            warnings.append(f"要求出 {p.count} 道，实际出了 {len(accepted)} 道")

        model = f"{result.provider}/{result.model}"
        with session_scope(tenant_id=tenant_id) as db:
            batch = db.get(QuestionBatch, batch_id)
            if batch is None:  # 出题过程中被删了
                return
            batch.status, batch.progress = BatchStatus.CHECKING, GEN_SHARE
            batch.warnings, batch.sources = warnings, meta
            questions = [
                Question(
                    tenant_id=tenant_id,
                    owner_id=owner_id,
                    batch_id=batch_id,
                    seq=i,
                    subject=p.subject,
                    grade=p.grade,
                    difficulty=p.difficulty,
                    **q.model_dump(),
                    source="ai",
                    status=QuestionStatus.CHECKING,
                    generated={
                        **q.model_dump(),
                        "model": model,
                        "prompt_version": question_gen.PROMPT_VERSION,
                    },
                    warnings=notes,
                )
                for i, (q, notes) in enumerate(accepted)
            ]
            db.add_all(questions)
            db.flush()
            ids = [q.id for q in questions]

        done = 0
        sem = asyncio.Semaphore(CHECK_CONCURRENCY)

        async def check_one(qid: uuid.UUID, q: question_gen.QuestionData) -> None:
            nonlocal done
            async with sem:
                await _check_and_save(gateway, ctx, tenant_id, qid, q, p.subject)
            done += 1
            _update_batch(tenant_id, batch_id, progress=GEN_SHARE + (100 - GEN_SHARE) * done // len(ids))

        await asyncio.gather(*(check_one(qid, q) for qid, (q, _) in zip(ids, accepted, strict=True)))
        _update_batch(tenant_id, batch_id, status=BatchStatus.DONE, progress=100)
    except AppError as exc:
        _update_batch(tenant_id, batch_id, status=BatchStatus.FAILED, error=exc.message[:500])
    except Exception:
        log.exception("出题失败：%s", batch_id)
        _update_batch(tenant_id, batch_id, status=BatchStatus.FAILED, error="出题失败，请稍后重试")


async def run_check(question_id: uuid.UUID, gateway: AIGateway) -> None:
    """老师改题后重新校验。"""
    with session_scope(bypass=True) as db:
        q = db.get(Question, question_id)
        if q is None or q.status != QuestionStatus.CHECKING:
            return
        tenant_id, owner_id, subject = q.tenant_id, q.owner_id, q.subject
        data = question_gen.QuestionData(
            qtype=q.qtype,  # type: ignore[arg-type]
            stem=q.stem,
            options=q.options,
            answer=q.answer,
            analysis=q.analysis,
            knowledge_points=q.knowledge_points,
        )
    ctx = CallContext(tenant_id=tenant_id, user_id=owner_id)
    try:
        await _check_and_save(gateway, ctx, tenant_id, question_id, data, subject)
    except Exception:
        log.exception("校验失败：%s", question_id)
        with session_scope(tenant_id=tenant_id) as db:
            q = db.get(Question, question_id)
            if q is not None and q.status == QuestionStatus.CHECKING:
                q.status = QuestionStatus.UNCHECKED


async def _check_and_save(
    gateway: AIGateway,
    ctx: CallContext,
    tenant_id: uuid.UUID,
    question_id: uuid.UUID,
    q: question_gen.QuestionData,
    subject: str,
) -> None:
    result = await answer_check.check(gateway, q, subject, ctx)
    with session_scope(tenant_id=tenant_id) as db:
        question = db.get(Question, question_id)
        if question is None or question.status != QuestionStatus.CHECKING:  # 校验期间被删除或已审核
            return
        db.add(
            QuestionCheck(
                tenant_id=tenant_id,
                question_id=question_id,
                verdict=result.verdict,
                method=result.method,
                solver_model=result.solver_model,
                solver_answer=result.solver_answer,
                solver_work=result.solver_work,
                reason=result.reason,
            )
        )
        question.status = _STATUS.get(result.verdict, QuestionStatus.UNCHECKED)

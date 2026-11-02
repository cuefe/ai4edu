"""主观题 AI 批改：一份作业提交后，把要批改的题并发交给批改技能，结果等老师确认。"""

import asyncio
import logging
import uuid

from sqlalchemy import select

from app.ai.gateway.gateway import AIGateway, CallContext, build_gateway
from app.ai.skills import grade_subjective
from app.ai.skills.common import parse_json
from app.core import storage
from app.core.db import session_scope
from app.core.errors import AppError
from app.modules.assignment.models import Answer, AnswerStatus, Assignment, AssignmentItem, Submission
from app.modules.assignment.service import refresh_submission
from app.workers.celery_app import celery_app

log = logging.getLogger(__name__)

GRADE_CONCURRENCY = 3


@celery_app.task(name="assignment.grade_submission")
def grade_submission(submission_id: str) -> None:
    asyncio.run(run_grading(uuid.UUID(submission_id), build_gateway()))


async def run_grading(submission_id: uuid.UUID, gateway: AIGateway) -> None:
    with session_scope(bypass=True) as db:
        row = db.execute(
            select(Submission, Assignment.subject)
            .join(Assignment, Assignment.id == Submission.assignment_id)
            .where(Submission.id == submission_id)
        ).first()
        if row is None:
            return
        sub, subject = row
        tenant_id, student_id = sub.tenant_id, sub.student_id
        jobs = [
            (answer.id, dict(item.content), item.score, answer.response, list(answer.images))
            for answer, item in db.execute(
                select(Answer, AssignmentItem)
                .join(AssignmentItem, AssignmentItem.id == Answer.item_id)
                .where(Answer.submission_id == submission_id, Answer.status == AnswerStatus.GRADING)
            ).all()
        ]
    ctx = CallContext(tenant_id=tenant_id, user_id=student_id)
    sem = asyncio.Semaphore(GRADE_CONCURRENCY)

    async def grade(
        answer_id: uuid.UUID, question: dict, full: float, response: str, keys: list[str]
    ) -> None:
        async with sem:
            result = None
            try:
                images = [storage.get(k) for k in keys]
                reply = await gateway.chat(
                    grade_subjective.SKILL,
                    grade_subjective.build_messages(subject, question, full, response, images),
                    ctx=ctx,
                    temperature=0,
                    max_tokens=1500,
                )
                result = grade_subjective.parse_result(parse_json(reply.text), full)
            except (AppError, FileNotFoundError):
                log.warning("AI 批改失败：answer=%s", answer_id)
            except Exception:
                log.exception("AI 批改出错：answer=%s", answer_id)
        with session_scope(tenant_id=tenant_id) as db:
            answer = db.get(Answer, answer_id)
            if answer is None or answer.status != AnswerStatus.GRADING:
                return
            answer.status = AnswerStatus.AI_DONE
            if result is None:
                answer.ai_confidence = 0
                answer.ai_comment = "AI 没能批改这道题，请老师打分"
            else:
                answer.ai_score, answer.ai_confidence = result.score, result.confidence
                answer.ai_points, answer.ai_comment = result.points, result.comment

    await asyncio.gather(*(grade(*job) for job in jobs))
    with session_scope(tenant_id=tenant_id) as db:
        sub = db.get(Submission, submission_id)
        if sub is not None:
            refresh_submission(db, sub)

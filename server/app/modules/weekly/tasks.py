"""周测的定时任务：周四傍晚提醒老师更新进度，周五下午给所有开启周测的班级发卷。

时间在 celery_app 的 beat_schedule 里。一个班出错不影响其他班：每个班单独一个事务，
已经发过的学生会跳过，任务重跑是安全的。
"""

import logging
import uuid
from datetime import date

from sqlalchemy import select

from app.core.db import session_scope
from app.core.errors import AppError
from app.modules.notify.service import notify
from app.modules.org import service as org
from app.modules.weekly import service
from app.modules.weekly.models import ClassProgress
from app.workers.celery_app import celery_app

log = logging.getLogger(__name__)


def _enabled() -> list[tuple[uuid.UUID, uuid.UUID]]:
    with session_scope(bypass=True) as db:
        rows = db.execute(
            select(ClassProgress.id, ClassProgress.tenant_id).where(ClassProgress.enabled.is_(True))
        ).all()
    return [(pid, tenant_id) for pid, tenant_id in rows]


def issue_all(week: date | None = None) -> dict[str, int]:
    """给所有开启周测的班级发卷。"""
    classes = papers = failed = 0
    for pid, tenant_id in _enabled():
        try:
            with session_scope(tenant_id=tenant_id) as db:
                progress = db.get(ClassProgress, pid)
                if progress is None:
                    continue
                link = "/teacher/weekly"
                names = org.class_names(db, tenant_id, [progress.klass_id])
                label = f"{names.get(progress.klass_id, '')}{progress.subject}周测"
                try:
                    result = service.issue_class(db, progress, week=week)
                except AppError as exc:  # 题库不够这类老师能处理的问题，告诉老师，不算系统错误
                    notify(
                        db,
                        tenant_id,
                        [progress.teacher_id],
                        kind="weekly",
                        title=f"{label}这周没有发出",
                        body=str(exc.message),
                        link=link,
                    )
                    failed += 1
                    continue
                classes += 1
                papers += result.created
                if result.created or result.short:
                    notify(
                        db,
                        tenant_id,
                        [progress.teacher_id],
                        kind="weekly",
                        title=f"{label}已发出",
                        body=service.issue_summary(result),
                        link=link,
                    )
        except Exception:
            failed += 1
            log.exception("发周测失败：progress=%s", pid)
    return {"classes": classes, "papers": papers, "failed": failed}


def remind_all() -> int:
    """这周还没更新进度的老师，提醒一下明天要发卷。"""
    sent = 0
    week = service.week_of()
    for pid, tenant_id in _enabled():
        with session_scope(tenant_id=tenant_id) as db:
            progress = db.get(ClassProgress, pid)
            if progress is None or progress.week_start == week:
                continue
            names = org.class_names(db, tenant_id, [progress.klass_id])
            sent += notify(
                db,
                tenant_id,
                [progress.teacher_id],
                kind="weekly",
                title=f"{names.get(progress.klass_id, '')}{progress.subject}的教学进度这周还没更新",
                body="周五下午会发周测。不更新的话，按上次设置的节出题。",
                link="/teacher/weekly",
            )
    return sent


@celery_app.task(name="weekly.issue_all")
def issue_all_task() -> dict[str, int]:
    return issue_all()


@celery_app.task(name="weekly.remind_progress")
def remind_progress_task() -> int:
    return remind_all()

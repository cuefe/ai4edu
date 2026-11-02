"""投递后台任务。

配了 Redis 时进 Celery 队列，由 Worker 执行；本地开发（REDIS_URL=memory://）没有 Worker，
任务放在后台线程里跑，免得像 Celery 同步模式那样卡住请求（解析一份扫描件要几分钟）。
"""

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from celery import Task

from app.workers.celery_app import celery_app

log = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="bg-task")


def submit(task: Task, *args: Any) -> None:
    if celery_app.conf.task_always_eager:
        _executor.submit(_run, task, args)
    else:
        task.delay(*args)


def _run(task: Task, args: tuple[Any, ...]) -> None:
    try:
        task.apply(args=args)
    except Exception:
        log.exception("后台任务失败：%s", task.name)

"""异步任务：资料解析、整篇生成、批改、定时推送都放在这里跑。

启动 Worker：uv run celery -A app.workers.celery_app worker --pool=solo -l info
（Windows 只支持 solo / threads 池；Linux 生产环境用默认的 prefork）

REDIS_URL=memory:// 时任务在当前进程里同步执行，本地开发不需要启动 Worker。
"""

from celery import Celery

import app.models  # noqa: F401  Worker 进程不经过 app.main，要在这里注册全部表
from app.core.config import get_settings

settings = get_settings()
_eager = settings.redis_url.startswith("memory://")

celery_app = Celery(
    "ai4edu",
    broker="memory://" if _eager else settings.redis_url,
    backend="cache+memory://" if _eager else settings.redis_url,
    include=[
        "app.workers.tasks",
        "app.modules.library.tasks",
        "app.modules.qbank.tasks",
        "app.modules.assignment.tasks",
    ],
)
celery_app.conf.update(
    task_always_eager=_eager,
    task_eager_propagates=True,
    timezone="Asia/Shanghai",
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    beat_schedule={},  # 定时任务（复习推送、周报）后续在这里登记
)

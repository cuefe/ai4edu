import subprocess
import sys

from sqlalchemy import func, select

from app.ai.models import AiUsage
from app.core.config import SERVER_DIR
from app.core.db import open_session
from app.workers.tasks import ping


def _run_fresh(code: str) -> None:
    """在新进程里执行：测试进程早已通过 app.main 导入了全部模型，查不出漏导入的问题。

    新进程继承 conftest 设置的环境变量，连的是同一个测试数据库。
    """
    result = subprocess.run([sys.executable, "-c", code], cwd=SERVER_DIR, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "写入 AI 用量失败" not in result.stderr, result.stderr


def test_ping_task_runs_eagerly_in_dev():
    assert ping.delay().get(timeout=5) == "pong"


def test_usage_is_recorded_outside_api_process():
    """脚本、Worker 不导入 app.main，也要能写 ai_usage（外键指向 tenant、user_account）。"""
    _run_fresh(
        "from app.ai.gateway.config import MOCK\n"
        "from app.ai.gateway.gateway import CallContext, DbUsageSink, UsageRecord\n"
        "DbUsageSink._write(UsageRecord(CallContext(), 'ping', MOCK))\n"
    )
    with open_session(bypass=True) as db:
        assert db.scalar(select(func.count()).select_from(AiUsage)) == 1


def test_worker_registers_all_tables():
    _run_fresh(
        "import app.workers.celery_app\n"
        "from app.core.db import Base\n"
        "assert {'tenant', 'user_account', 'ai_usage'} <= set(Base.metadata.tables)\n"
    )

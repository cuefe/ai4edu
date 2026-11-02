"""测试用独立的临时 PostgreSQL（pgserver 自带二进制，Windows / Linux / macOS 都能跑）。

注意：环境变量必须在导入 app 之前设置。
"""

import os
import socket
import tempfile
from pathlib import Path


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


PORT = _free_port()
DB = "ai4edu_test"
APP_ROLE = "ai4edu_app"
STORAGE = tempfile.TemporaryDirectory(prefix="ai4edu-files-", ignore_cleanup_errors=True)
os.environ.update(
    ENV="test",
    DATABASE_URL=f"postgresql+psycopg://postgres@127.0.0.1:{PORT}/{DB}",
    APP_DATABASE_URL=f"postgresql+psycopg://{APP_ROLE}@127.0.0.1:{PORT}/{DB}",
    APP_DB_ROLE=APP_ROLE,
    REDIS_URL="memory://",
    AI_ALLOW_MOCK="true",
    STORAGE_DIR=STORAGE.name,
)
# 确保真实的模型 Key 不会被测试用到
for key in ("DEEPSEEK_API_KEY", "DASHSCOPE_API_KEY"):
    os.environ.pop(key, None)

import psycopg  # noqa: E402
import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core.config import SERVER_DIR, get_settings  # noqa: E402
from app.core.db import reset_engine, session_scope  # noqa: E402
from app.core.redis import get_redis  # noqa: E402
from app.devtools.localpg import LocalPostgres  # noqa: E402
from app.modules.iam import service as iam  # noqa: E402
from app.modules.iam.models import Role, Tenant  # noqa: E402

TABLES = ", ".join(
    [
        "review_log",
        "review_state",
        "wrong_item",
        "answer",
        "submission",
        "assignment_item",
        "assignment",
        "chat_message",
        "chat_session",
        "crisis_alert",
        "moderation_log",
        "notification",
        "question_check",
        "question",
        "question_batch",
        "recite_card",
        "recite_deck",
        "resource_chunk",
        "resource_file",
        "document",
        "ai_usage",
        "audit_log",
        "class_member",
        "klass",
        "campus",
        "user_account",
        "tenant",
    ]
)


@pytest.fixture(scope="session", autouse=True)
def database():
    get_settings.cache_clear()
    reset_engine()
    tmp = tempfile.TemporaryDirectory(prefix="ai4edu-pg-", ignore_cleanup_errors=True)
    pg = LocalPostgres(Path(tmp.name), PORT)
    pg.start()
    try:
        pg.setup_database(DB, APP_ROLE)
        command.upgrade(Config(str(SERVER_DIR / "alembic.ini")), "head")
        yield pg
    finally:
        reset_engine()
        pg.stop()
        tmp.cleanup()


@pytest.fixture(autouse=True)
def clean(database):
    yield
    with psycopg.connect(database.owner_url(DB), autocommit=True) as conn:
        conn.execute(f"TRUNCATE {TABLES} CASCADE")
    get_redis().flushall()


@pytest.fixture
def client():
    from app.main import app

    return TestClient(app)


@pytest.fixture
def owner_conn(database):
    with psycopg.connect(database.owner_url(DB), autocommit=True) as conn:
        yield conn


def make_tenant(code: str, admin_phone: str, *, password: str = "admin123") -> Tenant:
    with session_scope(bypass=True) as db:
        tenant = Tenant(code=code, name=f"{code} 学校", kind="school")
        db.add(tenant)
        db.flush()
        iam.create_user(
            db,
            tenant_id=tenant.id,
            name=f"{code} 管理员",
            roles=[Role.ORG_ADMIN, Role.TEACHER],
            phone=admin_phone,
            password=password,
        )
        return tenant


def make_platform_admin(phone: str = "13900000000", password: str = "admin123") -> None:
    with session_scope(bypass=True) as db:
        iam.create_user(
            db, tenant_id=None, name="运营", roles=[Role.PLATFORM_ADMIN], phone=phone, password=password
        )


def auth(client: TestClient, phone: str, password: str = "admin123") -> dict[str, str]:
    resp = client.post("/api/auth/login/phone", json={"phone": phone, "password": password})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def student_auth(client: TestClient, code: str, username: str, password: str) -> dict[str, str]:
    resp = client.post(
        "/api/auth/login/student", json={"tenant_code": code, "username": username, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}

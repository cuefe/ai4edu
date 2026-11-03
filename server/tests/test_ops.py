"""M3：套餐与额度、运营后台、登录审计、短信开关。"""

import io
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import anyio
import pytest
from openpyxl import Workbook
from sqlalchemy import select

from app.ai.gateway.gateway import CallContext, build_gateway
from app.ai.models import AiUsage
from app.core.config import Settings, get_settings
from app.core.db import open_session, session_scope
from app.core.errors import AppError
from app.core.redis import get_redis
from app.core.security import phone_hash
from app.main import _check_prod_settings
from app.modules.ops import quota
from app.modules.ops.models import AuditLog
from app.modules.safety.models import CrisisAlert, ModerationLog
from tests.conftest import auth, make_platform_admin, make_tenant, student_auth
from tests.school import make_school


@pytest.fixture
def ops(client):
    make_platform_admin()
    return auth(client, "13900000000")


def _tenant_body(code: str, phone: str, **terms) -> dict:
    return {
        "code": code,
        "name": f"{code} 学校",
        "kind": "school",
        "admin_name": "校长",
        "admin_phone": phone,
        "admin_password": "admin123",
        **terms,
    }


def _spend(tenant_id: uuid.UUID, yuan: str, *, skill: str = "tutor", when: datetime | None = None) -> None:
    with session_scope(bypass=True) as db:
        usage = AiUsage(
            tenant_id=tenant_id,
            skill=skill,
            provider="dashscope",
            model="qwen-flash",
            cost_yuan=Decimal(yuan),
        )
        if when:
            usage.created_at = when
        db.add(usage)


# —— 套餐和机构 ——


def test_plans_and_tenant_terms(client, ops):
    plan = client.post(
        "/api/ops/plans",
        headers=ops,
        json={
            "name": "标准版",
            "student_quota": 300,
            "teacher_quota": 30,
            "ai_budget_yuan": "500",
            "months": 12,
        },
    ).json()
    assert plan["tenant_count"] == 0
    dup = client.post("/api/ops/plans", headers=ops, json={"name": "标准版"})
    assert dup.status_code == 409

    expires = (datetime.now(UTC) + timedelta(days=365)).isoformat()
    body = _tenant_body(
        "yz", "13700000000", plan_id=plan["id"], expires_at=expires, student_quota=300, ai_budget_yuan="500"
    )
    tenant = client.post("/api/ops/tenants", headers=ops, json=body).json()
    assert tenant["plan_name"] == "标准版"
    assert tenant["student_quota"] == 300 and tenant["teacher_quota"] is None
    assert tenant["teachers"] == 1 and tenant["ai_spend_yuan"] == "0"

    _spend(uuid.UUID(tenant["id"]), "12.5")
    _spend(uuid.UUID(tenant["id"]), "100", when=datetime.now(UTC) - timedelta(days=40))  # 上个月的不算
    patched = client.patch(
        f"/api/ops/tenants/{tenant['id']}",
        headers=ops,
        json={"student_quota": None, "teacher_quota": 5, "note": "合同 2026-01"},
    ).json()
    assert patched["student_quota"] is None and patched["teacher_quota"] == 5
    assert patched["ai_budget_yuan"] == "500.00"  # 没传的不改
    assert Decimal(patched["ai_spend_yuan"]) == Decimal("12.5")

    assert client.get("/api/ops/plans", headers=ops).json()[0]["tenant_count"] == 1
    audit = client.get("/api/ops/audit", headers=ops, params={"action": "update_tenant"}).json()
    assert audit["total"] == 1
    assert audit["items"][0]["detail"] == {"student_quota": None, "teacher_quota": 5, "note": "合同 2026-01"}
    assert audit["items"][0]["actor_name"] == "运营"


def test_disabled_or_expired_tenant_cannot_login(client, ops):
    tenant = client.post("/api/ops/tenants", headers=ops, json=_tenant_body("t1", "13700000000")).json()
    first = client.post("/api/auth/login/phone", json={"phone": "13700000000", "password": "admin123"}).json()

    past = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    client.patch(f"/api/ops/tenants/{tenant['id']}", headers=ops, json={"expires_at": past})
    resp = client.post("/api/auth/login/phone", json={"phone": "13700000000", "password": "admin123"})
    assert resp.status_code == 403 and resp.json()["code"] == "tenant_expired"
    # 已登录的设备也不能续期
    assert client.post("/api/auth/refresh", json={"refresh_token": first["refresh_token"]}).status_code == 403

    client.patch(f"/api/ops/tenants/{tenant['id']}", headers=ops, json={"expires_at": None, "active": False})
    resp = client.post("/api/auth/login/phone", json={"phone": "13700000000", "password": "admin123"})
    assert resp.json()["code"] == "tenant_disabled"
    client.patch(f"/api/ops/tenants/{tenant['id']}", headers=ops, json={"active": True})
    assert auth(client, "13700000000")


# —— 名额 ——


def test_student_seats(client, ops):
    tenant = client.post(
        "/api/ops/tenants", headers=ops, json=_tenant_body("t1", "13700000000", student_quota=2)
    ).json()
    admin = auth(client, "13700000000")
    ids = []
    for i in (1, 2):
        out = client.post("/api/org/students", headers=admin, json={"name": f"学生{i}", "username": f"s{i}"})
        ids.append(out.json()["user"]["id"])
    full = client.post("/api/org/students", headers=admin, json={"name": "学生3", "username": "s3"})
    assert full.status_code == 409 and full.json()["code"] == "seat_quota"

    # 导入：名额用完后停止，前面的行照常导入
    client.patch(f"/api/ops/tenants/{tenant['id']}", headers=ops, json={"student_quota": 3})
    wb = Workbook()
    ws = wb.active
    ws.append(["姓名", "学号"])
    for i in (4, 5, 6):
        ws.append([f"学生{i}", f"s{i}"])
    buf = io.BytesIO()
    wb.save(buf)
    files = {"file": ("students.xlsx", buf.getvalue())}
    result = client.post("/api/org/students/import", headers=admin, files=files).json()
    assert result["created"] == 1
    assert len(result["errors"]) == 1 and "名额已用完" in result["errors"][0]["message"]

    # 停用的账号不占名额；再启用要有空名额
    stopped = client.patch(f"/api/org/users/{ids[0]}", headers=admin, json={"active": False}).json()
    assert stopped["active"] is False
    assert (
        client.post("/api/org/students", headers=admin, json={"name": "学生7", "username": "s7"}).status_code
        == 200
    )
    again = client.patch(f"/api/org/users/{ids[0]}", headers=admin, json={"active": True})
    assert again.status_code == 409

    overview = client.get("/api/org/overview", headers=admin).json()
    assert overview["students"] == {"used": 3, "quota": 3}
    assert overview["teachers"] == {"used": 1, "quota": None}


def test_disable_user_logs_out_and_blocks_login(client):
    school = make_school(client, n_students=1)
    [s1] = school.students
    resp = client.patch(
        f"/api/org/users/{school.student_ids[0]}", headers=school.teacher, json={"active": False}
    )
    assert resp.status_code == 200
    assert client.get("/api/me", headers=s1).status_code == 401
    login = client.post(
        "/api/auth/login/student", json={"tenant_code": "a", "username": "s1", "password": "s12345"}
    )
    assert login.status_code == 403
    # 不能停用自己，也不能停用机构管理员
    assert (
        client.patch(
            f"/api/org/users/{school.teacher_id}", headers=school.teacher, json={"active": False}
        ).status_code
        == 400
    )
    with session_scope(bypass=True) as db:
        actions = db.scalars(select(AuditLog.action).where(AuditLog.action == "disable_user")).all()
    assert actions == ["disable_user"]


# —— AI 额度 ——


def test_ai_budget_blocks_calls_except_safety(client, ops):
    school = make_school(client, n_students=1)
    tid = school.tenant_id
    client.patch(f"/api/ops/tenants/{tid}", headers=ops, json={"ai_budget_yuan": "10"})
    _spend(tid, "9.99")
    quota.ensure_ai_budget(tid)  # 还没用完

    _spend(tid, "0.02")
    quota.forget_ai_budget(tid)
    with pytest.raises(AppError) as err:
        quota.ensure_ai_budget(tid)
    assert err.value.status == 429

    gateway = build_gateway()

    async def call(skill: str):
        return await gateway.chat(skill, [{"role": "user", "content": "hi"}], ctx=CallContext(tenant_id=tid))

    with pytest.raises(AppError):
        anyio.run(call, "tutor")
    # 危机识别不受额度限制
    assert anyio.run(call, "safety_classify").text.startswith("[mock:safety_classify]")

    # 接口在开始前就拒绝
    session = client.post("/api/student/tutor/sessions", headers=school.students[0], json={}).json()
    resp = client.post(
        f"/api/student/tutor/sessions/{session['id']}/messages",
        headers=school.students[0],
        json={"text": "1+1"},
    )
    assert resp.status_code == 429 and resp.json()["code"] == "ai_budget_exhausted"
    gen = client.post(
        "/api/teacher/questions/generate",
        headers=school.teacher,
        json={"subject": "数学", "grade": "七年级上册", "topic": "有理数", "count": 1},
    )
    assert gen.status_code == 429

    # 运营提高额度后马上生效
    client.patch(f"/api/ops/tenants/{tid}", headers=ops, json={"ai_budget_yuan": "100"})
    quota.ensure_ai_budget(tid)


def test_teacher_daily_ai_limit(client, monkeypatch):
    school = make_school(client, n_students=0)
    monkeypatch.setattr(get_settings(), "teacher_daily_ai_tasks", 1)
    quota.start_teacher_task(school.tenant_id, school.teacher_id)
    with pytest.raises(AppError) as err:
        quota.start_teacher_task(school.tenant_id, school.teacher_id)
    assert err.value.code == "daily_limit"


# —— 用量、内容安全、审计 ——


def test_usage_summary_and_overview(client, ops):
    school = make_school(client, n_students=0)
    _spend(school.tenant_id, "1.5", skill="lesson_plan")
    _spend(school.tenant_id, "0.5", skill="tutor")
    summary = client.get("/api/ops/usage/summary", headers=ops).json()
    assert summary["total"]["calls"] == 2 and Decimal(summary["total"]["cost_yuan"]) == Decimal("2")
    assert summary["by_tenant"][0]["tenant_name"] == "a 学校"
    assert len(summary["daily"]) == 1

    overview = client.get("/api/org/overview", headers=school.teacher).json()
    assert Decimal(overview["ai_spend_yuan"]) == Decimal("2")
    assert {s["skill"] for s in overview["ai_by_skill"]} == {"lesson_plan", "tutor"}


def test_moderation_and_alert_summary(client, ops):
    school = make_school(client, n_students=1)
    with session_scope(bypass=True) as db:
        db.add_all(
            [
                ModerationLog(
                    tenant_id=school.tenant_id,
                    source="tutor_input",
                    category="chat",
                    crisis="none",
                    excerpt="打游戏",
                ),
                ModerationLog(
                    tenant_id=school.tenant_id,
                    source="tutor_input",
                    category="study",
                    crisis="high",
                    excerpt="……",
                ),
                CrisisAlert(
                    tenant_id=school.tenant_id,
                    student_id=school.student_ids[0],
                    level="high",
                    excerpt="……",
                    created_at=datetime.now(UTC) - timedelta(hours=3),
                ),
            ]
        )
    page = client.get("/api/ops/moderation", headers=ops).json()
    assert page["total"] == 2 and page["items"][0]["tenant_name"] == "a 学校"
    crisis = client.get("/api/ops/moderation", headers=ops, params={"crisis_only": True}).json()
    assert [r["crisis"] for r in crisis["items"]] == ["high"]

    [row] = client.get("/api/ops/alerts/summary", headers=ops).json()
    assert (row["open"], row["overdue"], row["handled"], row["high"]) == (1, 1, 0, 1)
    assert client.get("/api/ops/moderation", headers=school.teacher).status_code == 403


def test_login_audit(client):
    make_tenant("t1", "13811110000")
    client.post("/api/auth/login/phone", json={"phone": "13811110000", "password": "bad"})
    client.post("/api/auth/login/phone", json={"phone": "13811110000", "password": "admin123"})
    client.post("/api/auth/login/phone", json={"phone": "13899999999", "password": "bad"})  # 不存在的号码不记
    with open_session(bypass=True) as db:
        rows = db.execute(select(AuditLog.action, AuditLog.detail).order_by(AuditLog.created_at)).all()
    assert [a for a, _ in rows] == ["login_failed", "login"]
    assert rows[1][1]["method"] == "password" and rows[1][1]["ip"] == "testclient"


# —— 短信开关、生产配置检查 ——


def test_sms_disabled(client, monkeypatch):
    make_tenant("t1", "13811110000")
    assert client.get("/api/auth/methods").json() == {"sms": True}
    monkeypatch.setattr(get_settings(), "sms_provider", "none")
    assert client.get("/api/auth/methods").json() == {"sms": False}
    resp = client.post("/api/auth/sms/send", json={"phone": "13811110000"})
    assert resp.status_code == 400 and resp.json()["code"] == "sms_disabled"
    # 没有短信时老师只能用密码登录，建账号必须设初始密码
    admin = auth(client, "13811110000")
    teacher = {"name": "张老师", "phone": "13811112222"}
    resp = client.post("/api/org/teachers", headers=admin, json=teacher)
    assert resp.json()["code"] == "password_required"
    assert (
        client.post("/api/org/teachers", headers=admin, json={**teacher, "password": "abc123"}).status_code
        == 200
    )


def test_sms_daily_limit(client, monkeypatch):
    make_tenant("t1", "13811110000")
    monkeypatch.setattr(get_settings(), "sms_daily_limit", 2)
    codes = []
    for _ in range(3):
        codes.append(client.post("/api/auth/sms/send", json={"phone": "13811110000"}).status_code)
        get_redis().delete(f"sms:cooldown:{phone_hash('13811110000')}")  # 跳过 60 秒的重发间隔
    assert codes == [200, 200, 429]


def test_prod_settings_check():
    good = {
        "env": "prod",
        "jwt_secret": "x" * 40,
        "data_encryption_key": "a" * 44,
        "phone_hash_key": "y" * 20,
        "redis_url": "redis://redis:6379/0",
        "sms_provider": "none",
        "cors_origins": ["https://example.com"],
    }
    _check_prod_settings(Settings(**good))
    for bad in ({"sms_provider": "console"}, {"redis_url": "memory://"}, {"cors_origins": ["*"]}):
        with pytest.raises(RuntimeError):
            _check_prod_settings(Settings(**{**good, **bad}))


def test_student_login_audit_method(client):
    school = make_school(client, n_students=1)
    student_auth(client, "a", "s1", "s12345")
    with open_session(bypass=True) as db:
        methods = db.scalars(
            select(AuditLog.detail["method"].astext).where(
                AuditLog.action == "login", AuditLog.actor_id == school.student_ids[0]
            )
        ).all()
    assert methods and set(methods) == {"student"}

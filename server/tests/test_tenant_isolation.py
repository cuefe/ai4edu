"""跨机构隔离：接口层和数据库行级安全两层都要挡住。"""

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import ProgrammingError

from app.core.db import open_session
from app.modules.iam.models import User
from app.modules.org.models import Klass
from tests.conftest import auth, make_tenant


def test_api_cannot_reach_other_tenant(client):
    make_tenant("a", "13811110001")
    make_tenant("b", "13811110002")
    admin_a, admin_b = auth(client, "13811110001"), auth(client, "13811110002")

    klass_b = client.post("/api/org/classes", headers=admin_b, json={"name": "B 班"}).json()
    student_b = client.post(
        "/api/org/students", headers=admin_b, json={"name": "乙", "username": "s1"}
    ).json()

    assert client.get("/api/org/classes", headers=admin_a).json() == []
    assert client.get(f"/api/org/classes/{klass_b['id']}/members", headers=admin_a).status_code == 404
    assert (
        client.post(f"/api/org/users/{student_b['user']['id']}/reset-password", headers=admin_a).status_code
        == 404
    )
    # 同名学号在不同机构可以共存
    assert (
        client.post("/api/org/students", headers=admin_a, json={"name": "甲", "username": "s1"}).status_code
        == 200
    )


def test_rls_filters_rows_without_app_filters():
    a = make_tenant("a", "13811110001")
    b = make_tenant("b", "13811110002")

    # 不带任何 where 条件，数据库也只返回当前机构的行
    with open_session(tenant_id=a.id) as db:
        assert {u.tenant_id for u in db.scalars(select(User))} == {a.id}
    with open_session(tenant_id=b.id) as db:
        assert {u.tenant_id for u in db.scalars(select(User))} == {b.id}
    # 没有设置机构上下文：什么都看不到
    with open_session() as db:
        assert db.scalars(select(User)).all() == []
    # 跨机构模式：都能看到
    with open_session(bypass=True) as db:
        assert {u.tenant_id for u in db.scalars(select(User))} == {a.id, b.id}


def test_rls_blocks_writes_into_other_tenant():
    a = make_tenant("a", "13811110001")
    b = make_tenant("b", "13811110002")
    with open_session(tenant_id=a.id) as db:
        db.add(Klass(tenant_id=b.id, name="越权写入"))
        with pytest.raises(ProgrammingError, match="row-level security"):
            db.flush()


def test_context_survives_commit():
    """提交后开启的新事务要重新带上机构上下文。"""
    a = make_tenant("a", "13811110001")
    with open_session(tenant_id=a.id) as db:
        db.add(Klass(tenant_id=a.id, name="一班"))
        db.commit()
        assert db.scalar(text("select current_setting('app.tenant_id', true)")) == str(a.id)
        assert [k.name for k in db.scalars(select(Klass))] == ["一班"]


def test_app_role_is_not_superuser(owner_conn):
    row = owner_conn.execute(
        "select rolsuper, rolbypassrls from pg_roles where rolname = 'ai4edu_app'"
    ).fetchone()
    assert row == (False, False)
    tables = owner_conn.execute(
        "select relname from pg_class "
        "where relrowsecurity and relforcerowsecurity and relkind = 'r' order by 1"
    ).fetchall()
    assert [t[0] for t in tables] == [
        "ai_usage",
        "audit_log",
        "campus",
        "class_member",
        "document",
        "klass",
        "question",
        "question_batch",
        "question_check",
        "recite_card",
        "recite_deck",
        "resource_chunk",
        "resource_file",
        "user_account",
    ]

import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.db import open_session, session_scope
from app.core.errors import AppError
from app.modules.ops.models import AuditLog
from app.modules.qbank import tasks
from app.modules.qbank.models import QuestionBatch
from app.workers import dispatch
from tests.conftest import auth, make_tenant
from tests.fake_ai import FakeChat

GEN = {"subject": "数学", "grade": "七年级上册", "topic": "有理数的加法", "qtype": "单选题", "count": 4}


def choice(stem: str, answer: str, options=("1", "2", "3", "4")) -> dict:
    return {
        "stem": stem,
        "options": list(options),
        "answer": answer,
        "analysis": "略",
        "knowledge_points": ["有理数的加法"],
    }


QUESTIONS = [
    choice("$(-3)+5$ 等于", "B", ["-8", "2", "8", "-2"]),
    choice("$(-2)+(-3)$ 等于", "C", ["5", "1", "-5", "-1"]),
    choice("坏题", "E"),  # 答案不是选项字母：丢掉
    choice("$(-3)+5$ 等于", "B", ["-8", "2", "8", "-2"]),  # 重复：丢掉
]
# 独立求解的结果：第一题一致，第二题不一致
SOLVED = {"$(-3)+5$": "【答案】B", "$(-2)+(-3)$": "计算得 -5……【答案】A"}


def make_handler(questions=QUESTIONS, solved=SOLVED, judge=None):
    def handler(skill, messages):
        user = messages[-1]["content"]
        if skill == "question_gen":
            return json.dumps({"questions": questions}, ensure_ascii=False)
        if skill == "answer_check":
            for key, reply in solved.items():
                if key in user:
                    return reply
            return "不会做"
        if skill == "answer_judge":
            return (
                judge(user)
                if judge
                else json.dumps({"consistent": False, "reason": "参考答案选错了，应为 C"})
            )
        raise AssertionError(skill)

    return handler


@pytest.fixture
def ai(monkeypatch):
    """后台任务同步执行，网关换成假的。返回一个可以替换 handler 的 FakeChat。"""
    fake = FakeChat(make_handler())
    monkeypatch.setattr(tasks, "build_gateway", lambda: fake)
    monkeypatch.setattr(dispatch, "submit", lambda task, *args: task.apply(args=args))
    return fake


def _teacher(client, admin, phone="13811110010"):
    resp = client.post(
        "/api/org/teachers", headers=admin, json={"name": "同事", "phone": phone, "password": "t12345"}
    )
    assert resp.status_code == 200, resp.text
    return auth(client, phone, "t12345")


def _generate(client, headers, body=GEN) -> dict:
    resp = client.post("/api/teacher/questions/generate", headers=headers, json=body)
    assert resp.status_code == 200, resp.text
    return client.get(f"/api/teacher/question-batches/{resp.json()['id']}", headers=headers).json()


def _view(client, headers, view, **query):
    resp = client.get("/api/teacher/questions", headers=headers, params={"view": view, **query})
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_generate_check_and_review(client, ai):
    make_tenant("a", "13811110001")
    teacher = auth(client, "13811110001")
    colleague = _teacher(client, teacher)

    batch = _generate(client, teacher)
    assert (batch["status"], batch["progress"]) == ("done", 100)
    assert batch["warnings"] == [
        "去掉了 2 道有问题的题：答案要写选项字母（A～D）；和前面的题重复",
        "要求出 4 道，实际出了 2 道",
    ]
    assert batch["params"]["topic"] == "有理数的加法"
    first, second = batch["questions"]
    assert (first["status"], first["check"]["verdict"], first["check"]["method"]) == (
        "checked",
        "agree",
        "rule",
    )
    assert (second["status"], second["check"]["solver_answer"]) == ("disputed", "A")
    assert second["check"]["reason"] == "参考答案选错了，应为 C"
    assert first["options"] == ["-8", "2", "8", "-2"] and first["source"] == "ai"

    # 校验时看不到答案和解析
    solve_calls = [c for c in ai.calls if c["skill"] == "answer_check"]
    assert len(solve_calls) == 2
    assert all("略" not in c["messages"][-1]["content"] for c in solve_calls)
    assert "A. -8" in solve_calls[0]["messages"][-1]["content"]

    # 待审核：有分歧的排最前；同事看不到
    review = _view(client, teacher, "review")
    assert [q["id"] for q in review["items"]] == [second["id"], first["id"]]
    assert _view(client, colleague, "review")["total"] == 0
    assert client.get(f"/api/teacher/questions/{first['id']}", headers=colleague).status_code == 404

    approved = client.post(f"/api/teacher/questions/{first['id']}/approve", headers=teacher).json()
    assert approved["status"] == "approved"
    rejected = client.post(f"/api/teacher/questions/{second['id']}/reject", headers=teacher).json()
    assert rejected["status"] == "rejected"
    counts = client.get("/api/teacher/questions/counts", headers=teacher).json()
    assert counts == {"review": 0, "bank": 1, "rejected": 1}

    # 入库的题本机构老师都能看到，但只有出题的老师能改
    bank = _view(client, colleague, "bank")
    assert [(q["id"], q["mine"], q["owner_name"]) for q in bank["items"]] == [
        (first["id"], False, "a 管理员")
    ]
    assert _view(client, colleague, "bank", mine=True)["total"] == 0
    fields = ("qtype", "stem", "options", "answer", "analysis", "knowledge_points", "subject", "grade")
    edit = {k: first[k] for k in fields}
    assert (
        client.put(f"/api/teacher/questions/{first['id']}", headers=colleague, json=edit).status_code == 403
    )
    assert client.delete(f"/api/teacher/questions/{first['id']}", headers=colleague).status_code == 403

    same = client.put(f"/api/teacher/questions/{first['id']}", headers=teacher, json=edit).json()
    assert same["edited"] is False  # 内容没变不算改过
    changed = client.put(
        f"/api/teacher/questions/{first['id']}", headers=teacher, json={**edit, "analysis": "老师改的解析"}
    ).json()
    assert changed["edited"] is True and changed["status"] == "approved"


def test_fill_blank_numeric_and_model_judge(client, ai):
    questions = [
        {"stem": "$\\frac{1}{4}+\\frac{1}{4}$ = ＿＿＿＿", "answer": "$\\frac{1}{2}$"},
        {"stem": "3 和 -3 的关系：＿＿＿＿", "answer": "互为相反数"},
        {"stem": "难题：＿＿＿＿", "answer": "7"},
    ]
    solved = {
        "frac{1}{4}": "【答案】0.5",
        "3 和 -3": "【答案】相反数",
        "难题": AppError("x", code="ai_unavailable"),
    }
    ai.handler = make_handler(
        questions, solved, judge=lambda _: json.dumps({"consistent": True, "reason": "说法等价"})
    )
    make_tenant("a", "13811110001")
    teacher = auth(client, "13811110001")
    batch = _generate(client, teacher, {**GEN, "qtype": "填空题", "count": 3})

    checks = [(q["status"], q["check"]["verdict"], q["check"]["method"]) for q in batch["questions"]]
    assert checks == [
        ("checked", "agree", "numeric"),
        ("checked", "agree", "judge"),
        ("unchecked", "error", ""),
    ]
    assert batch["questions"][2]["check"]["reason"] == "校验服务暂时不可用，可以稍后重新校验"
    assert ai.skills().count("answer_judge") == 1  # 数值比对能确定的不再问模型


def test_recheck_after_edit(client, ai):
    make_tenant("a", "13811110001")
    teacher = auth(client, "13811110001")
    disputed = _generate(client, teacher)["questions"][1]
    qid = disputed["id"]

    fields = ("qtype", "stem", "options", "analysis", "knowledge_points", "subject", "grade")
    fixed = {**{k: disputed[k] for k in fields}, "answer": "A"}
    updated = client.put(f"/api/teacher/questions/{qid}", headers=teacher, json=fixed).json()
    assert (updated["answer"], updated["edited"], updated["status"]) == ("A", True, "disputed")

    rechecked = client.post(f"/api/teacher/questions/{qid}/recheck", headers=teacher)
    assert rechecked.status_code == 200
    q = client.get(f"/api/teacher/questions/{qid}", headers=teacher).json()
    assert (q["status"], q["check"]["verdict"]) == ("checked", "agree")

    client.post(f"/api/teacher/questions/{qid}/approve", headers=teacher)
    again = client.post(f"/api/teacher/questions/{qid}/recheck", headers=teacher)
    assert again.status_code == 400


def test_bulk_review(client, ai):
    make_tenant("a", "13811110001")
    teacher = auth(client, "13811110001")
    ids = [q["id"] for q in _generate(client, teacher)["questions"]]
    resp = client.post("/api/teacher/questions/bulk-review", headers=teacher, json={"ids": ids})
    assert resp.json() == {"count": 2}
    assert _view(client, teacher, "bank")["total"] == 2


def test_manual_question(client):
    make_tenant("a", "13811110001")
    teacher = auth(client, "13811110001")
    body = {
        "subject": "数学",
        "grade": "七年级上册",
        "qtype": "单选题",
        "difficulty": "容易",
        "stem": "下列各数中，是负数的是",
        "options": ["A. 2", "B. 0", "C. -1", "D. 3"],
        "answer": "e",
        "knowledge_points": ["正数和负数"],
    }
    bad = client.post("/api/teacher/questions", headers=teacher, json=body)
    assert bad.status_code == 400 and bad.json()["message"] == "答案要写选项字母（A～D）"

    q = client.post("/api/teacher/questions", headers=teacher, json={**body, "answer": "c"}).json()
    assert (q["status"], q["source"], q["answer"], q["options"]) == (
        "approved",
        "manual",
        "C",
        ["2", "0", "-1", "3"],
    )
    assert q["check"] is None

    assert _view(client, teacher, "bank", keyword="负数")["total"] == 1
    assert _view(client, teacher, "bank", keyword="正数和负数")["total"] == 1  # 知识点也能搜
    assert _view(client, teacher, "bank", keyword="%")["total"] == 0
    assert _view(client, teacher, "bank", qtype="填空题")["total"] == 0

    assert client.delete(f"/api/teacher/questions/{q['id']}", headers=teacher).json() == {"ok": True}
    with open_session(bypass=True) as db:
        assert db.scalars(select(AuditLog.action)).all() == ["delete_question"]


def test_bad_output_fails_batch(client, ai):
    ai.handler = lambda skill, messages: "这不是 JSON"
    make_tenant("a", "13811110001")
    teacher = auth(client, "13811110001")
    batch = _generate(client, teacher)
    assert (batch["status"], batch["error"]) == ("failed", "AI 返回的内容格式不对，请重试")
    assert batch["questions"] == []


def test_stale_batch_and_limit(client, monkeypatch):
    monkeypatch.setattr(dispatch, "submit", lambda task, *args: None)  # 任务不执行，模拟一直在跑
    make_tenant("a", "13811110001")
    teacher = auth(client, "13811110001")
    first = client.post("/api/teacher/questions/generate", headers=teacher, json=GEN).json()
    client.post("/api/teacher/questions/generate", headers=teacher, json=GEN)
    third = client.post("/api/teacher/questions/generate", headers=teacher, json=GEN)
    assert third.status_code == 429

    with session_scope(bypass=True) as db:
        db.get(QuestionBatch, first["id"]).updated_at = datetime.now(UTC) - timedelta(hours=1)
    stale = client.get(f"/api/teacher/question-batches/{first['id']}", headers=teacher).json()
    assert (stale["status"], stale["error"]) == ("failed", "出题中断了，请重新出题")

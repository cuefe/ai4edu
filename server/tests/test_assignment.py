import json
from datetime import UTC, datetime, timedelta
from io import BytesIO

import pytest
from PIL import Image
from sqlalchemy import select

from app.core.db import open_session
from app.modules.assignment import tasks
from app.modules.assignment.grading import objective_ratio
from app.modules.ops.models import AuditLog
from app.workers import dispatch
from tests.fake_ai import FakeChat
from tests.school import assign, make_school

GRADE = {
    "score": 4,
    "confidence": 0.6,
    "points": ["最后一步符号写错，扣 6 分"],
    "comment": "思路对了，注意减负数",
}


@pytest.fixture
def grader(monkeypatch):
    fake = FakeChat(lambda skill, messages: json.dumps(GRADE, ensure_ascii=False))
    monkeypatch.setattr(tasks, "build_gateway", lambda: fake)
    monkeypatch.setattr(dispatch, "submit", lambda task, *args: task.apply(args=args))
    return fake


def _photo() -> bytes:
    buf = BytesIO()
    Image.new("RGB", (2400, 1200), "white").save(buf, "PNG")
    return buf.getvalue()


@pytest.mark.parametrize(
    ("qtype", "answer", "response", "ratio"),
    [
        ("单选题", "A", "A", 1),
        ("单选题", "A", "B", 0),
        ("多选题", "AC", "CA", 1),
        ("多选题", "AC", "A", 0.5),  # 少选得一半
        ("多选题", "AC", "AB", 0),  # 错选不得分
        ("判断题", "对", "√", 1),
        ("填空题", "3；$-\\frac{1}{2}$", "3；-0.5", 1),
        ("填空题", "3；$-\\frac{1}{2}$", "3；0.5", 0.5),
        ("填空题", "3；$-\\frac{1}{2}$", "3", 0.5),  # 少填一个空
        ("填空题", "互为相反数", "相反数", None),  # 判断不了，交给 AI
        ("解答题", "6", "6", None),
        ("单选题", "A", "  ", 0),
    ],
)
def test_objective_ratio(qtype, answer, response, ratio):
    assert objective_ratio(qtype, answer, response) == ratio


def test_assign_answer_submit_and_grade(client, grader):
    school = make_school(client)
    s1, s2 = school.students
    report = assign(client, school, due_at=(datetime.now(UTC) + timedelta(days=1)).isoformat())
    aid = report["id"]
    assert (report["student_count"], report["total_score"], report["class_names"]) == (2, 25, ["初一(1)班"])

    # 学生收到通知；作答前看不到答案
    notes = client.get("/api/me/notifications", headers=s1).json()
    assert notes["unread"] == 1 and notes["items"][0]["link"] == f"/student/assignments/{aid}"
    [brief] = client.get("/api/student/assignments", headers=s1).json()
    assert (brief["question_count"], brief["task_count"], brief["status"]) == (4, 2, "todo")
    detail = client.get(f"/api/student/assignments/{aid}", headers=s1).json()
    items = {i["content"].get("qtype") or i["item_type"]: i for i in detail["items"]}
    assert "answer" not in items["单选题"]["content"] and detail["revealed"] is False
    assert items["document"]["content"]["markdown"].startswith("# 1.2.4 绝对值")
    assert len(items["recite"]["content"]["cards"]) == 2

    def answer(headers, key, text):
        resp = client.put(
            f"/api/student/assignments/{aid}/answers/{items[key]['id']}",
            headers=headers,
            json={"response": text},
        )
        assert resp.status_code == 200, resp.text

    answer(s1, "单选题", "A")
    answer(s1, "多选题", "A")
    answer(s1, "填空题", "3；-0.5")
    solve = items["解答题"]["id"]
    up = client.post(
        f"/api/student/assignments/{aid}/answers/{solve}/images",
        headers=s1,
        files={"file": ("p.png", _photo())},
    )
    assert up.json()["image_count"] == 1
    photo = client.get(f"/api/student/assignments/{aid}/answers/{solve}/images/0", headers=s1)
    assert Image.open(BytesIO(photo.content)).size == (1600, 800)  # 压到 1600 长边
    client.post(f"/api/student/assignments/{aid}/items/{items['document']['id']}/done", headers=s1)

    done = client.post(f"/api/student/assignments/{aid}/submit", headers=s1).json()
    assert (done["status"], done["revealed"], done["pending_count"]) == ("submitted", True, 1)
    scores = {a["item_id"]: (a["score"], a["correct"], a["status"]) for a in done["answers"]}
    assert scores[items["单选题"]["id"]] == (5, True, "auto")
    assert scores[items["多选题"]["id"]] == (2.5, False, "auto")
    assert scores[items["填空题"]["id"]] == (5, True, "auto")
    # 主观题：AI 给了分，但老师确认前学生看不到
    solved = next(a for a in done["answers"] if a["item_id"] == solve)
    assert (solved["status"], solved["score"], solved["ai_score"], solved["ai_comment"]) == (
        "ai_done",
        None,
        None,
        "",
    )
    assert done["items"][0]["content"]["answer"] == "A"  # 提交后公布答案
    assert (
        client.put(
            f"/api/student/assignments/{aid}/answers/{solve}", headers=s1, json={"response": "改"}
        ).status_code
        == 409
    )

    # 批改用的是图片：模型收到了照片
    content = grader.calls[0]["messages"][1]["content"]
    assert grader.calls[0]["skill"] == "grade_subjective" and content[1]["type"] == "image_url"

    # 老师端：报告、待确认
    report = client.get(f"/api/teacher/assignments/{aid}", headers=school.teacher).json()
    assert (report["submitted_count"], report["pending_review"], report["graded_count"]) == (1, 1, 0)
    multi_stat = next(s for s in report["item_stats"] if s["item_id"] == items["多选题"]["id"])
    assert (multi_stat["accuracy"], multi_stat["common_wrong"]) == (0, True)
    rows = {r["student_name"]: r for r in report["submissions"]}
    assert (rows["学生1"]["progress_done"], rows["学生2"]["status"]) == (1, "todo")

    [row] = client.get(f"/api/teacher/assignments/{aid}/grading", headers=school.teacher).json()
    assert (row["ai_score"], row["ai_confidence"], row["student_name"]) == (4, 0.6, "学生1")
    img = client.get(f"/api/teacher/answers/{row['id']}/images/0", headers=school.teacher)
    assert img.headers["content-type"] == "image/jpeg"
    too_high = client.post(
        f"/api/teacher/answers/{row['id']}/confirm", headers=school.teacher, json={"score": 11}
    )
    assert too_high.status_code == 400
    ok = client.post(
        f"/api/teacher/answers/{row['id']}/confirm",
        headers=school.teacher,
        json={"score": 10, "comment": "其实对了"},
    ).json()
    assert (ok["score"], ok["correct"], ok["status"]) == (10, True, "confirmed")

    after = client.get(f"/api/student/assignments/{aid}", headers=s1).json()
    assert (after["status"], after["score"]) == ("graded", 22.5)
    solved = next(a for a in after["answers"] if a["item_id"] == solve)
    assert (solved["score"], solved["teacher_comment"], solved["ai_comment"]) == (
        10,
        "其实对了",
        GRADE["comment"],
    )

    # 多选少选：进错题本；老师把它改成满分，错题本里就拿掉
    book = client.get("/api/student/wrong-items", headers=s1).json()
    assert [w["question"]["qtype"] for w in book["items"]] == ["多选题"] and book["pending"] == 1
    multi_answer = next(a for a in after["answers"] if a["item_id"] == items["多选题"]["id"])
    client.post(
        f"/api/teacher/answers/{multi_answer['id']}/confirm", headers=school.teacher, json={"score": 5}
    )
    assert client.get("/api/student/wrong-items", headers=s1).json()["pending"] == 0
    with open_session(bypass=True) as db:
        changes = db.scalars(select(AuditLog.detail).where(AuditLog.action == "change_score")).all()
    assert changes == [{"before": 2.5, "after": 5}]

    # 催交：只发给没交的
    assert client.post(f"/api/teacher/assignments/{aid}/remind", headers=school.teacher).json() == {
        "count": 1
    }
    assert (
        client.get("/api/me/notifications", headers=s2)
        .json()["items"][0]["title"]
        .startswith("a 管理员老师提醒你")
    )


def test_blank_answers_and_release_after_due(client, grader):
    school = make_school(client, n_students=1)
    [s1] = school.students
    due = datetime.now(UTC) + timedelta(hours=1)
    aid = assign(client, school, keys=("single", "solve"), answer_release="due", due_at=due.isoformat())["id"]
    done = client.post(f"/api/student/assignments/{aid}/submit", headers=s1).json()
    # 没写的题直接 0 分，不用 AI 批改；截止前不公布答案，错题本里也先不出现
    assert (done["status"], done["score"], done["revealed"]) == ("graded", 0, False)
    assert all("answer" not in i["content"] for i in done["items"] if i["item_type"] == "question")
    assert grader.calls == []
    assert client.get("/api/student/wrong-items", headers=s1).json()["items"] == []


def test_assignment_permissions(client, grader):
    school = make_school(client)
    other = make_school(client, code="b", phone="13811110002", n_students=1)
    body = {
        "title": "x",
        "subject": "数学",
        "class_ids": [str(other.class_id)],
        "items": [{"item_type": "question", "ref_id": school.questions["single"]}],
    }
    assert client.post("/api/teacher/assignments", headers=school.teacher, json=body).status_code == 400
    aid = assign(client, school)["id"]
    assert client.get(f"/api/student/assignments/{aid}", headers=other.students[0]).status_code == 404
    assert client.get(f"/api/teacher/assignments/{aid}", headers=other.teacher).status_code == 404
    assert client.get("/api/teacher/assignments", headers=school.students[0]).status_code == 403

    # 定时发布：发布前学生看不到
    later = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    assign(client, school, keys=("single",), publish_at=later)
    assert len(client.get("/api/student/assignments", headers=school.students[0]).json()) == 1

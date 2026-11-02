import json

import pytest

from app.modules.notify import service as notify_service
from app.modules.tutor import service as tutor_service
from tests.fake_ai import FakeChat
from tests.school import assign, make_school


class TutorAI(FakeChat):
    """安全分类、作业泄露检查走 chat；回答走 stream。"""

    def __init__(self):
        self.category = "study"
        self.crisis = "none"
        self.answer = "我们先看看题目问的是什么。"
        self.leak_first = False
        self.leak_checks = 0
        super().__init__(self._handle)

    def _handle(self, skill, messages):
        system = messages[0]["content"]
        if "安全审核员" in system:
            return json.dumps({"category": self.category, "crisis": self.crisis, "reason": "测试"})
        if "审核员" in system:  # 作业模式泄露检查
            self.leak_checks += 1
            return json.dumps({"leak": self.leak_first and self.leak_checks == 1})
        return "答案是 A" if self.leak_first and self.leak_checks == 0 else "提示：想想相反数的定义。"

    async def stream(self, skill, messages, *, ctx, **params):
        self.calls.append({"skill": skill, "messages": messages, "params": params})
        for i in range(0, len(self.answer), 5):
            yield self.answer[i : i + 5]


@pytest.fixture
def ai(monkeypatch):
    fake = TutorAI()
    monkeypatch.setattr(tutor_service, "get_gateway", lambda: fake)
    return fake


def _send(client, headers, sid, text, **extra) -> list[tuple[str, dict]]:
    events = []
    body = {"text": text, **extra}
    with client.stream(
        "POST", f"/api/student/tutor/sessions/{sid}/messages", headers=headers, json=body
    ) as resp:
        assert resp.status_code == 200, resp.read()
        name = None
        for line in resp.iter_lines():
            if line.startswith("event: "):
                name = line[7:]
            elif line.startswith("data: "):
                events.append((name, json.loads(line[6:])))
    return events


def _text(events) -> str:
    return "".join(d["text"] for n, d in events if n == "delta")


def test_learn_mode_and_styles(client, ai):
    school = make_school(client, n_students=1)
    [s1] = school.students
    session = client.post("/api/student/tutor/sessions", headers=s1, json={}).json()
    assert session["mode"] == "learn" and session["hotlines"][0].endswith("12356")

    events = _send(client, s1, session["id"], "什么是相反数？", style="example")
    assert _text(events) == ai.answer and events[-1][0] == "done"
    call = next(c for c in ai.calls if c["skill"] == "tutor")
    assert "学习模式" in call["messages"][0]["content"]
    assert call["messages"][-1]["content"].endswith("（请举一个生活中的例子来讲这个知识点或者这道题。）")

    _send(client, s1, session["id"], "", style="simpler")  # 只点了讲解方式按钮，没打字
    assert ai.calls[-1]["messages"][-1]["content"].startswith("请讲简单点")
    history = [m["role"] for m in ai.calls[-1]["messages"]]
    assert history == ["system", "user", "assistant", "user"]  # 带上了之前的对话

    detail = client.get(f"/api/student/tutor/sessions/{session['id']}", headers=s1).json()
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant", "user", "assistant"]
    assert detail["title"] == "什么是相反数？"


class FakeSms:
    def __init__(self):
        self.sent: list[tuple[str, str]] = []

    def send_notice(self, phone: str, text: str) -> None:
        self.sent.append((phone, text))


def test_crisis_alert(client, ai, monkeypatch):
    sms = FakeSms()
    monkeypatch.setattr(notify_service, "get_sms_sender", lambda: sms)
    school = make_school(client, n_students=1)
    [s1] = school.students
    sid = client.post("/api/student/tutor/sessions", headers=s1, json={}).json()["id"]

    # 模型说没事，但命中关键词：照样按危机处理（宁可多报）
    events = _send(client, s1, sid, "作业好多，我真的不想活了")
    assert events[0] == ("notice", {"kind": "crisis", "hotlines": events[0][1]["hotlines"]})
    reply = _text(events)
    assert "12356" in reply and "12355" in reply and events[-1][1]["flag"] == "crisis"
    assert not any(c["skill"] == "tutor" for c in ai.calls)  # 危机回复不交给模型发挥
    # 高风险同时发短信给老师；短信里不带学生的原话
    assert [(phone, "心理预警" in text, "不想活" in text) for phone, text in sms.sent] == [
        ("13811110001", True, False)
    ]

    alerts = client.get("/api/alerts", headers=school.teacher).json()
    assert [(a["level"], a["student_name"], a["status"]) for a in alerts] == [("high", "学生1", "open")]
    assert alerts[0]["class_names"] == ["初一(1)班"]
    notes = client.get("/api/me/notifications", headers=school.teacher).json()
    assert notes["items"][0]["kind"] == "crisis" and notes["items"][0]["link"] == "/alerts"
    msgs = client.get(f"/api/alerts/{alerts[0]['id']}/messages", headers=school.teacher).json()
    assert msgs[0]["content"] == "作业好多，我真的不想活了"

    handled = client.post(
        f"/api/alerts/{alerts[0]['id']}/handle", headers=school.teacher, json={"note": "已和学生、家长沟通"}
    ).json()
    assert (handled["status"], handled["handled_by_name"]) == ("handled", "a 管理员")
    assert client.get("/api/alerts", headers=s1).status_code == 403

    # 对话不中断：接着问学习问题正常回答
    assert _text(_send(client, s1, sid, "那这道题怎么做？")) == ai.answer

    # 口头夸张不算危机
    assert _send(client, s1, sid, "这题难死了")[0][0] == "delta"


def test_off_topic_and_unsafe(client, ai):
    school = make_school(client, n_students=1)
    [s1] = school.students
    sid = client.post("/api/student/tutor/sessions", headers=s1, json={}).json()["id"]
    ai.category = "chat"
    events = _send(client, s1, sid, "你喜欢哪个明星？")
    assert "学习小助手" in _text(events) and events[-1][1]["flag"] == "chat"
    ai.category = "unsafe"
    assert "不能聊" in _text(_send(client, s1, sid, "不当内容"))
    assert not any(c["skill"] == "tutor" for c in ai.calls)


def test_homework_mode_hides_answer(client, ai):
    school = make_school(client, n_students=1)
    [s1] = school.students
    aid = assign(client, school, keys=("single",))["id"]
    item = client.get(f"/api/student/assignments/{aid}", headers=s1).json()["items"][0]["id"]
    session = client.post(
        "/api/student/tutor/sessions", headers=s1, json={"assignment_id": aid, "item_id": item}
    ).json()
    assert session["mode"] == "homework" and "answer" not in session["question"]

    ai.leak_first = True  # 第一版回复泄露了答案：改写后再发
    events = _send(client, s1, session["id"], "直接告诉我答案")
    assert _text(events) == "提示：想想相反数的定义。" and events[-1][1]["flag"] == "leak"
    system = next(c for c in ai.calls if c["skill"] == "tutor")["messages"][0]["content"]
    assert "作业提示模式" in system and "参考答案：A" in system  # 模型知道答案，但被要求不说

    # 提交后再问同一道题：学习模式
    client.post(f"/api/student/assignments/{aid}/submit", headers=s1)
    after = client.post(
        "/api/student/tutor/sessions", headers=s1, json={"assignment_id": aid, "item_id": item}
    ).json()
    assert after["mode"] == "learn" and after["question"]["answer"] == "A"


def test_ai_disabled_during_homework(client, ai):
    school = make_school(client, n_students=1)
    [s1] = school.students
    aid = assign(client, school, keys=("single",), allow_ai=False)["id"]
    item = client.get(f"/api/student/assignments/{aid}", headers=s1).json()["items"][0]["id"]
    assert client.get("/api/student/tutor/status", headers=s1).json() == {"blocked_by": "第一章练习"}
    blocked = client.post(
        "/api/student/tutor/sessions", headers=s1, json={"assignment_id": aid, "item_id": item}
    )
    assert blocked.status_code == 403
    assert client.post("/api/student/tutor/sessions", headers=s1, json={}).status_code == 403
    client.post(f"/api/student/assignments/{aid}/submit", headers=s1)
    assert client.get("/api/student/tutor/status", headers=s1).json() == {"blocked_by": None}
    assert client.post("/api/student/tutor/sessions", headers=s1, json={}).status_code == 200


def test_correction_mode_and_quota(client, ai, monkeypatch):
    school = make_school(client, n_students=1)
    [s1] = school.students
    aid = assign(client, school, keys=("single",))["id"]
    client.post(f"/api/student/assignments/{aid}/submit", headers=s1)
    wrong = client.get("/api/student/wrong-items", headers=s1).json()["items"][0]
    session = client.post(
        "/api/student/tutor/sessions", headers=s1, json={"wrong_item_id": wrong["id"]}
    ).json()
    assert session["mode"] == "correction" and session["title"].startswith("订正：")
    _send(client, s1, session["id"], "我没思路")
    assert "订正模式" in ai.calls[-1]["messages"][0]["content"]

    monkeypatch.setattr(tutor_service, "DAILY_LIMIT", 1)
    resp = client.post(
        f"/api/student/tutor/sessions/{session['id']}/messages", headers=s1, json={"text": "还有"}
    )
    assert resp.status_code == 429

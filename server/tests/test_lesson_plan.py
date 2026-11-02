import json
from datetime import UTC, datetime, timedelta
from io import BytesIO

import docx
import pytest
from sqlalchemy import select

from app.ai.skills import lesson_plan
from app.core.db import open_session, session_scope
from app.core.errors import AppError
from app.modules.content import generation
from app.modules.content.docx_export import doc_to_docx
from app.modules.content.markdown import markdown_to_doc
from app.modules.content.models import DocStatus, Document
from app.modules.iam.models import User
from app.modules.ops.models import AuditLog
from tests.conftest import auth, make_tenant, student_auth

BODY = {"subject": "数学", "grade": "七年级上册", "topic": "1.2.1 有理数的概念", "duration": 45}

PLAN = """## 一、教材分析
本节在学习了正数和负数的基础上，引入**有理数**的概念。

## 二、学情分析
学生已经认识了负数。

## 三、教学目标
1. 学生能说出有理数的定义。
2. 学生能把给定的数按整数、分数分类。

## 四、教学重点与难点
- 重点：有理数的概念
- 难点：有理数的分类

## 五、教学准备
课件、练习单。

## 六、教学过程
### 环节一：情境导入（5 分钟）
**教师活动**：出示温度计，提问"零下 3 摄氏度怎么表示？"
**学生活动**：回答 $-3$。
**设计意图**：联系生活。

### 环节二：探究新知（25 分钟）
**教师活动**：给出数 $\\frac{1}{2}$、$-0.5$、$0$，请学生分类。

| 整数 | 分数 |
| --- | --- |
| $0$、$-3$ | $\\frac{1}{2}$、$-0.5$ |

$$
\\text{有理数} = \\text{整数} + \\text{分数}
$$

### 环节三：练习巩固（15 分钟）
**学生活动**：完成练习。

## 七、板书设计
- 有理数：整数和分数统称有理数

## 八、作业设计
- 基础（10 分钟）：课本练习

## 九、教学反思
（课后填写）
"""


class FakeGateway:
    def __init__(self, text: str = PLAN, fail_after: int | None = None):
        self.text = text
        self.fail_after = fail_after
        self.calls: list[dict] = []

    async def stream(self, skill, messages, *, ctx, **params):
        self.calls.append({"skill": skill, "messages": messages, "ctx": ctx, "params": params})
        for i in range(0, len(self.text), 40):
            if self.fail_after is not None and i >= self.fail_after:
                raise AppError("AI 服务暂时不可用，请稍后再试", code="ai_unavailable", status=503)
            yield self.text[i : i + 40]


@pytest.fixture
def gateway(monkeypatch):
    fake = FakeGateway()
    monkeypatch.setattr(generation, "get_gateway", lambda: fake)
    return fake


def _events(client, headers, body=BODY) -> list[tuple[str, dict]]:
    events = []
    with client.stream("POST", "/api/teacher/lesson-plans/generate", headers=headers, json=body) as resp:
        assert resp.status_code == 200, resp.read()
        assert resp.headers["content-type"].startswith("text/event-stream")
        name = None
        for line in resp.iter_lines():
            if line.startswith("event: "):
                name = line[7:]
            elif line.startswith("data: "):
                events.append((name, json.loads(line[6:])))
    return events


def _teacher(client, admin, phone="13811110010", name="王老师"):
    resp = client.post(
        "/api/org/teachers", headers=admin, json={"name": name, "phone": phone, "password": "t12345"}
    )
    assert resp.status_code == 200, resp.text
    return auth(client, phone, "t12345")


def test_generate_streams_and_saves(client, gateway, monkeypatch):
    monkeypatch.setattr(generation, "FLUSH_SECONDS", 0)  # 每段都写库，覆盖进度保存
    make_tenant("a", "13811110001")
    teacher = auth(client, "13811110001")

    events = _events(client, teacher)
    names = [n for n, _ in events]
    assert names[0] == "created" and names[-1] == "done" and set(names[1:-1]) == {"delta"}
    doc_id = events[0][1]["id"]
    assert events[-1][1] == {"id": doc_id, "warnings": []}
    streamed = "".join(d["text"] for n, d in events if n == "delta")
    assert streamed.startswith("# 1.2.1 有理数的概念\n\n| 学科 |")
    assert streamed.endswith(PLAN)

    call = gateway.calls[0]
    assert call["skill"] == "lesson_plan"
    assert "45 分钟" in call["messages"][0]["content"]
    assert "课题：1.2.1 有理数的概念" in call["messages"][1]["content"]

    doc = client.get(f"/api/teacher/documents/{doc_id}", headers=teacher).json()
    assert (doc["status"], doc["title"], doc["version"]) == ("ready", "1.2.1 有理数的概念", 1)
    assert doc["generated_md"] is None
    assert doc["params"]["topic"] == "1.2.1 有理数的概念"
    nodes = doc["content"]["content"]
    assert nodes[0]["type"] == "heading" and nodes[1]["type"] == "table"
    assert any(n["type"] == "blockMath" for n in nodes)

    with open_session(bypass=True) as db:
        saved = db.get(Document, doc["id"])
        assert saved.generated_md == streamed
        assert saved.params["prompt_version"] == lesson_plan.PROMPT_VERSION

    listed = client.get("/api/teacher/documents", headers=teacher).json()
    assert [d["id"] for d in listed] == [doc_id]


def test_checks_are_reported(client, monkeypatch):
    bad = PLAN.replace("（15 分钟）", "（10 分钟）").replace(
        "## 九、教学反思\n（课后填写）\n", "见教材第 12 页"
    )
    monkeypatch.setattr(generation, "get_gateway", lambda: FakeGateway(bad))
    make_tenant("a", "13811110001")
    teacher = auth(client, "13811110001")

    warnings = _events(client, teacher)[-1][1]["warnings"]
    assert len(warnings) == 3
    assert "教学反思" in warnings[0]
    assert "合计 40 分钟" in warnings[1]
    assert "页码" in warnings[2]


def test_failure_marks_document_failed(client, monkeypatch):
    monkeypatch.setattr(generation, "get_gateway", lambda: FakeGateway(fail_after=80))
    make_tenant("a", "13811110001")
    teacher = auth(client, "13811110001")

    events = _events(client, teacher)
    assert events[-1] == ("error", {"message": "AI 服务暂时不可用，请稍后再试"})
    doc = client.get(f"/api/teacher/documents/{events[0][1]['id']}", headers=teacher).json()
    assert doc["status"] == "failed" and doc["error"] == "AI 服务暂时不可用，请稍后再试"
    assert client.get(f"/api/teacher/documents/{doc['id']}/docx", headers=teacher).status_code == 400


def test_mock_gateway_end_to_end(client):
    """不替换网关：开发环境没配 Key 时走 mock 模型，流程也要能跑通。"""
    make_tenant("a", "13811110001")
    teacher = auth(client, "13811110001")
    events = _events(client, teacher, {**BODY, "subject": "英语", "topic": "Unit 1 You and Me"})
    assert events[-1][0] == "done"
    assert any("缺少" in w for w in events[-1][1]["warnings"])


def test_save_with_version_check(client, gateway):
    make_tenant("a", "13811110001")
    teacher = auth(client, "13811110001")
    doc_id = _events(client, teacher)[0][1]["id"]
    content = markdown_to_doc("# 改过的教案\n\n老师自己写的内容")

    resp = client.put(
        f"/api/teacher/documents/{doc_id}",
        headers=teacher,
        json={"title": "新标题", "content": content, "version": 1},
    )
    assert resp.status_code == 200, resp.text
    assert (resp.json()["title"], resp.json()["version"]) == ("新标题", 2)
    assert resp.json()["content"] == content

    stale = client.put(
        f"/api/teacher/documents/{doc_id}",
        headers=teacher,
        json={"title": "旧窗口", "content": content, "version": 1},
    )
    assert stale.status_code == 409 and stale.json()["code"] == "version_conflict"
    bad = client.put(
        f"/api/teacher/documents/{doc_id}",
        headers=teacher,
        json={"title": "x", "content": {"a": 1}, "version": 2},
    )
    assert bad.status_code == 400


def test_documents_are_private(client, gateway):
    make_tenant("a", "13811110001")
    make_tenant("b", "13811110002")
    admin_a = auth(client, "13811110001")
    doc_id = _events(client, admin_a)[0][1]["id"]

    colleague = _teacher(client, admin_a)
    other_school = auth(client, "13811110002")
    client.post(
        "/api/org/students", headers=admin_a, json={"name": "学生", "username": "s1", "password": "s12345"}
    )
    student = student_auth(client, "a", "s1", "s12345")

    for headers in (colleague, other_school):
        assert client.get("/api/teacher/documents", headers=headers).json() == []
        assert client.get(f"/api/teacher/documents/{doc_id}", headers=headers).status_code == 404
        assert client.get(f"/api/teacher/documents/{doc_id}/docx", headers=headers).status_code == 404
        assert client.delete(f"/api/teacher/documents/{doc_id}", headers=headers).status_code == 404
    assert client.get("/api/teacher/documents", headers=student).status_code == 403
    assert client.post("/api/teacher/lesson-plans/generate", headers=student, json=BODY).status_code == 403


def test_export_and_delete(client, gateway):
    make_tenant("a", "13811110001")
    teacher = auth(client, "13811110001")
    doc_id = _events(client, teacher)[0][1]["id"]

    resp = client.get(f"/api/teacher/documents/{doc_id}/docx", headers=teacher)
    assert resp.status_code == 200
    assert "filename*=UTF-8''1.2.1_" in resp.headers["content-disposition"]
    word = docx.Document(BytesIO(resp.content))
    assert word.paragraphs[0].text == "1.2.1 有理数的概念"
    assert word.paragraphs[0].style.name == "Heading 1"
    assert [c.text for c in word.tables[0].rows[1].cells][:2] == ["数学", "七年级上册"]
    assert "m:oMath" in word.element.xml  # 公式转成了 Word 原生公式

    assert client.delete(f"/api/teacher/documents/{doc_id}", headers=teacher).json() == {"ok": True}
    assert client.get(f"/api/teacher/documents/{doc_id}", headers=teacher).status_code == 404
    with open_session(bypass=True) as db:
        actions = db.scalars(select(AuditLog.action).order_by(AuditLog.created_at)).all()
    assert actions == ["export_document", "delete_document"]


def test_generation_limit_and_stale_documents(client, gateway):
    tenant = make_tenant("a", "13811110001")
    teacher = auth(client, "13811110001")
    with session_scope(bypass=True) as db:
        owner_id = db.scalar(select(User.id).where(User.tenant_id == tenant.id))
        old = datetime.now(UTC) - timedelta(minutes=10)
        for i, updated in enumerate([None, None, old]):
            doc = Document(
                tenant_id=tenant.id,
                owner_id=owner_id,
                doc_type="lesson_plan",
                title=f"进行中 {i}",
                status=DocStatus.GENERATING,
            )
            if updated:
                doc.updated_at = updated
            db.add(doc)

    resp = client.post("/api/teacher/lesson-plans/generate", headers=teacher, json=BODY)
    assert resp.status_code == 429 and resp.json()["code"] == "too_many_generating"

    statuses = {d["title"]: d["status"] for d in client.get("/api/teacher/documents", headers=teacher).json()}
    assert statuses == {"进行中 0": "generating", "进行中 1": "generating", "进行中 2": "failed"}


def test_docx_handles_lists_merged_cells_and_bad_math():
    content = {
        "type": "doc",
        "content": [
            {
                "type": "orderedList",
                "attrs": {"start": 3},
                "content": [
                    {
                        "type": "listItem",
                        "content": [
                            {"type": "paragraph", "content": [{"type": "text", "text": "第三条"}]},
                            {
                                "type": "bulletList",
                                "content": [
                                    {
                                        "type": "listItem",
                                        "content": [
                                            {
                                                "type": "paragraph",
                                                "content": [{"type": "text", "text": "子项"}],
                                            }
                                        ],
                                    }
                                ],
                            },
                        ],
                    }
                ],
            },
            {
                "type": "table",
                "content": [
                    {
                        "type": "tableRow",
                        "content": [
                            {
                                "type": "tableHeader",
                                "attrs": {"colspan": 2, "rowspan": 1},
                                "content": [
                                    {"type": "paragraph", "content": [{"type": "text", "text": "合并"}]}
                                ],
                            }
                        ],
                    },
                    {
                        "type": "tableRow",
                        "content": [
                            {"type": "tableCell", "content": [{"type": "paragraph"}]},
                            {
                                "type": "tableCell",
                                "content": [
                                    {
                                        "type": "paragraph",
                                        "content": [{"type": "inlineMath", "attrs": {"latex": "\\frac{"}}],
                                    }
                                ],
                            },
                        ],
                    },
                ],
            },
        ],
    }
    word = docx.Document(BytesIO(doc_to_docx("测试", content)))
    assert [p.text for p in word.paragraphs[:2]] == ["3. 第三条", "• 子项"]
    table = word.tables[0]
    assert table.cell(0, 0).text == table.cell(0, 1).text == "合并"
    assert table.cell(1, 1).text == "$\\frac{$"  # 转换失败的公式保留原文
    assert word.core_properties.title == "测试"

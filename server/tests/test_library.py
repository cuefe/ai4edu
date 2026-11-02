import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.db import open_session, session_scope
from app.modules.content import generation
from app.modules.content.models import Document
from app.modules.library.models import Resource, ResourceChunk, ResourceStatus
from app.workers import dispatch
from tests.conftest import auth, make_tenant
from tests.pdf_utils import make_pdf
from tests.test_lesson_plan import BODY, PLAN, FakeGateway

PPTX = Path(__file__).parent / "fixtures" / "pptx" / "01-title-bullets.pptx"

NOTE = """# 有理数的分类

## 按定义分类
有理数分为整数和分数。整数包括正整数、0、负整数；分数包括正分数、负分数。

## 易错点
学生常把小数排除在分数之外。有限小数和无限循环小数都可以化成分数，所以都是有理数。
"""


@pytest.fixture(autouse=True)
def inline_tasks(monkeypatch):
    """测试里后台任务直接同步执行，上传接口返回时解析已经完成。"""
    monkeypatch.setattr(dispatch, "submit", lambda task, *args: task.apply(args=args))


def _upload(client, headers, name: str, data: bytes, **form) -> dict:
    resp = client.post("/api/teacher/resources", headers=headers, files={"file": (name, data)}, data=form)
    assert resp.status_code == 200, resp.text
    return client.get(f"/api/teacher/resources/{resp.json()['id']}", headers=headers).json()


def _teacher(client, admin, phone: str) -> dict:
    resp = client.post(
        "/api/org/teachers", headers=admin, json={"name": "同事", "phone": phone, "password": "t12345"}
    )
    assert resp.status_code == 200, resp.text
    return auth(client, phone, "t12345")


def test_upload_parse_and_search(client):
    make_tenant("a", "13811110001")
    teacher = auth(client, "13811110001")

    r = _upload(client, teacher, "1.1 正数和负数.pptx", PPTX.read_bytes(), subject="数学")
    assert (r["status"], r["pages"], r["mine"], r["error"]) == ("ready", 6, True, None)
    assert r["chunk_count"] > 0 and r["progress"] == 100

    chunks = client.get(f"/api/teacher/resources/{r['id']}/chunks", headers=teacher).json()
    assert chunks[0]["page_start"] == 1
    assert any("相反意义的量" in c["text"] for c in chunks)

    hits = client.post(
        "/api/teacher/resources/search", headers=teacher, json={"query": "相反意义的量"}
    ).json()
    assert hits and hits[0]["filename"] == "1.1 正数和负数.pptx"
    assert 0 < hits[0]["score"] <= 1
    # 学科过滤：英语里找不到数学资料
    english = {"query": "相反意义的量", "subject": "英语"}
    assert client.post("/api/teacher/resources/search", headers=teacher, json=english).json() == []

    file = client.get(f"/api/teacher/resources/{r['id']}/file", headers=teacher)
    assert file.content == PPTX.read_bytes()

    dup = client.post(
        "/api/teacher/resources", headers=teacher, files={"file": ("again.pptx", PPTX.read_bytes())}
    )
    assert dup.status_code == 409 and "已经上传过" in dup.json()["message"]
    old = client.post("/api/teacher/resources", headers=teacher, files={"file": ("old.ppt", b"x")})
    assert old.status_code == 400 and "另存为" in old.json()["message"]


def test_scanned_pdf_goes_through_ocr(client):
    make_tenant("a", "13811110001")
    teacher = auth(client, "13811110001")
    r = _upload(client, teacher, "scan.pdf", make_pdf([None]))
    assert (r["status"], r["ocr_pages"]) == ("ready", 1)
    [chunk] = client.get(f"/api/teacher/resources/{r['id']}/chunks", headers=teacher).json()
    assert chunk["text"].startswith("[mock:ocr]")  # 开发环境没有模型 Key，走 mock


def test_broken_file_fails_and_can_be_deleted(client, database):
    make_tenant("a", "13811110001")
    teacher = auth(client, "13811110001")
    r = _upload(client, teacher, "broken.docx", b"not a zip")
    assert r["status"] == "failed" and "打不开" in r["error"]

    with open_session(bypass=True) as db:
        key = db.get(Resource, r["id"]).storage_key
    from app.core.config import get_settings

    path = get_settings().storage_dir / key
    assert path.exists()
    assert client.delete(f"/api/teacher/resources/{r['id']}", headers=teacher).json() == {"ok": True}
    assert not path.exists()
    assert client.get(f"/api/teacher/resources/{r['id']}", headers=teacher).status_code == 404


def test_reparse_and_stale(client):
    make_tenant("a", "13811110001")
    teacher = auth(client, "13811110001")
    r = _upload(client, teacher, "note.md", NOTE.encode())
    assert r["pages"] == 0  # 纯文本没有页
    again = client.post(f"/api/teacher/resources/{r['id']}/reparse", headers=teacher)
    assert again.status_code == 200
    assert client.get(f"/api/teacher/resources/{r['id']}", headers=teacher).json()["status"] == "ready"
    with open_session(bypass=True) as db:
        assert db.scalar(select(ResourceChunk.seq).where(ResourceChunk.resource_id == r["id"]).limit(1)) == 0

    # 解析中途服务重启：长时间没有进度，显示为失败，可以重新解析
    with session_scope(bypass=True) as db:
        res = db.get(Resource, r["id"])
        res.status = ResourceStatus.PARSING
        res.updated_at = datetime.now(UTC) - timedelta(hours=1)
    stale = client.get(f"/api/teacher/resources/{r['id']}", headers=teacher).json()
    assert stale["status"] == "failed" and "中断" in stale["error"]


def test_visibility_and_sharing(client):
    make_tenant("a", "13811110001")
    make_tenant("b", "13811110002")
    owner = auth(client, "13811110001")
    colleague = _teacher(client, owner, "13811110010")
    other_school = auth(client, "13811110002")
    r = _upload(client, owner, "note.md", NOTE.encode(), subject="数学")
    query = {"query": "有理数的分类"}

    assert client.get("/api/teacher/resources", headers=colleague).json() == []
    assert client.post("/api/teacher/resources/search", headers=colleague, json=query).json() == []
    assert client.get(f"/api/teacher/resources/{r['id']}/chunks", headers=colleague).status_code == 404

    shared = client.patch(f"/api/teacher/resources/{r['id']}", headers=owner, json={"shared": True}).json()
    assert shared["shared"] is True and shared["subject"] == "数学"  # 没传的字段不变

    listed = client.get("/api/teacher/resources", headers=colleague).json()
    assert [(x["id"], x["mine"], x["owner_name"]) for x in listed] == [(r["id"], False, "a 管理员")]
    assert client.post("/api/teacher/resources/search", headers=colleague, json=query).json()
    assert client.delete(f"/api/teacher/resources/{r['id']}", headers=colleague).status_code == 403
    assert client.post(f"/api/teacher/resources/{r['id']}/reparse", headers=colleague).status_code == 403

    # 共享只在本机构内
    assert client.get("/api/teacher/resources", headers=other_school).json() == []
    assert client.get(f"/api/teacher/resources/{r['id']}", headers=other_school).status_code == 404


def _generate(client, headers, body) -> list[tuple[str, dict]]:
    events = []
    with client.stream("POST", "/api/teacher/lesson-plans/generate", headers=headers, json=body) as resp:
        assert resp.status_code == 200
        name = None
        for line in resp.iter_lines():
            if line.startswith("event: "):
                name = line[7:]
            elif line.startswith("data: "):
                events.append((name, json.loads(line[6:])))
    return events


def test_lesson_plan_cites_library(client, monkeypatch):
    fake = FakeGateway(PLAN.replace("引入**有理数**的概念。", "引入**有理数**的概念 [1]。"))
    monkeypatch.setattr(generation, "get_gateway", lambda: fake)
    make_tenant("a", "13811110001")
    teacher = auth(client, "13811110001")
    r = _upload(client, teacher, "有理数笔记.md", NOTE.encode(), subject="数学")

    events = _generate(client, teacher, {**BODY, "topic": "有理数的分类"})
    names = [n for n, _ in events]
    assert names[:2] == ["created", "delta"] and "sources" in names
    sources = dict(events)["sources"]["items"]
    assert sources[0]["resource_id"] == r["id"] and sources[0]["label"] == "《有理数笔记.md》"
    prompt = fake.calls[0]["messages"][1]["content"]
    assert "[1] 《有理数笔记.md》" in prompt and "有限小数和无限循环小数" in prompt
    assert events[-1] == ("done", {"id": events[0][1]["id"], "warnings": []})

    def last_heading(doc_id: str) -> str:
        doc = client.get(f"/api/teacher/documents/{doc_id}", headers=teacher).json()
        return [n for n in doc["content"]["content"] if n["type"] == "heading"][-1]["content"][0]["text"]

    assert last_heading(events[0][1]["id"]) == "参考资料"
    with open_session(bypass=True) as db:
        saved = db.get(Document, events[0][1]["id"]).params["sources"]
    assert (saved[0]["chunk_id"], saved[0]["cited"]) == (sources[0]["chunk_id"], True)

    # 检索到了但正文没引用：不附参考资料，免得老师以为用了
    fake.text = PLAN
    events = _generate(client, teacher, {**BODY, "topic": "有理数的分类"})
    assert "sources" in [n for n, _ in events]
    assert last_heading(events[0][1]["id"]) == "九、教学反思"

    # 关掉资料库：不检索
    fake.calls.clear()
    events = _generate(client, teacher, {**BODY, "topic": "有理数的分类", "use_library": False})
    assert "sources" not in [n for n, _ in events]
    assert "资料库" not in fake.calls[0]["messages"][1]["content"]

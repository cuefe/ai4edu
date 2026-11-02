"""M2 测试用的一所学校：一个班、一位老师（也是机构管理员）、两名学生，外加入库的题、讲义和卡片组。"""

import uuid
from dataclasses import dataclass, field

from fastapi.testclient import TestClient

from app.core.db import session_scope
from app.modules.content.markdown import markdown_to_doc
from app.modules.content.models import DocStatus, Document
from app.modules.recite.models import ReciteCard, ReciteDeck
from tests.conftest import auth, make_tenant, student_auth

QUESTIONS = {
    "single": {
        "qtype": "单选题",
        "stem": "$-3$ 的相反数是",
        "options": ["$3$", "$-3$", "$\\frac{1}{3}$", "$0$"],
        "answer": "A",
        "analysis": "只有符号不同的两个数互为相反数。",
        "knowledge_points": ["相反数"],
    },
    "multi": {
        "qtype": "多选题",
        "stem": "下列数中是负数的有",
        "options": ["$-1$", "$0$", "$-0.5$", "$2$"],
        "answer": "AC",
        "knowledge_points": ["正数和负数"],
    },
    "fill": {
        "qtype": "填空题",
        "stem": "$|-3|=$＿＿＿＿，$\\frac{1}{2}$ 的相反数是＿＿＿＿",
        "answer": "3；$-\\frac{1}{2}$",
        "knowledge_points": ["绝对值", "相反数"],
    },
    "solve": {
        "qtype": "解答题",
        "stem": "计算：$(-2)+5-(-3)$",
        "answer": "6",
        "analysis": "$(-2)+5-(-3)=3+3=6$",
        "knowledge_points": ["有理数的加减"],
    },
}


@dataclass
class School:
    tenant_id: uuid.UUID
    teacher: dict[str, str]
    teacher_id: uuid.UUID
    class_id: uuid.UUID
    students: list[dict[str, str]] = field(default_factory=list)
    student_ids: list[uuid.UUID] = field(default_factory=list)
    questions: dict[str, str] = field(default_factory=dict)
    doc_id: uuid.UUID | None = None
    deck_id: uuid.UUID | None = None


def make_school(
    client: TestClient, code: str = "a", phone: str = "13811110001", n_students: int = 2
) -> School:
    tenant = make_tenant(code, phone)
    teacher = auth(client, phone)
    me = client.get("/api/me", headers=teacher).json()
    klass = client.post(
        "/api/org/classes", headers=teacher, json={"name": "初一(1)班", "grade": "初一"}
    ).json()
    client.post(
        f"/api/org/classes/{klass['id']}/members",
        headers=teacher,
        json={"user_id": me["id"], "member_role": "teacher", "subject": "数学"},
    )
    school = School(tenant.id, teacher, uuid.UUID(me["id"]), uuid.UUID(klass["id"]))
    for i in range(1, n_students + 1):
        out = client.post(
            "/api/org/students",
            headers=teacher,
            json={"name": f"学生{i}", "username": f"s{i}", "class_id": klass["id"], "password": "s12345"},
        ).json()
        school.student_ids.append(uuid.UUID(out["user"]["id"]))
        school.students.append(student_auth(client, code, f"s{i}", "s12345"))
    for key, q in QUESTIONS.items():
        resp = client.post("/api/teacher/questions", headers=teacher, json={"subject": "数学", **q})
        assert resp.status_code == 200, resp.text
        school.questions[key] = resp.json()["id"]
    with session_scope(bypass=True) as db:
        doc = Document(
            tenant_id=tenant.id,
            owner_id=school.teacher_id,
            doc_type="handout",
            title="1.2.4 绝对值",
            subject="数学",
            status=DocStatus.READY,
            content=markdown_to_doc("# 1.2.4 绝对值\n\n**【考点】** 一个负数的绝对值是它的相反数"),
        )
        deck = ReciteDeck(tenant_id=tenant.id, owner_id=school.teacher_id, title="绝对值 必背", card_count=2)
        db.add_all([doc, deck])
        db.flush()
        db.add_all(
            [
                ReciteCard(
                    tenant_id=tenant.id, deck_id=deck.id, seq=0, kind="cloze", front="0 的绝对值是{{0}}"
                ),
                ReciteCard(
                    tenant_id=tenant.id, deck_id=deck.id, seq=1, kind="qa", front="$|-5|$ 等于？", back="5"
                ),
            ]
        )
        school.doc_id, school.deck_id = doc.id, deck.id
    return school


def assign(client: TestClient, school: School, keys=("single", "multi", "fill", "solve"), **extra) -> dict:
    items = [{"item_type": "question", "ref_id": school.questions[k]} for k in keys]
    items += [
        {"item_type": "document", "ref_id": str(school.doc_id)},
        {"item_type": "recite", "ref_id": str(school.deck_id)},
    ]
    body = {
        "title": "第一章练习",
        "subject": "数学",
        "class_ids": [str(school.class_id)],
        "items": items,
        **extra,
    }
    resp = client.post("/api/teacher/assignments", headers=school.teacher, json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()

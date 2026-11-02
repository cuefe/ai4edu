import json

import pytest

from app.ai.skills import handout
from app.ai.skills.recite_cards.prompt import fix_cloze_in_math
from app.modules.content import generation
from app.modules.content.markdown import doc_to_markdown, markdown_to_doc
from app.modules.recite import service as recite_service
from tests.conftest import auth, make_tenant
from tests.fake_ai import FakeChat
from tests.test_lesson_plan import FakeGateway

BODY = {"subject": "数学", "grade": "七年级上册", "topic": "1.2.4 绝对值"}

HANDOUT = """## 一、学习目标
1. 能说出绝对值的意义。

## 二、知识梳理
**【考点】** 一个正数的绝对值是它本身；一个负数的绝对值是它的相反数；0 的绝对值是 0。

## 三、典型例题
例 1 求 $|-3|$。
【分析】负数的绝对值是它的相反数。
【解答】$|-3|=3$。

## 四、易错提醒
- 误以为 $|a|=a$ 对所有数成立。

## 五、课堂练习
1. $|-5|=$＿＿＿＿
2. $|0|=$＿＿＿＿

## 六、参考答案
1. 5
"""


def _events(client, headers, body) -> list[tuple[str, dict]]:
    events = []
    with client.stream("POST", "/api/teacher/handouts/generate", headers=headers, json=body) as resp:
        assert resp.status_code == 200, resp.read()
        name = None
        for line in resp.iter_lines():
            if line.startswith("event: "):
                name = line[7:]
            elif line.startswith("data: "):
                events.append((name, json.loads(line[6:])))
    return events


def test_handout_generation(client, monkeypatch):
    fake = FakeGateway(HANDOUT)
    monkeypatch.setattr(generation, "get_gateway", lambda: fake)
    make_tenant("a", "13811110001")
    teacher = auth(client, "13811110001")

    events = _events(client, teacher, BODY)
    doc_id = events[0][1]["id"]
    # 练习 2 道、答案只有 1 条
    assert events[-1] == (
        "done",
        {"id": doc_id, "warnings": ["课堂练习有 2 道题，参考答案只有 1 条，请核对"]},
    )
    assert fake.calls[0]["skill"] == "handout"
    system = fake.calls[0]["messages"][0]["content"]
    assert "## 六、参考答案" in system and "【考点】" in system

    doc = client.get(f"/api/teacher/documents/{doc_id}", headers=teacher).json()
    assert (doc["doc_type"], doc["params"]["kind"]) == ("handout", "课堂讲义")
    assert doc["content"]["content"][0]["content"][0]["text"] == "1.2.4 绝对值"
    handouts = client.get("/api/teacher/documents", headers=teacher, params={"doc_type": "handout"}).json()
    assert [d["id"] for d in handouts] == [doc_id]
    assert client.get("/api/teacher/documents", headers=teacher).json() == []  # 默认只列教案

    word = client.get(f"/api/teacher/documents/{doc_id}/docx", headers=teacher)
    assert word.status_code == 200


def test_review_handout_checks(client, monkeypatch):
    monkeypatch.setattr(generation, "get_gateway", lambda: FakeGateway("## 一、知识框架\n- 有理数\n"))
    make_tenant("a", "13811110001")
    teacher = auth(client, "13811110001")
    events = _events(client, teacher, {**BODY, "kind": "复习讲义", "topic": "第一章 有理数 复习"})
    warnings = events[-1][1]["warnings"]
    assert warnings[0].startswith("缺少以下部分：考点梳理、易错提醒、巩固练习、参考答案")
    assert warnings[1] == "考点梳理没有按考点分条"
    assert handout.SECTIONS["复习讲义"][0] == "知识框架"


def test_doc_to_markdown_round_trip():
    md = "\n\n".join(
        [
            "# 标题",
            "**【考点】** 绝对值 $|a|$",
            "1. 第一条\n2. 第二条",
            "| 数 | 绝对值 |\n| --- | --- |\n| -3 | 3 |",
            "$$\nx^2\n$$",
        ]
    )
    text = doc_to_markdown(markdown_to_doc(md))
    assert text.startswith("# 标题\n\n**【考点】** 绝对值 $|a|$")
    assert "1. 第一条\n2. 第二条" in text
    assert "| -3 | 3 |" in text and "$$x^2$$" in text


# —— 背诵卡片 ——

CARDS = {
    "cards": [
        {"kind": "cloze", "front": "一个负数的绝对值是它的{{相反数}}", "back": ""},
        {"kind": "qa", "front": "0 的绝对值是多少？", "back": "0"},
        {"kind": "qa", "front": "一个{{正数}}的绝对值是它本身", "back": ""},  # 有挖空：按挖空卡算
        {"kind": "cloze", "front": "没有挖空的句子", "back": ""},  # 挖空卡没有空：丢掉
        {"kind": "qa", "front": "0 的绝对值是多少？", "back": "0"},  # 重复：丢掉
        {"kind": "qa", "front": "没有答案的问题", "back": ""},  # 问答卡没答案：丢掉
    ]
}


@pytest.fixture
def cards_ai(monkeypatch):
    fake = FakeChat(lambda skill, messages: json.dumps(CARDS, ensure_ascii=False))
    monkeypatch.setattr(recite_service, "get_gateway", lambda: fake)
    return fake


def test_recite_from_handout(client, monkeypatch, cards_ai):
    monkeypatch.setattr(generation, "get_gateway", lambda: FakeGateway(HANDOUT))
    make_tenant("a", "13811110001")
    make_tenant("b", "13811110002")
    teacher = auth(client, "13811110001")
    doc_id = _events(client, teacher, BODY)[0][1]["id"]

    body = {"subject": "数学", "grade": "七年级上册", "title": "绝对值 必背", "doc_id": doc_id}
    resp = client.post("/api/teacher/recite-decks/generate", headers=teacher, json=body)
    assert resp.status_code == 200, resp.text
    deck = resp.json()
    assert [(c["kind"], c["front"]) for c in deck["cards"]] == [
        ("cloze", "一个负数的绝对值是它的{{相反数}}"),
        ("qa", "0 的绝对值是多少？"),
        ("cloze", "一个{{正数}}的绝对值是它本身"),
    ]
    assert (deck["card_count"], deck["source_doc_id"]) == (3, doc_id)
    assert deck["warnings"] == ["有 3 张卡片格式不对或重复，已经去掉"]
    call = cards_ai.calls[0]
    assert call["skill"] == "recite_cards" and call["params"]["response_format"] == {"type": "json_object"}
    assert "**【考点】** 一个正数的绝对值是它本身" in call["messages"][1]["content"]  # 读的是讲义正文

    # 修改：整组替换
    cards = [{"kind": "qa", "front": "$|-3|$ 等于多少？", "back": "3"}, deck["cards"][0]]
    updated = client.put(
        f"/api/teacher/recite-decks/{deck['id']}", headers=teacher, json={"title": "新标题", "cards": cards}
    ).json()
    assert (updated["title"], updated["card_count"]) == ("新标题", 2)
    assert [c["front"] for c in updated["cards"]] == ["$|-3|$ 等于多少？", "一个负数的绝对值是它的{{相反数}}"]
    bad = [{"kind": "cloze", "front": "没有挖空", "back": ""}]
    resp = client.put(
        f"/api/teacher/recite-decks/{deck['id']}", headers=teacher, json={"title": "x", "cards": bad}
    )
    assert resp.status_code == 422

    listed = client.get("/api/teacher/recite-decks", headers=teacher).json()
    assert [(d["id"], d["card_count"]) for d in listed] == [(deck["id"], 2)]
    other = auth(client, "13811110002")
    assert client.get(f"/api/teacher/recite-decks/{deck['id']}", headers=other).status_code == 404

    # 删除讲义，卡片组保留
    client.delete(f"/api/teacher/documents/{doc_id}", headers=teacher)
    kept = client.get(f"/api/teacher/recite-decks/{deck['id']}", headers=teacher).json()
    assert kept["source_doc_id"] is None and kept["card_count"] == 2
    assert client.delete(f"/api/teacher/recite-decks/{deck['id']}", headers=teacher).json() == {"ok": True}


@pytest.mark.parametrize(
    ("front", "fixed"),
    [
        ("对任意有理数 $a$，都有 $|a|{{\\ge 0}}$", "对任意有理数 $a$，都有 $|a|${{$\\ge 0$}}"),
        ("$x=${{0}}，$y={{1}}+z$", "$x=${{0}}，$y=${{$1$}}$+z$"),
        ("公式：{{$(a+b)^2$}}", "公式：{{$(a+b)^2$}}"),
        ("$$x^2$$ 不动", "$$x^2$$ 不动"),
    ],
)
def test_cloze_moved_out_of_math(front, fixed):
    assert fix_cloze_in_math(front) == fixed


def test_recite_from_text_and_errors(client, cards_ai):
    make_tenant("a", "13811110001")
    teacher = auth(client, "13811110001")
    base = {"subject": "英语", "grade": "七年级上册", "title": "Unit 1 必背"}

    empty = client.post("/api/teacher/recite-decks/generate", headers=teacher, json=base)
    assert empty.status_code == 400 and "粘贴" in empty.json()["message"]

    ok = client.post(
        "/api/teacher/recite-decks/generate", headers=teacher, json={**base, "text": "Good morning!"}
    )
    assert ok.status_code == 200 and ok.json()["subject"] == "英语"
    assert "单词卡用问答" in cards_ai.calls[0]["messages"][0]["content"]

    cards_ai.handler = lambda skill, messages: json.dumps({"cards": []})
    none = client.post("/api/teacher/recite-decks/generate", headers=teacher, json={**base, "text": "你好"})
    assert none.status_code == 400 and "没有从材料里找到" in none.json()["message"]

    cards_ai.handler = lambda skill, messages: "不是 JSON"
    broken = client.post("/api/teacher/recite-decks/generate", headers=teacher, json={**base, "text": "你好"})
    assert broken.status_code == 502

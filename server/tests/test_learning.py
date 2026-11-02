import json
from datetime import UTC, datetime

import pytest

from app.modules.learning import service as learning
from tests.fake_ai import FakeChat
from tests.school import assign, make_school

GUIDE = {
    "analysis": "题目问的是 $-3$ 的相反数。",
    "knowledge": "相反数：只有符号不同的两个数。",
    "steps": ["第 1 步：把符号变一下", "第 2 步：得到 \\(3\\)"],
    "summary": "求相反数就是改变符号，不要和倒数混淆。",
}


@pytest.fixture
def guide_ai(monkeypatch):
    fake = FakeChat(lambda skill, messages: json.dumps(GUIDE, ensure_ascii=False))
    monkeypatch.setattr(learning, "get_gateway", lambda: fake)
    return fake


def test_wrong_book_and_correction(client, guide_ai):
    school = make_school(client, n_students=1)
    [s1] = school.students
    aid = assign(client, school, keys=("single", "fill", "solve"))["id"]
    items = client.get(f"/api/student/assignments/{aid}", headers=s1).json()["items"]
    single, fill = items[0]["id"], items[1]["id"]
    client.put(f"/api/student/assignments/{aid}/answers/{single}", headers=s1, json={"response": "B"})
    client.put(f"/api/student/assignments/{aid}/answers/{fill}", headers=s1, json={"response": "3；0.5"})
    client.post(f"/api/student/assignments/{aid}/submit", headers=s1)

    book = client.get("/api/student/wrong-items", headers=s1).json()
    assert book["pending"] == 3 and book["corrected"] == 0  # 单选错、填空错一个空、解答题没写
    assert book["knowledge_points"] == ["有理数的加减", "相反数", "绝对值"]
    assert (
        len(
            client.get("/api/student/wrong-items", headers=s1, params={"knowledge_point": "绝对值"}).json()[
                "items"
            ]
        )
        == 1
    )
    by_type = {w["question"]["qtype"]: w for w in book["items"]}
    w_single, w_solve = by_type["单选题"], by_type["解答题"]
    assert (w_single["wrong_response"], w_single["question"]["answer"]) == ("B", "A")

    # 客观题重做：做错次数加一；做对就订正好了
    wrong = client.post(
        f"/api/student/wrong-items/{w_single['id']}/redo", headers=s1, json={"response": "C"}
    ).json()
    assert (wrong["correct"], wrong["item"]["wrong_count"], wrong["item"]["status"]) == (False, 2, "pending")
    right = client.post(
        f"/api/student/wrong-items/{w_single['id']}/redo", headers=s1, json={"response": "A"}
    ).json()
    assert (right["correct"], right["item"]["status"]) == (True, "corrected")

    # 解答题：判断不了，对照答案自己判断
    unsure = client.post(
        f"/api/student/wrong-items/{w_solve['id']}/redo", headers=s1, json={"response": "6"}
    ).json()
    assert unsure["correct"] is None
    checked = client.post(
        f"/api/student/wrong-items/{w_solve['id']}/self-check", headers=s1, json={"correct": True}
    )
    assert checked.json()["status"] == "corrected"

    # 四步引导：生成一次后缓存
    g1 = client.post(f"/api/student/wrong-items/{w_single['id']}/guide", headers=s1).json()
    g2 = client.post(f"/api/student/wrong-items/{w_single['id']}/guide", headers=s1).json()
    assert g1 == g2 and g1["steps"][1] == "第 2 步：得到 $3$"
    assert len(guide_ai.calls) == 1 and "学生做错时的作答：B" in guide_ai.calls[0]["messages"][1]["content"]

    final = client.get("/api/student/wrong-items", headers=s1).json()
    assert (final["pending"], final["corrected"]) == (1, 2)
    assert client.delete(f"/api/student/wrong-items/{by_type['填空题']['id']}", headers=s1).json() == {
        "ok": True
    }
    other = make_school(client, code="b", phone="13811110002", n_students=1).students[0]
    assert client.get(f"/api/student/wrong-items/{w_single['id']}", headers=other).status_code == 404


def test_recite_review_with_fsrs(client):
    school = make_school(client, n_students=1)
    [s1] = school.students
    aid = assign(client, school, keys=())["id"]
    today = client.get("/api/student/review/today", headers=s1).json()
    assert (today["due_count"], today["new_count"]) == (0, 2)
    assert [d["total"] for d in today["decks"]] == [2]
    first, second = today["cards"]
    assert (first["kind"], first["front"], first["new"]) == ("cloze", "0 的绝对值是{{0}}", True)

    out = client.post(f"/api/student/review/{first['item_id']}/0", headers=s1, json={"rating": 3}).json()
    assert datetime.fromisoformat(out["due"]) > datetime.now(UTC)
    # 忘了：很快再出现
    client.post(f"/api/student/review/{second['item_id']}/1", headers=s1, json={"rating": 1})
    today = client.get("/api/student/review/today", headers=s1).json()
    assert today["new_count"] == 0 and today["decks"][0]["learned"] == 2

    # 两张都学过，作业里的背诵项算完成
    detail = client.get(f"/api/student/assignments/{aid}", headers=s1).json()
    recite = next(i for i in detail["items"] if i["item_type"] == "recite")
    assert detail["recite_progress"] == {recite["id"]: 2} and detail["progress_done"] == 1

    assert (
        client.post(f"/api/student/review/{first['item_id']}/9", headers=s1, json={"rating": 3}).status_code
        == 404
    )
    assert (
        client.post(f"/api/student/review/{first['item_id']}/0", headers=s1, json={"rating": 5}).status_code
        == 422
    )

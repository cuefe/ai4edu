"""每周个性化试卷：组卷规则、掌握度、发卷、成绩反馈到下一周。"""

import json
import random
import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.core.db import open_session, session_scope
from app.modules.assignment import tasks as grading_tasks
from app.modules.assignment.models import Assignment, AssignmentItem
from app.modules.curriculum import pack as content_pack
from app.modules.curriculum import pool
from app.modules.curriculum.models import Chapter, KnowledgePoint, PoolQuestion, Textbook
from app.modules.learning.models import KpEvidence
from app.modules.learning.service import compute_mastery, mastery
from app.modules.notify.models import Notification
from app.modules.weekly import compose as rules
from app.modules.weekly import service as weekly
from app.modules.weekly import tasks as weekly_tasks
from app.modules.weekly.models import ClassProgress, WeeklyPaper
from app.workers import dispatch
from app.workers.celery_app import celery_app
from tests.conftest import auth, make_platform_admin, make_tenant
from tests.fake_ai import FakeChat
from tests.school import School, make_school

# 模拟过去的四周：卷子要已经发布，学生才能打开
THIS_WEEK = weekly.week_of()
WEEK1, WEEK2, WEEK3, WEEK4 = (THIS_WEEK - timedelta(days=7 * n) for n in (4, 3, 2, 1))


# —— 组卷规则（纯函数）——


def _item(section, qtype="单选题", difficulty="中等", kps=()):
    return rules.PoolItem(uuid.uuid4(), section, qtype, difficulty, tuple(kps))


def _full_pool(section, kp, n=20):
    """每种题型、每种难度都有 n 道。"""
    return [
        _item(section, qtype, difficulty, (kp,))
        for qtype in ("单选题", "填空题", "解答题")
        for difficulty in rules.DIFFICULTIES
        for _ in range(n)
    ]


def _compose(pool_items, **kw):
    args = {
        "this_week": set(),
        "learned": set(),
        "weak_kps": [],
        "wrong_kps": [],
        "seen": set(),
        "level": 2,
        "rng": random.Random(1),
    }
    return rules.compose(pool_items, **{**args, **kw})


@pytest.mark.parametrize(
    ("level", "ratio", "expected"),
    [
        (None, None, 2),  # 第一份
        (2, None, 2),  # 没提交：不变
        (2, 0.85, 3),  # 刚好 85% 升一档
        (2, 0.849, 2),
        (2, 0.6, 2),  # 刚好 60% 不变
        (2, 0.59, 1),
        (3, 1.0, 3),  # 已经最高
        (1, 0.0, 1),  # 已经最低
    ],
)
def test_next_level(level, ratio, expected):
    new_level, reason = rules.next_level(level, ratio)
    assert new_level == expected
    assert reason


def test_difficulty_slots_shift_with_level():
    def hard(level):
        return rules.difficulty_slots(8, level).count("较难")

    assert all(len(rules.difficulty_slots(n, lv)) == n for n in (2, 4, 8) for lv in (1, 2, 3))
    assert hard(1) < hard(2) < hard(3)
    assert rules.difficulty_slots(8, 1).count("容易") > rules.difficulty_slots(8, 3).count("容易")


def test_scale_scores_always_total_100():
    assert sum(rules.scale_scores([5] * 8 + [5] * 4 + [20] * 2)) == 100
    assert sum(rules.scale_scores([5, 5, 5, 20, 20, 5, 5])) == 100
    assert rules.scale_scores([]) == []


def test_first_week_is_all_this_week_and_totals_100():
    now_sec, future = uuid.uuid4(), uuid.uuid4()
    kp = uuid.uuid4()
    pool_items = _full_pool(now_sec, kp) + _full_pool(future, uuid.uuid4())
    paper = _compose(pool_items, this_week={now_sec})
    assert len(paper.picked) == 14 and paper.shortage == 0
    assert paper.counts == {rules.ORIGIN_THIS_WEEK: 14}
    assert {p.item.section_id for p in paper.picked} == {now_sec}  # 没教的不考
    assert sum(p.score for p in paper.picked) == 100
    assert [p.item.qtype for p in paper.picked] == ["单选题"] * 8 + ["填空题"] * 4 + ["解答题"] * 2


def test_mix_of_this_week_weak_and_wrong():
    now_sec, past = uuid.uuid4(), uuid.uuid4()
    kp_now, kp_weak, kp_wrong = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    pool_items = _full_pool(now_sec, kp_now) + _full_pool(past, kp_weak) + _full_pool(past, kp_wrong)
    paper = _compose(
        pool_items, this_week={now_sec}, learned={past}, weak_kps=[kp_weak], wrong_kps=[kp_wrong]
    )
    assert paper.counts == {rules.ORIGIN_THIS_WEEK: 10, rules.ORIGIN_WEAK: 3, rules.ORIGIN_WRONG: 1}
    for p in paper.picked:
        expected = {rules.ORIGIN_THIS_WEEK: kp_now, rules.ORIGIN_WEAK: kp_weak, rules.ORIGIN_WRONG: kp_wrong}
        assert expected[p.origin] in p.item.kp_ids
    # 解答题要老师确认：薄弱点和错题的位置只用客观题
    assert all(p.item.qtype != "解答题" for p in paper.picked if p.origin != rules.ORIGIN_THIS_WEEK)


def test_weak_point_in_untaught_section_is_never_used():
    now_sec, future = uuid.uuid4(), uuid.uuid4()
    kp_now, kp_future = uuid.uuid4(), uuid.uuid4()
    pool_items = _full_pool(now_sec, kp_now) + _full_pool(future, kp_future)
    paper = _compose(pool_items, this_week={now_sec}, weak_kps=[kp_future], wrong_kps=[kp_future])
    assert {p.item.section_id for p in paper.picked} == {now_sec}


def test_weakest_point_comes_first():
    now_sec, past = uuid.uuid4(), uuid.uuid4()
    weakest, weaker = uuid.uuid4(), uuid.uuid4()
    pool_items = _full_pool(now_sec, uuid.uuid4()) + _full_pool(past, weakest) + _full_pool(past, weaker)
    paper = _compose(pool_items, this_week={now_sec}, learned={past}, weak_kps=[weakest, weaker])
    picked = [p for p in paper.picked if p.origin == rules.ORIGIN_WEAK]
    assert picked and all(weakest in p.item.kp_ids for p in picked)


def test_seen_questions_excluded_and_result_is_repeatable():
    section, kp = uuid.uuid4(), uuid.uuid4()
    pool_items = _full_pool(section, kp)
    first = _compose(pool_items, this_week={section})
    again = _compose(pool_items, this_week={section})
    assert [p.item.id for p in first.picked] == [p.item.id for p in again.picked]  # 同样的输入同样的卷子
    other = _compose(pool_items, this_week={section}, rng=random.Random(2))
    assert {p.item.id for p in other.picked} != {p.item.id for p in first.picked}  # 不同学生不一样
    seen = {p.item.id for p in first.picked}
    next_week = _compose(pool_items, this_week={section}, seen=seen)
    assert not seen & {p.item.id for p in next_week.picked}


def test_level_changes_what_is_picked():
    section, kp = uuid.uuid4(), uuid.uuid4()
    pool_items = _full_pool(section, kp)

    def hard_count(level):
        paper = _compose(pool_items, this_week={section}, level=level)
        return sum(p.item.difficulty == "较难" for p in paper.picked)

    assert hard_count(1) < hard_count(2) < hard_count(3)


def test_short_pool_falls_back_and_reports_shortage():
    now_sec, past = uuid.uuid4(), uuid.uuid4()
    kp = uuid.uuid4()
    # 本周只有 3 道单选，学过的内容有 2 道填空：全用上，其余位置报缺
    pool_items = [_item(now_sec, "单选题", "中等", (kp,)) for _ in range(3)]
    pool_items += [_item(past, "填空题", "容易", (kp,)) for _ in range(2)]
    paper = _compose(pool_items, this_week={now_sec}, learned={past})
    assert len(paper.picked) == 5 and paper.shortage == 9
    assert paper.counts == {rules.ORIGIN_THIS_WEEK: 3, rules.ORIGIN_REVIEW: 2}
    assert sum(p.score for p in paper.picked) == 100

    # 客观题不够时不会用解答题凑，免得增加批改量
    only_solve = [_item(now_sec, "解答题", "中等", (kp,)) for _ in range(10)]
    paper = _compose(only_solve, this_week={now_sec})
    assert len(paper.picked) == 2


# —— 掌握度 ——


def test_mastery_decays_with_time():
    kp = uuid.uuid4()
    at = datetime(2026, 11, 30, tzinfo=UTC)
    # 一道题答对、答错，先验把结果拉向中间
    assert compute_mastery([(kp, 1.0, at)], at)[kp] == pytest.approx(0.75)
    assert compute_mastery([(kp, 0.0, at)], at)[kp] == pytest.approx(0.25)
    # 最近做对、以前做错，比反过来的掌握度高
    long_ago = at - timedelta(weeks=8)
    improving = compute_mastery([(kp, 0.0, long_ago), (kp, 1.0, at)], at)[kp]
    slipping = compute_mastery([(kp, 1.0, long_ago), (kp, 0.0, at)], at)[kp]
    assert improving > 0.6 > 0.4 > slipping


# —— 准备数据 ——


def _make_book(sections=3, per_type=(18, 9, 6), key="rj-math-9a", subject="数学") -> uuid.UUID:
    """一册书：sections 节，每节 2 个知识点，题库里每种题型各若干道（三种难度轮流）。"""
    numbers = [f"25.{i + 1}" for i in range(sections)]
    raw = {
        "key": key,
        "stage": "初中",
        "subject": subject,
        "edition": "人教版",
        "grade": "初一",
        "title": "九年级上册",
        "chapters": [
            {
                "no": "25",
                "title": "方程",
                "sections": [
                    {
                        "no": no,
                        "title": f"第{no}节",
                        "knowledge_points": [
                            {
                                "name": f"{no}甲",
                                "content": "内容",
                                "kind": "概念",
                                "importance": "核心",
                                "recite": False,
                            },
                            {
                                "name": f"{no}乙",
                                "content": "内容",
                                "kind": "方法",
                                "importance": "重点",
                                "recite": False,
                            },
                        ],
                    }
                    for no in numbers
                ],
            }
        ],
    }
    questions = []
    for no in numbers:
        for qtype, count in zip(("单选题", "填空题", "解答题"), per_type, strict=True):
            for i in range(count):
                questions.append(
                    {
                        "section_no": no,
                        "qtype": qtype,
                        "difficulty": rules.DIFFICULTIES[i % 3],
                        "stem": f"{no} {qtype} 第 {i} 题＿＿＿＿",
                        "options": ["一", "二", "三", "四"] if qtype == "单选题" else [],
                        "answer": {"单选题": "A", "填空题": "7", "解答题": "6"}[qtype],
                        "analysis": "解析",
                        "knowledge_points": [f"{no}{'甲' if i % 2 else '乙'}"],
                        "source": "generated",
                        "status": "checked",
                    }
                )
    with session_scope(bypass=True) as db:
        result = content_pack.import_pack(db, content_pack.BookPack.model_validate(raw), publish=True)
        pool.import_pool(db, pool.PoolPack(book_key=key, questions=questions))
        pool.approve_checked(db, result.book_id, None, None)
        return result.book_id


def _sections(book_id: uuid.UUID) -> dict[str, uuid.UUID]:
    with session_scope(bypass=True) as db:
        return {
            c.no: c.id
            for c in db.scalars(
                select(Chapter).where(Chapter.book_id == book_id, Chapter.parent_id.is_not(None))
            )
        }


def _set_progress(client, school: School, book_id, section_ids, **extra):
    resp = client.put(
        f"/api/teacher/weekly/classes/{school.class_id}/progress",
        headers=school.teacher,
        json={"book_id": str(book_id), "section_ids": [str(s) for s in section_ids], **extra},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _issue(school: School, week: date, subject="数学") -> weekly.IssueResult:
    """按指定的周发卷，模拟一周一周过去。"""
    with session_scope(tenant_id=school.tenant_id) as db:
        progress = db.scalar(
            select(ClassProgress).where(
                ClassProgress.klass_id == school.class_id, ClassProgress.subject == subject
            )
        )
        at = datetime.combine(week + timedelta(days=4), datetime.min.time(), tzinfo=UTC)
        return weekly.issue_class(db, progress, week=week, at=at)


def _paper(school: School, student_id: uuid.UUID, week: date) -> WeeklyPaper:
    with session_scope(tenant_id=school.tenant_id) as db:
        return db.scalar(
            select(WeeklyPaper).where(WeeklyPaper.student_id == student_id, WeeklyPaper.week_start == week)
        )


def _items(school: School, paper: WeeklyPaper) -> list[AssignmentItem]:
    with session_scope(tenant_id=school.tenant_id) as db:
        return list(
            db.scalars(
                select(AssignmentItem)
                .where(AssignmentItem.assignment_id == paper.assignment_id)
                .order_by(AssignmentItem.seq)
            )
        )


def _wrong_answer(content: dict) -> str:
    if content["qtype"] == "单选题":  # 选项打乱过，正确答案不一定是 A
        return "A" if content["answer"] != "A" else "B"
    return {"填空题": "999", "解答题": "不会"}[content["qtype"]]


def _take(client, school: School, index: int, week: date, *, right: float) -> None:
    """学生做完并提交：前 right 比例的题做对，其余做错。"""
    paper = _paper(school, school.student_ids[index], week)
    headers = school.students[index]
    items = _items(school, paper)
    for i, item in enumerate(items):
        correct = i < round(len(items) * right)
        answer = item.content["answer"] if correct else _wrong_answer(item.content)
        resp = client.put(
            f"/api/student/assignments/{paper.assignment_id}/answers/{item.id}",
            headers=headers,
            json={"response": answer},
        )
        assert resp.status_code == 200, resp.text
    resp = client.post(f"/api/student/assignments/{paper.assignment_id}/submit", headers=headers)
    assert resp.status_code == 200, resp.text


@pytest.fixture
def grader(monkeypatch):
    """解答题的 AI 批改：写了“不会”给 0 分，否则满分。"""

    def reply(skill, messages):
        wrong = "不会" in json.dumps(messages, ensure_ascii=False)
        return json.dumps(
            {"score": 0 if wrong else 100, "confidence": 0.9, "points": [], "comment": "评语"},
            ensure_ascii=False,
        )

    fake = FakeChat(reply)
    monkeypatch.setattr(grading_tasks, "build_gateway", lambda: fake)
    monkeypatch.setattr(dispatch, "submit", lambda task, *args: task.apply(args=args))
    return fake


# —— 教学进度和发卷 ——


def test_progress_permissions_and_listing(client):
    school = make_school(client)
    book = _make_book()
    sections = _sections(book)
    [row] = client.get("/api/teacher/weekly", headers=school.teacher).json()
    assert (row["subject"], row["progress"], row["week"], row["student_count"]) == ("数学", None, None, 2)

    out = _set_progress(client, school, book, [sections["25.1"]])
    assert out["progress"]["section_labels"] == ["25.1 第25.1节"]
    assert out["progress"]["up_to_date"] is True

    listed = client.get(f"/api/teacher/weekly/books/{book}/sections", headers=school.teacher).json()
    assert [(s["no"], s["approved_count"]) for s in listed] == [("25.1", 33), ("25.2", 33), ("25.3", 33)]

    # 学科对不上：这位老师在这个班教数学
    other = _make_book(key="rj-english", subject="英语")
    resp = client.put(
        f"/api/teacher/weekly/classes/{school.class_id}/progress",
        headers=school.teacher,
        json={"book_id": str(other), "section_ids": [str(next(iter(_sections(other).values())))]},
    )
    assert resp.status_code == 400 and "数学" in resp.json()["message"]
    # 节不属于这册书
    resp = client.put(
        f"/api/teacher/weekly/classes/{school.class_id}/progress",
        headers=school.teacher,
        json={"book_id": str(book), "section_ids": [str(uuid.uuid4())]},
    )
    assert resp.status_code == 400

    # 学生不能调用老师的接口；别的机构的老师碰不到这个班
    assert client.get("/api/teacher/weekly", headers=school.students[0]).status_code == 403
    make_tenant("b", "13811110009")
    outsider = auth(client, "13811110009")
    resp = client.put(
        f"/api/teacher/weekly/classes/{school.class_id}/progress",
        headers=outsider,
        json={"book_id": str(book), "section_ids": [str(sections["25.1"])]},
    )
    assert resp.status_code == 403
    assert (
        client.get(
            f"/api/teacher/weekly/classes/{school.class_id}/report",
            headers=outsider,
            params={"subject": "数学"},
        ).status_code
        == 403
    )


def test_only_approved_questions_are_issued(client):
    school = make_school(client)
    book = _make_book()
    sections = _sections(book)
    _set_progress(client, school, book, [sections["25.1"]])
    with session_scope(bypass=True) as db:
        for q in db.scalars(select(PoolQuestion).where(PoolQuestion.section_id == sections["25.1"])):
            q.status = "checked"
    resp = client.post(
        f"/api/teacher/weekly/classes/{school.class_id}/issue",
        headers=school.teacher,
        params={"subject": "数学"},
    )
    assert resp.status_code == 400 and resp.json()["code"] == "pool_empty"


def test_issue_paper_for_each_student(client):
    school = make_school(client)
    book = _make_book()
    sections = _sections(book)
    _set_progress(client, school, book, [sections["25.2"]])

    resp = client.post(
        f"/api/teacher/weekly/classes/{school.class_id}/issue",
        headers=school.teacher,
        params={"subject": "数学"},
    )
    assert resp.status_code == 200, resp.text
    result = resp.json()
    assert (result["created"], result["existing"], result["short"]) == (2, 0, [])

    # 重复调用不会重复发
    again = client.post(
        f"/api/teacher/weekly/classes/{school.class_id}/issue",
        headers=school.teacher,
        params={"subject": "数学"},
    ).json()
    assert (again["created"], again["existing"]) == (0, 2)

    # 学生收到通知；卷子是自己的；提交前看不到答案；不能问 AI
    s1, s2 = school.students
    [brief] = client.get("/api/student/assignments", headers=s1).json()
    assert (brief["kind"], brief["question_count"], brief["total_score"]) == ("weekly", 14, 100)
    notes = client.get("/api/me/notifications", headers=s1).json()
    assert notes["items"][0]["link"] == f"/student/assignments/{brief['id']}"
    detail = client.get(f"/api/student/assignments/{brief['id']}", headers=s1).json()
    assert detail["allow_ai"] is False
    assert all("answer" not in i["content"] for i in detail["items"])
    assert {i["content"]["section_no"] for i in detail["items"]} == {"25.2"}
    assert client.get(f"/api/student/assignments/{brief['id']}", headers=s2).status_code == 404

    # 第一周两个学生都是标准难度，但题不完全一样
    p1, p2 = (
        _paper(school, school.student_ids[0], weekly.week_of()),
        _paper(school, school.student_ids[1], weekly.week_of()),
    )
    assert p1.level == p2.level == 2
    assert p1.reason.startswith("这是你的第一份")
    refs1 = {i.ref_id for i in _items(school, p1)}
    refs2 = {i.ref_id for i in _items(school, p2)}
    assert refs1 != refs2

    # 周测不混进老师的作业列表，但老师能看单份报告
    assert client.get("/api/teacher/assignments", headers=school.teacher).json() == []
    assert (
        client.get(f"/api/teacher/assignments/{p1.assignment_id}", headers=school.teacher).status_code == 200
    )


def test_new_student_gets_paper_on_reissue(client):
    school = make_school(client)
    book = _make_book()
    _set_progress(client, school, book, [_sections(book)["25.1"]])
    assert _issue(school, WEEK1).created == 2
    added = client.post(
        "/api/org/students",
        headers=school.teacher,
        json={"name": "插班生", "username": "s9", "class_id": str(school.class_id), "password": "s12345"},
    )
    assert added.status_code == 200, added.text
    result = _issue(school, WEEK1)
    assert (result.created, result.existing) == (1, 2)


def test_short_pool_is_reported_not_silently_empty(client):
    school = make_school(client)
    book = _make_book(per_type=(2, 1, 0))  # 每节只有 3 道题，整本 9 道
    sections = _sections(book)
    _set_progress(client, school, book, [sections["25.1"]])
    result = _issue(school, WEEK1)
    assert result.created == 0 and sorted(result.short) == ["学生1", "学生2"]
    # 选到后面的节时，前面学过的题可以补上
    _set_progress(client, school, book, [sections["25.3"]])
    result = _issue(school, WEEK1)
    assert result.created == 2 and sorted(result.partial) == ["学生1", "学生2"]
    paper = _paper(school, school.student_ids[0], WEEK1)
    assert paper.plan["shortage"] > 0
    assert sum(i.score for i in _items(school, paper)) == 100


# —— 成绩反馈到下一周 ——


def test_score_drives_next_week(client, grader):
    school = make_school(client)
    book = _make_book()
    sections = _sections(book)
    _set_progress(client, school, book, [sections["25.1"]])
    _issue(school, WEEK1)
    strong, weak = school.student_ids
    _take(client, school, 0, WEEK1, right=1.0)
    _take(client, school, 1, WEEK1, right=0.0)

    _set_progress(client, school, book, [sections["25.2"]])
    _issue(school, WEEK2)
    p_strong, p_weak = _paper(school, strong, WEEK2), _paper(school, weak, WEEK2)
    assert (p_strong.level, p_weak.level) == (3, 1)
    assert p_strong.prev_ratio == 1.0 and p_weak.prev_ratio == 0.0
    assert "提高一档" in p_strong.reason and "降一档" in p_weak.reason

    # 考得差的：错题同类题、薄弱点都在第一周的节，且不会再做原题
    items_weak = _items(school, p_weak)
    origins = {o: sum(i.content["origin"] == o for i in items_weak) for o in ("this_week", "weak", "wrong")}
    assert origins == {"this_week": 10, "weak": 3, "wrong": 1}
    for i in items_weak:
        expected = "25.2" if i.content["origin"] == "this_week" else "25.1"
        assert i.content["section_no"] == expected
    first_refs = {i.ref_id for i in _items(school, _paper(school, weak, WEEK1))}
    assert not first_refs & {i.ref_id for i in items_weak}
    # 考得好的：没有错题，也没有薄弱点，全考本周内容，难题更多
    items_strong = _items(school, p_strong)
    assert {i.content["origin"] for i in items_strong} == {"this_week"}
    hard = lambda rows: sum(i.content["difficulty"] == "较难" for i in rows)  # noqa: E731
    assert hard(items_strong) > hard(items_weak)


def test_unsubmitted_paper_keeps_level(client):
    school = make_school(client)
    book = _make_book()
    sections = _sections(book)
    _set_progress(client, school, book, [sections["25.1"]])
    _issue(school, WEEK1)
    _issue(school, WEEK2)
    paper = _paper(school, school.student_ids[0], WEEK2)
    assert (paper.level, paper.prev_ratio) == (2, None)
    assert "没有提交" in paper.reason


def _pool_question(**extra) -> PoolQuestion:
    fields = {
        "qtype": "单选题",
        "options": ["甲", "乙", "丙", "丁"],
        "answer": "C",
        "analysis": "解析",
        **extra,
    }
    return PoolQuestion(**fields)


def test_shuffled_options_keep_the_right_answer():
    q = _pool_question()
    answers = set()
    for seed in range(30):
        options, answer = weekly.shuffled_options(q, random.Random(seed))
        assert sorted(options) == sorted(q.options)
        assert options["ABCD".index(answer)] == "丙"  # 打乱后答案还指向同一个选项
        answers.add(answer)
    assert answers == set("ABCD")  # 正确选项的位置确实会变


@pytest.mark.parametrize(
    "extra",
    [
        {"analysis": "选项 B 含两个未知数，所以选 C"},  # 解析提到了选项字母
        {"options": ["甲", "乙", "丙", "以上都对"]},  # 选项之间有依赖
        {"qtype": "填空题", "options": [], "answer": "7"},
    ],
)
def test_options_stay_in_place_when_order_matters(extra):
    q = _pool_question(**extra)
    assert weekly.shuffled_options(q, random.Random(1)) == (q.options, q.answer)


def test_letters_inside_formulas_do_not_stop_shuffling():
    q = _pool_question(analysis="在 $\\triangle ABC$ 中，$AB=AC$", options=["$A$", "$B$", "$C$", "$D$"])
    results = {tuple(weekly.shuffled_options(q, random.Random(s))[0]) for s in range(10)}
    assert len(results) > 1


def test_same_question_has_different_option_order_between_students(client):
    school = make_school(client)
    book = _make_book()
    _set_progress(client, school, book, [_sections(book)["25.1"]])
    _issue(school, WEEK1)

    def by_ref(sid):
        items = _items(school, _paper(school, sid, WEEK1))
        return {i.ref_id: i.content for i in items if i.content["qtype"] == "单选题"}

    first, second = by_ref(school.student_ids[0]), by_ref(school.student_ids[1])
    assert {c["answer"] for c in first.values()} != {"A"}  # 题库里答案都是 A，发到卷子上已经打乱
    for content in first.values():
        assert content["options"]["ABCD".index(content["answer"])] == "一"
    common = set(first) & set(second)
    assert common and any(first[r]["options"] != second[r]["options"] for r in common)


def test_answers_stay_hidden_until_due(client):
    """同班同学的卷子有部分题目相同：交卷后马上知道对错，但答案要截止后才公布。"""
    school = make_school(client)
    book = _make_book()
    _set_progress(client, school, book, [_sections(book)["25.1"]])
    client.post(
        f"/api/teacher/weekly/classes/{school.class_id}/issue",
        headers=school.teacher,
        params={"subject": "数学"},
    )
    s1 = school.students[0]
    [brief] = client.get("/api/student/assignments", headers=s1).json()
    aid = brief["id"]
    done = client.post(f"/api/student/assignments/{aid}/submit", headers=s1).json()
    assert done["revealed"] is False
    assert all("answer" not in i["content"] and "analysis" not in i["content"] for i in done["items"])
    assert all(a["correct"] is False for a in done["answers"])  # 没作答的题判错，马上能看到

    with session_scope(tenant_id=school.tenant_id) as db:
        db.get(Assignment, uuid.UUID(aid)).due_at = datetime.now(UTC) - timedelta(minutes=1)
    after = client.get(f"/api/student/assignments/{aid}", headers=s1).json()
    assert after["revealed"] is True
    assert all("answer" in i["content"] for i in after["items"])


def test_simulated_weeks(client, grader):
    """连跑四周：一直好的升到最高并保持，一直差的降到最低；每周不重复做题，掌握度跟着变。"""
    school = make_school(client)
    book = _make_book(sections=4)
    sections = _sections(book)
    good, bad = school.student_ids
    numbers = ["25.1", "25.2", "25.3", "25.4"]
    weeks = [WEEK1, WEEK2, WEEK3, WEEK4]
    levels = {good: [], bad: []}
    for no, week in zip(numbers, weeks, strict=True):
        _set_progress(client, school, book, [sections[no]])
        assert _issue(school, week).created == 2
        for sid in (good, bad):
            levels[sid].append(_paper(school, sid, week).level)
        _take(client, school, 0, week, right=1.0)
        _take(client, school, 1, week, right=0.2)
    assert levels[good] == [2, 3, 3, 3]
    assert levels[bad] == [2, 1, 1, 1]

    with session_scope(tenant_id=school.tenant_id) as db:
        for sid in (good, bad):
            refs = list(
                db.scalars(
                    select(AssignmentItem.ref_id)
                    .join(WeeklyPaper, WeeklyPaper.assignment_id == AssignmentItem.assignment_id)
                    .where(WeeklyPaper.student_id == sid)
                )
            )
            assert len(refs) == len(set(refs)) == 14 * 4
        scores_good = mastery(db, school.tenant_id, good, "数学")
        scores_bad = mastery(db, school.tenant_id, bad, "数学")
    assert sum(scores_good.values()) / len(scores_good) > 0.7
    assert sum(scores_bad.values()) / len(scores_bad) < 0.5

    # 老师和学生都能看到走势和薄弱点
    report = client.get(
        f"/api/teacher/weekly/classes/{school.class_id}/report",
        headers=school.teacher,
        params={"subject": "数学"},
    ).json()
    assert report["weeks"] == [str(w) for w in reversed(weeks)]
    rows = {r["student_name"]: r for r in report["rows"]}
    assert (rows["学生1"]["level_label"], rows["学生2"]["level_label"]) == ("提高", "基础")
    assert rows["学生1"]["percent"] == 100 and rows["学生2"]["percent"] < 40
    assert rows["学生2"]["weak_kps"] and not rows["学生1"]["weak_kps"]
    assert report["class_weak_kps"]

    [mine] = client.get("/api/student/weekly", headers=school.students[1]).json()
    assert (mine["subject"], mine["level_label"], len(mine["weeks"])) == ("数学", "基础", 4)
    assert mine["weak_kps"] and mine["tested_kps"] > 0


def test_teacher_change_of_score_updates_mastery_without_double_count(client, grader):
    school = make_school(client)
    book = _make_book()
    _set_progress(client, school, book, [_sections(book)["25.1"]])
    _issue(school, WEEK1)
    _take(client, school, 0, WEEK1, right=0.0)
    student = school.student_ids[0]

    def evidence():
        with session_scope(tenant_id=school.tenant_id) as db:
            return db.scalar(
                select(func.count()).select_from(KpEvidence).where(KpEvidence.student_id == student)
            )

    before = evidence()
    assert before == 14  # 每题一个知识点
    # 解答题 AI 判了 0 分，老师确认前已经计入，下一周的难度也能用上
    rows = client.get(
        f"/api/teacher/weekly/classes/{school.class_id}/grading",
        headers=school.teacher,
        params={"subject": "数学"},
    ).json()
    assert len(rows) == 2 and all(r["ai_score"] == 0 for r in rows)
    # 老师改成满分
    resp = client.post(
        f"/api/teacher/answers/{rows[0]['id']}/confirm",
        headers=school.teacher,
        json={"score": rows[0]["item_score"]},
    )
    assert resp.status_code == 200, resp.text
    assert evidence() == before  # 覆盖，不增加
    with session_scope(tenant_id=school.tenant_id) as db:
        ratios = sorted(
            db.scalars(select(KpEvidence.ratio).where(KpEvidence.item_id == uuid.UUID(rows[0]["item_id"])))
        )
    assert ratios == [1.0]

    # 一键确认剩下的
    done = client.post(
        f"/api/teacher/weekly/classes/{school.class_id}/confirm-all",
        headers=school.teacher,
        params={"subject": "数学"},
    ).json()
    assert done["count"] == 1
    paper = _paper(school, student, WEEK1)
    detail = client.get(f"/api/student/assignments/{paper.assignment_id}", headers=school.students[0]).json()
    assert detail["status"] == "graded"


def test_unconfirmed_ai_score_is_hidden_from_student_but_used_for_level(client, grader):
    school = make_school(client)
    book = _make_book()
    _set_progress(client, school, book, [_sections(book)["25.1"]])
    _issue(school, WEEK1)
    _take(client, school, 0, WEEK1, right=1.0)  # 客观题全对，解答题 AI 给满分但没确认
    [mine] = client.get("/api/student/weekly", headers=school.students[0]).json()
    assert mine["weeks"][0]["status"] == "submitted"
    assert mine["weeks"][0]["score"] is None and mine["weeks"][0]["percent"] == 100  # 只算已出分的题
    _issue(school, WEEK2)
    assert _paper(school, school.student_ids[0], WEEK2).level == 3  # 不等老师确认也能定下周难度


# —— 定时任务 ——


def test_beat_schedule_registered():
    tasks = {v["task"] for v in celery_app.conf.beat_schedule.values()}
    assert tasks == {"weekly.issue_all", "weekly.remind_progress"}
    assert all(t in celery_app.tasks for t in tasks)


def test_issue_all_across_tenants_and_tells_teacher(client):
    a = make_school(client, "a", "13811110001")
    b = make_school(client, "b", "13811110002")
    book = _make_book()
    sections = _sections(book)
    _set_progress(client, a, book, [sections["25.1"]])
    _set_progress(client, b, book, [sections["25.1"]])
    # c 校设置了进度，但把周测关了：不发
    c = make_school(client, "c", "13811110003")
    _set_progress(client, c, book, [sections["25.1"]], enabled=False)

    assert weekly_tasks.issue_all() == {"classes": 2, "papers": 4, "failed": 0}
    assert weekly_tasks.issue_all() == {"classes": 2, "papers": 0, "failed": 0}  # 重跑不重复

    with open_session(tenant_id=a.tenant_id) as db:
        assert db.scalar(select(func.count()).select_from(WeeklyPaper)) == 2  # 行级安全：只看到自己机构的
        titles = list(db.scalars(select(Notification.title).where(Notification.user_id == a.teacher_id)))
    assert titles == ["初一(1)班数学周测已发出"]
    with open_session(tenant_id=c.tenant_id) as db:
        assert db.scalar(select(func.count()).select_from(Assignment)) == 0


def test_issue_all_tells_teacher_when_pool_is_empty(client):
    school = make_school(client)
    book = _make_book()
    sections = _sections(book)
    _set_progress(client, school, book, [sections["25.1"]])
    with session_scope(bypass=True) as db:
        for q in db.scalars(select(PoolQuestion)):
            q.status = "checked"
    assert weekly_tasks.issue_all() == {"classes": 0, "papers": 0, "failed": 1}
    with open_session(tenant_id=school.tenant_id) as db:
        titles = list(db.scalars(select(Notification.title).where(Notification.user_id == school.teacher_id)))
    assert titles == ["初一(1)班数学周测这周没有发出"]


def test_remind_only_when_progress_is_stale(client):
    school = make_school(client)
    book = _make_book()
    _set_progress(client, school, book, [_sections(book)["25.1"]])
    assert weekly_tasks.remind_all() == 0
    with session_scope(tenant_id=school.tenant_id) as db:
        db.scalar(select(ClassProgress)).week_start = WEEK1 - timedelta(days=7)
    assert weekly_tasks.remind_all() == 1


def test_due_time_uses_school_time_and_leaves_enough_time():
    monday = date(2026, 11, 2)
    friday = datetime(2026, 11, 6, 8, 0, tzinfo=UTC)  # 北京时间周五 16 点
    assert weekly.week_of(friday) == monday
    due = weekly.due_of(monday, friday)
    assert due.astimezone(weekly.SCHOOL_TZ).strftime("%m-%d %H:%M") == "11-08 22:00"
    # 周日晚上才发：至少留 48 小时
    late = datetime(2026, 11, 8, 13, 0, tzinfo=UTC)
    assert weekly.due_of(monday, late) == late + timedelta(hours=48)
    # 北京时间周一凌晨算新的一周
    assert weekly.week_of(datetime(2026, 11, 8, 17, 0, tzinfo=UTC)) == date(2026, 11, 9)


# —— 平台题库 ——


def _question(section="25.1", stem="题干＿＿＿＿", **extra):
    return {
        "section_no": section,
        "qtype": "填空题",
        "difficulty": "中等",
        "stem": stem,
        "answer": "7",
        "analysis": "解析",
        "knowledge_points": [f"{section}甲"],
        "source": "generated",
        "status": "checked",
        **extra,
    }


def _import(questions, key="rj-math-9a") -> pool.PoolImportResult:
    with session_scope(bypass=True) as db:
        return pool.import_pool(db, pool.PoolPack(book_key=key, questions=questions))


def test_pool_import_keeps_reviewed_and_removes_stale():
    book = _make_book(per_type=(0, 0, 0))
    first = _import(
        [_question(stem="甲＿＿＿＿"), _question(stem="乙＿＿＿＿"), _question(stem="丙＿＿＿＿")]
    )
    assert (first.created, first.updated, first.removed) == (3, 0, 0)

    with session_scope(bypass=True) as db:
        rows = {q.stem: q for q in db.scalars(select(PoolQuestion).where(PoolQuestion.book_id == book))}
        rows["甲＿＿＿＿"].status = "approved"
        rows["乙＿＿＿＿"].status = "rejected"
    # 新题包：甲乙的答案变了，丙不见了，多了丁
    second = _import(
        [
            _question(stem="甲＿＿＿＿", answer="8"),
            _question(stem="乙＿＿＿＿", answer="8"),
            _question(stem="丁＿＿＿＿"),
        ]
    )
    assert (second.created, second.kept, second.removed) == (1, 2, 1)
    with session_scope(bypass=True) as db:
        rows = {q.stem: q for q in db.scalars(select(PoolQuestion).where(PoolQuestion.book_id == book))}
    assert set(rows) == {"甲＿＿＿＿", "乙＿＿＿＿", "丁＿＿＿＿"}
    assert rows["甲＿＿＿＿"].answer == "7"  # 审核过的不被覆盖
    assert rows["乙＿＿＿＿"].status == "rejected"  # 驳回的不会复活


def test_pool_import_drops_questions_it_cannot_link():
    _make_book(per_type=(0, 0, 0))
    result = _import(
        [
            _question(section="99.9"),
            _question(knowledge_points=["不存在的知识点"]),
            _question(knowledge_points=["不存在的知识点", "25.1甲"], stem="有一个对得上＿＿＿＿"),
        ]
    )
    assert result.created == 1 and len(result.dropped) == 2
    with pytest.raises(Exception, match="不存在"):
        _import([_question()], key="no-such-book")


def test_pool_review_api(client):
    make_platform_admin()
    admin = auth(client, "13900000000")
    book = _make_book(per_type=(0, 0, 0))
    _import(
        [
            _question(stem="一致＿＿＿＿"),
            _question(
                stem="有分歧＿＿＿＿",
                status="disputed",
                check_result={"verdict": "disagree", "reason": "算错了"},
            ),
            _question(stem="没校验＿＿＿＿", status="unchecked"),
        ]
    )
    url = f"/api/courses/{book}/questions"
    page = client.get(url, headers=admin, params={"status": "pending"}).json()
    assert page["total"] == 3 and page["counts"] == {"checked": 1, "disputed": 1, "unchecked": 1}
    assert page["items"][0]["stem"] == "有分歧＿＿＿＿"  # 有分歧的排最前面
    assert page["items"][0]["knowledge_points"] == ["25.1甲"]
    assert page["items"][0]["section_no"] == "25.1"

    # 一键通过只通过校验一致的
    done = client.post(f"{url}/approve-checked", headers=admin, json={}).json()
    assert done["count"] == 1
    page = client.get(url, headers=admin, params={"status": "pending"}).json()
    assert {q["stem"] for q in page["items"]} == {"有分歧＿＿＿＿", "没校验＿＿＿＿"}

    # 逐题改、通过、驳回
    disputed = page["items"][0]
    resp = client.put(
        f"/api/courses/questions/{disputed['id']}",
        headers=admin,
        json={"qtype": "填空题", "stem": "改过的题＿＿＿＿", "answer": "9", "difficulty": "容易"},
    )
    assert resp.status_code == 200, resp.text
    assert (resp.json()["edited"], resp.json()["answer"], resp.json()["status"]) == (True, "9", "disputed")
    assert (
        client.post(f"/api/courses/questions/{disputed['id']}/approve", headers=admin).json()["status"]
        == "approved"
    )
    other = page["items"][1]["id"]
    assert client.post(f"/api/courses/questions/{other}/reject", headers=admin).json()["status"] == "rejected"
    counts = client.get(url, headers=admin).json()["counts"]
    assert counts == {"approved": 2, "rejected": 1}

    # 选择题的答案不合法时不让存
    resp = client.put(
        f"/api/courses/questions/{other}",
        headers=admin,
        json={
            "qtype": "单选题",
            "stem": "题",
            "options": ["一", "二", "三"],
            "answer": "Z",
            "difficulty": "容易",
        },
    )
    assert resp.status_code == 400


def test_pool_is_admin_only(client):
    school = make_school(client)
    book = _make_book(per_type=(1, 0, 0))
    url = f"/api/courses/{book}/questions"
    assert client.get(url, headers=school.teacher).status_code == 403
    assert client.get(url, headers=school.students[0]).status_code == 403
    assert client.post(f"{url}/approve-checked", headers=school.teacher, json={}).status_code == 403
    with session_scope(bypass=True) as db:
        qid = db.scalar(select(PoolQuestion.id).limit(1))
    assert client.post(f"/api/courses/questions/{qid}/approve", headers=school.teacher).status_code == 403


def test_reimporting_knowledge_points_keeps_question_links():
    book = _make_book(per_type=(1, 0, 0))
    with session_scope(bypass=True) as db:
        raw = {
            "key": "rj-math-9a",
            "stage": "初中",
            "subject": "数学",
            "edition": "人教版",
            "grade": "初一",
            "title": "九年级上册",
            "chapters": [
                {
                    "no": "25",
                    "title": "方程",
                    "sections": [
                        {
                            "no": f"25.{i + 1}",
                            "title": f"第25.{i + 1}节",
                            "knowledge_points": [
                                {
                                    "name": f"25.{i + 1}甲",
                                    "content": "新内容",
                                    "kind": "概念",
                                    "importance": "核心",
                                },
                                {
                                    "name": f"25.{i + 1}乙",
                                    "content": "新内容",
                                    "kind": "方法",
                                    "importance": "重点",
                                },
                            ],
                        }
                        for i in range(3)
                    ],
                }
            ],
        }
        assert db.scalar(select(func.count()).select_from(Textbook)) == 1
        ids = set(db.scalars(select(KnowledgePoint.id).where(KnowledgePoint.book_id == book)))
        content_pack.import_pack(db, content_pack.BookPack.model_validate(raw), publish=True)
        assert ids == set(db.scalars(select(KnowledgePoint.id).where(KnowledgePoint.book_id == book)))
        assert (
            db.scalar(select(func.count()).select_from(PoolQuestion).where(PoolQuestion.book_id == book)) == 3
        )

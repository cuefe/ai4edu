"""教材内容：内容包导入、可见范围、文件读取、生成流程。"""

import json
import re
import uuid
from pathlib import Path

import pypdfium2 as pdfium
import pytest
from sqlalchemy import func, select

from app.ai.skills import curriculum_gen
from app.ai.skills.question_gen import blanks_out_of_math
from app.core.db import session_scope
from app.devtools import content_gen, pool_gen
from app.modules.curriculum import pack as content_pack
from app.modules.curriculum import pool
from app.modules.curriculum.models import Chapter, KnowledgePoint, PoolQuestion
from app.modules.curriculum.pack import BookPack, parse_mind_map
from tests.conftest import auth, make_platform_admin
from tests.school import make_school


def _kp(name: str, content: str = "内容") -> dict:
    return {"name": name, "content": content, "kind": "概念", "importance": "核心", "recite": True}


def _pack(**extra) -> dict:
    return {
        "key": "rj-math-9a",
        "stage": "初中",
        "subject": "数学",
        "edition": "人教版",
        "grade": "初一",
        "title": "九年级上册",
        "chapters": [
            {
                "no": "25",
                "title": "一元二次方程",
                "summary": "本章概览",
                "mind_map": "- 一元二次方程\n  - 概念\n  - 解法\n    - 配方法",
                "sections": [
                    {
                        "no": "25.1",
                        "title": "概念",
                        "mind_map": "- 概念\n  - 一般形式",
                        "knowledge_points": [_kp("一般形式", "$ax^2+bx+c=0$"), _kp("二次项系数")],
                    },
                    {"no": "25.2", "title": "配方法", "knowledge_points": [_kp("配方")]},
                ],
            }
        ],
        **extra,
    }


def _import(raw: dict, base: Path | None = None, *, publish: bool = True) -> content_pack.ImportResult:
    with session_scope(bypass=True) as db:
        return content_pack.import_pack(db, BookPack.model_validate(raw), base, publish=publish)


def test_parse_mind_map():
    tree = parse_mind_map("- 根\n  - 甲\n    - 子\n  - 乙", "备用")
    assert tree == {
        "text": "根",
        "children": [
            {"text": "甲", "children": [{"text": "子", "children": []}]},
            {"text": "乙", "children": []},
        ],
    }
    # 多个顶层节点时用备用根；标题和列表可以混用；不是列表的行忽略
    assert parse_mind_map("- 甲\n- 乙", "备用")["text"] == "备用"
    mixed = parse_mind_map("# 根\n说明文字\n- 甲\n  - 子", "备用")
    assert mixed["text"] == "根" and mixed["children"][0]["children"][0]["text"] == "子"
    assert parse_mind_map("没有列表", "备用") is None


def test_parse_mind_map_limits():
    deep = "\n".join(f"{'  ' * i}- 第{i}层" for i in range(20))
    tree = parse_mind_map(deep, "备用")
    depth = 0
    while tree["children"]:
        tree = tree["children"][0]
        depth += 1
    assert depth < content_pack.MAX_MAP_DEPTH
    wide = "- 根\n" + "\n".join(f"  - 节点{i}" for i in range(500))
    assert len(parse_mind_map(wide, "备用")["children"]) < content_pack.MAX_MAP_NODES


def test_pack_rejects_repeated_numbers_and_unknown_file_chapter():
    raw = _pack()
    raw["chapters"][0]["sections"][1]["no"] = "25.1"
    with pytest.raises(ValueError, match="编号重复"):
        BookPack.model_validate(raw)
    with pytest.raises(ValueError, match="不存在"):
        BookPack.model_validate(
            _pack(files=[{"path": "a.pdf", "title": "A", "kind": "courseware", "chapter_no": "99"}])
        )


def test_reimport_keeps_ids_and_removes_stale(client):
    first = _import(_pack())
    assert first.created and first.chapters == 3 and first.knowledge_points == 3
    with session_scope(bypass=True) as db:
        kept = db.query(KnowledgePoint).filter_by(name="一般形式").one().id
        section = db.query(Chapter).filter_by(no="25.1").one().id

    raw = _pack()
    raw["chapters"][0]["sections"][0]["knowledge_points"] = [_kp("一般形式", "新内容")]
    raw["chapters"][0]["sections"].pop(1)
    second = _import(raw)
    assert not second.created and second.chapters == 2 and second.knowledge_points == 1
    with session_scope(bypass=True) as db:
        kp = db.query(KnowledgePoint).filter_by(name="一般形式").one()
        assert kp.id == kept and kp.content == "新内容"
        assert db.query(Chapter).filter_by(no="25.1").one().id == section
        assert db.query(Chapter).filter_by(no="25.2").one_or_none() is None
        assert db.query(KnowledgePoint).count() == 1


def test_draft_only_visible_to_platform_admin(client):
    school = make_school(client)
    make_platform_admin()
    admin = auth(client, "13900000000")
    book_id = str(_import(_pack(), publish=False).book_id)
    student = school.students[0]

    assert client.get("/api/courses", headers=student).json()["books"] == []
    assert client.get(f"/api/courses/{book_id}", headers=student).status_code == 404
    assert [b["id"] for b in client.get("/api/courses", headers=admin).json()["books"]] == [book_id]

    assert (
        client.put(
            f"/api/courses/{book_id}/status", headers=school.teacher, json={"published": True}
        ).status_code
        == 403
    )
    resp = client.put(f"/api/courses/{book_id}/status", headers=admin, json={"published": True})
    assert resp.status_code == 200 and resp.json()["status"] == "published"
    assert [b["id"] for b in client.get("/api/courses", headers=student).json()["books"]] == [book_id]

    client.put(f"/api/courses/{book_id}/status", headers=admin, json={"published": False})
    assert client.get(f"/api/courses/{book_id}", headers=student).status_code == 404


def test_public_content_shared_across_tenants_and_my_grades(client):
    a = make_school(client, "a", "13811110001")
    b = make_school(client, "b", "13811110002")
    _import(_pack())
    for school in (a, b):
        out = client.get("/api/courses", headers=school.students[0]).json()
        assert out["my_grades"] == ["初一"]
        book = out["books"][0]
        assert (book["chapter_count"], book["section_count"], book["kp_count"]) == (1, 2, 3)
    assert client.get("/api/courses").status_code == 401


def test_book_and_chapter_detail(client):
    school = make_school(client)
    book_id = _import(_pack()).book_id
    student = school.students[0]
    book = client.get(f"/api/courses/{book_id}", headers=student).json()
    assert [c["no"] for c in book["chapters"]] == ["25"]
    assert [(s["no"], s["kp_count"]) for s in book["chapters"][0]["sections"]] == [("25.1", 2), ("25.2", 1)]
    assert book["chapters"][0]["kp_count"] == 3

    section = client.get(
        f"/api/courses/chapters/{book['chapters'][0]['sections'][0]['id']}", headers=student
    ).json()
    assert [k["name"] for k in section["knowledge_points"]] == ["一般形式", "二次项系数"]
    assert section["mind_map"]["children"][0]["text"] == "一般形式"
    # 看整章时带上各节的知识点，并标明属于哪一节
    chapter = client.get(f"/api/courses/chapters/{book['chapters'][0]['id']}", headers=student).json()
    assert [k["section_no"] for k in chapter["knowledge_points"]] == ["25.1", "25.1", "25.2"]
    assert chapter["summary"] == "本章概览"
    assert client.get(f"/api/courses/chapters/{uuid.uuid4()}", headers=student).status_code == 404


def test_course_file_range_and_permissions(client, tmp_path):
    school = make_school(client)
    (tmp_path / "课本.pdf").write_bytes(b"%PDF-" + b"x" * 100)
    (tmp_path / "第一章.pdf").write_bytes(b"%PDF-" + b"y" * 100)
    files = [
        {"path": "课本.pdf", "title": "九上课本", "kind": "textbook", "source": "测试"},
        {"path": "第一章.pdf", "title": "25.1 课件", "kind": "courseware", "chapter_no": "25.1"},
    ]
    raw = _pack(files=files)
    result = _import(raw, tmp_path, publish=False)
    assert result.files_added == 2
    # 内容没变，重新导入不会多存
    assert _import(raw, tmp_path, publish=True).files_added == 0

    student = school.students[0]
    book = client.get(f"/api/courses/{result.book_id}", headers=student).json()
    assert [f["kind"] for f in book["files"]] == ["textbook", "courseware"]
    file_id = book["files"][0]["id"]
    url = f"/api/courses/files/{file_id}"
    assert client.get(url).status_code == 401

    full = client.get(url, headers=student)
    assert full.status_code == 200 and full.content.startswith(b"%PDF-")
    assert full.headers["content-type"] == "application/pdf"
    assert full.headers["content-disposition"].startswith("inline")
    part = client.get(url, headers={**student, "Range": "bytes=0-4"})
    assert part.status_code == 206 and part.content == b"%PDF-"

    section = next(s for s in book["chapters"][0]["sections"] if s["no"] == "25.1")
    detail = client.get(f"/api/courses/chapters/{section['id']}", headers=student).json()
    assert [f["title"] for f in detail["files"]] == ["25.1 课件"]

    # 下架后文件也看不到；删除时存储里的文件一起删
    make_platform_admin()
    client.put(
        f"/api/courses/{result.book_id}/status",
        headers=auth(client, "13900000000"),
        json={"published": False},
    )
    assert client.get(url, headers=student).status_code == 404
    with session_scope(bypass=True) as db:
        assert content_pack.remove_book(db, "rj-math-9a")
        assert not content_pack.remove_book(db, "rj-math-9a")
    assert client.get(url, headers=student).status_code == 404


def _outline(tmp_path: Path) -> Path:
    outline = {
        "key": "rj-math-9a",
        "stage": "初中",
        "subject": "数学",
        "edition": "人教版",
        "grade": "初三",
        "title": "九年级上册",
        "chapters": [
            {"no": "25", "title": "一元二次方程", "sections": [{"no": "25.1", "title": "概念"}]},
            {"no": "26", "title": "二次函数", "sections": [{"no": "26.1", "title": "概念"}]},
        ],
    }
    path = tmp_path / "outline.json"
    path.write_text(json.dumps(outline, ensure_ascii=False), encoding="utf-8")
    return path


def _answer(no: str) -> dict:
    return {
        "summary": r"学 \(x\) 的方程",
        "mind_map": "- 根\n  - 枝",
        "sections": [
            {
                "no": f"{no}.1",
                "summary": "小节",
                "mind_map": "- 概念\n  - 定义",
                "knowledge_points": [_kp("定义", r"形如 \(ax^2=0\) 的方程")],
            }
        ],
    }


def test_check_chapter_normalizes_math_and_rejects_missing_section():
    outline = BookPack.model_validate(
        {
            "key": "k",
            "stage": "初中",
            "subject": "数学",
            "edition": "人教版",
            "grade": "初三",
            "title": "t",
            "chapters": [{"no": "25", "title": "方程", "sections": [{"no": "25.1", "title": "概念"}]}],
        }
    ).chapters[0]
    chapter, warnings = curriculum_gen.check_chapter(_answer("25"), outline)
    assert chapter.summary == "学 $x$ 的方程"
    assert chapter.sections[0].knowledge_points[0].content == "形如 $ax^2=0$ 的方程"
    assert warnings == []
    with pytest.raises(ValueError, match="缺少"):
        curriculum_gen.check_chapter({"sections": []}, outline)
    empty = _answer("25")
    empty["sections"][0]["knowledge_points"] = []
    with pytest.raises(ValueError, match="没有知识点"):
        curriculum_gen.check_chapter(empty, outline)
    odd = _answer("25")
    odd["sections"][0]["knowledge_points"][0]["content"] = "只有一个 $ 符号"
    assert any("不成对" in w for w in curriculum_gen.check_chapter(odd, outline)[1])


def test_generate_retries_with_feedback_and_merges(tmp_path, client):
    calls: list[list[dict]] = []

    def engine(messages):
        calls.append(messages)
        text = str(messages[1]["content"])
        no = "25" if "第 25 章" in text else "26"
        if no == "26" and len([m for m in calls if "第 26 章" in str(m[1]["content"])]) == 1:
            return {"sections": []}, "fake-model"  # 第一次输出缺节
        return _answer(no), "fake-model"

    path = content_gen.run(_outline(tmp_path), engine=engine, concurrency=1, engine_name="fake")
    assert path == tmp_path / "pack.json"
    retried = [m for m in calls if len(m) == 3]
    assert len(retried) == 1 and "缺少这些节" in str(retried[0][2]["content"])

    pack = content_pack.load_pack(path)
    assert [c.no for c in pack.chapters] == ["25", "26"]
    assert pack.provenance["models"] == ["fake-model"]
    assert pack.provenance["prompt_version"] == curriculum_gen.PROMPT_VERSION
    assert _import(json.loads(path.read_text(encoding="utf-8"))).knowledge_points == 2


def test_generate_resumes_missing_chapters(tmp_path, capsys):
    outline = _outline(tmp_path)

    def only_25(messages):
        if "第 25 章" in str(messages[1]["content"]):
            return _answer("25"), "m"
        raise RuntimeError("额度用完了")

    assert content_gen.run(outline, engine=only_25, concurrency=1, engine_name="fake") is None
    assert (tmp_path / "ch-25.json").exists() and not (tmp_path / "pack.json").exists()
    assert "额度用完了" in capsys.readouterr().out

    seen: list[str] = []

    def rest(messages):
        seen.append(str(messages[1]["content"]))
        return _answer("26"), "m"

    assert content_gen.run(outline, engine=rest, concurrency=1, engine_name="fake") == tmp_path / "pack.json"
    assert len(seen) == 1 and "第 26 章" in seen[0]


def test_load_material_matches_chapter_title(tmp_path):
    (tmp_path / "第二十五章 一元二次方程").mkdir()
    (tmp_path / "第二十五章 一元二次方程" / "讲义.txt").write_text("配方法的步骤", encoding="utf-8")
    (tmp_path / "第二十六章 二次函数.txt").write_text("抛物线", encoding="utf-8")
    (tmp_path / "一元二次方程.mp4").write_bytes(b"video")
    chapter = content_pack.ChapterPack(no="25", title="一元二次方程")
    text, used = content_gen.load_material(tmp_path, chapter)
    assert "配方法" in text and "抛物线" not in text
    assert len(used) == 1
    assert content_gen.load_material(None, chapter) == ("", [])


def _scanned_book(tmp_path: Path) -> content_pack.ChapterPack:
    """第 25 章：书上第 1 页引言，第 2–3 页 25.1，第 4 页 25.2，第 5 页章末；PDF 页码 = 书上页码 + 6。"""
    index = {
        "page_offset": 6,
        "chapters": {"25": {"start": 1, "sections": {"25.1": 2, "25.2": 4}, "tail": 5, "end": 5}},
    }
    (tmp_path / "scan.json").write_text(json.dumps(index), encoding="utf-8")
    (tmp_path / "ocr").mkdir()
    for page in range(1, 6):
        (tmp_path / "ocr" / f"p-{page + 6:03d}.md").write_text(f"书第{page}页\n", encoding="utf-8")
    return content_pack.ChapterPack(
        no="25",
        title="方程",
        sections=[{"no": "25.1", "title": "概念"}, {"no": "25.2", "title": "解法"}],
    )


def test_scan_material_splits_pages_by_section(tmp_path):
    chapter = _scanned_book(tmp_path)
    text, used = content_gen.scan_material(tmp_path, chapter)
    assert used == ["课本原文：第 1–5 页"]
    intro, first, second, tail = text.split("\n\n【")
    assert "本章引言" in intro and "书第1页" in intro and "书第2页" not in intro
    assert first.startswith("25.1 概念】（课本第 2–3 页）") and "书第2页" in first and "书第3页" in first
    assert second.startswith("25.2 解法】（课本第 4–4 页）") and "书第4页" in second
    assert "书第5页" in tail
    # 另一章没写页码：不用课本原文
    assert content_gen.scan_material(tmp_path, content_pack.ChapterPack(no="26", title="函数")) == ("", [])

    (tmp_path / "ocr" / "p-009.md").unlink()
    with pytest.raises(FileNotFoundError, match="第 3 页"):
        content_gen.scan_material(tmp_path, chapter)
    wrong = chapter.model_copy(update={"sections": chapter.sections[:1]})
    with pytest.raises(ValueError, match="对不上"):
        content_gen.scan_material(tmp_path, wrong)


def test_generate_refuses_when_textbook_pages_are_missing(tmp_path, capsys):
    outline = {
        "key": "k",
        "stage": "初中",
        "subject": "数学",
        "edition": "人教版",
        "grade": "初三",
        "title": "t",
        "chapters": [_scanned_book(tmp_path).model_dump()],
    }
    path = tmp_path / "outline.json"
    path.write_text(json.dumps(outline, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "ocr" / "p-009.md").unlink()

    def engine(messages):
        raise AssertionError("缺页时不该调模型")

    assert content_gen.run(path, engine=engine, concurrency=1, engine_name="fake") is None
    assert "还没转写" in capsys.readouterr().out


def _blank_pdf(path: Path, pages: int) -> None:
    doc = pdfium.PdfDocument.new()
    for _ in range(pages):
        doc.new_page(200, 300)
    doc.save(str(path))
    doc.close()


def test_ocr_pdf_retries_and_resumes(tmp_path, capsys):
    pdf = tmp_path / "book.pdf"
    _blank_pdf(pdf, 5)
    out = tmp_path / "ocr"
    calls: list[list[int]] = []

    def flaky(images, numbers):
        calls.append(list(numbers))
        assert all(image.stat().st_size > 0 for image in images)
        if len(calls) == 1:
            return {numbers[0]: "只有一页"}  # 第一次漏页，要重试
        return {n: f"第{n}页" for n in numbers}

    failed = content_gen.ocr_pdf(pdf, out, pages="2-4", batch=3, concurrency=1, engine=flaky)
    assert failed == []
    assert calls == [[2, 3, 4], [2, 3, 4]]
    assert (out / "p-003.md").read_text(encoding="utf-8") == "第3页\n"
    assert not (out / "p-001.md").exists()

    # 重跑：已转写的页跳过，只补新要的页
    calls.clear()
    assert content_gen.ocr_pdf(pdf, out, pages="1-4", batch=3, concurrency=1, engine=flaky) == []
    assert calls == [[1]]


def test_ocr_pdf_reports_failed_batches(tmp_path, capsys):
    pdf = tmp_path / "book.pdf"
    _blank_pdf(pdf, 2)

    def broken(images, numbers):
        raise RuntimeError("额度用完了")

    failed = content_gen.ocr_pdf(pdf, tmp_path / "ocr", batch=2, concurrency=1, engine=broken)
    assert len(failed) == 1 and "额度用完了" in failed[0]
    assert not (tmp_path / "ocr" / "p-001.md").exists()


def _pool_engine(*, wrong_answers: set[str] = frozenset(), broken_check: bool = False):
    """假的出题和校验：出题返回固定的题；校验时默认答对，stem 在 wrong_answers 里的答错。"""
    good = (
        [
            {
                "qtype": "单选题",
                "difficulty": "容易",
                "stem": f"单选 {i}",
                "options": ["一", "二", "三", "四"],
                "answer": "A",
                "analysis": "解析",
                "knowledge_points": ["一般形式"],
                "source": "textbook",
                "source_ref": "课本第 3 页",
            }
            for i in range(12)
        ]
        + [
            {
                "qtype": "填空题",
                "difficulty": "中等",
                "stem": f"填空 {i} ＿＿＿＿",
                "options": [],
                "answer": "$\\frac{1}{2}$",
                "analysis": "解析",
                "knowledge_points": ["一般形式", "不存在的知识点"],
                "source": "generated",
                "source_ref": "写了也不要",
            }
            for i in range(8)
        ]
        + [
            {
                "qtype": "解答题",
                "difficulty": "较难",
                "stem": f"解答 {i}",
                "options": [],
                "answer": "$x=1$",
                "analysis": "先移项，再合并同类项，得到结果。",
                "knowledge_points": ["一般形式"],
                "source": "generated",
                "source_ref": "",
            }
            for i in range(6)
        ]
    )
    calls = {"gen": 0, "check": 0, "judge": 0}

    def engine(prompt, schema):
        if "questions" in schema["properties"]:
            calls["gen"] += 1
            question = schema["properties"]["questions"]["items"]["properties"]
            assert question["knowledge_points"]["items"]["enum"] == ["一般形式"]  # 只能选清单里的名称
            bad = {"qtype": "单选题", "stem": "如图，求角度", "options": [], "answer": "A"}
            return {
                "questions": [*good, bad, {**good[0], "knowledge_points": ["不存在的知识点"], "stem": "新题"}]
            }
        if "answers" in schema["properties"]:
            calls["check"] += 1
            if broken_check:
                raise RuntimeError("额度用完了")
            assert "参考答案" not in prompt and "解析" not in prompt  # 校验时看不到答案
            answers = []
            for i, q in enumerate(good):
                if f"【{i}】" not in prompt:
                    continue
                if q["stem"] in wrong_answers:
                    answers.append({"id": i, "work": "过程", "answer": "B", "problem": ""})
                elif q["qtype"] == "填空题":
                    answers.append(
                        {"id": i, "work": "过程", "answer": "0.5", "problem": ""}
                    )  # 写法不同，数值相等
                elif q["qtype"] == "解答题":
                    answers.append({"id": i, "work": "过程", "answer": "解得 x 等于 1", "problem": ""})
                else:
                    answers.append({"id": i, "work": "过程", "answer": "A", "problem": ""})
            return {"answers": answers}
        calls["judge"] += 1
        ids = [int(x) for x in re.findall(r"【(\d+)】", prompt)]
        return {"results": [{"id": i, "consistent": True, "reason": "一致"} for i in ids]}

    engine.calls = calls
    return engine


def _pool_dir(tmp_path: Path) -> Path:
    """有一节课本原文和知识点的内容包目录。"""
    pack = {
        "key": "rj-math-9a",
        "stage": "初中",
        "subject": "数学",
        "edition": "人教版",
        "grade": "初三",
        "title": "九年级上册",
        "chapters": [
            {
                "no": "25",
                "title": "方程",
                "sections": [
                    {
                        "no": "25.1",
                        "title": "概念",
                        "knowledge_points": [_kp("一般形式")],
                    }
                ],
            }
        ],
    }
    (tmp_path / "pack.json").write_text(json.dumps(pack, ensure_ascii=False), encoding="utf-8")
    index = {"page_offset": 0, "chapters": {"25": {"start": 1, "sections": {"25.1": 2}, "tail": 3, "end": 3}}}
    (tmp_path / "scan.json").write_text(json.dumps(index), encoding="utf-8")
    (tmp_path / "ocr").mkdir()
    for page in (1, 2, 3):
        (tmp_path / "ocr" / f"p-{page:03d}.md").write_text(f"书第{page}页", encoding="utf-8")
    return tmp_path


def test_pool_gen_checks_answers_and_flags_disputes(tmp_path):
    out = _pool_dir(tmp_path)
    engine = _pool_engine(wrong_answers={"单选 3"})
    path = pool_gen.run(out, concurrency=1, engine=engine)
    assert path == out / "questions.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    questions = data["questions"]
    # 依赖插图的、知识点对不上的题被丢掉
    assert len(questions) == 26
    assert all("如图" not in q["stem"] and q["stem"] != "新题" for q in questions)
    by_stem = {q["stem"]: q for q in questions}
    # 独立解出来不一样：标成有分歧，题目里留下分歧
    assert by_stem["单选 3"]["status"] == "disputed"
    assert by_stem["单选 3"]["check_result"]["solver_answer"] == "B"
    # 写法不同但数值相等：规则就能判断一致，不用调模型
    assert by_stem["填空 0 ＿＿＿＿"]["status"] == "checked"
    assert by_stem["填空 0 ＿＿＿＿"]["check_result"]["method"] == "numeric"
    # 文字答案比不了：请模型比对
    assert by_stem["解答 0"]["status"] == "checked"
    assert by_stem["解答 0"]["check_result"]["method"] == "judge"
    assert engine.calls["judge"] >= 1
    # 课本出处只留在改编自课本的题上；对不上的知识点被去掉，对得上的留下
    assert by_stem["单选 0"]["source_ref"] == "课本第 3 页"
    assert by_stem["填空 0 ＿＿＿＿"]["source_ref"] == ""
    assert by_stem["填空 0 ＿＿＿＿"]["knowledge_points"] == ["一般形式"]

    # 重跑不重复调模型
    before = dict(engine.calls)
    assert pool_gen.run(out, concurrency=1, engine=engine) == path
    assert engine.calls == before


def test_pool_gen_marks_unchecked_when_check_fails(tmp_path):
    out = _pool_dir(tmp_path)
    path = pool_gen.run(out, concurrency=1, engine=_pool_engine(broken_check=True))
    statuses = {q["status"] for q in json.loads(path.read_text(encoding="utf-8"))["questions"]}
    assert statuses == {"unchecked"}  # 校验失败不能算校验通过


def test_pool_gen_needs_textbook_text(tmp_path, capsys):
    out = _pool_dir(tmp_path)
    (out / "ocr" / "p-002.md").unlink()
    engine = _pool_engine()
    assert pool_gen.run(out, concurrency=1, engine=engine) is None
    assert engine.calls["gen"] == 0
    assert "还没转写" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("stem", "expected"),
    [
        ("则$OP'=＿＿＿＿$米", "则$OP'=$＿＿＿＿米"),
        ("$\\angle A=＿＿＿＿^\\circ$", "$\\angle A=$＿＿＿＿$^\\circ$"),
        ("$＿＿＿＿+1=2$", "＿＿＿＿$+1=2$"),
        ("$x=$＿＿＿＿，$y=＿＿＿＿$", "$x=$＿＿＿＿，$y=$＿＿＿＿"),
        ("$a_1+a_2$ 等于＿＿＿＿", "$a_1+a_2$ 等于＿＿＿＿"),  # 公式外的不动，下标也不是横线
    ],
)
def test_blanks_moved_out_of_math(stem, expected):
    assert blanks_out_of_math(stem) == expected


def test_flag_beyond_compares_with_what_the_book_taught():
    question = {"stem": "题", "answer": "$\\{5,8\\}$", "analysis": "解析", "options": [], "status": "checked"}
    flagged = pool_gen.flag_beyond(question, "课本原文只讲了方程")
    assert flagged["status"] == "unchecked" and "集合" in flagged["warnings"][0]
    # 课本已经讲过：不算超纲
    assert pool_gen.flag_beyond(question, "本节学习集合")["status"] == "checked"
    # 分歧的题状态不变，只加提示
    disputed = pool_gen.flag_beyond({**question, "status": "disputed"}, "")
    assert disputed["status"] == "disputed" and disputed["warnings"]
    # 只是普通的分式和花括号，不算集合
    plain = {**question, "answer": "$\\frac{1}{2}$"}
    assert pool_gen.flag_beyond(plain, "")["status"] == "checked"
    # 解析里用了没学过的方法也要标
    used = {**question, "answer": "1", "analysis": "由相似三角形得"}
    assert pool_gen.flag_beyond(used, "")["status"] == "unchecked"
    # 课本只是预告“后面会学相似”，不算教过
    assert pool_gen.flag_beyond(used, "随着后面“相似”内容的学习")["status"] == "unchecked"
    formula = {**question, "answer": "1", "analysis": "$\\triangle AMN\\sim\\triangle ABC$"}
    assert pool_gen.flag_beyond(formula, "")["status"] == "unchecked"
    # 课本用 \sim 表示数值范围，也不算教过
    assert pool_gen.flag_beyond(formula, "$1\\sim 5$ 个")["status"] == "unchecked"


def test_pool_pack_imports_into_pool(tmp_path):
    out = _pool_dir(tmp_path)
    path = pool_gen.run(out, concurrency=1, engine=_pool_engine(wrong_answers={"单选 3"}))
    with session_scope(bypass=True) as db:
        content_pack.import_pack(db, content_pack.load_pack(out / "pack.json"), publish=True)
        result = pool.import_pool(db, pool.load_pack(path))
        assert result.created == 26 and result.dropped == []
        statuses = dict(
            db.execute(select(PoolQuestion.status, func.count()).group_by(PoolQuestion.status)).all()
        )
    assert statuses == {"checked": 25, "disputed": 1}


def test_parse_pages():
    assert content_gen.parse_pages("7-9,3", 10) == [3, 7, 8, 9]
    assert content_gen.parse_pages("5", 10) == [5]
    with pytest.raises(ValueError, match="页码范围不对"):
        content_gen.parse_pages("9-11", 10)

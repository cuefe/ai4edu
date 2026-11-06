"""离线生成周测题库：按节读课本原文出题，再独立解一遍核对答案，最后合并成题包 questions.json。

    uv run python -m app.cli pool-gen 内容包目录 [--sections 25.1,25.2] [--force]
    uv run python -m app.cli pool-import 内容包目录/questions.json

前提：目录里有 pack.json（知识点）和 scan.json + ocr/（课本原文，见 content_gen.py）。

每一节两步，结果都存盘，中途失败时重跑只补缺的：
1. gen-<节>.json：一个 Codex 进程出题。结构不合格、知识点对不上的题直接丢掉；题太少时带着问题重试。
2. checked-<节>.json：另一个 Codex 进程只看题干和选项独立解题，答案先用规则比对（选项字母、数值），
   判断不了的再请模型比对。一致的标 checked，不一致的标 disputed，没能判断的标 unchecked。

合并题包时再对照课本原文，用到了这本书到这一节还没讲过的记号或方法（集合、f(x)、相似……）的题标成 unchecked。

校验只是帮老师缩小要细看的范围，不能代替审核：两次都错的题照样会标成 checked。题包导入后要在
「平台运营 → 教材内容 → 题库」审核，只有审核通过的题才会进周测。
"""

import json
import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.ai.skills import pool_gen
from app.ai.skills.answer_check import compare
from app.ai.skills.common import normalize_math
from app.ai.skills.question_gen import QuestionData, blanks_out_of_math, normalize
from app.devtools.content_gen import MAX_ATTEMPTS, _codex_exec, _scan_parts, find_codex, section_material
from app.modules.curriculum.pack import BookPack, ChapterPack, SectionPack, load_pack

# 每节的题量：单选、填空、解答
PER_SECTION = {"单选题": 12, "填空题": 8, "解答题": 6}
MIN_SHARE = 0.7  # 合格的题少于目标的这个比例就重试
CHECK_BATCH = 15  # 校验时一次发几道题
# 模型容易顺手用上的记号和方法。对照课本原文判断有没有教过，不按学段写死：同一个词在高中教材里就是学过的
BEYOND_TERMS = {
    "集合": r"集合|\\in\b|\\\{",
    "函数记号 f(x)": r"\bf\(x\)",
    # 不能只匹配“相似”两个字：九上课本有一句“随着后面‘相似’内容的学习”，提到了但没教
    # \sim 也只看三角形之间的：课本里它还用来表示数值范围
    "相似": r"相似三角形|三角形[^。；]{0,30}相似|相似比|\\triangle[^$]{0,30}\\sim",
    "三角函数": r"\\sin|\\cos|\\tan|正弦|余弦|正切",
    "向量": r"向量|\\vec",
    "导数": r"导数",
    "对数": r"对数|\\log",
}

JsonEngine = Callable[[str, dict[str, Any]], dict[str, Any]]


def codex_json_engine(model: str | None = None, effort: str = "medium") -> JsonEngine:
    binary = find_codex()

    def run(prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        data, _ = _codex_exec(binary, prompt, schema, model=model, effort=effort)
        return data

    return run


def _gen_file(out_dir: Path, no: str) -> Path:
    return out_dir / "questions" / f"gen-{no}.json"


def _checked_file(out_dir: Path, no: str) -> Path:
    return out_dir / "questions" / f"checked-{no}.json"


def validate_question(raw: dict[str, Any], point_names: set[str]) -> tuple[dict[str, Any] | None, str]:
    """检查一道题。合格时返回规范化后的题，否则返回 None 和原因。"""
    stem = normalize_math(str(raw.get("stem") or "").strip())
    if any(word in stem for word in ("如图", "见上题", "上题中", "下图", "右图")):
        return None, f"依赖插图或其他题：{stem[:30]}"
    points = [p for p in raw.get("knowledge_points") or [] if p in point_names]
    if not points:
        return None, f"知识点和清单对不上：{stem[:30]}"
    try:
        data = QuestionData(
            qtype=raw.get("qtype"),
            stem=stem,
            options=raw.get("options") or [],
            answer=str(raw.get("answer") or "").strip(),
            analysis=str(raw.get("analysis") or ""),
            knowledge_points=points[:5],
        )
    except ValidationError as exc:
        return None, f"格式不对（{exc.errors()[0]['loc']}）：{stem[:30]}"
    fixed, fatal, warnings = normalize(data)
    if fatal:
        return None, f"{fatal}：{stem[:30]}"
    if fixed.qtype == "解答题" and len(fixed.analysis) < 10:
        return None, f"解答题没有解答步骤：{stem[:30]}"
    source = raw.get("source") if raw.get("source") in ("textbook", "generated") else "generated"
    return (
        {
            "qtype": fixed.qtype,
            "difficulty": raw.get("difficulty")
            if raw.get("difficulty") in ("容易", "中等", "较难")
            else "中等",
            "stem": fixed.stem,
            "options": fixed.options,
            "answer": fixed.answer,
            "analysis": fixed.analysis,
            "knowledge_points": points[:5],  # 导入时按名称关联，这里保留清单里的原名
            "source": source,
            "source_ref": str(raw.get("source_ref") or "")[:120] if source == "textbook" else "",
            "warnings": warnings,
        },
        "",
    )


def generate_section(
    book: BookPack, chapter: ChapterPack, section: SectionPack, engine: JsonEngine, out_dir: Path
) -> list[str]:
    """出一节的题，写 gen-<节>.json。返回丢掉的题和原因。"""
    material = section_material(out_dir, chapter, section.no)
    points = [(k.name, k.content) for k in section.knowledge_points]
    names = {name for name, _ in points}
    target = sum(PER_SECTION.values())
    prompt = pool_gen.gen_prompt(
        book,
        f"{section.no} {section.title}",
        points,
        material,
        single=PER_SECTION["单选题"],
        blank=PER_SECTION["填空题"],
        solve=PER_SECTION["解答题"],
    )
    problem = ""
    dropped: list[str] = []
    for attempt in range(1, MAX_ATTEMPTS + 1):
        request = (
            f"{prompt}\n\n上一次的输出有问题：{problem}。请修正后重新输出全部题目。" if problem else prompt
        )
        try:
            data = engine(request, pool_gen.gen_schema(sorted(names)))
        except Exception as exc:  # noqa: BLE001  命令行错误、输出不合格式都重试
            problem = str(exc)[:300]
            print(f"  {section.no} 第 {attempt} 次失败：{problem}", flush=True)
            continue
        good: list[dict[str, Any]] = []
        dropped = []
        for raw in data.get("questions") or []:
            question, reason = validate_question(raw, names)
            if question is None:
                dropped.append(reason)
            else:
                good.append(question)
        if len(good) < target * MIN_SHARE:
            problem = f"合格的题只有 {len(good)} 道，要 {target} 道；不合格的原因：{'；'.join(dropped[:5])}"
            print(f"  {section.no} 第 {attempt} 次题太少：{problem}", flush=True)
            continue
        path = _gen_file(out_dir, section.no)
        path.write_text(
            json.dumps(
                {"no": section.no, "questions": good, "dropped": dropped}, ensure_ascii=False, indent=2
            ),
            encoding="utf-8",
        )
        return dropped
    raise RuntimeError(f"{section.no} 出题失败：{problem}")


def _solve_batch(
    book: BookPack, numbered: list[tuple[int, dict[str, Any]]], engine: JsonEngine
) -> dict[int, dict[str, Any]]:
    data = engine(pool_gen.check_prompt(book, numbered), pool_gen.CHECK_SCHEMA)
    return {int(a["id"]): a for a in data.get("answers") or []}


def check_section(book: BookPack, section_no: str, engine: JsonEngine, out_dir: Path) -> dict[str, int]:
    """独立解一遍这一节的题，写 checked-<节>.json。返回各状态的题数。"""
    questions: list[dict[str, Any]] = json.loads(_gen_file(out_dir, section_no).read_text(encoding="utf-8"))[
        "questions"
    ]
    numbered = list(enumerate(questions))
    solved: dict[int, dict[str, Any]] = {}
    for start in range(0, len(numbered), CHECK_BATCH):
        batch = numbered[start : start + CHECK_BATCH]
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                solved.update(_solve_batch(book, batch, engine))
                break
            except Exception as exc:  # noqa: BLE001  校验失败的题标成没校验，不影响其他题
                print(f"  {section_no} 校验第 {attempt} 次失败：{str(exc)[:200]}", flush=True)

    to_judge: list[tuple[int, dict[str, Any], str]] = []
    for i, q in numbered:
        result = solved.get(i)
        if result is None:
            q["status"] = "unchecked"
            q["check_result"] = {"verdict": "error", "reason": "没能完成独立解答"}
            continue
        answer = normalize_math(str(result.get("answer") or "").strip())
        work = str(result.get("work") or "")[:2000]
        problem = str(result.get("problem") or "").strip()
        base = {"solver_answer": answer, "solver_work": normalize_math(work)}
        if problem:
            q["status"] = "disputed"
            q["check_result"] = {
                **base,
                "verdict": "disagree",
                "method": "rule",
                "reason": f"独立解答认为{problem}",
            }
            continue
        verdict, method = compare(q["qtype"], q["answer"], answer) if answer else (None, "")
        if verdict == "agree":
            q["status"] = "checked"
            q["check_result"] = {
                **base,
                "verdict": "agree",
                "method": method,
                "reason": "独立解答的答案和参考答案一致",
            }
        else:
            q["check_result"] = {**base, "verdict": verdict or "unsure", "method": method or "judge"}
            to_judge.append((i, q, answer or "（没有写出最终答案）"))

    for start in range(0, len(to_judge), CHECK_BATCH):
        batch = to_judge[start : start + CHECK_BATCH]
        verdicts: dict[int, dict[str, Any]] = {}
        try:
            data = engine(pool_gen.judge_prompt(book, batch), pool_gen.JUDGE_SCHEMA)
            verdicts = {int(r["id"]): r for r in data.get("results") or []}
        except Exception as exc:  # noqa: BLE001
            print(f"  {section_no} 比对失败：{str(exc)[:200]}", flush=True)
        for i, q, answer in batch:
            judged = verdicts.get(i) or {}
            consistent = judged.get("consistent")
            reason = str(judged.get("reason") or "").strip()[:500]
            if q["check_result"]["verdict"] == "disagree" and consistent is not False:
                # 规则或数值比对已经确定不一致，模型只负责说明
                consistent = False
                reason = f"独立解答得到「{answer}」，和参考答案「{q['answer']}」不一致"
            if consistent is True:
                q["status"] = "checked"
                q["check_result"].update(verdict="agree", method="judge", reason=reason or "答案一致")
            elif consistent is False:
                q["status"] = "disputed"
                q["check_result"].update(verdict="disagree", reason=reason or "答案不一致")
            else:
                q["status"] = "unchecked"
                q["check_result"].update(verdict="unsure", reason=reason or "没能自动判断，请人工核对")

    _checked_file(out_dir, section_no).write_text(
        json.dumps({"no": section_no, "questions": questions}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    counts: dict[str, int] = {}
    for q in questions:
        counts[q["status"]] = counts.get(q["status"], 0) + 1
    return counts


@dataclass
class SectionResult:
    no: str
    error: str = ""
    dropped: int = 0
    counts: dict[str, int] = field(default_factory=dict)


def _run_section(
    book: BookPack,
    chapter: ChapterPack,
    section: SectionPack,
    engine: JsonEngine,
    out_dir: Path,
    force: bool,
) -> SectionResult:
    try:
        dropped = 0
        if force or not _gen_file(out_dir, section.no).exists():
            dropped = len(generate_section(book, chapter, section, engine, out_dir))
            _checked_file(out_dir, section.no).unlink(missing_ok=True)
        if force or not _checked_file(out_dir, section.no).exists():
            counts = check_section(book, section.no, engine, out_dir)
        else:
            rows = json.loads(_checked_file(out_dir, section.no).read_text(encoding="utf-8"))["questions"]
            counts = {}
            for q in rows:
                counts[q["status"]] = counts.get(q["status"], 0) + 1
        return SectionResult(section.no, dropped=dropped, counts=counts)
    except Exception as exc:  # noqa: BLE001  一节失败不影响其他节，重跑时补上
        return SectionResult(section.no, error=str(exc)[:500])


def flag_beyond(question: dict[str, Any], taught: str) -> dict[str, Any]:
    """题目用了课本到这一节还没出现过的记号或方法：答案对也不算校验通过，要人工看。"""
    text = " ".join([question["stem"], question["answer"], question["analysis"], *question["options"]])
    found = [
        name
        for name, pattern in BEYOND_TERMS.items()
        if re.search(pattern, text) and not re.search(pattern, taught)
    ]
    if not found:
        return question
    status = "unchecked" if question["status"] == "checked" else question["status"]
    warning = f"用到了课本到这一节还没讲过的内容：{'、'.join(found)}，请确认学生学过"
    return {**question, "status": status, "warnings": [*question.get("warnings", []), warning]}


def merge(book: BookPack, out_dir: Path) -> Path:
    """把各节的结果合并成题包，同时把写在公式里的横线移出来、标出超出已学范围的题。"""
    questions = []
    taught = ""
    for chapter in book.chapters:
        parts = dict(_scan_parts(out_dir, chapter))
        taught += parts.get("intro", "")
        for section in chapter.sections:
            taught += parts.get(section.no, "")
            data = json.loads(_checked_file(out_dir, section.no).read_text(encoding="utf-8"))
            for q in data["questions"]:
                fixed = {**q, "stem": blanks_out_of_math(q["stem"])}
                questions.append({"section_no": section.no, **flag_beyond(fixed, taught)})
        taught += parts.get("tail", "")
    path = out_dir / "questions.json"
    path.write_text(
        json.dumps(
            {
                "book_key": book.key,
                "provenance": {
                    "prompt_version": pool_gen.PROMPT_VERSION,
                    "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
                },
                "questions": questions,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


def run(
    pack_dir: Path,
    *,
    only: set[str] | None = None,
    concurrency: int = 3,
    force: bool = False,
    model: str | None = None,
    effort: str = "medium",
    engine: JsonEngine | None = None,
) -> Path | None:
    """全部节都完成时写出 questions.json 并返回路径，否则返回 None。"""
    book = load_pack(pack_dir / "pack.json")
    (pack_dir / "questions").mkdir(exist_ok=True)
    if engine is None:
        engine = codex_json_engine(model, effort)
    chosen = engine
    todo = [
        (chapter, section)
        for chapter in book.chapters
        for section in chapter.sections
        if only is None or section.no in only
    ]
    print(f"《{book.title}》这次处理 {len(todo)} 节", flush=True)

    def work(pair: tuple[ChapterPack, SectionPack]) -> SectionResult:
        result = _run_section(book, pair[0], pair[1], chosen, pack_dir, force)
        label = result.error or f"{result.counts}，丢弃 {result.dropped} 道"
        print(f"  {result.no}：{label}", flush=True)
        return result

    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        results = list(pool.map(work, todo))
    failed = [r for r in results if r.error]
    if failed:
        print(f"有 {len(failed)} 节失败，重跑同样的命令会补上", flush=True)
    missing = [s.no for c in book.chapters for s in c.sections if not _checked_file(pack_dir, s.no).exists()]
    if missing:
        print(f"还有这些节没完成，没有写 questions.json：{'、'.join(missing)}", flush=True)
        return None
    path = merge(book, pack_dir)
    print(f"已写出 {path}", flush=True)
    return path

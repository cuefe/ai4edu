"""用真实模型跑教案生成评测：每条用例生成一份教案，记录自动检查结果，供人工按 README 的标准打分。

用法（在 server 目录下，需要 server/.env 里配好模型 Key）：
    uv run python ../evals/lesson_plan/run.py              # 全部用例
    uv run python ../evals/lesson_plan/run.py --cases 1,7  # 只跑第 1、7 条

结果写到 evals/lesson_plan/out/<时间>/：每条一个 .md，外加 summary.md。
"""

import argparse
import asyncio
import sys
import time
from datetime import datetime
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "server"))

from app.ai.gateway.gateway import CallContext, get_gateway  # noqa: E402
from app.ai.skills import lesson_plan  # noqa: E402

CONCURRENCY = 3


async def run_case(n: int, p: lesson_plan.LessonPlanIn, out: Path, sem: asyncio.Semaphore) -> dict:
    async with sem:
        started = time.monotonic()
        parts = [lesson_plan.header_markdown(p)]
        try:
            stream = get_gateway().stream(
                lesson_plan.SKILL,
                lesson_plan.build_messages(p),
                ctx=CallContext(),
                temperature=0.7,
                max_tokens=8000,
            )
            async for delta in stream:
                parts.append(delta)
            error = None
        except Exception as exc:  # 评测要跑完所有用例，单条失败只记录
            error = repr(exc)
        md = "".join(parts)
        (out / f"{n:02d}.md").write_text(md, encoding="utf-8")
        print(f"[{n}] {p.subject} {p.topic}：{'失败' if error else '完成'}", flush=True)
        return {
            "n": n,
            "case": p,
            "seconds": round(time.monotonic() - started),
            "chars": len(md),
            "warnings": [error] if error else lesson_plan.check_output(md, p),
        }


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", help="只跑这些编号（从 1 开始），逗号分隔")
    args = parser.parse_args()

    cases = yaml.safe_load((HERE / "cases.yaml").read_text(encoding="utf-8"))
    picked = {int(x) for x in args.cases.split(",")} if args.cases else set(range(1, len(cases) + 1))
    out = HERE / "out" / datetime.now().strftime("%Y%m%d-%H%M%S")
    out.mkdir(parents=True)

    sem = asyncio.Semaphore(CONCURRENCY)
    results = await asyncio.gather(
        *(
            run_case(n, lesson_plan.LessonPlanIn(**c), out, sem)
            for n, c in enumerate(cases, start=1)
            if n in picked
        )
    )

    lines = [
        f"# 教案生成评测 {out.name}",
        "",
        f"prompt 版本：{lesson_plan.PROMPT_VERSION}",
        "",
        "| # | 学科 | 课题 | 课型 | 用时 | 字数 | 自动检查 | 人工评分 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in results:
        p = r["case"]
        checks = "；".join(r["warnings"]) or "通过"
        lines.append(
            f"| [{r['n']}]({r['n']:02d}.md) | {p.subject} | {p.topic} | {p.lesson_type} "
            f"| {r['seconds']}s | {r['chars']} | {checks} |  |"
        )
    passed = sum(not r["warnings"] for r in results)
    lines += ["", f"自动检查通过 {passed}/{len(results)}。人工评分标准见 evals/lesson_plan/README.md。"]
    (out / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n自动检查通过 {passed}/{len(results)}，结果在 {out}")


if __name__ == "__main__":
    asyncio.run(main())

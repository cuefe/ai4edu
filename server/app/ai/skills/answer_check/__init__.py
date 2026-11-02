"""答案校验：推理模型在看不到答案的情况下独立求解，再和题目给的答案比对。

比对先用规则（选项字母、对错、文字、数值，见 compare.py），判断不了或不一致时请模型比对，
不一致时由模型说明分歧在哪、哪边更可能对，给老师审核参考。
"""

from dataclasses import dataclass
from typing import Literal

from app.ai.gateway.gateway import AIGateway, CallContext
from app.ai.skills.answer_check.compare import compare
from app.ai.skills.answer_check.prompt import (
    JUDGE_SKILL,
    PROMPT_VERSION,
    SOLVE_SKILL,
    final_answer,
    judge_messages,
    solve_messages,
)
from app.ai.skills.common import normalize_math, parse_json
from app.ai.skills.question_gen import QuestionData
from app.core.errors import AppError

__all__ = ["JUDGE_SKILL", "PROMPT_VERSION", "SOLVE_SKILL", "CheckResult", "check", "compare", "final_answer"]

SOLVE_TIMEOUT = 300  # 推理模型想得久，难题要一两分钟

Verdict = Literal["agree", "disagree", "unsure", "error"]


@dataclass
class CheckResult:
    verdict: Verdict  # agree 一致 / disagree 不一致 / unsure 判断不了 / error 校验失败
    method: str  # rule 规则比对 / numeric 数值比对 / judge 模型比对
    solver_model: str | None
    solver_answer: str | None
    solver_work: str
    reason: str


async def check(gateway: AIGateway, q: QuestionData, subject: str, ctx: CallContext) -> CheckResult:
    try:
        solved = await gateway.chat(SOLVE_SKILL, solve_messages(q, subject), ctx=ctx, timeout=SOLVE_TIMEOUT)
    except AppError:
        return CheckResult("error", "", None, None, "", "校验服务暂时不可用，可以稍后重新校验")
    model = f"{solved.provider}/{solved.model}"
    work = normalize_math(solved.text.strip())
    answer = final_answer(work)
    # 有的推理模型正文只写答案，解题过程都在思考内容里；老师核对分歧时要看过程
    if len(work) < 80 and solved.reasoning:
        work = f"{normalize_math(solved.reasoning.strip())}\n\n{work}"
    work = work[-6000:]
    if answer and answer.startswith("题目有问题"):
        return CheckResult("disagree", "rule", model, answer, work, f"独立解答认为{answer}")

    verdict, method = compare(q.qtype, q.answer, answer) if answer else (None, "")
    if verdict == "agree":
        return CheckResult("agree", method, model, answer, work, "独立解答的答案和参考答案一致")

    judged = await _judge(gateway, q, subject, answer or "（没有写出最终答案）", work, ctx)
    if verdict == "disagree":  # 规则或数值比对已确定不一致，模型只负责说明分歧
        reason = f"独立解答得到「{answer}」，和参考答案「{q.answer}」不一致"
        if judged and judged[0] is False:
            reason = judged[1]
        return CheckResult("disagree", method, model, answer, work, reason)
    if judged is None or judged[0] is None:
        reason = judged[1] if judged else "没能自动判断两个答案是否一致，请人工核对"
        return CheckResult("unsure", "judge", model, answer, work, reason)
    return CheckResult("agree" if judged[0] else "disagree", "judge", model, answer, work, judged[1])


async def _judge(
    gateway: AIGateway, q: QuestionData, subject: str, answer: str, work: str, ctx: CallContext
) -> tuple[bool | None, str] | None:
    try:
        result = await gateway.chat(
            JUDGE_SKILL,
            judge_messages(q, subject, answer, work),
            ctx=ctx,
            temperature=0,
            max_tokens=1000,
            response_format={"type": "json_object"},
        )
        data = parse_json(result.text)
    except AppError:
        return None
    consistent = data.get("consistent")
    if not isinstance(consistent, bool):
        consistent = None
    reason = str(data.get("reason") or "").strip()[:500]
    return consistent, reason or ("答案一致" if consistent else "答案不一致")

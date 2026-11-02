from app.ai.gateway.gateway import Messages
from app.ai.skills.question_gen import CHOICE_TYPES, QuestionData

SOLVE_SKILL = "answer_check"  # 推理模型独立求解
JUDGE_SKILL = "answer_judge"  # 比对两个答案是否一致
PROMPT_VERSION = "2026-11-02.2"  # .2：比对时只看参考答案，解析和答案矛盾算不一致

_SOLVE_SYSTEM = """你是一位严谨的初中{subject}老师，正在独立做一道题，用来核对它的标准答案。

要求：
1. 认真审题，独立解答，写出简要的解题过程。
2. 最后单独一行，以“【答案】”开头写最终答案：
   - 单选题只写选项字母，如“【答案】B”；多选题按字母顺序写全部正确选项，如“【答案】AC”
   - 判断题写“【答案】对”或“【答案】错”
   - 填空题按空的顺序写，多个空用“；”隔开
   - 解答题写最终结果，多问的按 (1)(2) 分别写；证明题写“【答案】见证明”
3. 如果题目条件不足、有歧义、没有正确选项或不止一个正确选项（单选题），写“【答案】题目有问题：”再说明原因。
4. 数学式子用 LaTeX，行内用 $...$。"""

_JUDGE_SYSTEM = """你是初中{subject}教研员，负责核对题目答案。下面有一道题、题目给出的参考答案和解析，以及另一位老师独立解出的答案和过程。判断两边的最终答案是否一致。

- 只拿“参考答案”这一项和独立解答的最终答案比。参考解析的结论和参考答案对不上（如解析说选 A、参考答案写 B），算不一致，并在 reason 里指出参考答案和解析自相矛盾。
- 数学上等价的不同写法算一致，如 $\\frac{{1}}{{2}}$ 和 0.5、x=2 和 2、$2\\sqrt{{3}}$ 和 $\\sqrt{{12}}$。
- 答案不唯一的题（如“写出一个负整数”），独立解出的答案也满足题意就算一致。
- 解答题、证明题看最终结论是否一致，过程写法不同不要紧。
- 独立解答认为题目有问题（条件不足、有歧义、没有正确选项）时，算不一致。
- 不一致时，在 reason 里说明分歧在哪里，并判断哪一边更可能是对的、为什么。一致时 reason 写一句话即可。

只输出 JSON：{{"consistent": true 或 false, "reason": "说明"}}"""

_MARK = "【答案】"


def format_question(q: QuestionData) -> str:
    lines = [f"题型：{q.qtype}", f"题目：{q.stem}"]
    if q.qtype in CHOICE_TYPES:
        lines += [f"{chr(65 + i)}. {o}" for i, o in enumerate(q.options)]
    return "\n".join(lines)


def solve_messages(q: QuestionData, subject: str) -> Messages:
    return [
        {"role": "system", "content": _SOLVE_SYSTEM.format(subject=subject)},
        {"role": "user", "content": format_question(q)},
    ]


def judge_messages(q: QuestionData, subject: str, solver_answer: str, solver_work: str) -> Messages:
    content = "\n".join(
        [
            format_question(q),
            "",
            f"参考答案：{q.answer}",
            f"参考解析：{q.analysis or '（无）'}",
            "",
            f"独立解答的答案：{solver_answer}",
            "独立解答的过程（在 <<< 和 >>> 之间）：",
            "<<<",
            solver_work,
            ">>>",
        ]
    )
    return [
        {"role": "system", "content": _JUDGE_SYSTEM.format(subject=subject)},
        {"role": "user", "content": content},
    ]


def final_answer(text: str) -> str | None:
    """取最后一个“【答案】”后面的内容。"""
    i = text.rfind(_MARK)
    if i == -1:
        return None
    answer = text[i + len(_MARK) :].lstrip(":： ").strip()
    return answer[:500] or None

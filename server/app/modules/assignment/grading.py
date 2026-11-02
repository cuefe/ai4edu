"""客观题自动判分。

返回得分比例（0～1）；判断不了的（如文字表述不同的填空）返回 None，交给 AI 批改、老师确认。
"""

import re

from app.ai.skills.answer_check import compare
from app.ai.skills.question_gen import choice_letters, truth_value

OBJECTIVE = ("单选题", "多选题", "判断题", "填空题")
DEFAULT_SCORE = {"单选题": 5, "多选题": 5, "判断题": 5, "填空题": 5, "解答题": 10}


def split_blanks(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"[；;]", text)]


def objective_ratio(qtype: str, answer: str, response: str) -> float | None:
    if qtype not in OBJECTIVE:
        return None
    if not response.strip():
        return 0.0
    if qtype in ("单选题", "多选题"):
        expected, got = choice_letters(answer), choice_letters(response)
        if expected is None:
            return None
        if got is None:
            return 0.0
        if got == expected:
            return 1.0
        # 多选题：少选（选的都对）得一半，错选不得分
        if qtype == "多选题" and set(got) < set(expected):
            return 0.5
        return 0.0
    if qtype == "判断题":
        expected_truth = truth_value(answer)
        if expected_truth is None:
            return None
        return 1.0 if truth_value(response) == expected_truth else 0.0

    expected_parts = [p for p in split_blanks(answer) if p]
    got_parts = split_blanks(response)
    got_parts += [""] * (len(expected_parts) - len(got_parts))
    correct = 0
    for exp, got in zip(expected_parts, got_parts, strict=False):
        if not got:
            continue
        verdict, _ = compare("填空题", exp, got)
        if verdict is None:
            return None
        correct += verdict == "agree"
    return correct / len(expected_parts) if expected_parts else None


def points(ratio: float, full: float) -> float:
    """按比例算分，保留到 0.5 分。"""
    return round(ratio * full * 2) / 2

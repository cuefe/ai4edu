"""题目结构检查：AI 出的题、老师录入的题都走这里。

致命问题（选项不全、答案不是选项字母等）返回错误说明，题目不能保存；
小问题（填空数和答案数对不上等）作为提示保存在题目上，老师审核时能看到。
"""

import re
import unicodedata

from app.ai.skills.common import normalize_math
from app.ai.skills.question_gen.schema import CHOICE_TYPES, QuestionData

LETTERS = "ABCDEF"
_OPTION_PREFIX = re.compile(r"^\s*[（(]?[A-Fa-f][)）]?\s*[.．、:：)）]\s*")
_BLANK = re.compile(r"_{3,}|＿{2,}|[（(]\s{2,}[)）]")
_BLANK_RUN = re.compile(r"(_{3,}|＿{2,})")
_INLINE_MATH = re.compile(r"(?<!\$)\$(?!\$)([^$]+?)\$(?!\$)")
TRUE_WORDS = {"对", "正确", "√", "✓", "T", "TRUE", "是"}
FALSE_WORDS = {"错", "错误", "×", "✗", "F", "FALSE", "否"}


def choice_letters(text: str) -> str | None:
    """'B'、'（B）'、'选 B'、'A,C' → 'B'、'AC'；有其他字母或没有选项字母时返回 None。"""
    s = unicodedata.normalize("NFKC", text).upper()
    s = re.sub(r"[一-鿿\s,，、;；.。()（）和与及]", "", s)
    if not s or not re.fullmatch(r"[A-F]+", s):
        return None
    return "".join(sorted(set(s)))


def truth_value(text: str) -> bool | None:
    s = unicodedata.normalize("NFKC", text).strip().strip("。.").upper()
    if s in TRUE_WORDS:
        return True
    if s in FALSE_WORDS:
        return False
    return None


def blanks_out_of_math(stem: str) -> str:
    """把写在公式里的填空横线移到公式外面：$x=＿＿＿＿$ → $x=$＿＿＿＿。公式里的全角横线显示不正常。"""

    def fix(match: re.Match[str]) -> str:
        pieces = _BLANK_RUN.split(match.group(1))
        if len(pieces) == 1:
            return match.group(0)
        out = []
        for piece in pieces:
            if _BLANK_RUN.fullmatch(piece):
                out.append(piece)
            elif piece.strip():
                out.append(f"${piece}$")
        return "".join(out)

    return _INLINE_MATH.sub(fix, stem)


def normalize(q: QuestionData) -> tuple[QuestionData, str | None, list[str]]:
    """返回（规范化后的题目，致命问题，提示）。"""
    warnings: list[str] = []
    options = [normalize_math(_OPTION_PREFIX.sub("", o).strip()) for o in q.options]
    answer = normalize_math(q.answer.strip())
    if q.qtype in CHOICE_TYPES:
        if len(options) < 3 or any(not o for o in options):
            return q, f"{q.qtype}要有 3～6 个选项，且不能为空", []
        if len(set(options)) != len(options):
            return q, "选项有重复", []
        letters = choice_letters(answer)
        valid = LETTERS[: len(options)]
        if letters is None or any(c not in valid for c in letters):
            return q, f"答案要写选项字母（{valid[0]}～{valid[-1]}）", []
        if q.qtype == "单选题" and len(letters) != 1:
            return q, "单选题只能有一个正确选项", []
        if q.qtype == "多选题" and len(letters) < 2:
            warnings.append("多选题只有一个正确选项，请确认题型")
        answer = letters
    else:
        options = []
        if q.qtype == "判断题":
            value = truth_value(answer)
            if value is None:
                return q, "判断题的答案要写“对”或“错”", []
            answer = "对" if value else "错"
        elif q.qtype == "填空题":
            blanks = len(_BLANK.findall(q.stem))
            parts = [a for a in re.split(r"[；;]", answer) if a.strip()]
            if not blanks:
                warnings.append("题干里没有找到填空横线（＿＿＿）")
            elif blanks != len(parts):
                warnings.append(f"题干有 {blanks} 个空，答案有 {len(parts)} 个，请核对")
    points = [p.strip()[:30] for p in q.knowledge_points if p.strip()][:5]
    fixed = q.model_copy(
        update={
            "stem": blanks_out_of_math(normalize_math(q.stem)),
            "options": options,
            "answer": answer,
            "analysis": normalize_math(q.analysis),
            "knowledge_points": points,
        }
    )
    return fixed, None, warnings

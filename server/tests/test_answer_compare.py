import asyncio

import pytest

from app.ai.gateway.gateway import CallContext, ChatResult
from app.ai.skills.answer_check import check, compare, final_answer
from app.ai.skills.common import normalize_math
from app.ai.skills.question_gen import QuestionData, normalize


@pytest.mark.parametrize(
    ("qtype", "expected", "got", "verdict", "method"),
    [
        ("单选题", "B", "B", "agree", "rule"),
        ("单选题", "B", "（B）", "agree", "rule"),
        ("单选题", "B", "选 C", "disagree", "rule"),
        ("多选题", "AC", "C、A", "agree", "rule"),
        ("多选题", "AC", "ACD", "disagree", "rule"),
        ("单选题", "B", "B. $-3$", None, ""),  # 带了选项内容，交给模型
        ("判断题", "对", "正确", "agree", "rule"),
        ("判断题", "对", "×", "disagree", "rule"),
        ("填空题", "-3", " -3 。", "agree", "rule"),
        ("填空题", "$\\frac{1}{2}$", "0.5", "agree", "numeric"),
        ("填空题", "\\dfrac{-3}{4}", "-0.75", "agree", "numeric"),
        ("填空题", "2\\sqrt{3}", "\\sqrt{12}", "agree", "numeric"),
        ("填空题", "\\sqrt[3]{-8}", "-2", "agree", "numeric"),
        ("填空题", "x=2", "2", "agree", "numeric"),
        ("填空题", "±2", "2 或 -2", "agree", "numeric"),
        ("填空题", "x_1=2，x_2=-3", "-3,2", "agree", "numeric"),
        ("填空题", "2(x+1)", "2x+2", "agree", "numeric"),
        ("填空题", "a^2-b^2", "(a+b)(a-b)", "agree", "numeric"),
        ("填空题", "2x+1", "2x-1", "disagree", "numeric"),
        ("填空题", "5", "-5", "disagree", "numeric"),
        ("填空题", "30°", "30", "agree", "numeric"),
        ("填空题", "50%", "0.5", "agree", "numeric"),
        ("填空题", "3；-1", "3；-1", "agree", "rule"),
        ("填空题", "3；-1", "3；1", "disagree", "numeric"),
        ("填空题", "3；-1", "3", None, ""),  # 空的个数不一样
        ("填空题", "0.33", "\\frac{1}{3}", None, ""),  # 近似值交给模型
        ("填空题", "5cm", "5", None, ""),  # 带单位交给模型
        ("填空题", "x>2", "x>2", "agree", "rule"),
        ("填空题", "x>2", "x≥2", None, ""),
        ("填空题", "互为相反数", "相反数", None, ""),
        ("填空题", "went", "Went", "agree", "rule"),
        ("填空题", "9^{9^{9}}", "1", None, ""),  # 太大的乘方不算
        ("解答题", "__import__('os')", "0", None, ""),  # 不执行任意代码
    ],
)
def test_compare(qtype, expected, got, verdict, method):
    assert compare(qtype, expected, got) == (verdict, method)


def test_normalize_math_delimiters():
    assert normalize_math("由 \\(a=2\\) 得\n\\[\n a^b \\]") == "由 $a=2$ 得\n$$a^b$$"


def test_check_shows_reasoning_when_answer_only():
    """推理模型正文只写了答案：解题过程取思考内容；\\( \\) 写法的答案也能做数值比对。"""

    class Gateway:
        async def chat(self, skill, messages, *, ctx, **params):
            return ChatResult(
                "【答案】\\(\\frac18\\)", "fake", "pro", 1, 1, 1, reasoning="a=2，b=-3，所以 \\(2^{-3}\\)"
            )

    q = QuestionData(qtype="填空题", stem="若 $|a-2|+(b+3)^2=0$，则 $a^b=$＿＿＿＿", answer="$\\frac{1}{8}$")
    result = asyncio.run(check(Gateway(), q, "数学", CallContext()))  # type: ignore[arg-type]
    assert (result.verdict, result.method, result.solver_answer) == ("agree", "numeric", "$\\frac18$")
    assert result.solver_work == "a=2，b=-3，所以 $2^{-3}$\n\n【答案】$\\frac18$"


def test_final_answer_takes_the_last_mark():
    text = "先想【答案】可能是 A。\n验算后发现不对。\n【答案】：B\n"
    assert final_answer(text) == "B"
    assert final_answer("没有写答案") is None


@pytest.mark.parametrize(
    ("data", "problem", "answer", "options"),
    [
        (
            {"qtype": "单选题", "options": ["A. 1", "B．2", "C、3", "(D) 4"], "answer": "（b）"},
            None,
            "B",
            ["1", "2", "3", "4"],
        ),
        (
            {"qtype": "单选题", "options": ["1", "2", "3", "4"], "answer": "E"},
            "答案要写选项字母（A～D）",
            None,
            None,
        ),
        (
            {"qtype": "单选题", "options": ["1", "2", "3", "4"], "answer": "AB"},
            "单选题只能有一个正确选项",
            None,
            None,
        ),
        (
            {"qtype": "单选题", "options": ["1", "2"], "answer": "A"},
            "单选题要有 3～6 个选项，且不能为空",
            None,
            None,
        ),
        ({"qtype": "单选题", "options": ["1", "1", "2", "3"], "answer": "A"}, "选项有重复", None, None),
        ({"qtype": "判断题", "options": ["对", "错"], "answer": "√"}, None, "对", []),
        ({"qtype": "判断题", "answer": "也许"}, "判断题的答案要写“对”或“错”", None, None),
    ],
)
def test_normalize(data, problem, answer, options):
    q = QuestionData(stem="题目＿＿＿＿", **data)
    fixed, found, _ = normalize(q)
    assert found == problem
    if problem is None:
        assert (fixed.answer, fixed.options) == (answer, options)


def test_normalize_warns_about_blanks():
    q = QuestionData(qtype="填空题", stem="$-3$ 的相反数是＿＿＿＿，绝对值是＿＿＿＿", answer="3")
    assert normalize(q)[2] == ["题干有 2 个空，答案有 1 个，请核对"]
    multi = QuestionData(qtype="多选题", stem="选出正数", options=["1", "-1", "0", "-2"], answer="A")
    assert normalize(multi)[2] == ["多选题只有一个正确选项，请确认题型"]

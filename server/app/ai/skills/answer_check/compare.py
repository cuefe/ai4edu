"""不调模型的答案比对：选择题比字母，判断题比对错，填空和解答题先比文字、再比数值。

数值比对把答案里的 LaTeX 转成算式，用受限的求值器（只允许数字、四则运算、乘方、开方、π 和单个字母的变量）
算出结果；含字母的式子在几组固定取值下分别求值，结果都相等就认为等价（如 2(x+1) 和 2x+2）。
不执行任意代码，也不依赖 SymPy。判断不了的（文字答案、不等式、近似值等）返回 None，交给模型判断。
"""

import ast
import math
import re
import unicodedata
from typing import Literal

from app.ai.skills.question_gen import CHOICE_TYPES, choice_letters, truth_value

Verdict = Literal["agree", "disagree"]

_MAX_LEN = 200
_SAMPLES = 3


class _Unsupported(Exception):
    pass


def compare(qtype: str, expected: str, got: str) -> tuple[Verdict | None, str]:
    """返回（结论，比对方式）。结论为 None 表示判断不了。比对方式：rule 规则 / numeric 数值。"""
    if qtype in CHOICE_TYPES:
        e, g = choice_letters(expected), choice_letters(got)
        if e is None or g is None:
            return None, ""
        return ("agree" if e == g else "disagree"), "rule"
    if qtype == "判断题":
        a, b = truth_value(expected), truth_value(got)
        if a is None or b is None:
            return None, ""
        return ("agree" if a == b else "disagree"), "rule"

    ep, gp = _parts(expected), _parts(got)
    if not ep or len(ep) != len(gp):
        return None, ""
    if [_norm(x) for x in ep] == [_norm(x) for x in gp]:
        return "agree", "rule"
    verdicts = [_numeric(a, b) for a, b in zip(ep, gp, strict=True)]
    if None in verdicts:
        return None, ""
    return ("agree" if all(v == "agree" for v in verdicts) else "disagree"), "numeric"


def _parts(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"[；;\n]", text) if p.strip()]


def _norm(text: str) -> str:
    s = unicodedata.normalize("NFKC", text).lower()
    s = re.sub(r"\$|\\[,;!]|\s", "", s)
    return s.rstrip("。.")


def _numeric(expected: str, got: str) -> Verdict | None:
    try:
        a, b = _values(expected), _values(got)
    except _Unsupported:
        return None
    names_a = {n for _, names in a for n in names}
    names_b = {n for _, names in b for n in names}
    if len(a) != len(b) or names_a != names_b:  # 值的个数或字母不一样（可能带了单位），交给模型
        return None
    approx = False
    for (va, _), (vb, _) in zip(sorted(a, key=lambda v: v[0]), sorted(b, key=lambda v: v[0]), strict=True):
        for x, y in zip(va, vb, strict=True):
            if math.isclose(x, y, rel_tol=1e-6, abs_tol=1e-9):
                continue
            if math.isclose(x, y, rel_tol=1e-2):  # 很接近：可能是四舍五入的近似值
                approx = True
                continue
            return "disagree"
    return None if approx else "agree"


def _values(text: str) -> list[tuple[tuple[float, ...], frozenset[str]]]:
    """一个空的答案可能有多个值："±2"、"2 或 -3"、"x₁=2，x₂=-3"。"""
    s = unicodedata.normalize("NFKC", text)
    if "≈" in s or "约" in s or len(s) > _MAX_LEN:
        raise _Unsupported
    s = re.sub(r"\$|\\left|\\right|\\displaystyle|\\[,;!]|\s", "", s)
    s = re.sub(r"\\[dt]frac", r"\\frac", s)
    out = []
    for piece in re.split(r"或|,|，|、|\\text\{或\}", s):
        if not piece:
            continue
        piece = re.sub(r"^[a-zA-Z](?:_?\{?\d+\}?)?=", "", piece)  # x=2、x_1=2 只看右边
        if "±" in piece or "\\pm" in piece:
            plus = piece.replace("\\pm", "+").replace("±", "+")
            minus = piece.replace("\\pm", "-").replace("±", "-")
            out += [_evaluate(_to_python(plus)), _evaluate(_to_python(minus))]
        else:
            out.append(_evaluate(_to_python(piece)))
    if not out:
        raise _Unsupported
    return out


def _to_python(s: str) -> str:
    s = s.replace("−", "-").replace("×", "*").replace("÷", "/").replace("·", "*").replace("π", "\\pi")
    s = s.replace("°", "").replace("%", "/100")
    s = s.replace("\\times", "*").replace("\\cdot", "*").replace("\\div", "/").replace("\\pi", " pi ")
    s = _replace_frac(s)
    s = _replace_sqrt(s)
    s = re.sub(r"√(\d+(?:\.\d+)?|[a-zA-Z])", r"sqrt(\1)", s).replace("√(", "sqrt(")
    if "\\" in s:  # 还有不认识的 LaTeX 命令
        raise _Unsupported
    s = s.replace("{", "(").replace("}", ")").replace("^", "**")
    return _implicit_multiply(s)


def _replace_frac(s: str) -> str:
    """\\frac{a}{b} → ((a)/(b))，支持嵌套。"""
    while (i := s.find("\\frac")) != -1:
        a, j = _braced(s, i + 5)
        b, k = _braced(s, j)
        s = f"{s[:i]}(({a})/({b})){s[k:]}"
    return s


def _replace_sqrt(s: str) -> str:
    """\\sqrt{x} → sqrt(x)，\\sqrt[n]{x} → root(n,x)。"""
    while (i := s.find("\\sqrt")) != -1:
        j = i + 5
        n = None
        if s[j : j + 1] == "[":
            end = s.find("]", j)
            if end == -1:
                raise _Unsupported
            n, j = s[j + 1 : end], end + 1
        x, k = _braced(s, j)
        s = f"{s[:i]}{f'root({n},{x})' if n else f'sqrt({x})'}{s[k:]}"
    return s


def _braced(s: str, i: int) -> tuple[str, int]:
    if i < len(s) and s[i] != "{":  # \frac12、\sqrt3 这种简写
        return s[i], i + 1
    depth = 0
    for j in range(i, len(s)):
        depth += {"{": 1, "}": -1}.get(s[j], 0)
        if depth == 0:
            return s[i + 1 : j], j + 1
    raise _Unsupported


_TOKEN = re.compile(r"\s*(sqrt|root|pi|\d+\.?\d*|\.\d+|[a-zA-Z]|\*\*|[-+*/(),])")


def _implicit_multiply(s: str) -> str:
    """补上省略的乘号：2x → 2*x，2(x+1) → 2*(x+1)，(a)(b) → (a)*(b)。"""
    tokens: list[str] = []
    pos = 0
    while pos < len(s):
        m = _TOKEN.match(s, pos)
        if not m:
            raise _Unsupported
        tokens.append(m.group(1))
        pos = m.end()
    out: list[str] = []
    for t in tokens:
        if out:
            prev = out[-1]
            left = (
                prev == ")"
                or prev[0].isdigit()
                or prev[0] == "."
                or (prev.isalpha() and prev not in ("sqrt", "root"))
            )
            right = t == "(" or t[0].isdigit() or t[0] == "." or t.isalpha()
            if left and right:
                out.append("*")
        out.append(t)
    return "".join(out)


def _evaluate(expr: str) -> tuple[tuple[float, ...], frozenset[str]]:
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        raise _Unsupported from exc
    names = frozenset(
        n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and n.id not in ("pi", "sqrt", "root")
    )
    values = []
    for k in range(_SAMPLES):
        env = {v: 1.1 + 0.7 * i + 0.9 * k for i, v in enumerate(sorted(names))}
        try:
            values.append(_eval(tree.body, env))
        except (ArithmeticError, ValueError) as exc:
            raise _Unsupported from exc
    return tuple(values), names


def _eval(node: ast.expr, env: dict[str, float]) -> float:
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        return float(node.value)
    if isinstance(node, ast.Name):
        if node.id == "pi":
            return math.pi
        if node.id in env:
            return env[node.id]
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        v = _eval(node.operand, env)
        return -v if isinstance(node.op, ast.USub) else v
    if isinstance(node, ast.BinOp):
        a, b = _eval(node.left, env), _eval(node.right, env)
        if isinstance(node.op, ast.Add):
            return a + b
        if isinstance(node.op, ast.Sub):
            return a - b
        if isinstance(node.op, ast.Mult):
            return a * b
        if isinstance(node.op, ast.Div):
            return a / b
        if isinstance(node.op, ast.Pow):
            if abs(b) > 64 or abs(a) > 1e8:  # 防止算出天文数字卡住
                raise ValueError("too large")
            result = a**b
            if isinstance(result, complex):
                raise ValueError("complex")
            return result
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and not node.keywords:
        args = [_eval(a, env) for a in node.args]
        if node.func.id == "sqrt" and len(args) == 1:
            return math.sqrt(args[0])
        if node.func.id == "root" and len(args) == 2:  # root(n,x)：n 次方根
            n, x = args
            if x >= 0:
                return x ** (1 / n)
            if n % 2 == 1:
                return -((-x) ** (1 / n))
            raise ValueError("even root of negative")
    raise _Unsupported

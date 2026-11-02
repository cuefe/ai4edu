"""各技能共用：学科年级选项、资料库引用、JSON 输出解析。"""

import json
import re
from dataclasses import dataclass
from typing import Any, Literal

from app.core.errors import AppError

Subject = Literal["数学", "英语"]
Grade = Literal["七年级上册", "七年级下册", "八年级上册", "八年级下册", "九年级上册", "九年级下册"]


@dataclass
class Source:
    """资料库检索到的片段，在生成的文档里按编号引用。"""

    label: str  # 如：《有理数.pptx》第 3 页
    text: str


CITE_RULE = (
    "用到资料库片段的内容时，在那句话末尾标注片段编号，如 [1]、[2]；没用到片段的地方不要标注。"
    "不要在文末另写参考资料列表（系统会自动附上）。"
)


def sources_prompt(sources: list[Source]) -> list[str]:
    """放进用户消息的资料库片段，方括号里是引用编号。"""
    if not sources:
        return []
    lines = ["", "从老师资料库里检索到的相关片段（在 <<< 和 >>> 之间，方括号里是引用编号）：", "<<<"]
    for i, s in enumerate(sources, start=1):
        lines += [f"[{i}] {s.label}", s.text, ""]
    lines.append(">>>")
    return lines


def cited_numbers(md: str, n_sources: int) -> set[int]:
    return {int(n) for n in re.findall(r"\[(\d{1,2})\]", md) if 1 <= int(n) <= n_sources}


def sources_markdown(sources: list[Source], cited: set[int]) -> str:
    """附在文档末尾的引用列表，只列正文里实际引用了的，编号和正文里的 [n] 对应。"""
    if not cited:
        return ""
    items = "\n".join(f"- [{i}] {s.label}" for i, s in enumerate(sources, start=1) if i in cited)
    intro = "正文中的 [编号] 对应以下资料库内容，可以在「资料库」里打开原文核对。"
    return f"\n\n## 参考资料\n\n{intro}\n\n{items}\n"


_INLINE_MATH = re.compile(r"\\\((.+?)\\\)", re.S)
_BLOCK_MATH = re.compile(r"\\\[(.+?)\\\]", re.S)


def normalize_math(text: str) -> str:
    r"""把 \( \)、\[ \] 公式定界符换成 $ $、$$ $$：前端和 Word 导出只认 $ 写法，个别模型会用 \( \)。"""
    text = _BLOCK_MATH.sub(lambda m: f"$${m.group(1).strip()}$$", text)
    return _INLINE_MATH.sub(lambda m: f"${m.group(1).strip()}$", text)


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$")


def parse_json(text: str) -> dict[str, Any]:
    """解析模型的 JSON 输出（开了 JSON 模式，个别模型仍会包一层代码块）。"""
    try:
        data = json.loads(_FENCE.sub("", text.strip()))
    except json.JSONDecodeError as exc:
        raise AppError("AI 返回的内容格式不对，请重试", code="ai_bad_output", status=502) from exc
    if not isinstance(data, dict):
        raise AppError("AI 返回的内容格式不对，请重试", code="ai_bad_output", status=502)
    return data

"""讲义生成后的自动检查。发现的问题作为提示展示给老师，不拦截保存。"""

import re

from app.ai.skills.handout.prompt import SECTIONS
from app.ai.skills.handout.schema import HandoutIn

_CITATION = re.compile(r"\[(\d{1,2})\]")
_PAGE_REF = re.compile(r"第\s*\d+\s*页")


def _section(md: str, name: str) -> str | None:
    m = re.search(rf"^##[ \t][^\n]*{name}[^\n]*\n(.*?)(?=^##[ \t]|\Z)", md, re.M | re.S)
    return m.group(1) if m else None


def _numbered_items(text: str) -> int:
    """按题号数练习题：行首的 1. / 1、/ **1.** 算；（1）这类小问不算。"""
    return len(re.findall(r"^\s*(?:[-*]\s*)?(?:\*\*)?\d{1,2}\s*[.．、]", text, re.M))


def check_output(md: str, p: HandoutIn, n_sources: int = 0) -> list[str]:
    warnings: list[str] = []
    sections = SECTIONS[p.kind]
    missing = [s for s in sections if _section(md, s) is None]
    if missing:
        warnings.append(f"缺少以下部分：{'、'.join(missing)}。内容可能没有生成完整，可以重新生成或手动补充")

    if p.kind == "课堂讲义":
        if "【考点】" not in md:
            warnings.append("知识梳理里没有标出考点")
    elif not re.search(r"^###[ \t]*考点", md, re.M):
        warnings.append("考点梳理没有按考点分条")

    practice = _section(md, sections[-2])
    answers = _section(md, "参考答案")
    if practice is not None and answers is not None:
        n_practice, n_answers = _numbered_items(practice), _numbered_items(answers)
        if n_practice and n_answers < n_practice:
            warnings.append(f"{sections[-2]}有 {n_practice} 道题，参考答案只有 {n_answers} 条，请核对")

    if _PAGE_REF.search(md) and not n_sources and not (p.reference and _PAGE_REF.search(p.reference)):
        warnings.append("讲义里提到了教材页码，AI 可能记错，请对照教材核实")

    bad = sorted({int(n) for n in _CITATION.findall(md) if not 1 <= int(n) <= n_sources})
    if bad and n_sources:
        warnings.append(f"正文引用了不存在的资料编号 {'、'.join(f'[{n}]' for n in bad)}，请删除")
    return warnings

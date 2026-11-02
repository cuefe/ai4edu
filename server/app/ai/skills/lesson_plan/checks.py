"""生成后的自动检查。发现的问题作为提示展示给老师，不拦截保存。"""

import re

from app.ai.skills.lesson_plan.schema import LessonPlanIn

SECTIONS = [
    "教材分析",
    "学情分析",
    "教学目标",
    "教学重点与难点",
    "教学准备",
    "教学过程",
    "板书设计",
    "作业设计",
    "教学反思",
]

_PROCESS = re.compile(r"^##[ \t][^\n]*教学过程[^\n]*\n(.*?)(?=^##[ \t]|\Z)", re.M | re.S)
_STEP_MINUTES = re.compile(r"^###[^\n]*?[（(]\s*约?\s*(\d+)\s*分钟\s*[)）]", re.M)
_PAGE_REF = re.compile(r"第\s*\d+\s*页")


def check_output(md: str, p: LessonPlanIn) -> list[str]:
    warnings: list[str] = []

    missing = [s for s in SECTIONS if not re.search(rf"^##[ \t][^\n]*{s}", md, re.M)]
    if missing:
        warnings.append(f"缺少以下部分：{'、'.join(missing)}。内容可能没有生成完整，可以重新生成或手动补充")

    process = _PROCESS.search(md)
    if process:
        minutes = [int(m) for m in _STEP_MINUTES.findall(process.group(1))]
        if not minutes:
            warnings.append("教学过程的环节没有标注时长")
        elif sum(minutes) != p.duration:
            warnings.append(f"教学过程各环节合计 {sum(minutes)} 分钟，和课时 {p.duration} 分钟对不上")

    if _PAGE_REF.search(md) and not (p.reference and _PAGE_REF.search(p.reference)):
        warnings.append("教案里提到了教材页码，AI 可能记错，请对照教材核实")
    return warnings

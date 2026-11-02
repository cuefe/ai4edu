"""可以 AI 生成的文档类型：每种用哪个技能、怎么拼 prompt、生成后怎么检查。"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.ai.gateway.gateway import Messages
from app.ai.skills import handout, lesson_plan
from app.ai.skills.common import Source
from app.modules.content.models import DocType

DocInput = lesson_plan.LessonPlanIn | handout.HandoutIn


@dataclass(frozen=True)
class DocSkill:
    label: str  # 教案、讲义：用在提示语里
    skill: str
    prompt_version: str
    input_type: type[DocInput]
    header: Callable[[Any], str]  # 标题等固定内容，由程序生成
    messages: Callable[[Any, list[Source]], Messages]
    check: Callable[[str, Any, int], list[str]]


DOC_SKILLS: dict[str, DocSkill] = {
    DocType.LESSON_PLAN: DocSkill(
        "教案",
        lesson_plan.SKILL,
        lesson_plan.PROMPT_VERSION,
        lesson_plan.LessonPlanIn,
        lesson_plan.header_markdown,
        lesson_plan.build_messages,
        lesson_plan.check_output,
    ),
    DocType.HANDOUT: DocSkill(
        "讲义",
        handout.SKILL,
        handout.PROMPT_VERSION,
        handout.HandoutIn,
        handout.header_markdown,
        handout.build_messages,
        handout.check_output,
    ),
}

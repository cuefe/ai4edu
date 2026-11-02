"""教案生成：按学科、年级、课题生成一节课的教案，流式输出 Markdown。"""

from app.ai.skills.common import Source, cited_numbers, sources_markdown
from app.ai.skills.lesson_plan.checks import SECTIONS, check_output
from app.ai.skills.lesson_plan.prompt import PROMPT_VERSION, SKILL, build_messages, header_markdown
from app.ai.skills.lesson_plan.schema import LessonPlanIn

__all__ = [
    "PROMPT_VERSION",
    "SECTIONS",
    "SKILL",
    "LessonPlanIn",
    "Source",
    "build_messages",
    "check_output",
    "cited_numbers",
    "header_markdown",
    "sources_markdown",
]

"""讲义生成：给学生看的课堂讲义或复习讲义（考点总结），流式输出 Markdown。"""

from app.ai.skills.handout.checks import check_output
from app.ai.skills.handout.prompt import PROMPT_VERSION, SECTIONS, SKILL, build_messages, header_markdown
from app.ai.skills.handout.schema import HandoutIn, HandoutKind

__all__ = [
    "PROMPT_VERSION",
    "SECTIONS",
    "SKILL",
    "HandoutIn",
    "HandoutKind",
    "build_messages",
    "check_output",
    "header_markdown",
]

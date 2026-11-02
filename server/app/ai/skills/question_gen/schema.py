import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.ai.skills.common import Grade, Subject

QType = Literal["单选题", "多选题", "判断题", "填空题", "解答题"]
Difficulty = Literal["容易", "中等", "较难"]
CHOICE_TYPES = ("单选题", "多选题")


class QuestionGenIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    subject: Subject
    grade: Grade
    textbook: str = Field(default="人教版", min_length=1, max_length=30)
    topic: str = Field(min_length=1, max_length=200, description="考查的知识点或课题，如：有理数的加法法则")
    qtype: QType = "单选题"
    difficulty: Difficulty = "中等"
    count: int = Field(default=5, ge=1, le=10)
    requirements: str | None = Field(
        default=None, max_length=1000, description="如：结合生活情境、考查易错点"
    )
    reference: str | None = Field(default=None, max_length=8000, description="参考题：AI 仿照风格和难度出题")
    use_library: bool = Field(default=True, description="从资料库里检索相关片段作为命题依据")
    resource_ids: list[uuid.UUID] = Field(
        default_factory=list, max_length=20, description="只在这些资料里检索；为空时检索整个资料库"
    )


class QuestionData(BaseModel):
    """一道题的内容。AI 出的题、老师录入或修改的题都是这个结构。

    选择题的 options 只有选项内容，不带“A.”；answer 是选项字母（多选按字母顺序，如 AC）。
    判断题 answer 是“对”或“错”。填空题多个空的答案用“；”隔开。
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    qtype: QType
    stem: str = Field(min_length=1, max_length=5000)
    options: list[str] = Field(default_factory=list, max_length=6)
    answer: str = Field(min_length=1, max_length=2000)
    analysis: str = Field(default="", max_length=5000)
    knowledge_points: list[str] = Field(default_factory=list, max_length=5)

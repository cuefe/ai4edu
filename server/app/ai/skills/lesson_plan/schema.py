import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.ai.skills.common import Grade, Source, Subject

LessonType = Literal["新授课", "复习课", "习题课", "讲评课"]

__all__ = ["Grade", "LessonPlanIn", "LessonType", "Source", "Subject"]


class LessonPlanIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    subject: Subject
    grade: Grade
    textbook: str = Field(default="人教版", min_length=1, max_length=30)
    topic: str = Field(min_length=1, max_length=100, description="课题，如：1.2.1 有理数的概念")
    lesson_type: LessonType = "新授课"
    duration: int = Field(default=45, ge=30, le=90, description="一节课的时长（分钟）")
    requirements: str | None = Field(default=None, max_length=1000, description="学情、侧重点等要求")
    reference: str | None = Field(default=None, max_length=8000, description="参考资料：教材原文、已有教案等")
    use_library: bool = Field(default=True, description="从资料库里检索相关片段作为参考")
    resource_ids: list[uuid.UUID] = Field(
        default_factory=list, max_length=20, description="只在这些资料里检索；为空时检索整个资料库"
    )

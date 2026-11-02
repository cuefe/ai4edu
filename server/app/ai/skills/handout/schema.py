import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.ai.skills.common import Grade, Subject

HandoutKind = Literal["课堂讲义", "复习讲义"]


class HandoutIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    subject: Subject
    grade: Grade
    textbook: str = Field(default="人教版", min_length=1, max_length=30)
    topic: str = Field(
        min_length=1, max_length=100, description="课题或复习范围，如：1.2 有理数、第一章 复习"
    )
    kind: HandoutKind = Field(
        default="课堂讲义", description="课堂讲义：新课预习和课后巩固；复习讲义：考点总结"
    )
    requirements: str | None = Field(default=None, max_length=1000, description="学情、侧重点等要求")
    reference: str | None = Field(default=None, max_length=8000, description="参考资料：教材原文、教案等")
    use_library: bool = Field(default=True, description="从资料库里检索相关片段作为参考")
    resource_ids: list[uuid.UUID] = Field(
        default_factory=list, max_length=20, description="只在这些资料里检索；为空时检索整个资料库"
    )

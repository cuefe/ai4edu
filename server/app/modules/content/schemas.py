import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.ai.skills.lesson_plan import LessonPlanIn


class DocumentBrief(BaseModel):
    id: uuid.UUID
    doc_type: str
    title: str
    subject: str | None
    grade: str | None
    status: str
    created_at: datetime
    updated_at: datetime


class DocumentOut(DocumentBrief):
    params: LessonPlanIn | None
    content: dict[str, Any] | None
    generated_md: str | None = Field(description="只在生成中返回：已生成的部分")
    warnings: list[str]
    error: str | None
    version: int


class DocumentUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content: dict[str, Any]
    version: int = Field(description="读取时拿到的版本号；文档已被别处修改时返回 409")

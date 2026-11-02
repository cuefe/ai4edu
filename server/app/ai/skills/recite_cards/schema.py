import re
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.ai.skills.common import Grade, Subject

CardKind = Literal["qa", "cloze"]


class ReciteIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    subject: Subject
    grade: Grade
    title: str = Field(min_length=1, max_length=100, description="卡片组名称，如：1.2 有理数 必背知识点")
    doc_id: uuid.UUID | None = Field(default=None, description="从这份讲义或教案里抽取")
    text: str | None = Field(default=None, max_length=20000, description="或者直接粘贴要整理的内容")
    requirements: str | None = Field(default=None, max_length=500, description="如：只要公式和定义")
    max_cards: int = Field(default=20, ge=5, le=50)


class Card(BaseModel):
    """一张背诵卡片。

    - qa（问答）：front 是问题，back 是答案
    - cloze（挖空）：front 是一句话，要背的部分用 {{ }} 括起来；back 是补充说明，可以为空
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    kind: CardKind
    front: str = Field(min_length=1, max_length=500)
    back: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def _check(self) -> "Card":
        if self.kind == "cloze" and not re.search(r"\{\{.+?\}\}", self.front, re.S):
            raise ValueError("挖空卡要用 {{ }} 标出要背的内容")
        if self.kind == "qa" and not self.back:
            raise ValueError("问答卡要填写答案")
        return self

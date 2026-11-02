import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.ai.skills.recite_cards import Card


class DeckBrief(BaseModel):
    id: uuid.UUID
    title: str
    subject: str | None
    grade: str | None
    source_doc_id: uuid.UUID | None
    card_count: int
    created_at: datetime
    updated_at: datetime


class CardOut(Card):
    id: uuid.UUID


class DeckOut(DeckBrief):
    cards: list[CardOut]
    warnings: list[str] = Field(description="生成时自动检查发现的问题")


class DeckUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=200)
    cards: list[Card] = Field(max_length=200)

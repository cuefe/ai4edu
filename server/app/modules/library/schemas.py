import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ResourceOut(BaseModel):
    id: uuid.UUID
    filename: str
    size: int
    subject: str | None
    shared: bool
    status: str
    progress: int
    error: str | None = Field(description="失败原因；解析成功但部分页没识别出来时也会有提示")
    pages: int
    ocr_pages: int
    chunk_count: int
    owner_name: str
    mine: bool = Field(description="是不是自己上传的；别人共享的只能查看和检索")
    created_at: datetime
    updated_at: datetime


class ResourcePatch(BaseModel):
    subject: str | None = Field(default=None, max_length=20)
    shared: bool | None = None


class ChunkOut(BaseModel):
    seq: int
    heading: str
    page_start: int | None
    page_end: int | None
    text: str


class SearchIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    query: str = Field(min_length=1, max_length=500)
    resource_ids: list[uuid.UUID] = Field(default_factory=list, max_length=50, description="只在这些资料里找")
    subject: str | None = Field(default=None, max_length=20)
    k: int = Field(default=6, ge=1, le=20)


class SearchHit(BaseModel):
    chunk_id: uuid.UUID
    resource_id: uuid.UUID
    filename: str
    heading: str
    page_start: int | None
    page_end: int | None
    text: str
    score: float = Field(description="相关度，0～1")

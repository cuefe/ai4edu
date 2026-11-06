import uuid

from pydantic import BaseModel, ConfigDict


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class BookBrief(_Out):
    id: uuid.UUID
    key: str
    stage: str
    subject: str
    edition: str
    grade: str
    title: str
    status: str
    chapter_count: int = 0
    section_count: int = 0
    kp_count: int = 0
    file_count: int = 0


class Catalog(BaseModel):
    my_grades: list[str]  # 当前用户所在班级的年级，前端默认按它筛选
    books: list[BookBrief]


class FileOut(_Out):
    id: uuid.UUID
    kind: str
    title: str
    filename: str
    mime: str
    size: int
    chapter_id: uuid.UUID | None


class SectionBrief(_Out):
    id: uuid.UUID
    no: str
    title: str
    kp_count: int = 0


class ChapterBrief(SectionBrief):
    sections: list[SectionBrief] = []


class BookDetail(BookBrief):
    chapters: list[ChapterBrief]
    files: list[FileOut]


class KpOut(_Out):
    id: uuid.UUID
    name: str
    content: str
    kind: str
    importance: str
    recite: bool
    section_no: str = ""  # 看整章时，知识点属于哪一节
    section_title: str = ""


class MindNode(BaseModel):
    text: str
    children: list["MindNode"] = []


class ChapterDetail(_Out):
    id: uuid.UUID
    book_id: uuid.UUID
    no: str
    title: str
    summary: str
    mind_map: MindNode | None
    knowledge_points: list[KpOut]
    files: list[FileOut]


class StatusIn(BaseModel):
    published: bool

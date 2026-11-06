"""内容包：一册教材的章节、知识点、思维导图、课件，存成一个 JSON 文件，离线生成后用命令行导入。

- 生成和导入分开：内容可以来自任何模型（Codex、DeepSeek……），导入前都走同一套检查。
- 可以重复导入：按编号和名称更新，ID 不变；内容包里没有了的章节和知识点会删掉。
- 思维导图在内容包里是 Markdown 无序列表（模型写起来不容易错），导入时转成树。
"""

import hashlib
import mimetypes
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core import storage
from app.modules.curriculum.models import BookStatus, Chapter, CourseFile, KnowledgePoint, Textbook

KpKind = Literal["概念", "公式", "定理", "方法", "易错"]
KpImportance = Literal["核心", "重点", "了解"]

MAX_MAP_NODES = 150
MAX_MAP_DEPTH = 6
_BULLET = re.compile(r"^(\s*)(?:[-*+]|\d+[.)])\s+(.+?)\s*$")
_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


class _Pack(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)


class KpPack(_Pack):
    name: str = Field(min_length=1, max_length=80)
    content: str = Field(min_length=1)
    kind: KpKind
    importance: KpImportance
    recite: bool = False


class SectionPack(_Pack):
    no: str = Field(min_length=1, max_length=20)
    title: str = Field(min_length=1, max_length=120)
    summary: str = ""
    mind_map: str = ""
    knowledge_points: list[KpPack] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique_names(self) -> "SectionPack":
        names = [k.name for k in self.knowledge_points]
        if len(names) != len(set(names)):
            raise ValueError(f"{self.no} 里有重名的知识点")
        return self


class ChapterPack(_Pack):
    no: str = Field(min_length=1, max_length=20)
    title: str = Field(min_length=1, max_length=120)
    summary: str = ""
    mind_map: str = ""
    sections: list[SectionPack] = Field(default_factory=list)


class FilePack(_Pack):
    path: str = Field(min_length=1, description="相对内容包所在目录的路径")
    title: str = Field(min_length=1, max_length=200)
    kind: Literal["textbook", "courseware"]
    chapter_no: str | None = None
    source: str = Field(default="", max_length=200)


class BookPack(_Pack):
    key: str = Field(pattern=r"^[a-z0-9-]{1,60}$")
    stage: Literal["初中", "高中"]
    subject: str = Field(min_length=1, max_length=20)
    edition: str = Field(min_length=1, max_length=40)
    grade: Literal["初一", "初二", "初三", "高一", "高二", "高三"]
    title: str = Field(min_length=1, max_length=60)
    seq: int = 0
    provenance: dict[str, Any] = Field(default_factory=dict)
    chapters: list[ChapterPack] = Field(default_factory=list)
    files: list[FilePack] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique_numbers(self) -> "BookPack":
        numbers = [c.no for c in self.chapters] + [s.no for c in self.chapters for s in c.sections]
        repeated = {n for n in numbers if numbers.count(n) > 1}
        if repeated:
            raise ValueError(f"章节编号重复：{sorted(repeated)}")
        for f in self.files:
            if f.chapter_no and f.chapter_no not in numbers:
                raise ValueError(f"文件 {f.path} 对应的章节 {f.chapter_no} 不存在")
        return self


def parse_mind_map(outline: str, fallback_root: str) -> dict[str, Any] | None:
    """Markdown 列表 → {"text", "children"}。多个顶层节点时用 fallback_root 做根；超出限制的节点丢掉。"""
    root: dict[str, Any] = {"text": fallback_root, "children": []}
    # 栈里是（缩进，节点）。标题按 # 数量算层级，缩进是负数，排在列表项外层
    stack: list[tuple[int, dict[str, Any]]] = [(-1000, root)]
    count = 0
    for line in outline.splitlines():
        if not line.strip():
            continue
        if m := _HEADING.match(line):
            indent, text = (len(m.group(1)) - 1) * 2 - 100, m.group(2)
        elif m := _BULLET.match(line):
            indent, text = len(m.group(1).replace("\t", "  ")), m.group(2)
        else:
            continue
        while stack[-1][0] >= indent:
            stack.pop()
        if len(stack) > MAX_MAP_DEPTH or count >= MAX_MAP_NODES:
            continue
        node: dict[str, Any] = {"text": text.strip()[:80], "children": []}
        stack[-1][1]["children"].append(node)
        stack.append((indent, node))
        count += 1
    if not root["children"]:
        return None
    if len(root["children"]) == 1:
        return root["children"][0]
    return root


@dataclass
class ImportResult:
    book_id: uuid.UUID
    created: bool
    chapters: int
    knowledge_points: int
    files_added: int


def _upsert_chapter(
    db: Session,
    book: Textbook,
    existing: dict[str, Chapter],
    *,
    no: str,
    title: str,
    summary: str,
    mind_map: str,
    seq: int,
    parent_id: uuid.UUID | None,
) -> Chapter:
    chapter = existing.get(no)
    if chapter is None:
        chapter = Chapter(book_id=book.id, no=no)
        db.add(chapter)
    chapter.parent_id = parent_id
    chapter.seq = seq
    chapter.title = title
    chapter.summary = summary
    chapter.mind_map = parse_mind_map(mind_map, title)
    db.flush()
    return chapter


def _sync_points(db: Session, book: Textbook, section: Chapter, points: list[KpPack]) -> None:
    current = {
        k.name: k for k in db.scalars(select(KnowledgePoint).where(KnowledgePoint.chapter_id == section.id))
    }
    for seq, p in enumerate(points):
        kp = current.pop(p.name, None)
        if kp is None:
            kp = KnowledgePoint(book_id=book.id, chapter_id=section.id, name=p.name)
            db.add(kp)
        kp.seq, kp.content, kp.kind, kp.importance, kp.recite = seq, p.content, p.kind, p.importance, p.recite
    for kp in current.values():
        db.delete(kp)


def _store_file(
    db: Session, book: Textbook, f: FilePack, seq: int, chapter_id: uuid.UUID | None, base: Path
) -> bool:
    """导入一个文件，内容相同的不重复存。返回是否新存了文件。"""
    path = (base / f.path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"内容包里的文件不存在：{path}")
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    row = db.scalar(select(CourseFile).where(CourseFile.book_id == book.id, CourseFile.sha256 == digest))
    added = row is None
    if row is None:
        key = f"curriculum/{book.key}/{uuid.uuid4().hex}{path.suffix.lower()[:10]}"
        storage.put(key, data)
        row = CourseFile(
            book_id=book.id,
            storage_key=key,
            sha256=digest,
            size=len(data),
            filename=path.name[:200],
            mime=mimetypes.guess_type(path.name)[0] or "application/octet-stream",
        )
        db.add(row)
    row.kind, row.title, row.source, row.seq, row.chapter_id = f.kind, f.title, f.source, seq, chapter_id
    return added


def import_pack(
    db: Session, pack: BookPack, base_dir: Path | None = None, *, publish: bool = False
) -> ImportResult:
    book = db.scalar(select(Textbook).where(Textbook.key == pack.key))
    created = book is None
    if book is None:
        book = Textbook(key=pack.key, status=BookStatus.DRAFT)
        db.add(book)
    book.stage, book.subject, book.edition = pack.stage, pack.subject, pack.edition
    book.grade, book.title, book.seq, book.provenance = pack.grade, pack.title, pack.seq, pack.provenance
    if publish:
        book.status = BookStatus.PUBLISHED
    db.flush()

    existing = {c.no: c for c in db.scalars(select(Chapter).where(Chapter.book_id == book.id))}
    by_no: dict[str, Chapter] = {}
    n_points = 0
    for i, c in enumerate(pack.chapters):
        chapter = _upsert_chapter(
            db,
            book,
            existing,
            no=c.no,
            title=c.title,
            summary=c.summary,
            mind_map=c.mind_map,
            seq=i,
            parent_id=None,
        )
        by_no[c.no] = chapter
        for j, s in enumerate(c.sections):
            section = _upsert_chapter(
                db,
                book,
                existing,
                no=s.no,
                title=s.title,
                summary=s.summary,
                mind_map=s.mind_map,
                seq=j,
                parent_id=chapter.id,
            )
            by_no[s.no] = section
            _sync_points(db, book, section, s.knowledge_points)
            n_points += len(s.knowledge_points)
    gone = [c.id for no, c in existing.items() if no not in by_no]
    if gone:
        db.execute(delete(Chapter).where(Chapter.id.in_(gone)))

    added = 0
    for i, f in enumerate(pack.files):
        chapter_id = by_no[f.chapter_no].id if f.chapter_no else None
        added += _store_file(db, book, f, i, chapter_id, base_dir or Path("."))
    db.flush()
    return ImportResult(book.id, created, len(by_no), n_points, added)


def load_pack(path: Path) -> BookPack:
    return BookPack.model_validate_json(path.read_text(encoding="utf-8"))


def remove_book(db: Session, key: str) -> bool:
    """整册下架并删除，连存储里的文件一起删。"""
    book = db.scalar(select(Textbook).where(Textbook.key == key))
    if book is None:
        return False
    for f in db.scalars(select(CourseFile).where(CourseFile.book_id == book.id)):
        storage.delete(f.storage_key)
    db.delete(book)
    return True

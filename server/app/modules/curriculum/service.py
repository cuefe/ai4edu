import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import NotFound
from app.modules.curriculum.models import BookStatus, Chapter, CourseFile, KnowledgePoint, Textbook
from app.modules.curriculum.schemas import (
    BookBrief,
    BookDetail,
    Catalog,
    ChapterBrief,
    ChapterDetail,
    FileOut,
    KpOut,
    MindNode,
    SectionBrief,
)
from app.modules.iam.models import Role, User
from app.modules.org.models import ClassMember, Klass

# 班级的年级是自由填写的，把常见写法归一成“初一”这种
_GRADE_ALIASES = {
    "七年级": "初一",
    "八年级": "初二",
    "九年级": "初三",
    "初中一年级": "初一",
    "初中二年级": "初二",
}
_GRADE_ORDER = ["初一", "初二", "初三", "高一", "高二", "高三"]
_SUBJECT_ORDER = ["语文", "数学", "英语", "物理", "化学", "生物", "历史", "地理", "政治", "道德与法治"]


def normalize_grade(grade: str | None) -> str | None:
    if not grade:
        return None
    value = grade.strip()
    return _GRADE_ALIASES.get(value, value)


def _rank(items: list[str], value: str) -> int:
    return items.index(value) if value in items else len(items)


def my_grades(db: Session, user: User) -> list[str]:
    if user.tenant_id is None:
        return []
    rows = db.scalars(
        select(Klass.grade)
        .join(ClassMember, ClassMember.klass_id == Klass.id)
        .where(ClassMember.tenant_id == user.tenant_id, ClassMember.user_id == user.id)
    )
    grades = {g for g in (normalize_grade(r) for r in rows) if g}
    return sorted(grades, key=lambda g: _rank(_GRADE_ORDER, g))


def _sees_drafts(user: User) -> bool:
    return user.has_role(Role.PLATFORM_ADMIN)


def _count(db: Session, column, *where) -> dict[uuid.UUID, int]:
    return {key: n for key, n in db.execute(select(column, func.count()).where(*where).group_by(column))}


def _briefs(db: Session, books: list[Textbook]) -> list[BookBrief]:
    ids = [b.id for b in books]
    chapters = _count(db, Chapter.book_id, Chapter.book_id.in_(ids), Chapter.parent_id.is_(None))
    sections = _count(db, Chapter.book_id, Chapter.book_id.in_(ids), Chapter.parent_id.is_not(None))
    points = _count(db, KnowledgePoint.book_id, KnowledgePoint.book_id.in_(ids))
    files = _count(db, CourseFile.book_id, CourseFile.book_id.in_(ids))
    return [
        BookBrief.model_validate(b).model_copy(
            update={
                "chapter_count": chapters.get(b.id, 0),
                "section_count": sections.get(b.id, 0),
                "kp_count": points.get(b.id, 0),
                "file_count": files.get(b.id, 0),
            }
        )
        for b in books
    ]


def catalog(db: Session, user: User) -> Catalog:
    query = select(Textbook)
    if not _sees_drafts(user):
        query = query.where(Textbook.status == BookStatus.PUBLISHED)
    books = sorted(
        db.scalars(query),
        key=lambda b: (
            _rank(_GRADE_ORDER, b.grade),
            _rank(_SUBJECT_ORDER, b.subject),
            b.subject,
            b.seq,
            b.title,
        ),
    )
    return Catalog(my_grades=my_grades(db, user), books=_briefs(db, books))


def get_book(db: Session, user: User, book_id: uuid.UUID) -> Textbook:
    book = db.get(Textbook, book_id)
    if book is None or (book.status != BookStatus.PUBLISHED and not _sees_drafts(user)):
        raise NotFound("这册教材不存在或还没有发布")
    return book


def book_detail(db: Session, user: User, book_id: uuid.UUID) -> BookDetail:
    book = get_book(db, user, book_id)
    rows = list(db.scalars(select(Chapter).where(Chapter.book_id == book.id).order_by(Chapter.seq)))
    points = _count(db, KnowledgePoint.chapter_id, KnowledgePoint.book_id == book.id)
    chapters = []
    for c in (r for r in rows if r.parent_id is None):
        sections = [
            SectionBrief.model_validate(s).model_copy(update={"kp_count": points.get(s.id, 0)})
            for s in rows
            if s.parent_id == c.id
        ]
        chapters.append(
            ChapterBrief.model_validate(c).model_copy(
                update={"sections": sections, "kp_count": sum(s.kp_count for s in sections)}
            )
        )
    files = db.scalars(select(CourseFile).where(CourseFile.book_id == book.id).order_by(CourseFile.seq))
    return BookDetail(
        **_briefs(db, [book])[0].model_dump(),
        chapters=chapters,
        files=[FileOut.model_validate(f) for f in files],
    )


def chapter_detail(db: Session, user: User, chapter_id: uuid.UUID) -> ChapterDetail:
    """章或节的内容。看整章时带上下面各节的知识点。"""
    chapter = db.get(Chapter, chapter_id)
    if chapter is None:
        raise NotFound("这一章不存在")
    get_book(db, user, chapter.book_id)
    sections = [chapter]
    if chapter.parent_id is None:
        sections += db.scalars(select(Chapter).where(Chapter.parent_id == chapter.id).order_by(Chapter.seq))
    ids = [s.id for s in sections]
    rows = db.scalars(
        select(KnowledgePoint).where(KnowledgePoint.chapter_id.in_(ids)).order_by(KnowledgePoint.seq)
    )
    by_section: dict[uuid.UUID, list[KnowledgePoint]] = {}
    for kp in rows:
        by_section.setdefault(kp.chapter_id, []).append(kp)
    points = [
        KpOut.model_validate(kp).model_copy(update={"section_no": s.no, "section_title": s.title})
        for s in sections
        for kp in by_section.get(s.id, [])
    ]
    files = db.scalars(select(CourseFile).where(CourseFile.chapter_id.in_(ids)).order_by(CourseFile.seq))
    return ChapterDetail(
        id=chapter.id,
        book_id=chapter.book_id,
        no=chapter.no,
        title=chapter.title,
        summary=chapter.summary,
        mind_map=MindNode.model_validate(chapter.mind_map) if chapter.mind_map else None,
        knowledge_points=points,
        files=[FileOut.model_validate(f) for f in files],
    )


def get_file(db: Session, user: User, file_id: uuid.UUID) -> CourseFile:
    row = db.get(CourseFile, file_id)
    if row is None:
        raise NotFound("文件不存在")
    get_book(db, user, row.book_id)
    return row


def set_published(db: Session, user: User, book_id: uuid.UUID, published: bool) -> BookBrief:
    book = get_book(db, user, book_id)
    book.status = BookStatus.PUBLISHED if published else BookStatus.DRAFT
    db.flush()
    return _briefs(db, [book])[0]

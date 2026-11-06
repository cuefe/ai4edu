"""每周个性化试卷。

每份周测是一份只发给一个学生的作业（assignment.kind = weekly），作答、判分、AI 批改、老师确认、
错题本都走作业的流程；这里负责教学进度、按学生情况组卷发卷、汇总成绩。

组卷规则在 compose.py。这里把数据库里的情况（题库、掌握度、错题、做过的题、上一份的成绩）喂给它。
"""

import random
import re
import uuid
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.skills.question_gen import CHOICE_TYPES
from app.core.errors import AppError, Forbidden, NotFound
from app.modules.assignment import service as assignments
from app.modules.assignment.models import (
    Answer,
    AnswerRelease,
    AnswerStatus,
    Assignment,
    AssignmentItem,
    AssignmentKind,
    ItemType,
    Submission,
    SubmissionStatus,
)
from app.modules.curriculum.models import (
    BookStatus,
    Chapter,
    KnowledgePoint,
    PoolQuestion,
    PoolQuestionKp,
    PoolStatus,
    Textbook,
)
from app.modules.iam.models import User
from app.modules.learning import service as learning
from app.modules.learning.models import WrongItem
from app.modules.notify.service import notify
from app.modules.org import service as org
from app.modules.org.models import ClassMember, Klass, MemberRole
from app.modules.weekly import compose as rules
from app.modules.weekly.models import ClassProgress, WeeklyPaper
from app.modules.weekly.schemas import (
    ClassWeeklyOut,
    ClassWeekReport,
    IssueResult,
    KpMastery,
    ProgressIn,
    ProgressOut,
    SectionOut,
    StudentWeekRow,
    SubjectWeekly,
    WeekRow,
    WeekStat,
)

SCHOOL_TZ = ZoneInfo("Asia/Shanghai")
DUE_TIME = time(22, 0)  # 周日晚上 10 点截止
MIN_HOURS_TO_DO = 24  # 发得太晚时至少留这么多时间
EXTRA_HOURS = 48
WRONG_LOOKBACK_DAYS = 28  # 只看最近几周的错题
MASTERED_AT = 0.8
WEAK_LIST = 3  # 老师列表里每个学生显示几个薄弱点
CLASS_WEAK_LIST = 5
_LETTERS = "ABCDEF"
_INLINE_MATH = re.compile(r"\$[^$]*\$")
_ORDER_DEPENDENT = re.compile(r"[A-F]|以上|以下|前两|后两|都不|都对|均不")


def now() -> datetime:
    return datetime.now(UTC)


def week_of(at: datetime | None = None) -> date:
    """at 所在这一周的周一（按北京时间）。"""
    local = (at or now()).astimezone(SCHOOL_TZ).date()
    return local - timedelta(days=local.weekday())


def due_of(week_start: date, at: datetime) -> datetime:
    sunday = datetime.combine(week_start + timedelta(days=6), DUE_TIME, tzinfo=SCHOOL_TZ)
    if sunday - at < timedelta(hours=MIN_HOURS_TO_DO):
        return at + timedelta(hours=EXTRA_HOURS)
    return sunday


def shuffled_options(q: PoolQuestion, rng: random.Random) -> tuple[list[str], str]:
    """每个学生的选项顺序不同，答案跟着换：题库里的正确选项不均匀，同一道题也更难互相传答案。

    解析里提到了选项字母、或者选项之间有依赖（“以上都对”）的题不打乱，否则解析和选项就对不上了。
    """
    if q.qtype not in CHOICE_TYPES:
        return q.options, q.answer
    if _ORDER_DEPENDENT.search(_INLINE_MATH.sub("", " ".join([q.analysis, *q.options]))):
        return q.options, q.answer
    order = list(range(len(q.options)))
    rng.shuffle(order)
    answer = "".join(sorted(_LETTERS[order.index(_LETTERS.index(c))] for c in q.answer))
    return [q.options[i] for i in order], answer


def score_ratio(db: Session, sub: Submission, a: Assignment) -> float | None:
    """一份周测的得分比例。还没确认的题先按 AI 给的分算，还没批改出来的题不计入。没提交时返回 None。"""
    if sub.status == SubmissionStatus.TODO:
        return None
    rows = db.execute(
        select(Answer.score, Answer.ai_score, AssignmentItem.score)
        .join(AssignmentItem, AssignmentItem.id == Answer.item_id)
        .where(Answer.submission_id == sub.id)
    ).all()
    earned = total = 0.0
    for score, ai_score, full in rows:
        value = score if score is not None else ai_score
        if value is None:
            continue
        earned += value
        total += full
    return earned / total if total else None


# —— 教材的节 ——


def _book_sections(db: Session, book_id: uuid.UUID) -> tuple[list[Chapter], dict[uuid.UUID, Chapter]]:
    """按书里的顺序返回全部节，以及章的字典。"""
    rows = list(db.scalars(select(Chapter).where(Chapter.book_id == book_id)))
    chapters = {c.id: c for c in rows if c.parent_id is None}
    sections = [c for c in rows if c.parent_id is not None]
    sections.sort(key=lambda s: (chapters[s.parent_id].seq, s.seq))  # type: ignore[index]
    return sections, chapters


def book_sections(db: Session, book_id: uuid.UUID) -> list[SectionOut]:
    book = db.get(Textbook, book_id)
    if book is None or book.status != BookStatus.PUBLISHED:
        raise NotFound("这册教材不存在或还没有发布")
    sections, chapters = _book_sections(db, book_id)
    approved = {
        sid: n
        for sid, n in db.execute(
            select(PoolQuestion.section_id, func.count())
            .where(PoolQuestion.book_id == book_id, PoolQuestion.status == PoolStatus.APPROVED)
            .group_by(PoolQuestion.section_id)
        )
    }
    return [
        SectionOut(
            id=s.id,
            no=s.no,
            title=s.title,
            chapter_no=chapters[s.parent_id].no,  # type: ignore[index]
            chapter_title=chapters[s.parent_id].title,  # type: ignore[index]
            approved_count=approved.get(s.id, 0),
        )
        for s in sections
    ]


# —— 教学进度 ——


def _membership(db: Session, tenant_id: uuid.UUID, klass_id: uuid.UUID, teacher_id: uuid.UUID) -> ClassMember:
    member = db.scalar(
        select(ClassMember).where(
            ClassMember.tenant_id == tenant_id,
            ClassMember.klass_id == klass_id,
            ClassMember.user_id == teacher_id,
            ClassMember.member_role == MemberRole.TEACHER,
        )
    )
    if member is None:
        raise Forbidden("只能操作自己任教的班级")
    return member


def set_progress(
    db: Session, tenant_id: uuid.UUID, teacher_id: uuid.UUID, klass_id: uuid.UUID, body: ProgressIn
) -> ClassProgress:
    member = _membership(db, tenant_id, klass_id, teacher_id)
    book = db.get(Textbook, body.book_id)
    if book is None or book.status != BookStatus.PUBLISHED:
        raise NotFound("这册教材不存在或还没有发布")
    if member.subject and member.subject != book.subject:
        raise AppError(f"你在这个班教{member.subject}，不能设置{book.subject}的进度")
    sections, _ = _book_sections(db, book.id)
    valid = {s.id for s in sections}
    if set(body.section_ids) - valid:
        raise AppError("选的节不属于这册教材")
    row = db.scalar(
        select(ClassProgress).where(ClassProgress.klass_id == klass_id, ClassProgress.subject == book.subject)
    )
    if row is None:
        row = ClassProgress(tenant_id=tenant_id, klass_id=klass_id, subject=book.subject)
        db.add(row)
    row.book_id, row.teacher_id = book.id, teacher_id
    row.section_ids = [str(s) for s in body.section_ids]
    row.week_start, row.enabled = week_of(), body.enabled
    db.flush()
    return row


def get_progress(
    db: Session, tenant_id: uuid.UUID, teacher_id: uuid.UUID, klass_id: uuid.UUID, subject: str
) -> ClassProgress:
    _membership(db, tenant_id, klass_id, teacher_id)
    row = db.scalar(
        select(ClassProgress).where(
            ClassProgress.tenant_id == tenant_id,
            ClassProgress.klass_id == klass_id,
            ClassProgress.subject == subject,
        )
    )
    if row is None:
        raise NotFound("这个班还没有设置教学进度")
    return row


def _progress_out(db: Session, p: ClassProgress) -> ProgressOut:
    book = db.get(Textbook, p.book_id)
    sections = {str(s.id): s for s in db.scalars(select(Chapter).where(Chapter.book_id == p.book_id))}
    labels = [f"{sections[s].no} {sections[s].title}" for s in p.section_ids if s in sections]
    return ProgressOut(
        subject=p.subject,
        book_id=p.book_id,
        book_title=book.title if book else "",
        section_ids=[uuid.UUID(s) for s in p.section_ids],
        section_labels=labels,
        enabled=p.enabled,
        week_start=p.week_start,
        up_to_date=p.week_start == week_of(),
    )


def _week_stat(
    db: Session, tenant_id: uuid.UUID, klass_id: uuid.UUID, subject: str, week: date
) -> WeekStat | None:
    rows = db.execute(
        select(Submission, Assignment)
        .join(Assignment, Assignment.id == Submission.assignment_id)
        .join(WeeklyPaper, WeeklyPaper.assignment_id == Assignment.id)
        .where(
            WeeklyPaper.tenant_id == tenant_id,
            WeeklyPaper.klass_id == klass_id,
            WeeklyPaper.subject == subject,
            WeeklyPaper.week_start == week,
        )
    ).all()
    if not rows:
        return None
    percents = [r * 100 for s, a in rows if (r := score_ratio(db, s, a)) is not None]
    return WeekStat(
        week_start=week,
        issued=len(rows),
        submitted=sum(1 for s, _ in rows if s.status != SubmissionStatus.TODO),
        graded=sum(1 for s, _ in rows if s.status == SubmissionStatus.GRADED),
        pending_review=sum(s.pending_count for s, _ in rows),
        avg_percent=round(sum(percents) / len(percents), 1) if percents else None,
    )


def list_for_teacher(db: Session, tenant_id: uuid.UUID, teacher_id: uuid.UUID) -> list[ClassWeeklyOut]:
    rows = db.execute(
        select(ClassMember, Klass)
        .join(Klass, Klass.id == ClassMember.klass_id)
        .where(
            ClassMember.tenant_id == tenant_id,
            ClassMember.user_id == teacher_id,
            ClassMember.member_role == MemberRole.TEACHER,
        )
        .order_by(Klass.grade, Klass.name)
    ).all()
    out: list[ClassWeeklyOut] = []
    week = week_of()
    for member, klass in rows:
        students = len(org.students_in_classes(db, tenant_id, [klass.id]))
        query = select(ClassProgress).where(ClassProgress.klass_id == klass.id)
        if member.subject:
            query = query.where(ClassProgress.subject == member.subject)
        else:
            query = query.where(ClassProgress.teacher_id == teacher_id)
        progresses = list(db.scalars(query.order_by(ClassProgress.subject)))
        for p in progresses:
            out.append(
                ClassWeeklyOut(
                    klass_id=klass.id,
                    class_name=klass.name,
                    grade=klass.grade,
                    subject=p.subject,
                    student_count=students,
                    progress=_progress_out(db, p),
                    week=_week_stat(db, tenant_id, klass.id, p.subject, week),
                )
            )
        if not progresses:
            out.append(
                ClassWeeklyOut(
                    klass_id=klass.id,
                    class_name=klass.name,
                    grade=klass.grade,
                    subject=member.subject,
                    student_count=students,
                    progress=None,
                    week=None,
                )
            )
    return out


# —— 发卷 ——


def _load_pool(db: Session, book_id: uuid.UUID) -> list[rules.PoolItem]:
    links: dict[uuid.UUID, list[uuid.UUID]] = {}
    for qid, kid in db.execute(
        select(PoolQuestionKp.question_id, PoolQuestionKp.kp_id)
        .join(PoolQuestion, PoolQuestion.id == PoolQuestionKp.question_id)
        .where(PoolQuestion.book_id == book_id, PoolQuestion.status == PoolStatus.APPROVED)
    ):
        links.setdefault(qid, []).append(kid)
    rows = db.execute(
        select(PoolQuestion.id, PoolQuestion.section_id, PoolQuestion.qtype, PoolQuestion.difficulty).where(
            PoolQuestion.book_id == book_id, PoolQuestion.status == PoolStatus.APPROVED
        )
    )
    return [
        rules.PoolItem(qid, section, qtype, difficulty, tuple(links.get(qid, ())))
        for qid, section, qtype, difficulty in rows
    ]


def _last_paper(
    db: Session, tenant_id: uuid.UUID, student_id: uuid.UUID, subject: str, week: date
) -> tuple[WeeklyPaper, Assignment, Submission] | None:
    row = db.execute(
        select(WeeklyPaper, Assignment, Submission)
        .join(Assignment, Assignment.id == WeeklyPaper.assignment_id)
        .join(Submission, Submission.assignment_id == Assignment.id)
        .where(
            WeeklyPaper.tenant_id == tenant_id,
            WeeklyPaper.student_id == student_id,
            WeeklyPaper.subject == subject,
            WeeklyPaper.week_start < week,
        )
        .order_by(WeeklyPaper.week_start.desc())
        .limit(1)
    ).first()
    return (row[0], row[1], row[2]) if row else None


def _seen_questions(
    db: Session, tenant_id: uuid.UUID, student_id: uuid.UUID, subject: str
) -> list[tuple[uuid.UUID, date]]:
    rows = db.execute(
        select(AssignmentItem.ref_id, WeeklyPaper.week_start)
        .join(WeeklyPaper, WeeklyPaper.assignment_id == AssignmentItem.assignment_id)
        .where(
            WeeklyPaper.tenant_id == tenant_id,
            WeeklyPaper.student_id == student_id,
            WeeklyPaper.subject == subject,
        )
    )
    return [(ref, week) for ref, week in rows if ref]


def _wrong_kps(
    db: Session, tenant_id: uuid.UUID, student_id: uuid.UUID, subject: str, at: datetime
) -> list[uuid.UUID]:
    """最近做错的题涉及的知识点，新的在前。只有周测的题才关联了知识点 ID。"""
    rows = db.scalars(
        select(WrongItem)
        .where(
            WrongItem.tenant_id == tenant_id,
            WrongItem.student_id == student_id,
            WrongItem.subject == subject,
            WrongItem.created_at >= at - timedelta(days=WRONG_LOOKBACK_DAYS),
        )
        .order_by(WrongItem.created_at.desc())
    )
    kps: dict[uuid.UUID, None] = {}
    for w in rows:
        for k in w.question.get("kp_ids") or []:
            kps[uuid.UUID(k)] = None
    return list(kps)


def _issue_one(
    db: Session,
    progress: ClassProgress,
    student_id: uuid.UUID,
    *,
    week: date,
    at: datetime,
    pool: list[rules.PoolItem],
    this_week: set[uuid.UUID],
    learned: set[uuid.UUID],
    kp_names: dict[uuid.UUID, str],
    section_no: dict[uuid.UUID, str],
    questions: dict[uuid.UUID, PoolQuestion],
) -> rules.Composition | None:
    """给一个学生组卷并发出。题目太少时不发，返回 None。"""
    tenant_id, subject = progress.tenant_id, progress.subject
    last = _last_paper(db, tenant_id, student_id, subject, week)
    ratio = score_ratio(db, last[2], last[1]) if last else None
    level, reason = rules.next_level(last[0].level if last else None, ratio)

    scope_kps = {k for q in pool if q.section_id in (this_week | learned) for k in q.kp_ids}
    scores = learning.mastery(db, tenant_id, student_id, subject, at)
    weak = sorted(
        (k for k, m in scores.items() if m < rules.WEAK_BELOW and k in scope_kps),
        key=lambda k: scores[k],
    )
    seen_rows = _seen_questions(db, tenant_id, student_id, subject)
    args = dict(
        this_week=this_week,
        learned=learned,
        weak_kps=weak,
        wrong_kps=_wrong_kps(db, tenant_id, student_id, subject, at),
        level=level,
    )
    seed = f"{student_id}:{subject}:{week}"
    paper = rules.compose(pool, seen={q for q, _ in seen_rows}, rng=random.Random(seed), **args)
    if len(paper.picked) < rules.MIN_QUESTIONS and last:
        # 没做过的题不够了：允许重复更早做过的题，但不重复上一周的
        recent = {q for q, w in seen_rows if w == last[0].week_start}
        paper = rules.compose(pool, seen=recent, rng=random.Random(seed), **args)
    if len(paper.picked) < rules.MIN_QUESTIONS:
        return None

    title = f"{subject}周测（{week.month} 月 {week.day} 日这周）"
    a = Assignment(
        tenant_id=tenant_id,
        owner_id=progress.teacher_id,
        kind=AssignmentKind.WEEKLY,
        title=title,
        subject=subject,
        note=(
            f"{reason}本卷{rules.LEVEL_LABELS[level]}难度，共 {len(paper.picked)} 题。"
            "请独立完成，提交后不能修改。"
        ),
        class_ids=[str(progress.klass_id)],
        publish_at=at,
        due_at=due_of(week, at),
        # 截止后才公布答案：同班同学的卷子有部分题目相同，先交的不能把答案传给没交的
        answer_release=AnswerRelease.DUE,
        allow_ai=False,
        total_score=sum(p.score for p in paper.picked),
        student_count=1,
    )
    db.add(a)
    db.flush()
    option_rng = random.Random(f"{seed}:options")
    for seq, p in enumerate(paper.picked):
        q = questions[p.item.id]
        options, answer = shuffled_options(q, option_rng)
        db.add(
            AssignmentItem(
                tenant_id=tenant_id,
                assignment_id=a.id,
                seq=seq,
                item_type=ItemType.QUESTION,
                ref_id=q.id,
                score=p.score,
                content={
                    "qtype": q.qtype,
                    "stem": q.stem,
                    "options": options,
                    "answer": answer,
                    "analysis": q.analysis,
                    "difficulty": q.difficulty,
                    "knowledge_points": [kp_names[k] for k in p.item.kp_ids if k in kp_names],
                    "kp_ids": [str(k) for k in p.item.kp_ids],
                    "origin": p.origin,
                    "section_no": section_no.get(q.section_id, ""),
                },
            )
        )
    db.add(
        Submission(tenant_id=tenant_id, assignment_id=a.id, student_id=student_id, klass_id=progress.klass_id)
    )
    db.add(
        WeeklyPaper(
            tenant_id=tenant_id,
            student_id=student_id,
            klass_id=progress.klass_id,
            subject=subject,
            book_id=progress.book_id,
            week_start=week,
            assignment_id=a.id,
            level=level,
            prev_ratio=ratio,
            reason=reason,
            plan={"counts": paper.counts, "shortage": paper.shortage},
        )
    )
    notify(
        db,
        tenant_id,
        [student_id],
        kind="assignment",
        title=f"本周{subject}周测来了",
        body=f"{reason}{a.due_at.astimezone(SCHOOL_TZ):%m-%d %H:%M} 截止。" if a.due_at else reason,
        link=f"/student/assignments/{a.id}",
    )
    return paper


def issue_class(
    db: Session, progress: ClassProgress, *, week: date | None = None, at: datetime | None = None
) -> IssueResult:
    """给一个班发这周的周测。已经发过的学生跳过，可以重复调用。"""
    at = at or now()
    week = week or week_of(at)
    tenant_id = progress.tenant_id
    book = db.get(Textbook, progress.book_id)
    if book is None or book.status != BookStatus.PUBLISHED:
        raise AppError("这册教材已经下架，发不了周测")
    sections, _ = _book_sections(db, book.id)
    chosen = {uuid.UUID(s) for s in progress.section_ids}
    order = [s.id for s in sections]
    last_taught = max((order.index(s) for s in chosen if s in order), default=-1)
    this_week = {s for s in chosen if s in order}
    learned = set(order[: last_taught + 1]) - this_week  # 书里排在这周内容之前的节
    pool = _load_pool(db, book.id)
    if not any(q.section_id in this_week for q in pool):
        raise AppError("这周的节还没有审核通过的题，请先在题库里审核", code="pool_empty")

    questions = {q.id: q for q in db.scalars(select(PoolQuestion).where(PoolQuestion.book_id == book.id))}
    kp_names = {
        kid: name
        for kid, name in db.execute(
            select(KnowledgePoint.id, KnowledgePoint.name).where(KnowledgePoint.book_id == book.id)
        )
    }
    section_no = {s.id: s.no for s in sections}
    students = [sid for sid, _ in org.students_in_classes(db, tenant_id, [progress.klass_id])]
    done = set(
        db.scalars(
            select(WeeklyPaper.student_id).where(
                WeeklyPaper.tenant_id == tenant_id,
                WeeklyPaper.subject == progress.subject,
                WeeklyPaper.week_start == week,
                WeeklyPaper.student_id.in_(students),
            )
        )
    )
    names = {uid: name for uid, name in db.execute(select(User.id, User.name).where(User.id.in_(students)))}
    created = 0
    short: list[str] = []
    partial: list[str] = []
    for student_id in dict.fromkeys(students):
        if student_id in done:
            continue
        paper = _issue_one(
            db,
            progress,
            student_id,
            week=week,
            at=at,
            pool=pool,
            this_week=this_week,
            learned=learned,
            kp_names=kp_names,
            section_no=section_no,
            questions=questions,
        )
        if paper is None:
            short.append(names.get(student_id, ""))
            continue
        created += 1
        if paper.shortage:
            partial.append(names.get(student_id, ""))
    db.flush()
    return IssueResult(
        week_start=week,
        created=created,
        existing=len(done),
        short=short,
        partial=partial,
        stale_progress=progress.week_start != week,
    )


def issue_summary(result: IssueResult) -> str:
    parts = [f"发出 {result.created} 份"]
    if result.short:
        parts.append(f"{len(result.short)} 名学生因为题库不够没发成")
    if result.partial:
        parts.append(f"{len(result.partial)} 名学生的卷子题目偏少")
    if result.stale_progress:
        parts.append("这周的进度没更新，用的是上次设置的节")
    return "，".join(parts)


# —— 老师看成绩 ——


def _percent(ratio: float | None) -> float | None:
    return round(ratio * 100, 1) if ratio is not None else None


def _kp_info(db: Session, kp_ids: list[uuid.UUID]) -> dict[uuid.UUID, tuple[str, str]]:
    if not kp_ids:
        return {}
    rows = db.execute(
        select(KnowledgePoint.id, KnowledgePoint.name, Chapter.no)
        .join(Chapter, Chapter.id == KnowledgePoint.chapter_id)
        .where(KnowledgePoint.id.in_(kp_ids))
    )
    return {kid: (name, no) for kid, name, no in rows}


def _weak_list(
    scores: dict[uuid.UUID, float], info: dict[uuid.UUID, tuple[str, str]], n: int
) -> list[KpMastery]:
    weak = sorted(
        (k for k, m in scores.items() if m < rules.WEAK_BELOW and k in info), key=lambda k: scores[k]
    )
    return [
        KpMastery(kp_id=k, name=info[k][0], section_no=info[k][1], mastery=round(scores[k], 2))
        for k in weak[:n]
    ]


def class_report(
    db: Session,
    tenant_id: uuid.UUID,
    teacher_id: uuid.UUID,
    klass_id: uuid.UUID,
    subject: str,
    week: date | None,
) -> ClassWeekReport:
    _membership(db, tenant_id, klass_id, teacher_id)
    klass = org.get_class(db, tenant_id, klass_id)
    weeks = list(
        db.scalars(
            select(WeeklyPaper.week_start)
            .where(
                WeeklyPaper.tenant_id == tenant_id,
                WeeklyPaper.klass_id == klass_id,
                WeeklyPaper.subject == subject,
            )
            .distinct()
            .order_by(WeeklyPaper.week_start.desc())
        )
    )
    week = week or (weeks[0] if weeks else week_of())
    papers = {
        p.student_id: (p, a, s)
        for p, a, s in db.execute(
            select(WeeklyPaper, Assignment, Submission)
            .join(Assignment, Assignment.id == WeeklyPaper.assignment_id)
            .join(Submission, Submission.assignment_id == Assignment.id)
            .where(
                WeeklyPaper.tenant_id == tenant_id,
                WeeklyPaper.klass_id == klass_id,
                WeeklyPaper.subject == subject,
                WeeklyPaper.week_start == week,
            )
        )
    }
    students = [sid for sid, _ in org.students_in_classes(db, tenant_id, [klass_id])]
    people = {
        u.id: u
        for u in db.scalars(select(User).where(User.id.in_(students)).order_by(User.username, User.name))
    }
    masteries = {sid: learning.mastery(db, tenant_id, sid, subject) for sid in people}
    info = _kp_info(db, list({k for m in masteries.values() for k in m}))
    rows = []
    for sid, user in people.items():
        scores = masteries[sid]
        row = papers.get(sid)
        if row is None:
            rows.append(
                StudentWeekRow(
                    student_id=sid,
                    student_name=user.name,
                    username=user.username,
                    assignment_id=None,
                    level=None,
                    level_label=None,
                    reason="",
                    status=None,
                    score=None,
                    total_score=None,
                    percent=None,
                    pending_count=0,
                    prev_percent=None,
                    weak_kps=_weak_list(scores, info, WEAK_LIST),
                )
            )
            continue
        p, a, s = row
        rows.append(
            StudentWeekRow(
                student_id=sid,
                student_name=user.name,
                username=user.username,
                assignment_id=a.id,
                level=p.level,
                level_label=rules.LEVEL_LABELS[p.level],
                reason=p.reason,
                status=s.status,
                score=s.score if s.status != SubmissionStatus.TODO else None,
                total_score=a.total_score,
                percent=_percent(score_ratio(db, s, a)),
                pending_count=s.pending_count,
                prev_percent=_percent(p.prev_ratio),
                weak_kps=_weak_list(scores, info, WEAK_LIST),
            )
        )
    totals: dict[uuid.UUID, list[float]] = {}
    for scores in masteries.values():
        for k, m in scores.items():
            totals.setdefault(k, []).append(m)
    means = {k: sum(v) / len(v) for k, v in totals.items()}
    return ClassWeekReport(
        klass_id=klass.id,
        class_name=klass.name,
        subject=subject,
        week_start=week,
        weeks=weeks,
        rows=rows,
        class_weak_kps=_weak_list(means, info, CLASS_WEAK_LIST),
    )


def week_assignment_ids(
    db: Session, tenant_id: uuid.UUID, teacher_id: uuid.UUID, klass_id: uuid.UUID, subject: str
) -> list[uuid.UUID]:
    """这个班这门课由这位老师负责确认的全部周测。"""
    _membership(db, tenant_id, klass_id, teacher_id)
    return list(
        db.scalars(
            select(WeeklyPaper.assignment_id)
            .join(Assignment, Assignment.id == WeeklyPaper.assignment_id)
            .where(
                WeeklyPaper.tenant_id == tenant_id,
                WeeklyPaper.klass_id == klass_id,
                WeeklyPaper.subject == subject,
                Assignment.owner_id == teacher_id,
            )
        )
    )


def confirm_all(db: Session, teacher: User, assignment_ids: list[uuid.UUID]) -> int:
    """AI 已批改的题全部按 AI 给的分确认。"""
    rows = db.execute(
        select(Answer, Submission, Assignment, AssignmentItem)
        .join(Submission, Submission.id == Answer.submission_id)
        .join(Assignment, Assignment.id == Submission.assignment_id)
        .join(AssignmentItem, AssignmentItem.id == Answer.item_id)
        .where(
            Submission.assignment_id.in_(assignment_ids),
            Answer.status == AnswerStatus.AI_DONE,
            Answer.ai_score.is_not(None),
        )
    ).all()
    for answer, sub, a, item in rows:
        assignments.confirm(db, teacher, answer, sub, a, item, None, None)
    return len(rows)


# —— 学生看成绩 ——


def for_student(db: Session, tenant_id: uuid.UUID, student_id: uuid.UUID) -> list[SubjectWeekly]:
    rows = db.execute(
        select(WeeklyPaper, Assignment, Submission, Textbook.title)
        .join(Assignment, Assignment.id == WeeklyPaper.assignment_id)
        .join(Submission, Submission.assignment_id == Assignment.id)
        .join(Textbook, Textbook.id == WeeklyPaper.book_id)
        .where(WeeklyPaper.tenant_id == tenant_id, WeeklyPaper.student_id == student_id)
        .order_by(WeeklyPaper.subject, WeeklyPaper.week_start.desc())
    ).all()
    grouped: dict[str, list] = {}
    for row in rows:
        grouped.setdefault(row[0].subject, []).append(row)
    out = []
    for subject, papers in grouped.items():
        scores = learning.mastery(db, tenant_id, student_id, subject)
        info = _kp_info(db, list(scores))
        weeks = []
        for p, a, s, _ in papers:
            weeks.append(
                WeekRow(
                    week_start=p.week_start,
                    assignment_id=a.id,
                    title=a.title,
                    status=s.status,
                    score=s.score if s.status == SubmissionStatus.GRADED else None,
                    total_score=a.total_score,
                    percent=_percent(_released_ratio(db, s)),
                    level=p.level,
                    level_label=rules.LEVEL_LABELS[p.level],
                    reason=p.reason,
                    origins=p.plan.get("counts", {}),
                )
            )
        latest = papers[0][0]
        out.append(
            SubjectWeekly(
                subject=subject,
                book_title=papers[0][3],
                level=latest.level,
                level_label=rules.LEVEL_LABELS[latest.level],
                weeks=weeks,
                weak_kps=_weak_list(scores, info, CLASS_WEAK_LIST),
                tested_kps=len(scores),
                mastered_kps=sum(1 for m in scores.values() if m >= MASTERED_AT),
            )
        )
    return out


def _released_ratio(db: Session, sub: Submission) -> float | None:
    """学生能看到的得分率：只算已经出最终分的题，老师没确认的 AI 分不给学生看。"""
    if sub.status == SubmissionStatus.TODO:
        return None
    rows = db.execute(
        select(Answer.score, AssignmentItem.score)
        .join(AssignmentItem, AssignmentItem.id == Answer.item_id)
        .where(Answer.submission_id == sub.id, Answer.score.is_not(None))
    ).all()
    total = sum(full for _, full in rows)
    return sum(score for score, _ in rows) / total if total else None

"""背诵卡片复习：FSRS 间隔重复。

老师布置的背诵项（作业里的卡片快照）就是学生要背的卡片。"今日复习"在读取时计算：到期的旧卡片全部复习，
新卡片每天最多学 NEW_PER_DAY 张。技术方案里写的是定时任务每天生成清单，读取时算结果一样，还省掉一个定时任务。
"""

import uuid
from datetime import UTC, datetime, timedelta

from fsrs import Card, Rating, Scheduler
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import NotFound
from app.modules.assignment import student as assignments
from app.modules.learning.models import ReviewLog, ReviewState

NEW_PER_DAY = 20
_scheduler = Scheduler()


class ReviewCard(BaseModel):
    item_id: uuid.UUID
    card_key: int
    deck_title: str
    kind: str
    front: str
    back: str
    new: bool


class DeckProgress(BaseModel):
    item_id: uuid.UUID
    assignment_id: uuid.UUID
    title: str
    subject: str
    total: int
    learned: int
    due: int


class ReviewToday(BaseModel):
    cards: list[ReviewCard] = Field(description="今天要复习的卡片：先到期的旧卡片，再新卡片")
    due_count: int
    new_count: int
    decks: list[DeckProgress]


class RateIn(BaseModel):
    rating: int = Field(ge=1, le=4, description="1 忘了 / 2 模糊 / 3 记得 / 4 很熟")
    duration_ms: int | None = Field(default=None, ge=0, le=3_600_000)


class RateOut(BaseModel):
    due: datetime = Field(description="下次复习时间")


def _today_start(now: datetime) -> datetime:
    # 按北京时间算"今天"
    local = now.astimezone(UTC) + timedelta(hours=8)
    return local.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(hours=8)


def today(
    db: Session, tenant_id: uuid.UUID, student_id: uuid.UUID, item_id: uuid.UUID | None = None
) -> ReviewToday:
    now = datetime.now(UTC)
    items = assignments.recite_items(db, tenant_id, student_id)
    if item_id:
        items = [row for row in items if row[0].id == item_id]
    states = {
        (s.item_id, s.card_key): s
        for s in db.scalars(
            select(ReviewState).where(
                ReviewState.student_id == student_id, ReviewState.item_id.in_([i.id for i, _, _ in items])
            )
        )
    }
    learned_today = db.scalar(
        select(func.count())
        .select_from(ReviewState)
        .where(ReviewState.student_id == student_id, ReviewState.created_at >= _today_start(now))
    )
    new_quota = max(0, NEW_PER_DAY - (learned_today or 0))

    due: list[tuple[datetime, ReviewCard]] = []
    new: list[ReviewCard] = []
    decks = []
    for item, a, _ in items:
        cards = item.content.get("cards") or []
        deck_due = 0
        for key, card in enumerate(cards):
            state = states.get((item.id, key))
            data = ReviewCard(
                item_id=item.id,
                card_key=key,
                deck_title=item.content.get("title", ""),
                kind=card["kind"],
                front=card["front"],
                back=card.get("back", ""),
                new=state is None,
            )
            if state is None:
                new.append(data)
            elif state.due <= now:
                due.append((state.due, data))
                deck_due += 1
        decks.append(
            DeckProgress(
                item_id=item.id,
                assignment_id=a.id,
                title=item.content.get("title", ""),
                subject=a.subject,
                total=len(cards),
                learned=sum(1 for k in range(len(cards)) if (item.id, k) in states),
                due=deck_due,
            )
        )
    due.sort(key=lambda x: x[0])
    new = new[:new_quota]
    return ReviewToday(cards=[c for _, c in due] + new, due_count=len(due), new_count=len(new), decks=decks)


def rate(
    db: Session, tenant_id: uuid.UUID, student_id: uuid.UUID, item_id: uuid.UUID, card_key: int, body: RateIn
) -> RateOut:
    row = next((r for r in assignments.recite_items(db, tenant_id, student_id) if r[0].id == item_id), None)
    if row is None or not 0 <= card_key < len(row[0].content.get("cards") or []):
        raise NotFound("卡片不存在")
    item, a, sub = row
    state = db.scalar(
        select(ReviewState).where(
            ReviewState.student_id == student_id,
            ReviewState.item_id == item_id,
            ReviewState.card_key == card_key,
        )
    )
    card = Card.from_dict(state.card) if state else Card()
    card, _ = _scheduler.review_card(card, Rating(body.rating), datetime.now(UTC), body.duration_ms)
    if state is None:
        state = ReviewState(tenant_id=tenant_id, student_id=student_id, item_id=item_id, card_key=card_key)
        db.add(state)
        state.reps, state.lapses = 0, 0
    state.card = card.to_dict()
    state.due = card.due
    state.reps += 1
    state.lapses += body.rating == Rating.Again
    db.flush()
    db.add(
        ReviewLog(tenant_id=tenant_id, state_id=state.id, rating=body.rating, duration_ms=body.duration_ms)
    )

    # 每张卡都学过一遍，作业里这个背诵项就算完成
    learned = db.scalar(
        select(func.count())
        .select_from(ReviewState)
        .where(ReviewState.student_id == student_id, ReviewState.item_id == item_id)
    )
    if learned >= len(item.content.get("cards") or []) and not sub.progress.get(str(item_id)):
        sub.progress = {**sub.progress, str(item_id): True}
    return RateOut(due=card.due)

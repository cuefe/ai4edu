"""组卷规则。不碰数据库的纯函数：给定题库和学生情况，算出这周的卷子，同样的输入得到同样的结果。

- 题量：8 道单选、4 道填空、2 道解答，折算成 100 分。
- 来源：约 70% 本周内容、20% 薄弱知识点、10% 错题的同类题（同一知识点的另一道题，不重复做原题）。
  没有薄弱点或错题时（比如第一周），这部分的位置改考本周内容；本周的题不够时，用学过的内容补。
- 难度：上周得分 85% 及以上升一档，低于 60% 降一档，没提交就不变。每一档按比例搭配容易、中等、较难的题。
- 同一个学生做过的题不再出现。解答题要老师确认，薄弱点和错题的位置优先用客观题，不增加批改量。
"""

import random
import uuid
from collections import Counter
from dataclasses import dataclass, field

LEVEL_LABELS = {1: "基础", 2: "标准", 3: "提高"}
DEFAULT_LEVEL = 2
LEVEL_UP_AT = 0.85
LEVEL_DOWN_BELOW = 0.60
WEAK_BELOW = 0.60  # 掌握度低于这个数算薄弱知识点
MIN_QUESTIONS = 5  # 题目少于这个数就不发了，告诉老师题库不够

DIFFICULTIES = ("容易", "中等", "较难")
_LEVEL_MIX = {1: (0.6, 0.3, 0.1), 2: (0.3, 0.5, 0.2), 3: (0.15, 0.45, 0.4)}

PAPER_MIX = (("单选题", 8), ("填空题", 4), ("解答题", 2))
RAW_SCORE = {"单选题": 5, "多选题": 5, "判断题": 5, "填空题": 5, "解答题": 20}
WRONG_SHARE = 0.1
WEAK_SHARE = 0.2
OBJECTIVE = ("单选题", "填空题", "多选题", "判断题")

ORIGIN_THIS_WEEK = "this_week"
ORIGIN_WEAK = "weak"
ORIGIN_WRONG = "wrong"
ORIGIN_REVIEW = "review"
ORIGIN_LABELS = {
    ORIGIN_THIS_WEEK: "本周内容",
    ORIGIN_WEAK: "巩固薄弱点",
    ORIGIN_WRONG: "错题同类题",
    ORIGIN_REVIEW: "复习",
}
# 一个位置找不到题时，依次改用哪种来源
_FALLBACK = {
    ORIGIN_WRONG: (ORIGIN_WRONG, ORIGIN_WEAK, ORIGIN_THIS_WEEK, ORIGIN_REVIEW),
    ORIGIN_WEAK: (ORIGIN_WEAK, ORIGIN_THIS_WEEK, ORIGIN_REVIEW),
    ORIGIN_THIS_WEEK: (ORIGIN_THIS_WEEK, ORIGIN_REVIEW),
}


@dataclass(frozen=True)
class PoolItem:
    id: uuid.UUID
    section_id: uuid.UUID
    qtype: str
    difficulty: str
    kp_ids: tuple[uuid.UUID, ...]


@dataclass(frozen=True)
class Slot:
    qtype: str
    difficulty: str
    origin: str


@dataclass(frozen=True)
class Picked:
    item: PoolItem
    origin: str
    score: float


@dataclass
class Composition:
    picked: list[Picked] = field(default_factory=list)
    shortage: int = 0  # 有几个位置没找到题

    @property
    def counts(self) -> dict[str, int]:
        return dict(Counter(p.origin for p in self.picked))


def next_level(level: int | None, ratio: float | None) -> tuple[int, str]:
    """根据上一份的难度和得分比例定这一份的难度，同时给出写给学生看的说明。"""
    if level is None:
        return DEFAULT_LEVEL, "这是你的第一份周测，难度按标准来。"
    if ratio is None:
        return level, "上一份周测没有提交，这周难度不变。"
    points = round(ratio * 100)
    if ratio >= LEVEL_UP_AT:
        if level >= max(LEVEL_LABELS):
            return level, f"上周得了 {points} 分，继续保持最高难度。"
        return level + 1, f"上周得了 {points} 分，这周难度提高一档。"
    if ratio < LEVEL_DOWN_BELOW:
        if level <= min(LEVEL_LABELS):
            return level, f"上周得了 {points} 分，这周继续打基础。"
        return level - 1, f"上周得了 {points} 分，这周难度降一档，先把基础打牢。"
    return level, f"上周得了 {points} 分，这周难度不变。"


def difficulty_slots(count: int, level: int) -> list[str]:
    """按这一档的比例把 count 个位置分给三种难度（最大余数法）。"""
    shares = [count * s for s in _LEVEL_MIX[level]]
    counts = [int(s) for s in shares]
    leftover = sorted(range(3), key=lambda i: (counts[i] - shares[i], i))
    for i in leftover[: count - sum(counts)]:
        counts[i] += 1
    return [d for d, n in zip(DIFFICULTIES, counts, strict=True) for _ in range(n)]


def plan_slots(level: int, rng: random.Random) -> list[Slot]:
    """定好每个位置的题型、难度和来源。"""
    planned = [(qtype, d) for qtype, count in PAPER_MIX for d in difficulty_slots(count, level)]
    total = len(planned)
    n_wrong = max(1, round(total * WRONG_SHARE))
    n_weak = max(1, round(total * WEAK_SHARE))
    objective = [i for i, (qtype, _) in enumerate(planned) if qtype in OBJECTIVE]
    rng.shuffle(objective)
    origins = dict.fromkeys(objective[:n_wrong], ORIGIN_WRONG)
    origins.update(dict.fromkeys(objective[n_wrong : n_wrong + n_weak], ORIGIN_WEAK))
    return [Slot(q, d, origins.get(i, ORIGIN_THIS_WEEK)) for i, (q, d) in enumerate(planned)]


def scale_scores(raw: list[float], total: float = 100) -> list[float]:
    """折算成总分 total，每题保留到 0.5 分，零头加在最后一题。"""
    if not raw:
        return []
    factor = total / sum(raw)
    scores = [round(r * factor * 2) / 2 for r in raw]
    scores[-1] += total - sum(scores)
    return scores


def compose(
    pool: list[PoolItem],
    *,
    this_week: set[uuid.UUID],
    learned: set[uuid.UUID],
    weak_kps: list[uuid.UUID],
    wrong_kps: list[uuid.UUID],
    seen: set[uuid.UUID],
    level: int,
    rng: random.Random,
) -> Composition:
    """组一份卷子。this_week、learned 是节的 ID；weak_kps 按掌握度从低到高排。"""
    fresh = [q for q in pool if q.id not in seen]
    scope = this_week | learned
    wrong = set(wrong_kps)
    weak_rank = {k: i for i, k in enumerate(weak_kps)}
    used: set[uuid.UUID] = set()
    covered: Counter[uuid.UUID] = Counter()

    def in_origin(q: PoolItem, origin: str) -> bool:
        if origin == ORIGIN_THIS_WEEK:
            return q.section_id in this_week
        if origin == ORIGIN_REVIEW:
            return q.section_id in learned
        if q.section_id not in scope:  # 薄弱点、错题也不能考还没教的内容
            return False
        kps = wrong if origin == ORIGIN_WRONG else weak_rank
        return any(k in kps for k in q.kp_ids)

    def rank(q: PoolItem, slot: Slot, origin: str) -> tuple[float, ...]:
        gap = abs(DIFFICULTIES.index(q.difficulty) - DIFFICULTIES.index(slot.difficulty))
        weakest = (
            min((weak_rank[k] for k in q.kp_ids if k in weak_rank), default=len(weak_rank))
            if origin == ORIGIN_WEAK
            else 0
        )
        # 难度最接近的优先；同样接近时，优先最薄弱的知识点和还没考到的知识点
        return (gap, weakest, sum(covered[k] for k in q.kp_ids), rng.random())

    def alternatives(qtype: str) -> tuple[str, ...]:
        # 解答题不够可以换客观题；客观题不够不换解答题，免得增加批改量
        return (qtype, *(t for t in OBJECTIVE if t != qtype))

    result = Composition()
    chosen: list[tuple[PoolItem, str]] = []
    for slot in plan_slots(level, rng):
        pick: tuple[PoolItem, str] | None = None
        for origin in _FALLBACK[slot.origin]:
            for qtype in alternatives(slot.qtype):
                candidates = [
                    q for q in fresh if q.id not in used and q.qtype == qtype and in_origin(q, origin)
                ]
                if candidates:
                    pick = (min(candidates, key=lambda q: rank(q, slot, origin)), origin)
                    break
            if pick:
                break
        if pick is None:
            result.shortage += 1
            continue
        used.add(pick[0].id)
        covered.update(pick[0].kp_ids)
        chosen.append(pick)

    type_order = {qtype: i for i, (qtype, _) in enumerate(PAPER_MIX)}
    chosen.sort(key=lambda c: (type_order.get(c[0].qtype, 1), DIFFICULTIES.index(c[0].difficulty)))
    scores = scale_scores([RAW_SCORE[q.qtype] for q, _ in chosen])
    result.picked = [Picked(q, origin, s) for (q, origin), s in zip(chosen, scores, strict=True)]
    return result

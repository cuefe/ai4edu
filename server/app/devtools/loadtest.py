"""压测：模拟一所学校的学生同时做作业、老师看报告。

    uv run python -m app.cli seed-load --classes 12 --per-class 50     # 写入压测数据（仅开发环境）
    uv run python -m app.cli seed-load --reset                          # 再压一遍前清掉上次的作答
    uv run python -m app.devtools.loadtest --users 300 --duration 120   # 对 http://127.0.0.1:8000 压测

压测机构的代码是 load，学生账号 u0001…，密码都是 123456；老师手机号 199550000xx，密码 load1234。
题目都是客观题，按题型作答，提交时按规则直接判分。压测机构的 AI 月额度设成 0：万一有判不了的答案
要交给 AI 批改，也会被额度拦下，不会调用大模型（不花钱）。
每个虚拟学生：登录 → 首页 → 打开作业 → 逐题作答（自动保存）→ 提交 → 看结果、错题本、今日背诵，
之后反复刷新首页和作业；每步之间停顿 --think 秒（随机 0.5～1.5 倍），模拟真人操作。
"""

import argparse
import asyncio
import random
import statistics
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field

import httpx

CODE = "load"
STUDENT_PASSWORD = "123456"
TEACHER_PASSWORD = "load1234"
TEACHER_PHONE = "1995500{:04d}"

QUESTIONS = [
    {
        "qtype": "单选题",
        "stem": f"第 {i} 题：$-{i}$ 的相反数是",
        "options": [f"${i}$", f"$-{i}$", "$0$", f"${i + 10}$"],
        "answer": "A",
    }
    for i in range(1, 7)
] + [
    {
        "qtype": "多选题",
        "stem": "下列数中是负数的有",
        "options": ["$-1$", "$0$", "$-0.5$", "$2$"],
        "answer": "AC",
    },
    {
        "qtype": "多选题",
        "stem": "下列数中是整数的有",
        "options": ["$-1$", "$0.5$", "$0$", "$\\frac12$"],
        "answer": "AC",
    },
    {"qtype": "填空题", "stem": "$|-3|=$＿＿＿＿", "answer": "3"},
    {"qtype": "填空题", "stem": "$\\frac{1}{2}$ 的相反数是＿＿＿＿", "answer": "$-\\frac{1}{2}$"},
]
# 虚拟学生按题型随机作答，对错都有。填空只用数字：规则一定判得了，不会转给 AI 批改
ANSWERS = {
    "单选题": ["A", "B", "C", "D"],
    "多选题": ["AC", "A", "BD"],
    "填空题": ["3", "4", "-1/2", "0.5"],
}


# —— 写入压测数据 ——


def seed(classes: int, per_class: int) -> None:
    from sqlalchemy import select

    from app.core.db import session_scope
    from app.core.security import hash_password
    from app.modules.assignment import service as assignments
    from app.modules.assignment.schemas import AssignmentIn, ItemIn
    from app.modules.iam import service as iam
    from app.modules.iam.models import Role, Tenant, User
    from app.modules.org.models import ClassMember, Klass, MemberRole
    from app.modules.qbank import service as qbank
    from app.modules.qbank.schemas import QuestionIn

    with session_scope(bypass=True) as db:
        if db.scalar(select(Tenant.id).where(Tenant.code == CODE)):
            sys.exit("压测机构 load 已存在。要重新写入，先删掉本地数据库（server/.data/pg）或换一个库")
        # AI 月额度 0：压测不能调用大模型（判不了的答案会转 AI 批改，用的是 .env 里的真实 Key）
        tenant = Tenant(code=CODE, name="压测学校", kind="school", ai_budget_yuan=0)
        db.add(tenant)
        db.flush()
        student_hash = hash_password(STUDENT_PASSWORD)  # 所有学生同一个密码，只算一次哈希
        question_ids = []
        n = 0
        for c in range(1, classes + 1):
            klass = Klass(tenant_id=tenant.id, name=f"压测{c}班", grade="初一")
            db.add(klass)
            teacher = iam.create_user(
                db,
                tenant_id=tenant.id,
                name=f"压测老师{c}",
                roles=[Role.TEACHER, *([Role.ORG_ADMIN] if c == 1 else [])],
                phone=TEACHER_PHONE.format(c),
                password=TEACHER_PASSWORD,
            )
            db.flush()
            db.add(
                ClassMember(
                    tenant_id=tenant.id, klass_id=klass.id, user_id=teacher.id, member_role=MemberRole.TEACHER
                )
            )
            for _ in range(per_class):
                n += 1
                student = User(
                    tenant_id=tenant.id,
                    name=f"学生{n}",
                    username=f"u{n:04d}",
                    roles=[str(Role.STUDENT)],
                    password_hash=student_hash,
                )
                db.add(student)
                db.flush()
                db.add(
                    ClassMember(
                        tenant_id=tenant.id,
                        klass_id=klass.id,
                        user_id=student.id,
                        member_role=MemberRole.STUDENT,
                    )
                )
            db.flush()
            if not question_ids:
                question_ids = [
                    qbank.create_manual(db, tenant.id, teacher.id, QuestionIn(subject="数学", **q)).id
                    for q in QUESTIONS
                ]
            assignments.create(
                db,
                tenant.id,
                teacher,
                AssignmentIn(
                    title="压测作业：有理数",
                    subject="数学",
                    class_ids=[klass.id],
                    items=[ItemIn(item_type="question", ref_id=qid) for qid in question_ids],
                ),
            )
        print(f"已写入压测机构 {CODE}：{classes} 个班、{n} 名学生、{classes} 位老师")
        print(f"每班一份 {len(QUESTIONS)} 道客观题的作业")


def reset() -> None:
    """清掉压测学生的作答、错题，作业恢复成没交，可以再压一遍。"""
    from sqlalchemy import delete, select, update

    from app.core.db import session_scope
    from app.modules.assignment.models import Answer, Submission, SubmissionStatus
    from app.modules.iam.models import Tenant
    from app.modules.learning.models import WrongItem

    with session_scope(bypass=True) as db:
        tenant_id = db.scalar(select(Tenant.id).where(Tenant.code == CODE))
        if tenant_id is None:
            sys.exit("还没有压测数据，先运行 app.cli seed-load")
        db.execute(delete(WrongItem).where(WrongItem.tenant_id == tenant_id))
        db.execute(delete(Answer).where(Answer.tenant_id == tenant_id))
        db.execute(
            update(Submission)
            .where(Submission.tenant_id == tenant_id)
            .values(status=SubmissionStatus.TODO, submitted_at=None, score=None, pending_count=0)
        )
    print("压测学生的作答已清空，作业恢复成没交")


# —— 压测 ——


@dataclass
class Stats:
    latencies: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))
    errors: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    samples: dict[str, str] = field(default_factory=dict)

    def record(self, name: str, ms: float, ok: bool, detail: str = "") -> None:
        self.latencies[name].append(ms)
        if not ok:
            self.errors[name] += 1
            self.samples.setdefault(name, detail[:200])


def _pct(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    return values[min(len(values) - 1, int(len(values) * p))]


class VirtualUser:
    def __init__(self, client: httpx.AsyncClient, stats: Stats, think: float):
        self.client, self.stats, self.think = client, stats, think
        self.headers: dict[str, str] = {}

    async def call(self, name: str, method: str, url: str, **kw) -> httpx.Response | None:
        started = time.perf_counter()
        try:
            resp = await self.client.request(method, url, headers=self.headers, **kw)
        except httpx.HTTPError as exc:
            self.stats.record(name, (time.perf_counter() - started) * 1000, False, repr(exc))
            return None
        ok = resp.status_code < 400
        self.stats.record(name, (time.perf_counter() - started) * 1000, ok, f"{resp.status_code} {resp.text}")
        return resp if ok else None

    async def pause(self) -> None:
        if self.think:
            await asyncio.sleep(self.think * random.uniform(0.5, 1.5))


class Student(VirtualUser):
    def __init__(self, n: int, *args):
        super().__init__(*args)
        self.username = f"u{n:04d}"

    async def run(self, until: float) -> None:
        body = {"tenant_code": CODE, "username": self.username, "password": STUDENT_PASSWORD}
        resp = await self.call("登录（学生）", "POST", "/api/auth/login/student", json=body)
        if resp is None:
            return
        self.headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}
        submitted = False
        while time.monotonic() < until:
            await self.call("我的账号", "GET", "/api/me")
            await self.call("站内信", "GET", "/api/me/notifications")
            resp = await self.call("作业列表", "GET", "/api/student/assignments")
            await self.pause()
            if not resp or not resp.json():
                continue
            aid = resp.json()[0]["id"]
            resp = await self.call("打开作业", "GET", f"/api/student/assignments/{aid}")
            if resp is None:
                continue
            submitted = submitted or resp.json()["submitted_at"] is not None  # 上一轮压测已经交过
            if not submitted:
                for item in resp.json()["items"]:
                    if time.monotonic() >= until:
                        return
                    await self.pause()
                    answer = random.choice(ANSWERS[item["content"]["qtype"]])
                    await self.call(
                        "保存作答",
                        "PUT",
                        f"/api/student/assignments/{aid}/answers/{item['id']}",
                        json={"response": answer},
                    )
                await self.pause()
                submitted = (
                    await self.call("提交作业", "POST", f"/api/student/assignments/{aid}/submit") is not None
                )
            await self.pause()
            await self.call("错题本", "GET", "/api/student/wrong-items")
            await self.call("今日背诵", "GET", "/api/student/review/today")
            await self.pause()


class Teacher(VirtualUser):
    def __init__(self, n: int, *args):
        super().__init__(*args)
        self.phone = TEACHER_PHONE.format(n)

    async def run(self, until: float) -> None:
        body = {"phone": self.phone, "password": TEACHER_PASSWORD}
        resp = await self.call("登录（老师）", "POST", "/api/auth/login/phone", json=body)
        if resp is None:
            return
        self.headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}
        while time.monotonic() < until:
            resp = await self.call("老师作业列表", "GET", "/api/teacher/assignments")
            if resp and resp.json():
                aid = resp.json()[0]["id"]
                await self.call("作业报告", "GET", f"/api/teacher/assignments/{aid}")
                await self.call("批改队列", "GET", f"/api/teacher/assignments/{aid}/grading")
            await self.pause()
            await self.pause()


async def main(
    base: str, users: int, offset: int, teachers: int, duration: int, ramp: int, think: float
) -> None:
    stats = Stats()
    limits = httpx.Limits(max_connections=users + teachers, max_keepalive_connections=users + teachers)
    async with httpx.AsyncClient(base_url=base, timeout=60, limits=limits) as client:
        started = time.monotonic()
        until = started + duration
        tasks = []
        for i in range(users):
            tasks.append(asyncio.create_task(Student(offset + i + 1, client, stats, think).run(until)))
            if ramp:
                await asyncio.sleep(ramp / users)
        for i in range(teachers):
            tasks.append(asyncio.create_task(Teacher(i + 1, client, stats, think).run(until)))
        await asyncio.gather(*tasks)
        elapsed = time.monotonic() - started

    total = sum(len(v) for v in stats.latencies.values())
    errors = sum(stats.errors.values())
    print(f"\n{users} 名学生 + {teachers} 位老师，{elapsed:.0f} 秒")
    print(f"共 {total} 个请求，{total / elapsed:.1f} 个/秒，失败 {errors} 个")
    print(f"{'接口':<12}{'次数':>8}{'失败':>6}{'p50':>8}{'p95':>8}{'p99':>8}{'最大':>8}  （毫秒）")
    for name, values in sorted(stats.latencies.items(), key=lambda kv: -len(kv[1])):
        p50, p95, p99 = statistics.median(values), _pct(values, 0.95), _pct(values, 0.99)
        print(
            f"{name:<12}{len(values):>8}{stats.errors.get(name, 0):>6}"
            f"{p50:>8.0f}{p95:>8.0f}{p99:>8.0f}{max(values):>8.0f}"
        )
    for name, sample in stats.samples.items():
        print(f"  {name} 失败示例：{sample}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="压测（先运行 app.cli seed-load 写入压测数据）")
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    parser.add_argument("--users", type=int, default=100, help="同时在线的学生数")
    parser.add_argument(
        "--offset", type=int, default=0, help="从第几个学生账号之后开始（多开几个进程一起压时用）"
    )
    parser.add_argument("--teachers", type=int, default=5)
    parser.add_argument("--duration", type=int, default=60, help="秒")
    parser.add_argument("--ramp", type=int, default=10, help="多少秒内陆续登录完")
    parser.add_argument("--think", type=float, default=1.0, help="每步之间的平均停顿（秒），0 表示不停顿")
    args = parser.parse_args()
    asyncio.run(main(args.base, args.users, args.offset, args.teachers, args.duration, args.ramp, args.think))

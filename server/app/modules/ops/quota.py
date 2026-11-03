"""机构额度：账号名额、AI 月额度，以及每个账号每天的 AI 使用次数。

- 名额只算启用中的账号：毕业、离职的停用后就不占名额。
- AI 月额度按自然月（北京时间）汇总 ai_usage 的费用，用完后除安全分类外的模型调用都会被拒绝。
  每次调用都汇总太慢，结果在 Redis 里缓存 30 秒，所以额度可能超出几十秒内的用量。
- 服务到期、机构停用在登录和刷新令牌时检查（iam.service）。
"""

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import any_, func, literal_column, or_, select
from sqlalchemy.orm import Session

from app.ai.models import AiUsage
from app.core.config import get_settings
from app.core.db import session_scope
from app.core.errors import AppError
from app.core.redis import get_redis
from app.modules.iam.models import Role, Tenant, User

# 北京时间。中国不用夏令时，用固定的 UTC+8，不依赖时区数据库（部分 PostgreSQL 发行版没带）
LOCAL_TZ = timezone(timedelta(hours=8), "Asia/Shanghai")
BUDGET_CACHE_SECONDS = 30


def local_date(column: Any) -> Any:
    """SQL：时间列按北京时间取日期。"""
    return func.date(func.timezone(literal_column("interval '8 hours'"), column))


def local_today() -> str:
    return datetime.now(LOCAL_TZ).strftime("%Y%m%d")


def month_start(now: datetime | None = None) -> datetime:
    """本月 1 日 0 点（北京时间）。"""
    local = (now or datetime.now(UTC)).astimezone(LOCAL_TZ)
    return local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


# —— 账号名额 ——


def seat_role(roles: list[str]) -> Role | None:
    """账号占哪类名额：学生占学生名额，老师和管理员占老师名额，平台运营不占。"""
    if Role.STUDENT in roles:
        return Role.STUDENT
    if Role.TEACHER in roles or Role.ORG_ADMIN in roles:
        return Role.TEACHER
    return None


def seats_used(db: Session, tenant_id: uuid.UUID, role: Role) -> int:
    is_student = str(Role.STUDENT) == any_(User.roles)
    stmt = select(func.count()).where(User.tenant_id == tenant_id, User.active.is_(True))
    if role == Role.STUDENT:
        stmt = stmt.where(is_student)
    else:
        stmt = stmt.where(
            or_(str(Role.TEACHER) == any_(User.roles), str(Role.ORG_ADMIN) == any_(User.roles)),
            ~is_student,
        )
    return db.scalar(stmt) or 0


def ensure_seat(db: Session, tenant_id: uuid.UUID, role: Role, adding: int = 1) -> None:
    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        return
    quota = tenant.student_quota if role == Role.STUDENT else tenant.teacher_quota
    if quota is None:
        return
    if seats_used(db, tenant_id, role) + adding > quota:
        kind = "学生" if role == Role.STUDENT else "老师"
        raise AppError(
            f"{kind}账号名额已用完（共 {quota} 个），可以停用不再使用的账号，或联系平台增加名额",
            code="seat_quota",
            status=409,
        )


# —— AI 月额度 ——


@dataclass
class AiBudget:
    spend: Decimal
    budget: Decimal | None

    @property
    def exhausted(self) -> bool:
        return self.budget is not None and self.spend >= self.budget


def month_spend(db: Session, tenant_id: uuid.UUID, now: datetime | None = None) -> Decimal:
    total = db.scalar(
        select(func.coalesce(func.sum(AiUsage.cost_yuan), 0)).where(
            AiUsage.tenant_id == tenant_id, AiUsage.created_at >= month_start(now)
        )
    )
    return Decimal(total or 0)


def _budget_key(tenant_id: uuid.UUID) -> str:
    return f"ai:budget:{tenant_id}:{datetime.now(LOCAL_TZ):%Y%m}"


def ai_budget(tenant_id: uuid.UUID) -> AiBudget:
    redis = get_redis()
    cached = redis.get(_budget_key(tenant_id))
    if cached:
        data = json.loads(cached)
        return AiBudget(Decimal(data["spend"]), Decimal(data["budget"]) if data["budget"] else None)
    with session_scope(tenant_id=tenant_id) as db:
        tenant = db.get(Tenant, tenant_id)
        result = AiBudget(month_spend(db, tenant_id), tenant.ai_budget_yuan if tenant else None)
    payload = {
        "spend": str(result.spend),
        "budget": str(result.budget) if result.budget is not None else None,
    }
    redis.set(_budget_key(tenant_id), json.dumps(payload), ex=BUDGET_CACHE_SECONDS)
    return result


def forget_ai_budget(tenant_id: uuid.UUID) -> None:
    """改了机构的 AI 额度后调用，马上按新额度判断。"""
    get_redis().delete(_budget_key(tenant_id))


def ensure_ai_budget(tenant_id: uuid.UUID) -> None:
    if ai_budget(tenant_id).exhausted:
        raise AppError("本机构本月的 AI 额度已用完，请联系机构管理员", code="ai_budget_exhausted", status=429)


# —— 每个账号每天的次数 ——


def take_daily(user_id: uuid.UUID, bucket: str, limit: int, message: str) -> None:
    """记一次使用，超过当天上限就拒绝（按北京时间算天）。"""
    redis = get_redis()
    key = f"daily:{bucket}:{user_id}:{local_today()}"
    count = redis.incr(key)
    if count == 1:
        redis.expire(key, 2 * 24 * 3600)
    if count > limit:
        raise AppError(message, code="daily_limit", status=429)


def start_teacher_task(tenant_id: uuid.UUID, user_id: uuid.UUID) -> None:
    """老师发起一次 AI 生成（教案、讲义、背诵卡片、出题）前调用：先看机构额度，再记一次当天次数。"""
    ensure_ai_budget(tenant_id)
    limit = get_settings().teacher_daily_ai_tasks
    take_daily(user_id, "teacher_ai", limit, f"今天的 AI 生成次数用完了（每天 {limit} 次），明天再来吧")


def start_tutor_message(tenant_id: uuid.UUID, user_id: uuid.UUID) -> None:
    """学生在问一问里发一条消息前调用。"""
    ensure_ai_budget(tenant_id)
    limit = get_settings().student_daily_tutor_messages
    take_daily(user_id, "tutor", limit, "今天问得太多啦，休息一下，明天再来吧")

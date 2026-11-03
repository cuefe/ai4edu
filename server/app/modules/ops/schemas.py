import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

Money = Decimal  # 元，两位小数


class PlanIn(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    student_quota: int | None = Field(default=None, ge=1, description="为空表示不限")
    teacher_quota: int | None = Field(default=None, ge=1)
    ai_budget_yuan: Money | None = Field(
        default=None, ge=0, max_digits=10, decimal_places=2, description="每月"
    )
    months: int = Field(default=12, ge=1, le=60, description="服务期（月）")
    note: str = Field(default="", max_length=500)
    active: bool = True


class PlanOut(PlanIn):
    id: uuid.UUID
    tenant_count: int = 0


class TenantTerms(BaseModel):
    """机构的套餐和额度。名额、额度为空表示不限。"""

    plan_id: uuid.UUID | None = None
    expires_at: datetime | None = None
    student_quota: int | None = Field(default=None, ge=1)
    teacher_quota: int | None = Field(default=None, ge=1)
    ai_budget_yuan: Money | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    note: str = Field(default="", max_length=500)


class TenantIn(TenantTerms):
    code: str = Field(min_length=2, max_length=32, pattern=r"^[A-Za-z0-9_\-]+$")
    name: str = Field(min_length=1, max_length=100)
    kind: str = Field(pattern=r"^(school|institution)$")
    admin_name: str = Field(min_length=1, max_length=50)
    admin_phone: str = Field(min_length=11, max_length=20)
    admin_password: str | None = Field(default=None, min_length=6, max_length=64)


class TenantPatch(TenantTerms):
    """只改传了的字段；名额、额度、到期时间传 null 表示改成不限。"""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    active: bool | None = None
    note: str | None = Field(default=None, max_length=500)  # 不传不改（开通时默认是空字符串）


class TenantOut(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    kind: str
    active: bool
    created_at: datetime
    plan_id: uuid.UUID | None
    plan_name: str | None
    expires_at: datetime | None
    student_quota: int | None
    teacher_quota: int | None
    ai_budget_yuan: Money | None
    note: str
    students: int = Field(description="启用中的学生账号")
    teachers: int = Field(description="启用中的老师账号（含管理员）")
    ai_spend_yuan: Money = Field(description="本月 AI 费用")


class AiTestIn(BaseModel):
    skill: str = "ping"
    prompt: str = Field(min_length=1, max_length=2000)


class AiTestOut(BaseModel):
    text: str
    provider: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int


class AiCandidateOut(BaseModel):
    provider: str
    model: str


class AiSkillStatusOut(BaseModel):
    skill: str
    tier: str
    candidates: list[AiCandidateOut]  # 当前可用（已配置 Key）的候选，按优先级排序


class AiUsageRow(BaseModel):
    tenant_id: uuid.UUID | None
    tenant_name: str | None
    skill: str
    provider: str
    model: str
    calls: int
    failures: int
    prompt_tokens: int
    completion_tokens: int
    cost_yuan: Decimal | None


class UsageTotals(BaseModel):
    calls: int = 0
    failures: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_yuan: Decimal = Decimal(0)


class TenantUsageRow(UsageTotals):
    tenant_id: uuid.UUID | None
    tenant_name: str | None = Field(description="为空表示平台自己的调用（如运营后台测试）")


class DailyUsageRow(BaseModel):
    day: date
    calls: int
    cost_yuan: Decimal


class UsageSummaryOut(BaseModel):
    total: UsageTotals
    by_tenant: list[TenantUsageRow]
    daily: list[DailyUsageRow] = Field(description="按北京时间的日期")


class ModerationRow(BaseModel):
    id: uuid.UUID
    created_at: datetime
    tenant_name: str
    source: str
    category: str
    crisis: str
    reason: str
    excerpt: str


class ModerationPage(BaseModel):
    items: list[ModerationRow]
    total: int


class AlertSummaryRow(BaseModel):
    tenant_id: uuid.UUID
    tenant_name: str
    open: int
    overdue: int = Field(description="超过时限还没处理的")
    handled: int
    high: int = Field(description="高风险（含已处理）")


class AuditRow(BaseModel):
    id: uuid.UUID
    created_at: datetime
    tenant_name: str | None
    actor_name: str | None
    action: str
    target_type: str | None
    target_id: str | None
    detail: dict[str, Any]


class AuditPage(BaseModel):
    items: list[AuditRow]
    total: int

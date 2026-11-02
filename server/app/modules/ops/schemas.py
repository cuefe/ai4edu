import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class TenantIn(BaseModel):
    code: str = Field(min_length=2, max_length=32, pattern=r"^[A-Za-z0-9_\-]+$")
    name: str = Field(min_length=1, max_length=100)
    kind: str = Field(pattern=r"^(school|institution)$")
    admin_name: str = Field(min_length=1, max_length=50)
    admin_phone: str = Field(min_length=11, max_length=20)
    admin_password: str | None = Field(default=None, min_length=6, max_length=64)


class TenantOut(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    kind: str
    active: bool
    created_at: datetime
    user_count: int = 0


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

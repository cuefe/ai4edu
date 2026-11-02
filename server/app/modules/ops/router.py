"""平台运营接口：只有平台运营账号可以调用（跨机构）。"""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.ai.gateway import CallContext, get_gateway
from app.ai.models import AiUsage
from app.core.db import get_db
from app.core.deps import require_roles
from app.core.errors import AppError
from app.modules.iam import service as iam
from app.modules.iam.models import Role, Tenant, User
from app.modules.ops.schemas import (
    AiCandidateOut,
    AiSkillStatusOut,
    AiTestIn,
    AiTestOut,
    AiUsageRow,
    TenantIn,
    TenantOut,
)
from app.modules.ops.service import audit

router = APIRouter(prefix="/ops", tags=["平台运营"])
PlatformAdmin = Depends(require_roles(Role.PLATFORM_ADMIN))


@router.get("/tenants", response_model=list[TenantOut])
def list_tenants(_: User = PlatformAdmin, db: Session = Depends(get_db)):
    counts = select(User.tenant_id, func.count().label("n")).group_by(User.tenant_id).subquery()
    rows = db.execute(
        select(Tenant, counts.c.n)
        .outerjoin(counts, counts.c.tenant_id == Tenant.id)
        .order_by(Tenant.created_at)
    )
    return [
        TenantOut(
            id=t.id,
            code=t.code,
            name=t.name,
            kind=t.kind,
            active=t.active,
            created_at=t.created_at,
            user_count=n or 0,
        )
        for t, n in rows
    ]


@router.post("/tenants", response_model=TenantOut, summary="开通机构，并创建机构管理员")
def create_tenant(body: TenantIn, user: User = PlatformAdmin, db: Session = Depends(get_db)):
    code = body.code.lower()
    if db.scalar(select(Tenant.id).where(Tenant.code == code)):
        raise AppError(f"机构代码 {code} 已被使用", code="tenant_code_taken", status=409)
    tenant = Tenant(code=code, name=body.name.strip(), kind=body.kind)
    db.add(tenant)
    db.flush()
    iam.create_user(
        db,
        tenant_id=tenant.id,
        name=body.admin_name,
        roles=[Role.ORG_ADMIN, Role.TEACHER],
        phone=body.admin_phone,
        password=body.admin_password,
    )
    audit(
        db,
        tenant_id=tenant.id,
        actor_id=user.id,
        action="create_tenant",
        target_type="tenant",
        target_id=tenant.id,
        code=code,
    )
    db.commit()
    return TenantOut(
        id=tenant.id,
        code=tenant.code,
        name=tenant.name,
        kind=tenant.kind,
        active=tenant.active,
        created_at=tenant.created_at,
        user_count=1,
    )


@router.get("/ai/status", response_model=list[AiSkillStatusOut], summary="各技能当前可用的模型")
def ai_status(_: User = PlatformAdmin):
    gateway = get_gateway()
    return [
        AiSkillStatusOut(
            skill=skill,
            tier=tier,
            candidates=[
                AiCandidateOut(provider=c.provider, model=c.model) for c in gateway.candidates(skill)
            ],
        )
        for skill, tier in gateway.config.skills.items()
    ]


@router.post("/ai/test", response_model=AiTestOut, summary="测试某个技能的模型调用")
async def ai_test(body: AiTestIn, user: User = PlatformAdmin):
    if body.skill not in get_gateway().config.skills:
        raise AppError(f"未登记的技能：{body.skill}")
    result = await get_gateway().chat(
        body.skill, [{"role": "user", "content": body.prompt}], ctx=CallContext(user_id=user.id)
    )
    return AiTestOut(**result.__dict__)


@router.get("/ai/usage", response_model=list[AiUsageRow], summary="AI 用量汇总")
def ai_usage(days: int = Query(7, ge=1, le=90), _: User = PlatformAdmin, db: Session = Depends(get_db)):
    since = datetime.now(UTC) - timedelta(days=days)
    stmt = (
        select(
            AiUsage.tenant_id,
            Tenant.name,
            AiUsage.skill,
            AiUsage.provider,
            AiUsage.model,
            func.count(),
            func.count(case((AiUsage.ok.is_(False), 1))),
            func.coalesce(func.sum(AiUsage.prompt_tokens), 0),
            func.coalesce(func.sum(AiUsage.completion_tokens), 0),
            func.sum(AiUsage.cost_yuan),
        )
        .outerjoin(Tenant, Tenant.id == AiUsage.tenant_id)
        .where(AiUsage.created_at >= since)
        .group_by(AiUsage.tenant_id, Tenant.name, AiUsage.skill, AiUsage.provider, AiUsage.model)
        .order_by(func.count().desc())
    )
    return [
        AiUsageRow(
            tenant_id=r[0],
            tenant_name=r[1],
            skill=r[2],
            provider=r[3],
            model=r[4],
            calls=r[5],
            failures=r[6],
            prompt_tokens=r[7],
            completion_tokens=r[8],
            cost_yuan=r[9],
        )
        for r in db.execute(stmt)
    ]

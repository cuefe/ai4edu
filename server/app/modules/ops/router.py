"""平台运营接口：只有平台运营账号可以调用（跨机构）。"""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.ai.gateway import CallContext, get_gateway
from app.ai.models import AiUsage
from app.core.db import get_db
from app.core.deps import require_roles
from app.core.errors import AppError
from app.core.routing import DbRoute
from app.modules.iam import service as iam
from app.modules.iam import sms
from app.modules.iam.models import Role, Tenant, User
from app.modules.ops import service
from app.modules.ops.schemas import (
    AiCandidateOut,
    AiSkillStatusOut,
    AiTestIn,
    AiTestOut,
    AiUsageRow,
    AlertSummaryRow,
    AuditPage,
    ModerationPage,
    ModerationRow,
    PlanIn,
    PlanOut,
    TenantIn,
    TenantOut,
    TenantPatch,
    UsageSummaryOut,
)
from app.modules.ops.service import audit
from app.modules.safety import service as safety

router = APIRouter(route_class=DbRoute, prefix="/ops", tags=["平台运营"])
PlatformAdmin = Depends(require_roles(Role.PLATFORM_ADMIN))


# —— 机构 ——


@router.get("/tenants", response_model=list[TenantOut])
def list_tenants(_: User = PlatformAdmin, db: Session = Depends(get_db)):
    return service.list_tenants(db)


@router.post("/tenants", response_model=TenantOut, summary="开通机构，并创建机构管理员")
def create_tenant(body: TenantIn, user: User = PlatformAdmin, db: Session = Depends(get_db)):
    code = body.code.lower()
    sms.require_password_if_disabled(body.admin_password)
    if db.scalar(select(Tenant.id).where(Tenant.code == code)):
        raise AppError(f"机构代码 {code} 已被使用", code="tenant_code_taken", status=409)
    tenant = Tenant(code=code, name=body.name.strip(), kind=body.kind)
    db.add(tenant)
    db.flush()
    terms = service.apply_terms(db, tenant, body, body.model_fields_set)
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
        **terms,
    )
    db.commit()
    return service.list_tenants(db, [tenant.id])[0]


@router.patch(
    "/tenants/{tenant_id}", response_model=TenantOut, summary="修改机构：套餐、名额、额度、到期、停用"
)
def update_tenant(
    tenant_id: uuid.UUID, body: TenantPatch, user: User = PlatformAdmin, db: Session = Depends(get_db)
):
    tenant = service.get_tenant(db, tenant_id)
    changes = service.update_tenant(db, tenant, body)
    if changes:
        audit(
            db,
            tenant_id=tenant.id,
            actor_id=user.id,
            action="update_tenant",
            target_type="tenant",
            target_id=tenant.id,
            **changes,
        )
    db.commit()
    return service.list_tenants(db, [tenant.id])[0]


# —— 套餐 ——


@router.get("/plans", response_model=list[PlanOut])
def list_plans(_: User = PlatformAdmin, db: Session = Depends(get_db)):
    return service.list_plans(db)


@router.post("/plans", response_model=PlanOut, summary="新建套餐")
def create_plan(body: PlanIn, user: User = PlatformAdmin, db: Session = Depends(get_db)):
    plan = service.save_plan(db, body)
    audit(db, tenant_id=None, actor_id=user.id, action="create_plan", target_type="plan", target_id=plan.id)
    db.commit()
    return service.plan_out(plan)


@router.put(
    "/plans/{plan_id}",
    response_model=PlanOut,
    summary="修改套餐",
    description="只影响之后开通、续费的机构，已开通机构的名额和额度不变",
)
def update_plan(plan_id: uuid.UUID, body: PlanIn, user: User = PlatformAdmin, db: Session = Depends(get_db)):
    plan = service.save_plan(db, body, service.get_plan(db, plan_id))
    audit(db, tenant_id=None, actor_id=user.id, action="update_plan", target_type="plan", target_id=plan.id)
    db.commit()
    return next(p for p in service.list_plans(db) if p.id == plan.id)


# —— AI 模型和用量 ——


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


@router.get("/ai/usage", response_model=list[AiUsageRow], summary="AI 用量明细（按机构、技能、模型）")
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


@router.get("/usage/summary", response_model=UsageSummaryOut, summary="AI 用量汇总：合计、按机构、按天")
def usage_summary(days: int = Query(30, ge=1, le=90), _: User = PlatformAdmin, db: Session = Depends(get_db)):
    return service.usage_summary(db, days)


# —— 内容安全 ——


@router.get("/moderation", response_model=ModerationPage, summary="内容安全记录（被拦下的消息和危机信号）")
def moderation(
    tenant_id: uuid.UUID | None = None,
    category: str | None = Query(None, pattern="^(study|chat|unsafe)$"),
    crisis_only: bool = False,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _: User = PlatformAdmin,
    db: Session = Depends(get_db),
):
    rows, total = safety.moderation_page(
        db, tenant_id=tenant_id, category=category, crisis_only=crisis_only, page=page, page_size=page_size
    )
    return ModerationPage(
        items=[
            ModerationRow(
                id=log.id,
                created_at=log.created_at,
                tenant_name=name,
                source=log.source,
                category=log.category,
                crisis=log.crisis,
                reason=log.reason,
                excerpt=log.excerpt,
            )
            for log, name in rows
        ],
        total=total,
    )


@router.get("/alerts/summary", response_model=list[AlertSummaryRow], summary="各机构危机预警的处理情况")
def alerts_summary(_: User = PlatformAdmin, db: Session = Depends(get_db)):
    return [
        AlertSummaryRow(tenant_id=tid, tenant_name=name, open=o, overdue=od, handled=h, high=hi)
        for tid, name, o, od, h, hi in safety.alert_summary(db)
    ]


# —— 审计 ——


@router.get("/audit", response_model=AuditPage, summary="审计日志")
def audit_log(
    tenant_id: uuid.UUID | None = None,
    action: str | None = Query(None, max_length=50),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _: User = PlatformAdmin,
    db: Session = Depends(get_db),
):
    return service.audit_page(db, tenant_id=tenant_id, action=action, page=page, page_size=page_size)

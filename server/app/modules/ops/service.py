"""平台运营：机构开通和额度、套餐、AI 用量汇总、审计日志。调用方是平台运营账号（跨机构会话）。"""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import any_, case, func, or_, select
from sqlalchemy.orm import Session

from app.ai.models import AiUsage
from app.core.errors import AppError, NotFound
from app.modules.iam.models import Role, Tenant, User
from app.modules.ops import quota
from app.modules.ops.models import AuditLog, Plan
from app.modules.ops.schemas import (
    AuditPage,
    AuditRow,
    DailyUsageRow,
    PlanIn,
    PlanOut,
    TenantOut,
    TenantPatch,
    TenantTerms,
    TenantUsageRow,
    UsageSummaryOut,
    UsageTotals,
)


def audit(
    db: Session,
    *,
    tenant_id: uuid.UUID | None,
    actor_id: uuid.UUID | None,
    action: str,
    target_type: str | None = None,
    target_id: uuid.UUID | str | None = None,
    **detail: Any,
) -> None:
    db.add(
        AuditLog(
            tenant_id=tenant_id,
            actor_id=actor_id,
            action=action,
            target_type=target_type,
            target_id=str(target_id) if target_id else None,
            detail=detail,
        )
    )


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal | datetime | uuid.UUID):
        return str(value)
    return value


# —— 套餐 ——


def list_plans(db: Session) -> list[PlanOut]:
    counts = dict(
        db.execute(
            select(Tenant.plan_id, func.count()).where(Tenant.plan_id.is_not(None)).group_by(Tenant.plan_id)
        ).all()
    )
    plans = db.scalars(select(Plan).order_by(Plan.active.desc(), Plan.created_at))
    return [plan_out(p, counts.get(p.id, 0)) for p in plans]


def plan_out(p: Plan, tenant_count: int = 0) -> PlanOut:
    return PlanOut(
        id=p.id,
        name=p.name,
        student_quota=p.student_quota,
        teacher_quota=p.teacher_quota,
        ai_budget_yuan=p.ai_budget_yuan,
        months=p.months,
        note=p.note,
        active=p.active,
        tenant_count=tenant_count,
    )


def save_plan(db: Session, body: PlanIn, plan: Plan | None = None) -> Plan:
    name = body.name.strip()
    taken = db.scalar(select(Plan.id).where(Plan.name == name))
    if taken and (plan is None or taken != plan.id):
        raise AppError(f"套餐“{name}”已存在", code="plan_exists", status=409)
    if plan is None:
        plan = Plan()
        db.add(plan)
    for field, value in body.model_dump().items():
        setattr(plan, field, value)
    plan.name = name
    db.flush()
    return plan


def get_plan(db: Session, plan_id: uuid.UUID) -> Plan:
    plan = db.get(Plan, plan_id)
    if plan is None:
        raise NotFound("套餐不存在")
    return plan


# —— 机构 ——


def _seat_counts(db: Session, role: Role) -> dict[uuid.UUID, int]:
    is_student = str(Role.STUDENT) == any_(User.roles)
    stmt = select(User.tenant_id, func.count()).where(User.active.is_(True), User.tenant_id.is_not(None))
    if role == Role.STUDENT:
        stmt = stmt.where(is_student)
    else:
        stmt = stmt.where(
            or_(str(Role.TEACHER) == any_(User.roles), str(Role.ORG_ADMIN) == any_(User.roles)), ~is_student
        )
    return dict(db.execute(stmt.group_by(User.tenant_id)).all())


def list_tenants(db: Session, ids: list[uuid.UUID] | None = None) -> list[TenantOut]:
    students = _seat_counts(db, Role.STUDENT)
    teachers = _seat_counts(db, Role.TEACHER)
    spend = dict(
        db.execute(
            select(AiUsage.tenant_id, func.coalesce(func.sum(AiUsage.cost_yuan), 0))
            .where(AiUsage.tenant_id.is_not(None), AiUsage.created_at >= quota.month_start())
            .group_by(AiUsage.tenant_id)
        ).all()
    )
    stmt = select(Tenant, Plan.name).outerjoin(Plan, Plan.id == Tenant.plan_id).order_by(Tenant.created_at)
    if ids is not None:
        stmt = stmt.where(Tenant.id.in_(ids))
    return [
        TenantOut(
            id=t.id,
            code=t.code,
            name=t.name,
            kind=t.kind,
            active=t.active,
            created_at=t.created_at,
            plan_id=t.plan_id,
            plan_name=plan_name,
            expires_at=t.expires_at,
            student_quota=t.student_quota,
            teacher_quota=t.teacher_quota,
            ai_budget_yuan=t.ai_budget_yuan,
            note=t.note,
            students=students.get(t.id, 0),
            teachers=teachers.get(t.id, 0),
            ai_spend_yuan=Decimal(spend.get(t.id, 0)),
        )
        for t, plan_name in db.execute(stmt)
    ]


def get_tenant(db: Session, tenant_id: uuid.UUID) -> Tenant:
    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        raise NotFound("机构不存在")
    return tenant


def apply_terms(db: Session, tenant: Tenant, body: TenantTerms, fields: set[str]) -> dict[str, Any]:
    """按传了的字段更新套餐和额度，返回改动（审计用）。"""
    if "plan_id" in fields and body.plan_id:
        get_plan(db, body.plan_id)
    changes: dict[str, Any] = {}
    for field in ("plan_id", "expires_at", "student_quota", "teacher_quota", "ai_budget_yuan", "note"):
        value = getattr(body, field)
        if field == "note":
            value = (value or "").strip()
        if field in fields and getattr(tenant, field) != value:
            setattr(tenant, field, value)
            changes[field] = _jsonable(value)
    if "ai_budget_yuan" in changes:
        quota.forget_ai_budget(tenant.id)
    return changes


def update_tenant(db: Session, tenant: Tenant, body: TenantPatch) -> dict[str, Any]:
    fields = body.model_fields_set
    changes = apply_terms(db, tenant, body, fields)
    if body.name is not None and body.name.strip() != tenant.name:
        tenant.name = changes["name"] = body.name.strip()
    if body.active is not None and body.active != tenant.active:
        tenant.active = changes["active"] = body.active
    db.flush()
    return changes


# —— AI 用量 ——


def usage_by_skill(db: Session, tenant_id: uuid.UUID, since: datetime) -> list[tuple[str, int, Decimal]]:
    rows = db.execute(
        select(AiUsage.skill, func.count(), func.coalesce(func.sum(AiUsage.cost_yuan), 0))
        .where(AiUsage.tenant_id == tenant_id, AiUsage.created_at >= since)
        .group_by(AiUsage.skill)
        .order_by(func.count().desc())
    )
    return [(skill, calls, Decimal(cost)) for skill, calls, cost in rows]


def usage_summary(db: Session, days: int) -> UsageSummaryOut:
    since = datetime.now(UTC) - timedelta(days=days)
    measures = (
        func.count(),
        func.count(case((AiUsage.ok.is_(False), 1))),
        func.coalesce(func.sum(AiUsage.prompt_tokens), 0),
        func.coalesce(func.sum(AiUsage.completion_tokens), 0),
        func.coalesce(func.sum(AiUsage.cost_yuan), 0),
    )
    by_tenant = [
        TenantUsageRow(
            tenant_id=tid,
            tenant_name=name,
            calls=calls,
            failures=failures,
            prompt_tokens=pt,
            completion_tokens=ct,
            cost_yuan=Decimal(cost),
        )
        for tid, name, calls, failures, pt, ct, cost in db.execute(
            select(AiUsage.tenant_id, Tenant.name, *measures)
            .outerjoin(Tenant, Tenant.id == AiUsage.tenant_id)
            .where(AiUsage.created_at >= since)
            .group_by(AiUsage.tenant_id, Tenant.name)
            .order_by(func.sum(AiUsage.cost_yuan).desc().nulls_last())
        )
    ]
    total = UsageTotals(
        calls=sum(r.calls for r in by_tenant),
        failures=sum(r.failures for r in by_tenant),
        prompt_tokens=sum(r.prompt_tokens for r in by_tenant),
        completion_tokens=sum(r.completion_tokens for r in by_tenant),
        cost_yuan=sum((r.cost_yuan for r in by_tenant), Decimal(0)),
    )
    day = quota.local_date(AiUsage.created_at)
    daily = [
        DailyUsageRow(day=d, calls=calls, cost_yuan=Decimal(cost))
        for d, calls, cost in db.execute(
            select(day, func.count(), func.coalesce(func.sum(AiUsage.cost_yuan), 0))
            .where(AiUsage.created_at >= since)
            .group_by(day)
            .order_by(day)
        )
    ]
    return UsageSummaryOut(total=total, by_tenant=by_tenant, daily=daily)


# —— 审计日志 ——


def audit_page(
    db: Session,
    *,
    tenant_id: uuid.UUID | None,
    action: str | None,
    page: int,
    page_size: int,
) -> AuditPage:
    stmt = select(AuditLog)
    if tenant_id:
        stmt = stmt.where(AuditLog.tenant_id == tenant_id)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = list(
        db.scalars(stmt.order_by(AuditLog.created_at.desc()).offset((page - 1) * page_size).limit(page_size))
    )
    users = {r.actor_id for r in rows if r.actor_id}
    tenants = {r.tenant_id for r in rows if r.tenant_id}
    user_names = dict(db.execute(select(User.id, User.name).where(User.id.in_(users))).all())
    tenant_names = dict(db.execute(select(Tenant.id, Tenant.name).where(Tenant.id.in_(tenants))).all())
    return AuditPage(
        items=[
            AuditRow(
                id=r.id,
                created_at=r.created_at,
                tenant_name=tenant_names.get(r.tenant_id) if r.tenant_id else None,
                actor_name=user_names.get(r.actor_id) if r.actor_id else None,
                action=r.action,
                target_type=r.target_type,
                target_id=r.target_id,
                detail=r.detail,
            )
            for r in rows
        ],
        total=total,
    )

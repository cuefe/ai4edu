"""内容安全和危机预警。

危机预警流程：学生端立即显示安抚话术和求助电话（对话不中断）→ 生成工单 → 站内信通知学生所在班级的
任课老师和机构管理员，高风险同时发短信 → 老师确认处理并填写记录。家长通知等家长端（P1）上线后再接。
"""

import uuid
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.skills.safety import SafetyResult
from app.core.config import get_settings
from app.core.errors import Forbidden, NotFound
from app.modules.iam.models import Role, User
from app.modules.notify.service import notify
from app.modules.org import service as org
from app.modules.org.models import MemberRole
from app.modules.safety.models import AlertStatus, CrisisAlert, ModerationLog


class AlertOut(BaseModel):
    id: uuid.UUID
    student_id: uuid.UUID
    student_name: str
    class_names: list[str]
    level: str
    excerpt: str
    reason: str
    status: str
    overdue: bool
    session_id: uuid.UUID | None
    handled_by_name: str | None
    handled_at: datetime | None
    note: str
    created_at: datetime


def log_moderation(
    db: Session, tenant_id: uuid.UUID, user_id: uuid.UUID, source: str, result: SafetyResult, text: str
) -> None:
    db.add(
        ModerationLog(
            tenant_id=tenant_id,
            user_id=user_id,
            source=source,
            category=result.category,
            crisis=result.crisis,
            reason=result.reason,
            excerpt=text[:500],
        )
    )


def raise_alert(
    db: Session,
    tenant_id: uuid.UUID,
    student: User,
    session_id: uuid.UUID | None,
    result: SafetyResult,
    text: str,
) -> CrisisAlert:
    alert = CrisisAlert(
        tenant_id=tenant_id,
        student_id=student.id,
        session_id=session_id,
        level=result.crisis,
        excerpt=text[:1000],
        reason=result.reason,
    )
    db.add(alert)
    db.flush()
    recipients = [*org.teachers_of_student(db, tenant_id, student.id), *org.org_admins(db, tenant_id)]
    level = "高风险" if result.crisis == "high" else "需要关注"
    notify(
        db,
        tenant_id,
        recipients,
        kind="crisis",
        title=f"【心理预警·{level}】学生 {student.name} 需要关心，请尽快登录处理",
        body="学生在问一问里流露出需要关注的情绪。请尽快了解情况，并在“心理预警”里填写处理记录。",
        link="/alerts",
        sms=result.crisis == "high",
    )
    return alert


def _scope(db: Session, user: User) -> list[uuid.UUID] | None:
    """老师看自己班学生的预警；机构管理员看全部（返回 None）。"""
    assert user.tenant_id is not None
    if user.has_role(Role.ORG_ADMIN):
        return None
    class_ids = org.class_ids_of(db, user.tenant_id, user.id, MemberRole.TEACHER)
    return [sid for sid, _ in org.students_in_classes(db, user.tenant_id, class_ids)]


def list_alerts(db: Session, user: User, status: str | None = None) -> list[AlertOut]:
    assert user.tenant_id is not None
    tenant_id = user.tenant_id
    stmt = (
        select(CrisisAlert).where(CrisisAlert.tenant_id == tenant_id).order_by(CrisisAlert.created_at.desc())
    )
    students = _scope(db, user)
    if students is not None:
        stmt = stmt.where(CrisisAlert.student_id.in_(students))
    if status:
        stmt = stmt.where(CrisisAlert.status == status)
    alerts = list(db.scalars(stmt.limit(200)))
    ids = {a.student_id for a in alerts} | {a.handled_by for a in alerts if a.handled_by}
    names = {uid: name for uid, name in db.execute(select(User.id, User.name).where(User.id.in_(ids)))}
    deadline = datetime.now(UTC) - timedelta(hours=get_settings().crisis_escalate_hours)
    out = []
    for a in alerts:
        class_ids = org.class_ids_of(db, tenant_id, a.student_id, MemberRole.STUDENT)
        out.append(
            AlertOut(
                id=a.id,
                student_id=a.student_id,
                student_name=names.get(a.student_id, ""),
                class_names=list(org.class_names(db, tenant_id, class_ids).values()),
                level=a.level,
                excerpt=a.excerpt,
                reason=a.reason,
                status=a.status,
                overdue=a.status == AlertStatus.OPEN and a.created_at < deadline,
                session_id=a.session_id,
                handled_by_name=names.get(a.handled_by) if a.handled_by else None,
                handled_at=a.handled_at,
                note=a.note,
                created_at=a.created_at,
            )
        )
    return out


def get_alert(db: Session, user: User, alert_id: uuid.UUID) -> CrisisAlert:
    alert = db.scalar(
        select(CrisisAlert).where(CrisisAlert.id == alert_id, CrisisAlert.tenant_id == user.tenant_id)
    )
    if alert is None:
        raise NotFound("预警不存在")
    students = _scope(db, user)
    if students is not None and alert.student_id not in students:
        raise Forbidden("只能处理自己班学生的预警")
    return alert


def handle(alert: CrisisAlert, user: User, note: str) -> None:
    alert.status = AlertStatus.HANDLED
    alert.handled_by = user.id
    alert.handled_at = datetime.now(UTC)
    alert.note = note

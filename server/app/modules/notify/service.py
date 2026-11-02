"""站内信。其他模块通过 notify() 发消息；紧急的（危机预警）同时发短信。"""

import logging
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime

from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.security import decrypt_phone
from app.modules.iam.models import User
from app.modules.iam.sms import get_sms_sender
from app.modules.notify.models import Notification

log = logging.getLogger(__name__)

MAX_LIST = 50


class NotificationOut(BaseModel):
    id: uuid.UUID
    kind: str
    title: str
    body: str
    link: str | None
    read: bool
    created_at: datetime


class NotificationList(BaseModel):
    items: list[NotificationOut]
    unread: int


def notify(
    db: Session,
    tenant_id: uuid.UUID,
    user_ids: Iterable[uuid.UUID],
    *,
    kind: str,
    title: str,
    body: str = "",
    link: str | None = None,
    sms: bool = False,
) -> int:
    """给一批用户发站内信，返回发了几条。sms=True 时有手机号的用户同时收到短信（只发标题，不含具体内容）。"""
    ids = list(dict.fromkeys(user_ids))
    db.add_all(
        Notification(tenant_id=tenant_id, user_id=uid, kind=kind, title=title[:200], body=body, link=link)
        for uid in ids
    )
    if sms and ids:
        sender = get_sms_sender()
        for phone_enc in db.scalars(
            select(User.phone_enc).where(User.id.in_(ids), User.phone_enc.is_not(None))
        ):
            try:
                sender.send_notice(decrypt_phone(phone_enc), title)
            except Exception:  # 短信失败不影响站内信
                log.exception("通知短信发送失败")
    return len(ids)


def list_for(db: Session, tenant_id: uuid.UUID, user_id: uuid.UUID) -> NotificationList:
    mine = (Notification.tenant_id == tenant_id, Notification.user_id == user_id)
    rows = db.scalars(
        select(Notification).where(*mine).order_by(Notification.created_at.desc()).limit(MAX_LIST)
    )
    unread = db.scalar(
        select(func.count()).select_from(Notification).where(*mine, Notification.read_at.is_(None))
    )
    return NotificationList(
        items=[
            NotificationOut(
                id=n.id,
                kind=n.kind,
                title=n.title,
                body=n.body,
                link=n.link,
                read=n.read_at is not None,
                created_at=n.created_at,
            )
            for n in rows
        ],
        unread=unread or 0,
    )


def mark_read(db: Session, tenant_id: uuid.UUID, user_id: uuid.UUID, ids: list[uuid.UUID] | None) -> None:
    """ids 为空表示全部已读。"""
    stmt = update(Notification).where(
        Notification.tenant_id == tenant_id, Notification.user_id == user_id, Notification.read_at.is_(None)
    )
    if ids:
        stmt = stmt.where(Notification.id.in_(ids))
    db.execute(stmt.values(read_at=datetime.now(UTC)))

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.modules.ops.models import AuditLog


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

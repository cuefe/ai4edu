"""汇总导入所有模型，供 Alembic 和测试使用。"""

from app.ai.models import AiUsage
from app.core.db import Base
from app.modules.content.models import Document
from app.modules.iam.models import Tenant, User
from app.modules.ops.models import AuditLog
from app.modules.org.models import Campus, ClassMember, Klass

__all__ = ["AiUsage", "AuditLog", "Base", "Campus", "ClassMember", "Document", "Klass", "Tenant", "User"]

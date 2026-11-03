"""汇总导入所有模型，供 Alembic 和测试使用。"""

from app.ai.models import AiUsage
from app.core.db import Base
from app.modules.assignment.models import Answer, Assignment, AssignmentItem, Submission
from app.modules.content.models import Document
from app.modules.iam.models import Tenant, User
from app.modules.learning.models import ReviewLog, ReviewState, WrongItem
from app.modules.library.models import Resource, ResourceChunk
from app.modules.notify.models import Notification
from app.modules.ops.models import AuditLog, Plan
from app.modules.org.models import Campus, ClassMember, Klass
from app.modules.qbank.models import Question, QuestionBatch, QuestionCheck
from app.modules.recite.models import ReciteCard, ReciteDeck
from app.modules.safety.models import CrisisAlert, ModerationLog
from app.modules.tutor.models import ChatMessage, ChatSession

__all__ = [
    "AiUsage",
    "Answer",
    "Assignment",
    "AssignmentItem",
    "AuditLog",
    "Base",
    "Campus",
    "ChatMessage",
    "ChatSession",
    "ClassMember",
    "CrisisAlert",
    "Document",
    "Klass",
    "ModerationLog",
    "Notification",
    "Plan",
    "Question",
    "QuestionBatch",
    "QuestionCheck",
    "ReciteCard",
    "ReciteDeck",
    "Resource",
    "ResourceChunk",
    "ReviewLog",
    "ReviewState",
    "Submission",
    "Tenant",
    "User",
    "WrongItem",
]

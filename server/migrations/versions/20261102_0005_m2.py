"""M2 学生闭环；开启行级安全

- 作业：assignment、assignment_item、submission、answer
- 错题和背诵复习：wrong_item、review_state、review_log
- 问一问：chat_session、chat_message
- 内容安全和危机预警：moderation_log、crisis_alert
- 站内信：notification

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-03 01:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.rls import disable_tenant_rls, enable_tenant_rls, grant_app_role

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = [
    "assignment",
    "assignment_item",
    "submission",
    "answer",
    "wrong_item",
    "review_state",
    "review_log",
    "chat_session",
    "chat_message",
    "moderation_log",
    "crisis_alert",
    "notification",
]


def upgrade() -> None:
    op.create_table(
        "assignment",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("subject", sa.String(length=20), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("class_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("publish_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("answer_release", sa.String(length=10), nullable=False),
        sa.Column("allow_ai", sa.Boolean(), nullable=False),
        sa.Column("total_score", sa.Float(), nullable=False),
        sa.Column("student_count", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["user_account.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_assignment_owner", "assignment", ["tenant_id", "owner_id", "created_at"], unique=False
    )
    op.create_index(op.f("ix_assignment_tenant_id"), "assignment", ["tenant_id"], unique=False)
    op.create_table(
        "chat_session",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("mode", sa.String(length=12), nullable=False),
        sa.Column("subject", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=100), nullable=False),
        sa.Column("context", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["student_id"], ["user_account.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_chat_session_student", "chat_session", ["tenant_id", "student_id", "updated_at"], unique=False
    )
    op.create_index(op.f("ix_chat_session_tenant_id"), "chat_session", ["tenant_id"], unique=False)
    op.create_table(
        "crisis_alert",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=True),
        sa.Column("level", sa.String(length=10), nullable=False),
        sa.Column("excerpt", sa.Text(), nullable=False),
        sa.Column("reason", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("handled_by", sa.Uuid(), nullable=True),
        sa.Column("handled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["handled_by"], ["user_account.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["student_id"], ["user_account.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_crisis_alert_status", "crisis_alert", ["tenant_id", "status", "created_at"], unique=False
    )
    op.create_index(op.f("ix_crisis_alert_tenant_id"), "crisis_alert", ["tenant_id"], unique=False)
    op.create_table(
        "moderation_log",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("category", sa.String(length=10), nullable=False),
        sa.Column("crisis", sa.String(length=10), nullable=False),
        sa.Column("reason", sa.String(length=200), nullable=False),
        sa.Column("excerpt", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user_account.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_moderation_log_tenant_id"), "moderation_log", ["tenant_id"], unique=False)
    op.create_index("ix_moderation_tenant_time", "moderation_log", ["tenant_id", "created_at"], unique=False)
    op.create_table(
        "notification",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("link", sa.String(length=300), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user_account.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_notification_tenant_id"), "notification", ["tenant_id"], unique=False)
    op.create_index(
        "ix_notification_user", "notification", ["tenant_id", "user_id", "created_at"], unique=False
    )
    op.create_table(
        "assignment_item",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("assignment_id", sa.Uuid(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("item_type", sa.String(length=12), nullable=False),
        sa.Column("ref_id", sa.Uuid(), nullable=True),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("content", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["assignment_id"], ["assignment.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_assignment_item_assignment_id"), "assignment_item", ["assignment_id"], unique=False
    )
    op.create_index(op.f("ix_assignment_item_tenant_id"), "assignment_item", ["tenant_id"], unique=False)
    op.create_table(
        "chat_message",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=10), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("images", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("style", sa.String(length=12), nullable=True),
        sa.Column("flag", sa.String(length=10), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["chat_session.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_chat_message_session_id"), "chat_message", ["session_id"], unique=False)
    op.create_index(op.f("ix_chat_message_tenant_id"), "chat_message", ["tenant_id"], unique=False)
    op.create_table(
        "submission",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("assignment_id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("klass_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("pending_count", sa.Integer(), nullable=False),
        sa.Column("progress", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["assignment_id"], ["assignment.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["klass_id"], ["klass.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["student_id"], ["user_account.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("assignment_id", "student_id"),
    )
    op.create_index(op.f("ix_submission_assignment_id"), "submission", ["assignment_id"], unique=False)
    op.create_index("ix_submission_student", "submission", ["tenant_id", "student_id"], unique=False)
    op.create_index(op.f("ix_submission_tenant_id"), "submission", ["tenant_id"], unique=False)
    op.create_table(
        "answer",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("submission_id", sa.Uuid(), nullable=False),
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("response", sa.Text(), nullable=False),
        sa.Column("images", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("correct", sa.Boolean(), nullable=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("ai_score", sa.Float(), nullable=True),
        sa.Column("ai_confidence", sa.Float(), nullable=True),
        sa.Column("ai_comment", sa.Text(), nullable=False),
        sa.Column("ai_points", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("teacher_comment", sa.Text(), nullable=False),
        sa.Column("graded_by", sa.Uuid(), nullable=True),
        sa.Column("graded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["graded_by"], ["user_account.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["item_id"], ["assignment_item.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["student_id"], ["user_account.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["submission_id"], ["submission.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("submission_id", "item_id"),
    )
    op.create_index(op.f("ix_answer_item_id"), "answer", ["item_id"], unique=False)
    op.create_index(op.f("ix_answer_submission_id"), "answer", ["submission_id"], unique=False)
    op.create_index(op.f("ix_answer_tenant_id"), "answer", ["tenant_id"], unique=False)
    op.create_table(
        "review_state",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("card_key", sa.Integer(), nullable=False),
        sa.Column("card", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("due", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reps", sa.Integer(), nullable=False),
        sa.Column("lapses", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["item_id"], ["assignment_item.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["student_id"], ["user_account.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("student_id", "item_id", "card_key"),
    )
    op.create_index("ix_review_due", "review_state", ["tenant_id", "student_id", "due"], unique=False)
    op.create_index(op.f("ix_review_state_tenant_id"), "review_state", ["tenant_id"], unique=False)
    op.create_table(
        "wrong_item",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("item_id", sa.Uuid(), nullable=True),
        sa.Column("assignment_title", sa.String(length=200), nullable=False),
        sa.Column("subject", sa.String(length=20), nullable=False),
        sa.Column("question", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("wrong_response", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("wrong_count", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("corrected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("guide", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["item_id"], ["assignment_item.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["student_id"], ["user_account.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("student_id", "item_id"),
    )
    op.create_index(
        "ix_wrong_item_student", "wrong_item", ["tenant_id", "student_id", "status"], unique=False
    )
    op.create_index(op.f("ix_wrong_item_tenant_id"), "wrong_item", ["tenant_id"], unique=False)
    op.create_table(
        "review_log",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("state_id", sa.Uuid(), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["state_id"], ["review_state.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenant.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_review_log_state_id"), "review_log", ["state_id"], unique=False)
    op.create_index(op.f("ix_review_log_tenant_id"), "review_log", ["tenant_id"], unique=False)
    for table in TABLES:
        enable_tenant_rls(table)
    grant_app_role()


def downgrade() -> None:
    for table in TABLES:
        disable_tenant_rls(table)
    op.drop_index(op.f("ix_review_log_tenant_id"), table_name="review_log")
    op.drop_index(op.f("ix_review_log_state_id"), table_name="review_log")
    op.drop_table("review_log")
    op.drop_index(op.f("ix_wrong_item_tenant_id"), table_name="wrong_item")
    op.drop_index("ix_wrong_item_student", table_name="wrong_item")
    op.drop_table("wrong_item")
    op.drop_index(op.f("ix_review_state_tenant_id"), table_name="review_state")
    op.drop_index("ix_review_due", table_name="review_state")
    op.drop_table("review_state")
    op.drop_index(op.f("ix_answer_tenant_id"), table_name="answer")
    op.drop_index(op.f("ix_answer_submission_id"), table_name="answer")
    op.drop_index(op.f("ix_answer_item_id"), table_name="answer")
    op.drop_table("answer")
    op.drop_index(op.f("ix_submission_tenant_id"), table_name="submission")
    op.drop_index("ix_submission_student", table_name="submission")
    op.drop_index(op.f("ix_submission_assignment_id"), table_name="submission")
    op.drop_table("submission")
    op.drop_index(op.f("ix_chat_message_tenant_id"), table_name="chat_message")
    op.drop_index(op.f("ix_chat_message_session_id"), table_name="chat_message")
    op.drop_table("chat_message")
    op.drop_index(op.f("ix_assignment_item_tenant_id"), table_name="assignment_item")
    op.drop_index(op.f("ix_assignment_item_assignment_id"), table_name="assignment_item")
    op.drop_table("assignment_item")
    op.drop_index("ix_notification_user", table_name="notification")
    op.drop_index(op.f("ix_notification_tenant_id"), table_name="notification")
    op.drop_table("notification")
    op.drop_index("ix_moderation_tenant_time", table_name="moderation_log")
    op.drop_index(op.f("ix_moderation_log_tenant_id"), table_name="moderation_log")
    op.drop_table("moderation_log")
    op.drop_index(op.f("ix_crisis_alert_tenant_id"), table_name="crisis_alert")
    op.drop_index("ix_crisis_alert_status", table_name="crisis_alert")
    op.drop_table("crisis_alert")
    op.drop_index(op.f("ix_chat_session_tenant_id"), table_name="chat_session")
    op.drop_index("ix_chat_session_student", table_name="chat_session")
    op.drop_table("chat_session")
    op.drop_index(op.f("ix_assignment_tenant_id"), table_name="assignment")
    op.drop_index("ix_assignment_owner", table_name="assignment")
    op.drop_table("assignment")

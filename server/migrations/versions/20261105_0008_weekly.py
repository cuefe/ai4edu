"""每周个性化试卷：平台题库、教学进度、周测、知识点得分记录

- pool_question、pool_question_kp：平台公共内容，不带 tenant_id
- class_progress、weekly_paper、kp_evidence：带 tenant_id，开启行级安全
- assignment.kind：区分老师布置的作业和系统组的周测

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-05 09:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.rls import disable_tenant_rls, enable_tenant_rls, grant_app_role

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_TABLES = ["class_progress", "weekly_paper", "kp_evidence"]


def _created_at() -> sa.Column:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def _updated_at() -> sa.Column:
    return sa.Column(
        "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def upgrade() -> None:
    op.add_column(
        "assignment", sa.Column("kind", sa.String(length=10), server_default="normal", nullable=False)
    )
    op.create_table(
        "pool_question",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("book_id", sa.Uuid(), nullable=False),
        sa.Column("section_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=40), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("qtype", sa.String(length=10), nullable=False),
        sa.Column("difficulty", sa.String(length=10), nullable=False),
        sa.Column("stem", sa.Text(), nullable=False),
        sa.Column("options", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("analysis", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=12), nullable=False),
        sa.Column("source_ref", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("check_result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("warnings", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("edited", sa.Boolean(), nullable=False),
        sa.Column("reviewed_by", sa.Uuid(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        _updated_at(),
        _created_at(),
        sa.ForeignKeyConstraint(["book_id"], ["textbook.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["section_id"], ["chapter.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reviewed_by"], ["user_account.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("book_id", "key"),
    )
    op.create_index("ix_pool_question_book_id", "pool_question", ["book_id"])
    op.create_index("ix_pool_question_section", "pool_question", ["section_id", "status"])
    op.create_table(
        "pool_question_kp",
        sa.Column("question_id", sa.Uuid(), nullable=False),
        sa.Column("kp_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["question_id"], ["pool_question.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["kp_id"], ["knowledge_point.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("question_id", "kp_id"),
    )
    op.create_index("ix_pool_question_kp_kp_id", "pool_question_kp", ["kp_id"])
    op.create_table(
        "class_progress",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("klass_id", sa.Uuid(), nullable=False),
        sa.Column("subject", sa.String(length=20), nullable=False),
        sa.Column("book_id", sa.Uuid(), nullable=False),
        sa.Column("teacher_id", sa.Uuid(), nullable=False),
        sa.Column("section_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        _updated_at(),
        _created_at(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
        sa.ForeignKeyConstraint(["klass_id"], ["klass.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["book_id"], ["textbook.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["teacher_id"], ["user_account.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("klass_id", "subject"),
    )
    op.create_index("ix_class_progress_tenant_id", "class_progress", ["tenant_id"])
    op.create_index("ix_class_progress_klass_id", "class_progress", ["klass_id"])
    op.create_table(
        "weekly_paper",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("klass_id", sa.Uuid(), nullable=True),
        sa.Column("subject", sa.String(length=20), nullable=False),
        sa.Column("book_id", sa.Uuid(), nullable=False),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("assignment_id", sa.Uuid(), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.Column("prev_ratio", sa.Float(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("plan", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        _created_at(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
        sa.ForeignKeyConstraint(["student_id"], ["user_account.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["klass_id"], ["klass.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["book_id"], ["textbook.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["assignment_id"], ["assignment.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("student_id", "subject", "week_start"),
    )
    op.create_index("ix_weekly_paper_tenant_id", "weekly_paper", ["tenant_id"])
    op.create_index("ix_weekly_paper_assignment_id", "weekly_paper", ["assignment_id"])
    op.create_index(
        "ix_weekly_paper_class", "weekly_paper", ["tenant_id", "klass_id", "subject", "week_start"]
    )
    op.create_table(
        "kp_evidence",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("subject", sa.String(length=20), nullable=False),
        sa.Column("kp_id", sa.Uuid(), nullable=False),
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("ratio", sa.Float(), nullable=False),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=False),
        _created_at(),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
        sa.ForeignKeyConstraint(["student_id"], ["user_account.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["kp_id"], ["knowledge_point.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["item_id"], ["assignment_item.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("student_id", "item_id", "kp_id"),
    )
    op.create_index("ix_kp_evidence_tenant_id", "kp_evidence", ["tenant_id"])
    op.create_index("ix_kp_evidence_kp_id", "kp_evidence", ["kp_id"])
    op.create_index("ix_kp_evidence_student", "kp_evidence", ["tenant_id", "student_id", "subject"])
    for table in TENANT_TABLES:
        enable_tenant_rls(table)
    grant_app_role()


def downgrade() -> None:
    for table in TENANT_TABLES:
        disable_tenant_rls(table)
    op.drop_table("kp_evidence")
    op.drop_table("weekly_paper")
    op.drop_table("class_progress")
    op.drop_table("pool_question_kp")
    op.drop_table("pool_question")
    op.drop_column("assignment", "kind")

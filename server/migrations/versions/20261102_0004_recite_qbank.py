"""recite、qbank：背诵卡片组和卡片，出题批次、题目和答案校验记录；开启行级安全

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-02 23:50:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.rls import disable_tenant_rls, enable_tenant_rls, grant_app_role

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ["recite_deck", "recite_card", "question_batch", "question", "question_check"]
JSONB = postgresql.JSONB(astext_type=sa.Text())


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "recite_deck",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("subject", sa.String(length=20), nullable=True),
        sa.Column("grade", sa.String(length=20), nullable=True),
        sa.Column("source_doc_id", sa.Uuid(), nullable=True),
        sa.Column("params", JSONB, nullable=False),
        sa.Column("generated", JSONB, nullable=False),
        sa.Column("card_count", sa.Integer(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["owner_id"], ["user_account.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_doc_id"], ["document.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_recite_deck_owner", "recite_deck", ["tenant_id", "owner_id", "updated_at"])
    op.create_index(op.f("ix_recite_deck_tenant_id"), "recite_deck", ["tenant_id"])
    op.create_table(
        "recite_card",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("deck_id", sa.Uuid(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("front", sa.Text(), nullable=False),
        sa.Column("back", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["deck_id"], ["recite_deck.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_recite_card_deck_id"), "recite_card", ["deck_id"])
    op.create_index(op.f("ix_recite_card_tenant_id"), "recite_card", ["tenant_id"])

    op.create_table(
        "question_batch",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("topic", sa.String(length=200), nullable=False),
        sa.Column("params", JSONB, nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("error", sa.String(length=500), nullable=True),
        sa.Column("warnings", JSONB, nullable=False),
        sa.Column("sources", JSONB, nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["owner_id"], ["user_account.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_question_batch_owner", "question_batch", ["tenant_id", "owner_id", "created_at"])
    op.create_index(op.f("ix_question_batch_tenant_id"), "question_batch", ["tenant_id"])
    op.create_table(
        "question",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("batch_id", sa.Uuid(), nullable=True),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("subject", sa.String(length=20), nullable=False),
        sa.Column("grade", sa.String(length=20), nullable=True),
        sa.Column("qtype", sa.String(length=10), nullable=False),
        sa.Column("difficulty", sa.String(length=10), nullable=False),
        sa.Column("stem", sa.Text(), nullable=False),
        sa.Column("options", JSONB, nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("analysis", sa.Text(), nullable=False),
        sa.Column("knowledge_points", JSONB, nullable=False),
        sa.Column("source", sa.String(length=10), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("generated", JSONB, nullable=True),
        sa.Column("edited", sa.Boolean(), nullable=False),
        sa.Column("warnings", JSONB, nullable=False),
        sa.Column("reviewed_by", sa.Uuid(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["batch_id"], ["question_batch.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["owner_id"], ["user_account.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reviewed_by"], ["user_account.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_question_bank", "question", ["tenant_id", "status", "subject"])
    op.create_index("ix_question_owner", "question", ["tenant_id", "owner_id", "status"])
    op.create_index(op.f("ix_question_batch_id"), "question", ["batch_id"])
    op.create_index(op.f("ix_question_tenant_id"), "question", ["tenant_id"])
    op.create_table(
        "question_check",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("question_id", sa.Uuid(), nullable=False),
        sa.Column("verdict", sa.String(length=12), nullable=False),
        sa.Column("method", sa.String(length=10), nullable=False),
        sa.Column("solver_model", sa.String(length=80), nullable=True),
        sa.Column("solver_answer", sa.Text(), nullable=True),
        sa.Column("solver_work", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["question_id"], ["question.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_question_check_question_id"), "question_check", ["question_id"])
    op.create_index(op.f("ix_question_check_tenant_id"), "question_check", ["tenant_id"])
    for table in TABLES:
        enable_tenant_rls(table)
    grant_app_role()


def downgrade() -> None:
    for table in TABLES:
        disable_tenant_rls(table)
    for table in reversed(TABLES):
        op.drop_table(table)  # 索引随表一起删除

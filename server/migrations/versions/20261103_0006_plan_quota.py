"""M3 套餐与额度

- plan：套餐模板（平台级，不带 tenant_id）
- tenant：套餐、到期时间、学生和老师名额、每月 AI 费用上限、运营备注
- ai_usage 按（机构，时间）建索引，用于汇总本月费用；audit_log 按时间建索引

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-03 10:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from migrations.rls import grant_app_role

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "plan",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=50), nullable=False),
        sa.Column("student_quota", sa.Integer(), nullable=True),
        sa.Column("teacher_quota", sa.Integer(), nullable=True),
        sa.Column("ai_budget_yuan", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("months", sa.Integer(), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.add_column("tenant", sa.Column("plan_id", sa.Uuid(), nullable=True))
    op.add_column("tenant", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("tenant", sa.Column("student_quota", sa.Integer(), nullable=True))
    op.add_column("tenant", sa.Column("teacher_quota", sa.Integer(), nullable=True))
    op.add_column("tenant", sa.Column("ai_budget_yuan", sa.Numeric(precision=10, scale=2), nullable=True))
    op.add_column("tenant", sa.Column("note", sa.Text(), server_default="", nullable=False))
    op.create_foreign_key("fk_tenant_plan", "tenant", "plan", ["plan_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_ai_usage_tenant_time", "ai_usage", ["tenant_id", "created_at"], unique=False)
    op.create_index("ix_audit_log_time", "audit_log", ["created_at"], unique=False)
    grant_app_role()


def downgrade() -> None:
    op.drop_index("ix_audit_log_time", table_name="audit_log")
    op.drop_index("ix_ai_usage_tenant_time", table_name="ai_usage")
    op.drop_constraint("fk_tenant_plan", "tenant", type_="foreignkey")
    for column in ("note", "ai_budget_yuan", "teacher_quota", "student_quota", "expires_at", "plan_id"):
        op.drop_column("tenant", column)
    op.drop_table("plan")

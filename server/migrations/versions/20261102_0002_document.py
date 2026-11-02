"""document：教案、讲义等可编辑文档；开启行级安全

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-02 21:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.rls import disable_tenant_rls, enable_tenant_rls, grant_app_role

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "document",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("doc_type", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("subject", sa.String(length=20), nullable=True),
        sa.Column("grade", sa.String(length=20), nullable=True),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("params", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("content", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("generated_md", sa.Text(), nullable=True),
        sa.Column("warnings", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("error", sa.String(length=500), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["user_account.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_document_owner", "document", ["tenant_id", "owner_id", "updated_at"], unique=False)
    op.create_index(op.f("ix_document_tenant_id"), "document", ["tenant_id"], unique=False)
    enable_tenant_rls("document")
    grant_app_role()


def downgrade() -> None:
    disable_tenant_rls("document")
    op.drop_index(op.f("ix_document_tenant_id"), table_name="document")
    op.drop_index("ix_document_owner", table_name="document")
    op.drop_table("document")

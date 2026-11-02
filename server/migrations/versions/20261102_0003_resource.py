"""resource：资料库文件和检索片段（pgvector 向量）；开启行级安全

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-02 23:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

from migrations.rls import disable_tenant_rls, enable_tenant_rls, grant_app_role

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ["resource_file", "resource_chunk"]


def upgrade() -> None:
    op.create_table(
        "resource_file",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("storage_key", sa.String(length=255), nullable=False),
        sa.Column("subject", sa.String(length=20), nullable=True),
        sa.Column("shared", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("error", sa.String(length=500), nullable=True),
        sa.Column("pages", sa.Integer(), nullable=False),
        sa.Column("ocr_pages", sa.Integer(), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.Column("embedding_model", sa.String(length=80), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["user_account.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_resource_owner", "resource_file", ["tenant_id", "owner_id"], unique=False)
    op.create_index(op.f("ix_resource_file_tenant_id"), "resource_file", ["tenant_id"], unique=False)
    op.create_table(
        "resource_chunk",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("heading", sa.String(length=500), nullable=False),
        sa.Column("page_start", sa.Integer(), nullable=True),
        sa.Column("page_end", sa.Integer(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(dim=1024), nullable=False),
        sa.Column("embedding_model", sa.String(length=80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["resource_id"], ["resource_file.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_resource_chunk_resource_id"), "resource_chunk", ["resource_id"], unique=False)
    op.create_index(op.f("ix_resource_chunk_tenant_id"), "resource_chunk", ["tenant_id"], unique=False)
    for table in TABLES:
        enable_tenant_rls(table)
    grant_app_role()


def downgrade() -> None:
    for table in TABLES:
        disable_tenant_rls(table)
    op.drop_index(op.f("ix_resource_chunk_tenant_id"), table_name="resource_chunk")
    op.drop_index(op.f("ix_resource_chunk_resource_id"), table_name="resource_chunk")
    op.drop_table("resource_chunk")
    op.drop_index(op.f("ix_resource_file_tenant_id"), table_name="resource_file")
    op.drop_index("ix_resource_owner", table_name="resource_file")
    op.drop_table("resource_file")

"""教材、章节、知识点、课件（平台公共内容，不带 tenant_id）

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-04 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.rls import grant_app_role

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _created_at() -> sa.Column:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def upgrade() -> None:
    op.create_table(
        "textbook",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=60), nullable=False),
        sa.Column("stage", sa.String(length=10), nullable=False),
        sa.Column("subject", sa.String(length=20), nullable=False),
        sa.Column("edition", sa.String(length=40), nullable=False),
        sa.Column("grade", sa.String(length=10), nullable=False),
        sa.Column("title", sa.String(length=60), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("provenance", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        _created_at(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key"),
    )
    op.create_table(
        "chapter",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("book_id", sa.Uuid(), nullable=False),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("no", sa.String(length=20), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("mind_map", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        _created_at(),
        sa.ForeignKeyConstraint(["book_id"], ["textbook.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["parent_id"], ["chapter.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("book_id", "no"),
    )
    op.create_index("ix_chapter_book_id", "chapter", ["book_id"])
    op.create_index("ix_chapter_parent_id", "chapter", ["parent_id"])
    op.create_table(
        "knowledge_point",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("book_id", sa.Uuid(), nullable=False),
        sa.Column("chapter_id", sa.Uuid(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("importance", sa.String(length=10), nullable=False),
        sa.Column("recite", sa.Boolean(), nullable=False),
        _created_at(),
        sa.ForeignKeyConstraint(["book_id"], ["textbook.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["chapter_id"], ["chapter.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("chapter_id", "name"),
    )
    op.create_index("ix_knowledge_point_book_id", "knowledge_point", ["book_id"])
    op.create_index("ix_knowledge_point_chapter_id", "knowledge_point", ["chapter_id"])
    op.create_table(
        "course_file",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("book_id", sa.Uuid(), nullable=False),
        sa.Column("chapter_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.String(length=12), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("filename", sa.String(length=200), nullable=False),
        sa.Column("storage_key", sa.String(length=200), nullable=False),
        sa.Column("mime", sa.String(length=100), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=200), nullable=False),
        _created_at(),
        sa.ForeignKeyConstraint(["book_id"], ["textbook.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["chapter_id"], ["chapter.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("book_id", "sha256"),
    )
    op.create_index("ix_course_file_book_id", "course_file", ["book_id"])
    op.create_index("ix_course_file_chapter_id", "course_file", ["chapter_id"])
    grant_app_role()


def downgrade() -> None:
    op.drop_table("course_file")
    op.drop_table("knowledge_point")
    op.drop_table("chapter")
    op.drop_table("textbook")

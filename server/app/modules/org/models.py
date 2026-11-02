import uuid
from enum import StrEnum

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin, new_id


class Campus(TimestampMixin, Base):
    __tablename__ = "campus"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))


class Klass(TimestampMixin, Base):
    """班级。`class` 是 Python 关键字，所以叫 Klass。"""

    __tablename__ = "klass"
    __table_args__ = (UniqueConstraint("tenant_id", "name"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.id"), index=True)
    campus_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("campus.id"))
    name: Mapped[str] = mapped_column(String(50))
    grade: Mapped[str | None] = mapped_column(String(20))  # 如：初一、高二


class MemberRole(StrEnum):
    TEACHER = "teacher"
    STUDENT = "student"


class ClassMember(TimestampMixin, Base):
    __tablename__ = "class_member"
    __table_args__ = (UniqueConstraint("klass_id", "user_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.id"), index=True)
    klass_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("klass.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user_account.id", ondelete="CASCADE"), index=True)
    member_role: Mapped[str] = mapped_column(String(10))
    subject: Mapped[str | None] = mapped_column(String(20))  # 老师在这个班教的学科

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import ARRAY, Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin, new_id


class Role(StrEnum):
    PLATFORM_ADMIN = "platform_admin"
    ORG_ADMIN = "org_admin"
    TEACHER = "teacher"
    STUDENT = "student"
    PARENT = "parent"


class Tenant(TimestampMixin, Base):
    """机构：一所学校或一家教培机构。"""

    __tablename__ = "tenant"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(String(32), unique=True)  # 学生登录时填写的机构代码
    name: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(16))  # school / institution
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class User(TimestampMixin, Base):
    """账号。老师、管理员用手机号登录；学生用 机构代码 + 学号 + 密码 登录。

    平台运营账号的 tenant_id 为空。
    """

    __tablename__ = "user_account"
    __table_args__ = (UniqueConstraint("tenant_id", "username"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tenant.id"), index=True)
    name: Mapped[str] = mapped_column(String(50))
    username: Mapped[str | None] = mapped_column(String(50))
    phone_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    phone_enc: Mapped[str | None] = mapped_column(String(255))
    password_hash: Mapped[str | None] = mapped_column(String(255))
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    roles: Mapped[list[str]] = mapped_column(ARRAY(String(20)))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    # 改密码时加一，旧的刷新令牌随之失效
    token_version: Mapped[int] = mapped_column(Integer, default=0)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    def has_role(self, *roles: Role) -> bool:
        return any(r in self.roles for r in roles)

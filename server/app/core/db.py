"""数据库连接与租户上下文。

所有带 tenant_id 的表都开启了 PostgreSQL 行级安全（RLS），策略读取两个事务级变量：
- app.tenant_id：当前机构，只能看到这个机构的数据
- app.bypass_rls：'on' 时跨机构（仅用于登录查找账号、平台运营后台、后台任务）

应用层查询仍然要显式按 tenant_id 过滤，RLS 是第二道保护。
"""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from functools import lru_cache

from sqlalchemy import DateTime, create_engine, event, func, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


@lru_cache
def get_engine() -> Engine:
    return create_engine(get_settings().app_database_url, pool_pre_ping=True)


@lru_cache
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def reset_engine() -> None:
    """测试切换数据库时使用。"""
    if get_engine.cache_info().currsize:
        get_engine().dispose()
    get_engine.cache_clear()
    get_sessionmaker.cache_clear()


@event.listens_for(Session, "after_begin")
def _apply_rls_context(session: Session, transaction, connection) -> None:
    ctx = session.info.get("rls", {})
    connection.execute(
        text("select set_config('app.tenant_id', :t, true), set_config('app.bypass_rls', :b, true)"),
        {"t": str(ctx.get("tenant_id") or ""), "b": "on" if ctx.get("bypass") else "off"},
    )


def set_rls_context(session: Session, *, tenant_id: uuid.UUID | None = None, bypass: bool = False) -> None:
    session.info["rls"] = {"tenant_id": tenant_id, "bypass": bypass}
    if session.in_transaction():
        _apply_rls_context(session, None, session.connection())


def open_session(*, tenant_id: uuid.UUID | None = None, bypass: bool = False) -> Session:
    session = get_sessionmaker()()
    set_rls_context(session, tenant_id=tenant_id, bypass=bypass)
    return session


@contextmanager
def session_scope(*, tenant_id: uuid.UUID | None = None, bypass: bool = False) -> Iterator[Session]:
    """后台任务、命令行用：自动提交或回滚。"""
    session = open_session(tenant_id=tenant_id, bypass=bypass)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Iterator[Session]:
    """请求级会话。默认没有租户上下文（看不到任何租户数据），由认证依赖设置。"""
    session = open_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def new_id() -> uuid.UUID:
    return uuid.uuid4()

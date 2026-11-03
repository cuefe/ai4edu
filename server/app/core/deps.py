import uuid
from collections.abc import Callable

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db, set_rls_context
from app.core.errors import Forbidden, Unauthorized
from app.core.security import decode_token
from app.modules.iam.models import Role, User

_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer), db: Session = Depends(get_db)
) -> User:
    if creds is None:
        raise Unauthorized()
    try:
        payload = decode_token(creds.credentials, "access")
    except jwt.ExpiredSignatureError as exc:
        raise Unauthorized("登录已过期") from exc
    except jwt.InvalidTokenError as exc:
        raise Unauthorized() from exc

    tid = payload.get("tid")
    if tid:
        set_rls_context(db, tenant_id=uuid.UUID(tid))
    else:
        # 只有平台运营账号没有机构，可以跨机构访问
        set_rls_context(db, bypass=True)

    user = db.get(User, uuid.UUID(payload["sub"]))
    if user is None or not user.active or user.token_version != payload.get("ver"):
        raise Unauthorized("登录已失效，请重新登录")
    if not tid and not user.has_role(Role.PLATFORM_ADMIN):
        raise Unauthorized()
    # 结束事务、归还连接：接口本身要重新排队等线程，排队时不能占着连接（见 core/routing.py）
    db.commit()
    return user


def require_roles(*roles: Role) -> Callable[[User], User]:
    def checker(user: User = Depends(get_current_user)) -> User:
        if not user.has_role(*roles):
            raise Forbidden()
        return user

    return checker


def client_ip(request: Request) -> str:
    """客户端 IP，只用于审计记录（可以伪造，不能拿来做权限判断）。

    经过 CDN 时用 CLIENT_IP_HEADER 指定的请求头；否则用连接地址，反向代理传来的 X-Forwarded-For
    由 uvicorn --proxy-headers 处理。
    """
    header = get_settings().client_ip_header
    if header and (value := request.headers.get(header)):
        return value.split(",")[0].strip()[:64]
    return request.client.host if request.client else ""


def tenant_of(user: User) -> uuid.UUID:
    if user.tenant_id is None:
        raise Forbidden("该操作需要机构账号")
    return user.tenant_id

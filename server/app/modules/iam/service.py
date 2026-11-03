import uuid
from datetime import UTC, datetime

import jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import session_scope, set_rls_context
from app.core.errors import AppError, Unauthorized
from app.core.redis import get_redis
from app.core.security import (
    create_token,
    decode_token,
    decrypt_phone,
    encrypt_phone,
    generate_password,
    hash_password,
    mask_phone,
    normalize_phone,
    phone_hash,
    verify_and_upgrade,
    verify_password,
)
from app.modules.iam.models import Role, Tenant, User
from app.modules.iam.schemas import MeOut, TenantBrief, TokenOut
from app.modules.ops.service import audit

MAX_LOGIN_FAILURES = 10
LOGIN_LOCK_SECONDS = 15 * 60


def create_user(
    db: Session,
    *,
    tenant_id: uuid.UUID | None,
    name: str,
    roles: list[Role],
    phone: str | None = None,
    username: str | None = None,
    password: str | None = None,
    must_change_password: bool = False,
) -> User:
    if phone is not None:
        phone = normalize_phone(phone)
        if len(phone) != 11:
            raise AppError("手机号格式不正确")
        if db.scalar(select(User.id).where(User.phone_hash == phone_hash(phone))):
            raise AppError("这个手机号已经被使用", code="phone_taken", status=409)
    if username is not None and db.scalar(
        select(User.id).where(User.tenant_id == tenant_id, User.username == username)
    ):
        raise AppError(f"账号 {username} 已存在", code="username_taken", status=409)

    user = User(
        tenant_id=tenant_id,
        name=name.strip(),
        roles=[str(r) for r in roles],
        username=username,
        phone_hash=phone_hash(phone) if phone else None,
        phone_enc=encrypt_phone(phone) if phone else None,
        password_hash=hash_password(password) if password else None,
        must_change_password=must_change_password,
    )
    db.add(user)
    db.flush()
    return user


def user_phone_masked(user: User) -> str | None:
    return mask_phone(decrypt_phone(user.phone_enc)) if user.phone_enc else None


def to_me(db: Session, user: User) -> MeOut:
    tenant = db.get(Tenant, user.tenant_id) if user.tenant_id else None
    return MeOut(
        id=user.id,
        name=user.name,
        roles=user.roles,
        username=user.username,
        phone_masked=user_phone_masked(user),
        must_change_password=user.must_change_password,
        tenant=TenantBrief(
            id=tenant.id, code=tenant.code, name=tenant.name, kind=tenant.kind, expires_at=tenant.expires_at
        )
        if tenant
        else None,
    )


def issue_tokens(db: Session, user: User) -> TokenOut:
    common = {
        "user_id": user.id,
        "tenant_id": user.tenant_id,
        "roles": user.roles,
        "token_version": user.token_version,
    }
    return TokenOut(
        access_token=create_token(**common, kind="access"),
        refresh_token=create_token(**common, kind="refresh"),
        user=to_me(db, user),
    )


# —— 登录（调用方传入跨机构会话：此时还不知道是哪个机构）——


def _check_not_locked(key: str) -> None:
    failures = get_redis().get(f"login:fail:{key}")
    if failures and int(failures) >= MAX_LOGIN_FAILURES:
        raise AppError("密码错误次数过多，请 15 分钟后再试", code="login_locked", status=429)


def _record_failure(key: str, user: User | None, ip: str) -> None:
    redis = get_redis()
    failures = redis.incr(f"login:fail:{key}")
    redis.expire(f"login:fail:{key}", LOGIN_LOCK_SECONDS)
    if user is not None:
        # 请求的事务会因为登录失败回滚，审计记录用单独的会话写
        with session_scope(bypass=True) as db:
            audit(
                db,
                tenant_id=user.tenant_id,
                actor_id=user.id,
                action="login_failed",
                ip=ip,
                locked=failures >= MAX_LOGIN_FAILURES,
            )


def ensure_tenant_usable(db: Session, user: User) -> None:
    """机构停用或服务到期后，机构里的账号都不能登录、不能续期登录状态。"""
    if user.tenant_id is None:
        return
    tenant = db.get(Tenant, user.tenant_id)
    if tenant is None or not tenant.active:
        raise AppError("所在机构已停用", code="tenant_disabled", status=403)
    if tenant.expired():
        raise AppError("所在机构的服务已到期，请联系机构管理员续费", code="tenant_expired", status=403)


def _ensure_can_login(db: Session, user: User) -> None:
    if not user.active:
        raise AppError("账号已停用，请联系管理员", code="user_disabled", status=403)
    ensure_tenant_usable(db, user)
    user.last_login_at = datetime.now(UTC)


def audit_login(db: Session, user: User, method: str, ip: str) -> None:
    audit(db, tenant_id=user.tenant_id, actor_id=user.id, action="login", method=method, ip=ip)


def _password_ok(user: User | None, password: str) -> bool:
    if user is None:
        return False
    ok, upgraded = verify_and_upgrade(password, user.password_hash)
    if ok and upgraded:
        user.password_hash = upgraded  # 旧参数的哈希换成当前参数（core/security.py）
    return ok


def login_with_phone(db: Session, phone: str, password: str, ip: str = "") -> User:
    key = phone_hash(phone)
    _check_not_locked(key)
    user = db.scalar(select(User).where(User.phone_hash == key))
    if user is None or not _password_ok(user, password):
        _record_failure(key, user, ip)
        raise AppError("手机号或密码错误", code="bad_credentials", status=401)
    get_redis().delete(f"login:fail:{key}")
    _ensure_can_login(db, user)
    return user


def login_student(db: Session, tenant_code: str, username: str, password: str, ip: str = "") -> User:
    key = f"{tenant_code.strip().lower()}:{username.strip()}"
    _check_not_locked(key)
    user = db.scalar(
        select(User)
        .join(Tenant, Tenant.id == User.tenant_id)
        .where(Tenant.code == tenant_code.strip().lower(), User.username == username.strip())
    )
    if user is None or not _password_ok(user, password):
        _record_failure(key, user, ip)
        raise AppError("机构代码、账号或密码错误", code="bad_credentials", status=401)
    get_redis().delete(f"login:fail:{key}")
    _ensure_can_login(db, user)
    return user


def find_by_phone(db: Session, phone: str) -> User | None:
    return db.scalar(select(User).where(User.phone_hash == phone_hash(phone)))


def login_with_sms(db: Session, user: User | None) -> User:
    if user is None:
        raise AppError("验证码错误或已过期", code="bad_code", status=401)
    _ensure_can_login(db, user)
    return user


def refresh_tokens(db: Session, refresh_token: str) -> TokenOut:
    try:
        payload = decode_token(refresh_token, "refresh")
    except jwt.InvalidTokenError as exc:
        raise Unauthorized("登录已过期，请重新登录") from exc
    tid = payload.get("tid")
    set_rls_context(db, tenant_id=uuid.UUID(tid) if tid else None, bypass=not tid)
    user = db.get(User, uuid.UUID(payload["sub"]))
    if user is None or not user.active or user.token_version != payload.get("ver"):
        raise Unauthorized("登录已失效，请重新登录")
    ensure_tenant_usable(db, user)
    return issue_tokens(db, user)


# —— 密码 ——


def change_password(user: User, old_password: str, new_password: str) -> None:
    if not verify_password(old_password, user.password_hash):
        raise AppError("原密码不正确", code="bad_password")
    user.password_hash = hash_password(new_password)
    user.must_change_password = False
    user.token_version += 1


def reset_password(user: User) -> str:
    password = generate_password()
    user.password_hash = hash_password(password)
    user.must_change_password = True
    user.token_version += 1
    return password

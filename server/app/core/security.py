import hashlib
import hmac
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any, Literal

import jwt
from cryptography.fernet import Fernet
from pwdlib import PasswordHash

from app.core.config import get_settings

_password_hash = PasswordHash.recommended()

TokenType = Literal["access", "refresh"]


def hash_password(password: str) -> str:
    return _password_hash.hash(password)


def verify_password(password: str, hashed: str | None) -> bool:
    if not hashed:
        return False
    return _password_hash.verify(password, hashed)


def generate_password(length: int = 8) -> str:
    """给学生生成初始密码：去掉易混淆字符，方便抄写。"""
    alphabet = "abcdefghjkmnpqrstuvwxyz23456789"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def create_token(
    *, user_id: uuid.UUID, tenant_id: uuid.UUID | None, roles: list[str], token_version: int, kind: TokenType
) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    ttl = (
        timedelta(minutes=settings.access_token_minutes)
        if kind == "access"
        else timedelta(days=settings.refresh_token_days)
    )
    payload = {
        "sub": str(user_id),
        "tid": str(tenant_id) if tenant_id else None,
        "roles": roles,
        "ver": token_version,
        "typ": kind,
        "iat": now,
        "exp": now + ttl,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_token(token: str, kind: TokenType) -> dict[str, Any]:
    payload = jwt.decode(token, get_settings().jwt_secret, algorithms=["HS256"])
    if payload.get("typ") != kind:
        raise jwt.InvalidTokenError("wrong token type")
    return payload


# —— 手机号：加密存储，另存 HMAC 用于查找和唯一约束 ——


@lru_cache
def _fernet() -> Fernet:
    return Fernet(get_settings().data_encryption_key.encode())


def normalize_phone(phone: str) -> str:
    digits = "".join(ch for ch in phone if ch.isdigit())
    if digits.startswith("86") and len(digits) == 13:
        digits = digits[2:]
    return digits


def phone_hash(phone: str) -> str:
    key = get_settings().phone_hash_key.encode()
    return hmac.new(key, normalize_phone(phone).encode(), hashlib.sha256).hexdigest()


def encrypt_phone(phone: str) -> str:
    return _fernet().encrypt(normalize_phone(phone).encode()).decode()


def decrypt_phone(token: str) -> str:
    return _fernet().decrypt(token.encode()).decode()


def mask_phone(phone: str) -> str:
    return f"{phone[:3]}****{phone[-4:]}" if len(phone) >= 7 else "****"


def generate_sms_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"

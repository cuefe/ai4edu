import hmac
import logging
from datetime import UTC, datetime
from typing import Protocol

from app.core.config import get_settings
from app.core.errors import AppError
from app.core.redis import get_redis
from app.core.security import generate_sms_code, mask_phone, normalize_phone, phone_hash

log = logging.getLogger(__name__)

MAX_VERIFY_ATTEMPTS = 5


class SmsSender(Protocol):
    def send_code(self, phone: str, code: str) -> None: ...

    def send_notice(self, phone: str, text: str) -> None:
        """通知短信（如危机预警提醒老师登录处理）。正文不放学生的具体内容。"""
        ...


class ConsoleSmsSender:
    """开发环境：短信打印到服务端日志。"""

    def send_code(self, phone: str, code: str) -> None:
        log.warning("【开发环境短信】发送到 %s 的验证码：%s", mask_phone(phone), code)

    def send_notice(self, phone: str, text: str) -> None:
        log.warning("【开发环境短信】发送到 %s 的通知：%s", mask_phone(phone), text)


class NoSmsSender:
    """没开通短信：验证码登录关闭（接口直接拒绝），通知短信只记日志。"""

    def send_code(self, phone: str, code: str) -> None:
        raise AppError("还没有开通短信登录，请用密码登录", code="sms_disabled")

    def send_notice(self, phone: str, text: str) -> None:
        log.warning("短信通道未开通，通知短信没有发送：%s", mask_phone(phone))


def enabled() -> bool:
    return get_settings().sms_provider != "none"


def require_password_if_disabled(password: str | None) -> None:
    """没开通短信时，老师、管理员只能用密码登录，建账号时必须设初始密码。"""
    if not password and not enabled():
        raise AppError("还没有开通短信登录，请设置初始密码", code="password_required")


def get_sms_sender() -> SmsSender:
    provider = get_settings().sms_provider
    if provider == "console":
        return ConsoleSmsSender()
    if provider == "none":
        return NoSmsSender()
    # TODO: 接入阿里云短信（需要短信签名和模板审核通过）
    raise NotImplementedError(f"短信通道 {provider} 尚未接入")


def send_login_code(phone: str, *, registered: bool) -> None:
    """未注册的手机号也返回成功（不暴露哪些号码已注册），但不真正发送。"""
    settings = get_settings()
    redis = get_redis()
    key = phone_hash(phone)
    if not redis.set(f"sms:cooldown:{key}", 1, ex=settings.sms_resend_seconds, nx=True):
        raise AppError("发送太频繁，请稍后再试", code="sms_too_frequent", status=429)
    daily = f"sms:daily:{key}:{datetime.now(UTC):%Y%m%d}"
    if redis.incr(daily) > settings.sms_daily_limit:
        raise AppError("今天收验证码的次数太多了，请用密码登录或明天再试", code="sms_daily_limit", status=429)
    redis.expire(daily, 2 * 24 * 3600)
    if not registered:
        log.info("未注册手机号请求验证码，未发送：%s", mask_phone(normalize_phone(phone)))
        return
    code = generate_sms_code()
    redis.set(f"sms:code:{key}", code, ex=settings.sms_code_ttl_seconds)
    redis.delete(f"sms:attempts:{key}")
    get_sms_sender().send_code(normalize_phone(phone), code)


def verify_login_code(phone: str, code: str) -> bool:
    redis = get_redis()
    key = phone_hash(phone)
    attempts = redis.incr(f"sms:attempts:{key}")
    redis.expire(f"sms:attempts:{key}", get_settings().sms_code_ttl_seconds)
    if attempts > MAX_VERIFY_ATTEMPTS:
        redis.delete(f"sms:code:{key}")
        return False
    stored = redis.get(f"sms:code:{key}")
    if stored and hmac.compare_digest(stored, code.strip()):
        redis.delete(f"sms:code:{key}", f"sms:attempts:{key}")
        return True
    return False

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.db import get_db, set_rls_context
from app.core.deps import client_ip, get_current_user
from app.core.errors import AppError
from app.core.routing import DbRoute
from app.modules.iam import service, sms
from app.modules.iam.models import User
from app.modules.iam.schemas import (
    AuthMethodsOut,
    ChangePasswordIn,
    MeOut,
    OkOut,
    PhoneLoginIn,
    RefreshIn,
    SmsLoginIn,
    SmsSendIn,
    StudentLoginIn,
    TokenOut,
)

auth_router = APIRouter(route_class=DbRoute, prefix="/auth", tags=["认证"])
me_router = APIRouter(route_class=DbRoute, prefix="/me", tags=["认证"])


def _login_db(db: Session = Depends(get_db)) -> Session:
    # 登录时还不知道账号属于哪个机构，需要跨机构查找
    set_rls_context(db, bypass=True)
    return db


@auth_router.get("/methods", response_model=AuthMethodsOut, summary="可用的登录方式")
def methods() -> AuthMethodsOut:
    return AuthMethodsOut(sms=sms.enabled())


@auth_router.post("/login/phone", response_model=TokenOut, summary="手机号＋密码登录（老师、管理员）")
def login_phone(body: PhoneLoginIn, request: Request, db: Session = Depends(_login_db)) -> TokenOut:
    ip = client_ip(request)
    user = service.login_with_phone(db, body.phone, body.password, ip)
    service.audit_login(db, user, "password", ip)
    tokens = service.issue_tokens(db, user)
    db.commit()
    return tokens


@auth_router.post("/login/student", response_model=TokenOut, summary="机构代码＋账号＋密码登录（学生）")
def login_student(body: StudentLoginIn, request: Request, db: Session = Depends(_login_db)) -> TokenOut:
    ip = client_ip(request)
    user = service.login_student(db, body.tenant_code, body.username, body.password, ip)
    service.audit_login(db, user, "student", ip)
    tokens = service.issue_tokens(db, user)
    db.commit()
    return tokens


@auth_router.post("/sms/send", response_model=OkOut, summary="发送登录验证码")
def sms_send(body: SmsSendIn, db: Session = Depends(_login_db)) -> OkOut:
    if not sms.enabled():
        raise AppError("还没有开通短信登录，请用密码登录", code="sms_disabled")
    user = service.find_by_phone(db, body.phone)
    sms.send_login_code(body.phone, registered=user is not None and user.active)
    return OkOut()


@auth_router.post("/login/sms", response_model=TokenOut, summary="手机号＋验证码登录")
def login_sms(body: SmsLoginIn, request: Request, db: Session = Depends(_login_db)) -> TokenOut:
    if not sms.verify_login_code(body.phone, body.code):
        raise AppError("验证码错误或已过期", code="bad_code", status=401)
    user = service.login_with_sms(db, service.find_by_phone(db, body.phone))
    service.audit_login(db, user, "sms", client_ip(request))
    tokens = service.issue_tokens(db, user)
    db.commit()
    return tokens


@auth_router.post("/refresh", response_model=TokenOut, summary="刷新令牌")
def refresh(body: RefreshIn, db: Session = Depends(get_db)) -> TokenOut:
    return service.refresh_tokens(db, body.refresh_token)


@me_router.get("", response_model=MeOut, summary="当前账号")
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> MeOut:
    return service.to_me(db, user)


@me_router.post("/password", response_model=TokenOut, summary="修改密码（返回新令牌，其他设备需重新登录）")
def change_password(
    body: ChangePasswordIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> TokenOut:
    service.change_password(user, body.old_password, body.new_password)
    tokens = service.issue_tokens(db, user)
    db.commit()
    return tokens

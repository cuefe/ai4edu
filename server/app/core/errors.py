from fastapi import Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    """业务错误：message 直接展示给用户，code 供前端判断。"""

    def __init__(self, message: str, *, code: str = "bad_request", status: int = 400):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status


class NotFound(AppError):
    def __init__(self, message: str = "内容不存在"):
        super().__init__(message, code="not_found", status=404)


class Forbidden(AppError):
    def __init__(self, message: str = "没有权限"):
        super().__init__(message, code="forbidden", status=403)


class Unauthorized(AppError):
    def __init__(self, message: str = "请先登录"):
        super().__init__(message, code="unauthorized", status=401)


async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(status_code=exc.status, content={"code": exc.code, "message": exc.message})

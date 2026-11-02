import logging

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import Settings, get_settings
from app.core.errors import AppError, app_error_handler
from app.modules.assignment.router import student_router as assignment_student_router
from app.modules.assignment.router import teacher_router as assignment_teacher_router
from app.modules.content.router import router as content_router
from app.modules.iam.router import auth_router, me_router
from app.modules.learning.router import router as learning_router
from app.modules.library.router import router as library_router
from app.modules.notify.router import router as notify_router
from app.modules.ops.router import router as ops_router
from app.modules.org.router import org_router, student_router, teacher_router
from app.modules.qbank.router import router as qbank_router
from app.modules.recite.router import router as recite_router
from app.modules.safety.router import router as safety_router
from app.modules.tutor.router import router as tutor_router

DEV_DEFAULTS = {
    "jwt_secret": Settings.model_fields["jwt_secret"].default,
    "data_encryption_key": Settings.model_fields["data_encryption_key"].default,
    "phone_hash_key": Settings.model_fields["phone_hash_key"].default,
}


def _check_prod_settings(settings: Settings) -> None:
    if not settings.is_prod:
        return
    insecure = [name for name, default in DEV_DEFAULTS.items() if getattr(settings, name) == default]
    if insecure:
        raise RuntimeError(f"生产环境不能使用开发默认值：{', '.join(insecure)}")
    if settings.redis_url.startswith("memory://") or settings.sms_provider == "console":
        raise RuntimeError("生产环境需要配置真实的 Redis 和短信通道")


def create_app() -> FastAPI:
    settings = get_settings()
    _check_prod_settings(settings)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    app = FastAPI(
        title="AI 中小学智教平台",
        version="0.1.0",
        docs_url=None if settings.is_prod else "/api/docs",
        openapi_url=None if settings.is_prod else "/api/openapi.json",
    )
    app.add_exception_handler(AppError, app_error_handler)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    api = APIRouter(prefix="/api")

    @api.get("/health", tags=["系统"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    for router in (
        auth_router,
        me_router,
        notify_router,
        org_router,
        teacher_router,
        student_router,
        content_router,
        recite_router,
        qbank_router,
        library_router,
        assignment_teacher_router,
        assignment_student_router,
        learning_router,
        tutor_router,
        safety_router,
        ops_router,
    ):
        api.include_router(router)
    app.include_router(api)
    return app


app = create_app()

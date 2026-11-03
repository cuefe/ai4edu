import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import anyio
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
    if settings.redis_url.startswith("memory://"):
        raise RuntimeError("生产环境需要配置真实的 Redis")
    if settings.sms_provider == "console":
        raise RuntimeError("生产环境不能把短信打印到日志：没有短信通道时 SMS_PROVIDER 填 none")
    if "*" in settings.cors_origins:
        raise RuntimeError("生产环境 CORS_ORIGINS 不能用 *")


def _check_pool(settings: Settings) -> None:
    # 同步接口在线程池里执行，每个线程最多占一个数据库连接（请求结束、释放连接也要用线程）。
    # 线程数不小于连接池上限时，高并发下线程都在等连接、占着连接的请求又等不到线程收尾，
    # 互相卡住直到连接池超时（压测实测 300 人同时在线时全部超时）。留出余量给后台任务和嵌套会话
    if settings.api_threads + 5 > settings.db_pool_size + settings.db_max_overflow:
        raise RuntimeError("API_THREADS 要比 DB_POOL_SIZE + DB_MAX_OVERFLOW 至少小 5")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    anyio.to_thread.current_default_thread_limiter().total_tokens = get_settings().api_threads
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    _check_prod_settings(settings)
    _check_pool(settings)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    app = FastAPI(
        title="AI 中小学智教平台",
        version="0.1.0",
        docs_url=None if settings.is_prod else "/api/docs",
        openapi_url=None if settings.is_prod else "/api/openapi.json",
        lifespan=lifespan,
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

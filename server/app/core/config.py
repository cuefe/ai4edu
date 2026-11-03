from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

SERVER_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    # 空值视为未配置，使用默认值（.env.example、docker-compose 里留空的项）
    model_config = SettingsConfigDict(
        env_file=SERVER_DIR / ".env", env_file_encoding="utf-8", extra="ignore", env_ignore_empty=True
    )

    env: str = "dev"  # dev / test / prod

    # 两个数据库连接：迁移用表的所有者账号；应用运行用受行级安全约束的普通账号
    database_url: str = "postgresql+psycopg://postgres@127.0.0.1:54329/ai4edu"
    app_database_url: str = "postgresql+psycopg://ai4edu_app@127.0.0.1:54329/ai4edu"
    app_db_role: str = "ai4edu_app"

    # memory:// 表示用内存版（fakeredis、Celery 同步执行），只用于本地开发和测试
    redis_url: str = "memory://"

    jwt_secret: str = "dev-only-jwt-secret-change-me-in-prod"
    access_token_minutes: int = 30
    refresh_token_days: int = 14

    # 手机号加密：Fernet 密钥（base64，32 字节）和查询用的 HMAC 密钥
    data_encryption_key: str = "ZGV2LW9ubHktZGF0YS1lbmNyeXB0aW9uLWtleS0wMzI="
    phone_hash_key: str = "dev-only-phone-hash-key"

    # console = 验证码打印到日志（仅开发）；none = 不开通短信：只能密码登录，通知短信不发
    sms_provider: str = "console"
    sms_code_ttl_seconds: int = 300
    sms_resend_seconds: int = 60
    sms_daily_limit: int = 10  # 每个手机号每天最多收几条验证码

    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    # 经过 CDN 时取客户端 IP 的请求头（如 Cloudflare 填 cf-connecting-ip）；不填用连接地址。只用于审计记录
    client_ip_header: str = ""

    # 每个 API 进程：同步接口的线程数、数据库连接池。线程数要比连接池上限小（见 main._check_pool）。
    # 多进程部署时，连接数最多 = 进程数 ×（pool_size + max_overflow）+ Worker，
    # 不能超过 PostgreSQL 的 max_connections
    api_threads: int = 30
    db_pool_size: int = 10
    db_max_overflow: int = 30

    # 防刷量：每个账号每天的 AI 使用上限（机构的 AI 月额度另算）
    teacher_daily_ai_tasks: int = 60  # 老师生成教案、讲义、背诵卡片、出题的次数
    student_daily_tutor_messages: int = 200  # 学生在问一问里发消息的条数

    # 上传文件存放目录。试点阶段用本地磁盘（Docker 里挂数据卷），规模化时换成 OSS
    storage_dir: Path = SERVER_DIR / ".data" / "files"
    max_upload_mb: int = 50

    # 学生在问一问里流露危机念头时显示的求助电话。号码写在配置里，可以按地区调整，不让模型自己编
    crisis_hotlines: list[str] = [
        "全国心理援助热线：12356",
        "青少年服务台：12355",
        "遇到紧急危险，请立即拨打 110 或 120",
    ]
    # 危机预警多久没处理算超时，超时的在机构管理员那里标红
    crisis_escalate_hours: int = 2

    ai_config_path: Path = SERVER_DIR / "app" / "ai" / "gateway" / "models.yaml"
    ai_allow_mock: bool = True  # 没有可用模型时回退到 mock，生产环境必须关掉

    @property
    def is_prod(self) -> bool:
        return self.env == "prod"


@lru_cache
def get_settings() -> Settings:
    return Settings()

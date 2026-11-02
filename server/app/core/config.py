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

    sms_provider: str = "console"  # console = 验证码打印到日志
    sms_code_ttl_seconds: int = 300
    sms_resend_seconds: int = 60

    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    # 上传文件存放目录。试点阶段用本地磁盘（Docker 里挂数据卷），规模化时换成 OSS
    storage_dir: Path = SERVER_DIR / ".data" / "files"
    max_upload_mb: int = 50

    ai_config_path: Path = SERVER_DIR / "app" / "ai" / "gateway" / "models.yaml"
    ai_allow_mock: bool = True  # 没有可用模型时回退到 mock，生产环境必须关掉

    @property
    def is_prod(self) -> bool:
        return self.env == "prod"


@lru_cache
def get_settings() -> Settings:
    return Settings()

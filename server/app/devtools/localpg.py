"""本地开发 / 测试用的 PostgreSQL。

用 pgserver 包自带的 PostgreSQL + pgvector 二进制，不需要安装数据库服务，也不需要管理员权限。
生产和 CI 用正式的 PostgreSQL，不走这里。
"""

import subprocess
from pathlib import Path

import psycopg
from pgserver._commands import POSTGRES_BIN_PATH


class LocalPostgres:
    def __init__(self, data_dir: Path, port: int):
        self.data_dir = Path(data_dir)
        self.port = port

    def _bin(self, name: str) -> str:
        return str(Path(POSTGRES_BIN_PATH) / name)

    def owner_url(self, db: str = "postgres", driver: str = "") -> str:
        scheme = f"postgresql+{driver}" if driver else "postgresql"
        return f"{scheme}://postgres@127.0.0.1:{self.port}/{db}"

    def role_url(self, role: str, db: str, driver: str = "") -> str:
        scheme = f"postgresql+{driver}" if driver else "postgresql"
        return f"{scheme}://{role}@127.0.0.1:{self.port}/{db}"

    def is_running(self) -> bool:
        result = subprocess.run(
            [self._bin("pg_ctl"), "-D", str(self.data_dir), "status"], capture_output=True, text=True
        )
        return result.returncode == 0

    def start(self) -> None:
        if not (self.data_dir / "PG_VERSION").exists():
            self.data_dir.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                [
                    self._bin("initdb"),
                    "-D",
                    str(self.data_dir),
                    "-U",
                    "postgres",
                    "-A",
                    "trust",
                    "-E",
                    "UTF8",
                    "--locale=C",
                ],
                check=True,
                capture_output=True,
            )
        if self.is_running():
            return
        # 不能捕获输出：Windows 上数据库进程会继承管道句柄，导致这里一直等不到结束。日志写到 server.log
        subprocess.run(
            [
                self._bin("pg_ctl"),
                "-D",
                str(self.data_dir),
                "-l",
                str(self.data_dir / "server.log"),
                "-w",
                "-o",
                f"-p {self.port} -c listen_addresses=127.0.0.1",
                "start",
            ],
            check=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def stop(self) -> None:
        if self.is_running():
            subprocess.run(
                [self._bin("pg_ctl"), "-D", str(self.data_dir), "-m", "fast", "-w", "stop"],
                check=True,
                capture_output=True,
            )

    def setup_database(self, db: str, app_role: str) -> None:
        """建库、建应用账号（非超级用户、受行级安全约束）、启用 pgvector。重复执行无副作用。"""
        with psycopg.connect(self.owner_url(), autocommit=True) as conn:
            if not conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (app_role,)).fetchone():
                conn.execute(f'CREATE ROLE "{app_role}" LOGIN NOSUPERUSER NOBYPASSRLS')
            if not conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db,)).fetchone():
                conn.execute(f'CREATE DATABASE "{db}"')
        with psycopg.connect(self.owner_url(db), autocommit=True) as conn:
            conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            conn.execute(
                "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
                f'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO "{app_role}"'
            )

    def drop_database(self, db: str) -> None:
        with psycopg.connect(self.owner_url(), autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{db}" WITH (FORCE)')

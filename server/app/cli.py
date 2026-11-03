"""命令行工具。用法：uv run python -m app.cli <命令>

db-start               启动本地开发数据库（端口 54329，数据在 server/.data/pg）
db-stop                停止本地开发数据库
migrate                执行数据库迁移
create-platform-admin  创建平台运营账号
seed-demo              写入演示数据（仅开发环境）
dev                    一键起本地开发环境：数据库、迁移、后端、前端（pnpm dev）
dev-stop               结束残留的后端、前端进程和本地数据库（pnpm stop）
openapi --out FILE     导出接口定义（前端生成类型用）
"""

import argparse
import json
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import select

from app.core.config import SERVER_DIR, get_settings
from app.core.db import session_scope
from app.modules.iam import service as iam
from app.modules.iam.models import Role, Tenant
from app.modules.org import service as org
from app.modules.org.models import MemberRole
from app.modules.org.schemas import ClassIn, StudentIn

DEV_PG_PORT = 54329


def _local_pg():
    from app.devtools.localpg import LocalPostgres

    return LocalPostgres(SERVER_DIR / ".data" / "pg", DEV_PG_PORT)


def db_start(_: argparse.Namespace) -> None:
    pg = _local_pg()
    pg.start()
    pg.setup_database("ai4edu", get_settings().app_db_role)
    print(f"本地数据库已启动：127.0.0.1:{DEV_PG_PORT}，库名 ai4edu")


def db_stop(_: argparse.Namespace) -> None:
    _local_pg().stop()
    print("本地数据库已停止")


def migrate(_: argparse.Namespace) -> None:
    command.upgrade(Config(str(SERVER_DIR / "alembic.ini")), "head")
    print("迁移完成")


def create_platform_admin(args: argparse.Namespace) -> None:
    with session_scope(bypass=True) as db:
        user = iam.create_user(
            db,
            tenant_id=None,
            name=args.name,
            roles=[Role.PLATFORM_ADMIN],
            phone=args.phone,
            password=args.password,
        )
        print(f"已创建平台运营账号：{user.name}")


def seed_demo(_: argparse.Namespace) -> None:
    if get_settings().is_prod:
        sys.exit("生产环境不能写入演示数据")
    with session_scope(bypass=True) as db:
        if db.scalar(select(Tenant).where(Tenant.code == "demo")):
            print("演示数据已存在，跳过")
            return
        iam.create_user(
            db,
            tenant_id=None,
            name="平台运营",
            roles=[Role.PLATFORM_ADMIN],
            phone="13800000000",
            password="admin1234",
        )
        tenant = Tenant(code="demo", name="演示中学", kind="school")
        db.add(tenant)
        db.flush()
        iam.create_user(
            db,
            tenant_id=tenant.id,
            name="王校长",
            roles=[Role.ORG_ADMIN, Role.TEACHER],
            phone="13800000001",
            password="demo1234",
        )
        teacher = iam.create_user(
            db,
            tenant_id=tenant.id,
            name="李老师",
            roles=[Role.TEACHER],
            phone="13800000002",
            password="demo1234",
        )
        klass = org.create_class(db, tenant.id, ClassIn(name="初一(1)班", grade="初一"))
        org.add_member(db, tenant.id, klass.id, teacher.id, MemberRole.TEACHER, "数学")
        for i, name in enumerate(["张一鸣", "王小雨", "刘子涵", "陈思远", "赵欣怡"], start=1):
            student, _ = org.create_student(
                db,
                tenant.id,
                StudentIn(name=name, username=f"s{i:03d}", class_id=klass.id, password="123456"),
            )
            student.must_change_password = False
    print(
        "演示数据已写入：\n"
        "  平台运营   13800000000 / admin1234\n"
        "  机构管理员 13800000001 / demo1234（机构代码 demo）\n"
        "  老师       13800000002 / demo1234\n"
        "  学生       机构代码 demo，账号 s001～s005，密码 123456"
    )


def dev(args: argparse.Namespace) -> None:
    """pnpm dev：一键起本地开发环境，Ctrl+C 全部结束。"""
    from app.devtools import devrun

    devrun.ensure_ports_free()
    db_start(args)
    try:
        migrate(args)
        devrun.run(SERVER_DIR.parent, SERVER_DIR)
    finally:
        db_stop(args)


def dev_stop(args: argparse.Namespace) -> None:
    """pnpm stop：结束残留的后端、前端进程和本地数据库。"""
    from app.devtools import devrun

    devrun.stop_port_owners()
    db_stop(args)


def export_openapi(args: argparse.Namespace) -> None:
    """导出接口定义，前端据此生成类型（pnpm gen:api）。"""
    from app.main import app

    spec = json.dumps(app.openapi(), ensure_ascii=False, indent=2)
    Path(args.out).write_text(spec + "\n", encoding="utf-8")
    print(f"已导出 {args.out}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="app.cli", description="AI 智教平台命令行工具")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("db-start").set_defaults(func=db_start)
    sub.add_parser("db-stop").set_defaults(func=db_stop)
    sub.add_parser("migrate").set_defaults(func=migrate)
    p = sub.add_parser("create-platform-admin")
    p.add_argument("--name", required=True)
    p.add_argument("--phone", required=True)
    p.add_argument("--password", required=True)
    p.set_defaults(func=create_platform_admin)
    sub.add_parser("seed-demo").set_defaults(func=seed_demo)
    sub.add_parser("dev").set_defaults(func=dev)
    sub.add_parser("dev-stop").set_defaults(func=dev_stop)
    p = sub.add_parser("openapi")
    p.add_argument("--out", required=True)
    p.set_defaults(func=export_openapi)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

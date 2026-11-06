"""命令行工具。用法：uv run python -m app.cli <命令>

db-start               启动本地开发数据库（端口 54329，数据在 server/.data/pg）
db-stop                停止本地开发数据库
migrate                执行数据库迁移
create-platform-admin  创建平台运营账号
seed-demo              写入演示数据（仅开发环境）
seed-load              写入压测数据（仅开发环境，见 app/devtools/loadtest.py）
dev                    一键起本地开发环境：数据库、迁移、后端、前端（pnpm dev）
dev-stop               结束残留的后端、前端进程和本地数据库（pnpm stop）
openapi --out FILE     导出接口定义（前端生成类型用）
content-ocr PDF DIR    把扫描版课本逐页转写成 Markdown，供 content-gen 使用
content-gen OUTLINE    按大纲离线生成一册教材的内容包（app/devtools/content_gen.py）
content-import PACK    导入内容包（--publish 同时发布）
content-publish KEY    发布一册教材（--off 下架）
content-remove KEY     删除一册教材，连同上传的文件
pool-gen DIR           按课本原文离线生成周测题库并校验答案（app/devtools/pool_gen.py）
pool-import FILE       导入题包，审核通过后才会进周测
weekly-run             马上跑一次周测发卷（平时由定时任务在周五下午跑）
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


def seed_load(args: argparse.Namespace) -> None:
    """压测数据：一个机构、若干班、每班一份客观题作业（app/devtools/loadtest.py）。"""
    if get_settings().is_prod:
        sys.exit("生产环境不能写入压测数据")
    from app.devtools import loadtest

    if args.reset:
        loadtest.reset()
    else:
        loadtest.seed(args.classes, args.per_class)


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


def content_ocr(args: argparse.Namespace) -> None:
    from app.devtools import content_gen as gen

    failed = gen.ocr_pdf(
        Path(args.pdf),
        Path(args.out_dir),
        pages=args.pages,
        batch=args.batch,
        concurrency=args.concurrency,
        force=args.force,
        model=args.model,
        effort=args.effort,
    )
    if failed:
        sys.exit(1)


def content_gen(args: argparse.Namespace) -> None:
    from app.devtools import content_gen as gen

    only = {c.strip() for c in args.chapters.split(",")} if args.chapters else None
    path = gen.run(
        Path(args.outline),
        engine_name=args.engine,
        sources=Path(args.sources) if args.sources else None,
        only=only,
        concurrency=args.concurrency,
        force=args.force,
        model=args.model,
        effort=args.effort,
    )
    if path is None:
        sys.exit(1)


def pool_gen(args: argparse.Namespace) -> None:
    from app.devtools import pool_gen as gen

    only = {s.strip() for s in args.sections.split(",")} if args.sections else None
    path = gen.run(
        Path(args.pack_dir),
        only=only,
        concurrency=args.concurrency,
        force=args.force,
        model=args.model,
        effort=args.effort,
    )
    if path is None and only is None:
        sys.exit(1)


def pool_import(args: argparse.Namespace) -> None:
    from app.modules.curriculum import pool

    with session_scope(bypass=True) as db:
        result = pool.import_pool(db, pool.load_pack(Path(args.questions)))
    print(
        f"导入完成：新增 {result.created} 道，更新 {result.updated} 道，"
        f"审核过或改过的 {result.kept} 道没有动，删除 {result.removed} 道"
    )
    for reason in result.dropped:
        print(f"  没有导入：{reason}")
    print("题目要在「平台运营 → 教材内容 → 题库」审核通过后才会进周测")


def weekly_run(args: argparse.Namespace) -> None:
    from app.modules.weekly import tasks

    print(tasks.remind_all() if args.remind else tasks.issue_all())


def content_import(args: argparse.Namespace) -> None:
    from app.modules.curriculum import pack as content_pack

    path = Path(args.pack)
    with session_scope(bypass=True) as db:
        result = content_pack.import_pack(db, content_pack.load_pack(path), path.parent, publish=args.publish)
        state = "已发布" if args.publish else "未改变发布状态（新书默认是草稿）"
        print(
            f"导入完成（{'新建' if result.created else '更新'}，{state}）：{result.chapters} 个章节，"
            f"{result.knowledge_points} 个知识点，新增文件 {result.files_added} 个"
        )


def content_publish(args: argparse.Namespace) -> None:
    from app.modules.curriculum.models import BookStatus, Textbook

    with session_scope(bypass=True) as db:
        book = db.scalar(select(Textbook).where(Textbook.key == args.key))
        if book is None:
            sys.exit(f"没有这册教材：{args.key}")
        book.status = BookStatus.DRAFT if args.off else BookStatus.PUBLISHED
        print(f"《{book.title}》现在是：{'草稿' if args.off else '已发布'}")


def content_remove(args: argparse.Namespace) -> None:
    from app.modules.curriculum import pack as content_pack

    with session_scope(bypass=True) as db:
        if not content_pack.remove_book(db, args.key):
            sys.exit(f"没有这册教材：{args.key}")
    print(f"已删除：{args.key}")


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
    p = sub.add_parser("seed-load")
    p.add_argument("--classes", type=int, default=12)
    p.add_argument("--per-class", type=int, default=50)
    p.add_argument("--reset", action="store_true", help="清掉压测学生的作答，再压一遍前用")
    p.set_defaults(func=seed_load)
    sub.add_parser("dev").set_defaults(func=dev)
    sub.add_parser("dev-stop").set_defaults(func=dev_stop)
    p = sub.add_parser("openapi")
    p.add_argument("--out", required=True)
    p.set_defaults(func=export_openapi)
    p = sub.add_parser("content-ocr")
    p.add_argument("pdf")
    p.add_argument("out_dir", help="转写结果按页存在这个目录，已有的页不会重做")
    p.add_argument("--pages", help="PDF 页码，如 7-182 或 8,10-12，默认全部")
    p.add_argument("--batch", type=int, default=4, help="每次发给 Codex 几页")
    p.add_argument("--concurrency", type=int, default=3)
    p.add_argument("--force", action="store_true", help="已经转写的页也重做")
    p.add_argument("--model", help="默认用 Codex 的默认模型")
    p.add_argument("--effort", default="low", help="推理强度")
    p.set_defaults(func=content_ocr)
    p = sub.add_parser("content-gen")
    p.add_argument("outline", help="大纲 JSON，结果写在同一个目录")
    p.add_argument("--engine", choices=["codex", "gateway"], default="codex")
    p.add_argument("--sources", help="参考资料目录，文件路径里带章名的算这一章的资料")
    p.add_argument("--chapters", help="只生成这些章，逗号分隔，如 25,26")
    p.add_argument("--concurrency", type=int, default=2)
    p.add_argument("--force", action="store_true", help="已经生成的章也重新生成")
    p.add_argument("--model", help="codex 引擎用的模型，默认用 Codex 的默认模型")
    p.add_argument("--effort", default="medium", help="codex 引擎的推理强度")
    p.set_defaults(func=content_gen)
    p = sub.add_parser("pool-gen")
    p.add_argument("pack_dir", help="内容包目录，要有 pack.json、scan.json 和转写好的 ocr/")
    p.add_argument("--sections", help="只处理这些节，逗号分隔，如 25.1,25.2")
    p.add_argument("--concurrency", type=int, default=3)
    p.add_argument("--force", action="store_true", help="已经出好的节也重做")
    p.add_argument("--model", help="默认用 Codex 的默认模型")
    p.add_argument("--effort", default="medium", help="推理强度")
    p.set_defaults(func=pool_gen)
    p = sub.add_parser("pool-import")
    p.add_argument("questions", help="pool-gen 生成的 questions.json")
    p.set_defaults(func=pool_import)
    p = sub.add_parser("weekly-run")
    p.add_argument("--remind", action="store_true", help="只提醒老师更新进度，不发卷")
    p.set_defaults(func=weekly_run)
    p = sub.add_parser("content-import")
    p.add_argument("pack")
    p.add_argument("--publish", action="store_true")
    p.set_defaults(func=content_import)
    p = sub.add_parser("content-publish")
    p.add_argument("key")
    p.add_argument("--off", action="store_true", help="下架")
    p.set_defaults(func=content_publish)
    p = sub.add_parser("content-remove")
    p.add_argument("key")
    p.set_defaults(func=content_remove)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

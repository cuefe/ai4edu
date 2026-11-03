"""一键起停本地开发环境（在仓库根目录运行）。

pnpm dev   起数据库、执行迁移、装前端依赖，然后在同一个终端里跑后端和前端；Ctrl+C 全部结束，包括数据库
pnpm stop  结束占着 8000、5173 端口的进程和本地数据库（窗口被直接关掉、或别处起的服务占着端口时用）
"""

import contextlib
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import psutil

API_PORT = 8000
WEB_PORT = 5173


def port_owners(port: int) -> list[psutil.Process]:
    pids = {
        c.pid
        for c in psutil.net_connections(kind="inet")
        if c.laddr and c.laddr.port == port and c.status == psutil.CONN_LISTEN and c.pid
    }
    owners = []
    for pid in pids:
        with contextlib.suppress(psutil.NoSuchProcess):
            owners.append(psutil.Process(pid))
    return owners


def kill_tree(proc: psutil.Process) -> None:
    try:
        procs = [*proc.children(recursive=True), proc]
    except psutil.NoSuchProcess:
        return
    for p in procs:
        with contextlib.suppress(psutil.NoSuchProcess):
            p.kill()
    psutil.wait_procs(procs, timeout=5)


def ensure_ports_free() -> None:
    busy = [port for port in (API_PORT, WEB_PORT) if port_owners(port)]
    if busy:
        ports = "、".join(map(str, busy))
        sys.exit(f"端口 {ports} 被占用（可能是上次没关干净），先运行 pnpm stop")


def stop_port_owners() -> None:
    for port in (API_PORT, WEB_PORT):
        for proc in port_owners(port):
            print(f"结束占用 {port} 端口的进程：{proc.name()}（{proc.pid}）")
            kill_tree(proc)


def run(root: Path, server_dir: Path) -> None:
    """装前端依赖，起后端和前端，等到 Ctrl+C 或任一服务退出，再把两个都结束。"""
    pnpm = shutil.which("pnpm")
    if not pnpm:
        sys.exit("找不到 pnpm，先安装 Node.js 和 pnpm")
    subprocess.run([pnpm, "install"], cwd=root, check=True)

    # 子进程不接收 Ctrl+C，由这里统一结束：Windows 上 Ctrl+C 打断 pnpm.cmd 会卡在"终止批处理操作吗(Y/N)?"
    if os.name == "nt":
        detach = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    else:
        detach = {"start_new_session": True}
    services = {
        "后端": subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--reload", "--port", str(API_PORT)],
            cwd=server_dir,
            **detach,
        ),
        "前端": subprocess.Popen([pnpm, "dev:web"], cwd=root, **detach),
    }
    print(
        f"\n前端 http://localhost:{WEB_PORT}    接口文档 http://localhost:{API_PORT}/api/docs\n"
        "按 Ctrl+C 结束全部服务（包括数据库）\n",
        flush=True,
    )
    try:
        while all(p.poll() is None for p in services.values()):
            time.sleep(0.5)
        exited = next(name for name, p in services.items() if p.poll() is not None)
        print(f"\n{exited}已退出，正在结束其他服务……", flush=True)
    except KeyboardInterrupt:
        print("\n正在结束……", flush=True)
    finally:
        for p in services.values():
            with contextlib.suppress(psutil.NoSuchProcess):
                kill_tree(psutil.Process(p.pid))

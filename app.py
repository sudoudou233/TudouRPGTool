# -*- coding: utf-8 -*-
"""RPG Maker 全能工具 —— 唯一入口。

@feature  none
@layer    app
@public   App, main, build_app
@depends  core.*, features.*, ui.server, ui.routes
@tested   tests/unit/test_app.py, tests/integration/test_startup.py
@footprint docs/ARCHITECTURE.md#entry

职责（需求 §5 目标架构）
----------------------
1. 装配模块：显式构造 core 组件，发现 features/*，把路由登记进 router
2. 启动服务：绑定本机端口、可选打开浏览器、健康检查
3. 回收旧实例：沿用 translation_tool/main.py:20-64 的端口占用处理
4. 生命周期：`--check` 只做自检后退出；`--port 0` 取随机端口

**不做 import 副作用**：原实现 ``tool/server.py:434`` 在模块级构造
``ApiServer()`` 并启动落盘线程，导致无法多实例、测试无法隔离（B-25）。
本模块只提供 :func:`build_app` 与 :func:`main`，一切显式构造。
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request

#: 保证以 ``python app.py`` 直接运行时工程根在 sys.path 上。
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from core import __version__, config as config_mod, jobs as jobs_mod, paths, registry as registry_mod  # noqa: E402
from core.context import AppContext  # noqa: E402
from ui import routes as ui_routes  # noqa: E402
from ui import server as ui_server  # noqa: E402

DEFAULT_PORT = 8765


class App(object):
    """应用装配体：配置 + 任务队列 + 注册表 + 路由 + HTTP 服务。"""

    #: 展示给用户与 /api/health 的应用名
    NAME = "RPG Maker 全能工具"

    def __init__(self, config_path=None, port=DEFAULT_PORT, bind="127.0.0.1"):
        self.version = __version__
        self.port = port
        self.bind = bind

        # ---- core 组件 ----
        self.config = config_mod.AppConfig.load(config_path)
        self.jobs = jobs_mod.JobManager(max_workers=4, max_pending=64, ttl=900,
                                        id_prefix="job")
        self.registry = None
        self.context = None
        self.register_report = {}

        # ---- ui ----
        self.server = ui_server.JsonApiServer(router=None, web_dir=paths.web_dir(),
                                              app=self, bind=bind)

    # ------------------------------------------------------------ 装配
    def build(self, features_path=None, reload_modules=False):
        """发现功能模块 → 构造 ctx → 登记路由 → 调用各模块 register。"""
        self.registry = registry_mod.get_registry(features_path,
                                                 reload_modules=reload_modules)
        self.context = AppContext(app=self, config=self.config, jobs=self.jobs)
        self.server.router = self.context.router

        # 核心路由先登记（功能路由随后追加）
        ui_routes.register_core_routes(self.context, app=self)

        # 功能模块自行登记（契约：只能通过 ctx，不得改 app/server 内部）
        self.register_report = self.registry.register_all(self.context)
        return self

    # ------------------------------------------------------------ 自检/报告
    def version_info(self):
        return {"name": self.NAME, "version": self.version,
                "python": sys.version.split()[0],
                "port": self.port, "bind": self.bind}

    def registry_report(self):
        """注册表摘要（含每个模块的加载状态与健康检查）。"""
        if self.registry is None:
            return {"loaded": False, "count": 0, "errors": ["注册表未初始化"],
                    "features": [], "ok": False}
        features = []
        for module in self.registry.all():
            entry = module.nav_entry()
            entry["health"] = module.health()
            features.append(entry)
        return {
            "loaded": self.registry.loaded,
            "count": len(self.registry),
            "ids": self.registry.ids(),
            "errors": self.registry.errors,
            "register_report": self.register_report,
            "features": features,
            "ok": not self.registry.errors and all(m.ok for m in self.registry.all()),
        }

    def check(self):
        """启动前自检，返回 ``(ok, 报告 dict)``。

        检查项：功能目录存在、至少一个功能模块、模块健康、web 资源齐全、
        路由数量合理、核心路由都存在。
        """
        problems = []
        web_dir = paths.web_dir()
        for name in ("index.html", "app.js", "dom.js", "tokens.css", "components.css"):
            if not os.path.isfile(os.path.join(web_dir, name)):
                problems.append("缺少前端资源：ui/web/%s" % name)

        report = self.registry_report()
        if not report["count"]:
            problems.append("未发现任何功能模块（features/*/manifest.py）")
        for feature in report["features"]:
            health = feature.get("health") or {}
            if health.get("status") == "error":
                problems.append("功能 %s 健康检查失败：%s"
                                % (feature["id"], health.get("detail")))
        if report["errors"]:
            problems.extend(report["errors"])

        required_routes = ("/api/health", "/api/features", "/api/nav", "/api/job")
        have = {r["pattern"] for r in self.context.router.describe()}
        for pattern in required_routes:
            if pattern not in have:
                problems.append("缺少核心路由：%s" % pattern)

        return (not problems), {"problems": problems, "registry": report,
                                "routes": self.context.router.describe()}

    # ------------------------------------------------------------ 生命周期
    def start(self, port=None, open_browser=False, host=None):
        """启动 HTTP 服务，返回访问 URL。"""
        url = self.server.start(port=port if port is not None else self.port,
                               host=host or self.bind, open_browser=open_browser)
        self.port = self.server.httpd.server_address[1]
        return url

    def stop(self):
        self.jobs.shutdown()
        self.server.stop()


# ---------------------------------------------------------------------------
# 旧实例回收（沿用 translation_tool/main.py:20-64 的成熟做法）
# ---------------------------------------------------------------------------
def _listener_pid(port):
    """返回占用 ``port`` 的 LISTENING 进程 PID；查不到返回 None。"""
    try:
        out = subprocess.run(["netstat", "-ano", "-p", "tcp"],
                             capture_output=True, text=True, timeout=30).stdout
    except Exception:
        return None
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 5 and "LISTENING" in line and parts[1].endswith(":%d" % port):
            try:
                return int(parts[-1])
            except ValueError:
                continue
    return None


def _is_our_server(port, timeout=3):
    """通过 ``/api/health`` 判断占用端口的是不是本工具。"""
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/api/health" % port,
                                    timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        name = ((payload or {}).get("app") or {}).get("name", "")
        return "RPG Maker" in str(name) or bool((payload or {}).get("ok"))
    except Exception:
        return False


def _port_in_use(port):
    """端口是否已被占用（不区分占用者）。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def kill_old_instance(port, assume_yes=True):
    """若端口被本工具的旧实例占用则结束它。返回被结束的 PID 或 None。

    只对"确认是本工具"的进程动手（先校验 ``/api/health``），避免误杀。
    """
    pid = _listener_pid(port)
    if not pid or not _is_our_server(port):
        return None
    try:
        probe = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-CimInstance Win32_Process -Filter 'ProcessId=%d').CommandLine" % pid],
            capture_output=True, text=True, timeout=20, encoding="utf-8",
            errors="replace")
        cmdline = (probe.stdout or "").strip()
        if cmdline and ("app.py" not in cmdline and "main.py" not in cmdline):
            return None
    except Exception:
        pass
    try:
        subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                       capture_output=True, timeout=20)
        time.sleep(0.8)
        return pid
    except Exception:
        return None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def build_parser():
    parser = argparse.ArgumentParser(
        prog="app.py", description="RPG Maker 全能工具（统一入口）")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT,
                        help="本地服务端口（默认 %d；填 0 取随机空闲端口）" % DEFAULT_PORT)
    parser.add_argument("--host", default="127.0.0.1",
                        help="绑定地址（默认仅本机 127.0.0.1）")
    parser.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    parser.add_argument("--dir", default="", help="启动后直接载入的游戏目录")
    parser.add_argument("--config", default=None, help="指定 config.json 路径")
    parser.add_argument("--check", action="store_true",
                        help="只做启动自检并打印报告，然后退出")
    parser.add_argument("--json", action="store_true", help="配合 --check 输出 JSON")
    parser.add_argument("--no-reclaim", action="store_true",
                        help="不回收占用端口的旧实例")
    return parser


def build_app(args=None):
    """按命令行参数构造并装配 :class:`App`（供测试复用）。"""
    args = args or build_parser().parse_args([])
    app = App(config_path=getattr(args, "config", None),
              port=getattr(args, "port", DEFAULT_PORT),
              bind=getattr(args, "host", "127.0.0.1"))
    app.build()
    return app


def main(argv=None):
    args = build_parser().parse_args(argv)

    app = App(config_path=args.config, port=args.port, bind=args.host)
    app.build()

    ok, report = app.check()

    print("=" * 66)
    print("%s v%s  (Python %s)" % (App.NAME, app.version, sys.version.split()[0]))
    print("工程根目录：%s" % paths.project_root())
    print(app.registry.describe())
    for feature_id, result in sorted(app.register_report.items()):
        print("  · 注册 %-10s -> %s" % (feature_id, result))
    print("已登记路由：%d 条" % len(app.context.router))
    ok_ref = app.registry.errors
    if ok_ref:
        print("注册表告警：")
        for message in ok_ref:
            print("  ! %s" % message)
    print("自检结果：%s" % ("通过" if ok else "未通过"))
    for problem in report["problems"]:
        print("  ✗ %s" % problem)
    print("=" * 66)

    if args.check:
        if args.json:
            print(json.dumps({"ok": ok, "app": app.version_info(), **report},
                             ensure_ascii=False, indent=2))
        app.stop()
        return 0 if ok else 1

    port = args.port
    if port == 0:
        port = ui_server.free_port()
    elif not args.no_reclaim:
        reclaimed = kill_old_instance(port)
        if reclaimed:
            print("已回收占用端口 %d 的旧实例（PID %s）" % (port, reclaimed))
        elif _port_in_use(port):
            print("提示：端口 %d 已被其它程序占用，将尝试改用随机端口。" % port)
            port = ui_server.free_port()

    try:
        url = app.start(port=port, open_browser=not args.no_browser)
    except OSError as exc:
        print("启动失败：%s" % exc)
        print("端口 %d 可能已被占用。请关闭占用该端口的程序后重试，"
              "或使用 --port 指定其它端口。" % port)
        app.stop()
        return 1

    print("界面已就绪：%s" % url)
    print("按 Ctrl+C 退出。")
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n正在退出…")
    finally:
        app.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())

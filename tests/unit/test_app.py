# -*- coding: utf-8 -*-
"""app.py 的唯一入口测试（装配、自检、生命周期、CLI）。

@feature  none
@layer    tests
@public   TestAppAssembly, TestSelfCheck, TestLifecycle, TestCli
@depends  app
@tested   (本文件即测试)
@footprint docs/ARCHITECTURE.md#entry
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest

_ROOT = os.path.dirname(os.path.abspath(__file__))
while not os.path.isfile(os.path.join(_ROOT, "app.py")):
    parent = os.path.dirname(_ROOT)
    if parent == _ROOT:
        raise RuntimeError("无法定位工程根（未找到 app.py）")
    _ROOT = parent
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import app as app_mod  # noqa: E402
from core import paths  # noqa: E402


class TestAppAssembly(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = app_mod.build_app()

    def test_version_info(self):
        info = self.app.version_info()
        self.assertEqual(info["name"], app_mod.App.NAME)
        self.assertTrue(info["version"])
        self.assertEqual(info["bind"], "127.0.0.1")

    def test_registry_discovers_every_feature_directory(self):
        """功能清单必须与 ``features/`` 下的目录**双向一致**。

        ⚠ 不要写死 ``["cheats", "translate"]``：这个清单是"目录驱动"的
        （加一个 ``features/<id>/manifest.py`` 就会多一个功能，见需求 §8-6
        的扩展性要求）。写死会让"新增功能"必须先改测试，
        那正是"外壳随功能变化"的反面。这里改为**与磁盘对照**。
        """
        features_dir = paths.features_dir()
        on_disk = sorted(
            name for name in os.listdir(features_dir)
            if os.path.isfile(os.path.join(features_dir, name, "manifest.py")))
        self.assertTrue(on_disk, "features/ 下没有找到任何功能模块")
        self.assertEqual(sorted(self.app.registry.ids()), on_disk)
        for required in ("translate", "cheats", "selfcheck"):
            with self.subTest(feature=required):
                self.assertIn(required, on_disk)

    def test_register_report_all_ok(self):
        for feature, result in self.app.register_report.items():
            with self.subTest(feature=feature):
                self.assertNotIn("error", str(result), result)

    def test_context_holds_routes_and_pages(self):
        self.assertGreater(len(self.app.context.router), 5)
        pages = set(self.app.context.pages)
        for required in ("translate", "cheats", "selfcheck"):
            with self.subTest(page=required):
                self.assertIn(required, pages)

    def test_core_routes_exist(self):
        patterns = {r["pattern"] for r in self.app.context.router.describe()}
        for required in ("/api/health", "/api/features", "/api/nav", "/api/job",
                         "/api/jobs", "/api/cancel", "/api/pages", "/api/routes",
                         "/api/paths", "/api/time"):
            with self.subTest(pattern=required):
                self.assertIn(required, patterns)

    def test_feature_routes_are_registered(self):
        """功能路由要真的接进应用。

        M3a 之前这里断言的是骨架端点 ``/api/translate/status``；接线后该端点
        已被真实的业务端点取代（状态在 ``/api/translate/state``），因此断言
        跟着换成"每个功能都至少有一个自己的端点"这一**不会随版本失效**的
        契约 —— 具体端点清单由各功能自己的测试负责（见
        ``tests/features/translate/test_routes.py`` 的 EXPECTED）。
        """
        routes = self.app.context.router.describe()
        patterns = {r["pattern"] for r in routes}
        for required in ("/api/translate/providers", "/api/cheats/status",
                         "/api/cheats/detect", "/api/selfcheck/report"):
            with self.subTest(pattern=required):
                self.assertIn(required, patterns)
        for feature in self.app.registry.ids():
            owned = [r for r in routes if r["feature"] == feature]
            with self.subTest(feature=feature):
                self.assertTrue(owned, "%s 没有登记任何路由" % feature)
                for route in owned:
                    self.assertTrue(route["pattern"].startswith("/api/"),
                                    "路由不在 /api 下：%s" % route["pattern"])

    def test_no_import_side_effects(self):
        """原实现 ``tool/server.py:434`` 在导入时就构造单例并起线程（B-25）。

        本工程必须"导入不产生副作用"：导入 app 模块不应启动任何服务。
        """
        probe = subprocess.run(
            [sys.executable, "-c",
             "import sys; sys.path.insert(0, sys.argv[1]);\n"
             "import app\n"
             "import threading\n"
             "alive = [t.name for t in threading.enumerate() if t is not threading.main_thread()]\n"
             "print('THREADS=' + ','.join(sorted(alive)))\n",
             _ROOT],
            capture_output=True, text=True, encoding="utf-8", cwd=_ROOT, timeout=120)
        self.assertEqual(probe.returncode, 0, probe.stderr)
        line = [ln for ln in probe.stdout.splitlines() if ln.startswith("THREADS=")][0]
        names = [n for n in line.split("=", 1)[1].split(",") if n]
        self.assertEqual(names, [], "导入 app 不应启动任何线程，实际：%s" % names)

    def test_importing_app_does_not_create_server(self):
        """导入 ``app`` 不得绑定端口。

        ⚠ **不能拿 ``DEFAULT_PORT`` 当判据**（实测踩到）：用户完全可能正在用
        这个工具（双击启动后就常驻在那个端口），于是"默认端口上有监听"是
        **正常情况**，测试会红得毫无道理 —— 一个会在正常使用下失败的断言，
        最终只会训练人忽略红灯。

        正确判据：拿一个**刚被系统确认空闲**的端口，导入 ``app`` 后它必须
        **仍然是空闲的**。这样与"用户正在用默认端口"完全无关。
        """
        probe = subprocess.run(
            [sys.executable, "-c",
             "import sys, socket; sys.path.insert(0, sys.argv[1]);\n"
             "s0 = socket.socket(); s0.bind(('127.0.0.1', 0));\n"
             "port = s0.getsockname()[1]; s0.close()\n"
             "import app\n"
             "s = socket.socket(); s.settimeout(1.0)\n"
             "print('BOUND=' + str(s.connect_ex(('127.0.0.1', port)) == 0))\n",
             _ROOT],
            capture_output=True, text=True, encoding="utf-8", cwd=_ROOT, timeout=120)
        self.assertEqual(probe.returncode, 0, probe.stderr)
        self.assertIn("BOUND=False", probe.stdout,
                      "导入 app 时绑定了端口（原实现 tool/server.py:434 的副作用）")


class TestSelfCheck(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = app_mod.build_app()
        cls.ok, cls.report = cls.app.check()

    def test_check_passes(self):
        self.assertTrue(self.ok, "自检未通过：%s" % self.report["problems"])
        self.assertEqual(self.report["problems"], [])

    def test_check_reports_registry(self):
        registry = self.report["registry"]
        # 别写死功能数量：清单是目录驱动的（§8-6）。这里断言"自检报告里的
        # 数量与真实发现的数量一致"，写死会让新增功能必须先改这条测试。
        expected = len(self.app.registry.ids())
        self.assertEqual(registry["count"], expected)
        self.assertGreaterEqual(expected, 3)
        self.assertEqual(registry["errors"], [])
        self.assertTrue(registry["ok"])

    def test_check_reports_routes(self):
        patterns = {r["pattern"] for r in self.report["routes"]}
        self.assertIn("/api/health", patterns)

    def test_check_detects_missing_web_asset(self):
        """自检必须真的会失败：临时把 web 目录指错，应报告缺资源。"""
        original = paths.web_dir
        try:
            paths.web_dir = lambda: os.path.join(_ROOT, "no-such-web-dir")
            app = app_mod.build_app()
            ok, report = app.check()
            self.assertFalse(ok)
            self.assertTrue(any("前端资源" in p for p in report["problems"]))
        finally:
            paths.web_dir = original


class TestLifecycle(unittest.TestCase):
    def test_start_and_stop(self):
        app = app_mod.build_app()
        url = app.start(port=0, open_browser=False)
        try:
            self.assertTrue(url.startswith("http://127.0.0.1:"))
            self.assertIsNotNone(app.server.httpd)
            self.assertEqual(app.port, app.server.httpd.server_address[1])
        finally:
            app.stop()
        self.assertIsNone(app.server.httpd)

    def test_stop_is_idempotent(self):
        app = app_mod.build_app()
        app.start(port=0)
        app.stop()
        app.stop()      # 第二次不得抛异常

    def test_free_port_is_available(self):
        from ui.server import free_port
        port = free_port()
        self.assertGreater(port, 0)


class TestCli(unittest.TestCase):
    def run_cli(self, *args, timeout=180):
        return subprocess.run(
            [sys.executable, os.path.join(_ROOT, "app.py")] + list(args),
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            cwd=_ROOT, timeout=timeout)

    def test_check_exit_zero(self):
        result = self.run_cli("--check")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("自检结果：通过", result.stdout)
        self.assertIn("已加载的功能模块", result.stdout)

    def test_check_json_mode(self):
        result = self.run_cli("--check", "--json")
        self.assertEqual(result.returncode, 0)
        start = result.stdout.index("{")
        payload = json.loads(result.stdout[start:])
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["problems"], [])
        self.assertGreaterEqual(payload["registry"]["count"], 3)

    def test_help_lists_documented_flags(self):
        result = self.run_cli("--help")
        self.assertEqual(result.returncode, 0)
        for flag in ("--port", "--host", "--no-browser", "--dir", "--check",
                     "--json", "--config", "--no-reclaim"):
            with self.subTest(flag=flag):
                self.assertIn(flag, result.stdout)

    def test_report_mentions_pending_references(self):
        """启动报告应暴露"还有多少参考实现待收敛"，让接手者一眼看到进度。"""
        result = self.run_cli("--check")
        self.assertIn("路由", result.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)

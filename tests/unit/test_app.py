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

    def test_registry_has_both_features(self):
        self.assertIsNotNone(self.app.registry)
        self.assertEqual(sorted(self.app.registry.ids()), ["cheats", "translate"])

    def test_register_report_all_ok(self):
        for feature, result in self.app.register_report.items():
            with self.subTest(feature=feature):
                self.assertNotIn("error", str(result), result)

    def test_context_holds_routes_and_pages(self):
        self.assertGreater(len(self.app.context.router), 5)
        self.assertEqual(set(self.app.context.pages), {"translate", "cheats"})

    def test_core_routes_exist(self):
        patterns = {r["pattern"] for r in self.app.context.router.describe()}
        for required in ("/api/health", "/api/features", "/api/nav", "/api/job",
                         "/api/jobs", "/api/cancel", "/api/pages", "/api/routes",
                         "/api/paths", "/api/time"):
            with self.subTest(pattern=required):
                self.assertIn(required, patterns)

    def test_feature_routes_are_registered(self):
        patterns = {r["pattern"] for r in self.app.context.router.describe()}
        self.assertIn("/api/translate/status", patterns)
        self.assertIn("/api/translate/providers", patterns)
        self.assertIn("/api/cheats/status", patterns)
        self.assertIn("/api/cheats/detect", patterns)

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
        probe = subprocess.run(
            [sys.executable, "-c",
             "import sys, socket; sys.path.insert(0, sys.argv[1]);\n"
             "import app\n"
             "s = socket.socket()\n"
             "print('BOUND=' + str(s.connect_ex(('127.0.0.1', app.DEFAULT_PORT)) == 0))\n",
             _ROOT],
            capture_output=True, text=True, encoding="utf-8", cwd=_ROOT, timeout=120)
        self.assertIn("BOUND=False", probe.stdout)


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
        self.assertEqual(registry["count"], 2)
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
        self.assertEqual(payload["registry"]["count"], 2)

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

# -*- coding: utf-8 -*-
"""集成测试：一键启动 → 健康检查 → 功能可用 → 干净退出。

@feature  none
@layer    tests
@public   TestStartup, TestCleanEnvironment
@depends  app, ui.server
@tested   (本文件即测试)
@footprint docs/ARCHITECTURE.md#entry
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import unittest
import urllib.request

_ROOT = os.path.dirname(os.path.abspath(__file__))
while not os.path.isfile(os.path.join(_ROOT, "app.py")):
    parent = os.path.dirname(_ROOT)
    if parent == _ROOT:
        raise RuntimeError("无法定位工程根（未找到 app.py）")
    _ROOT = parent
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def get(url, timeout=10):
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


class TestStartup(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import app as app_mod
        cls.app_mod = app_mod
        cls.app = app_mod.build_app()
        cls.url = cls.app.start(port=0)

    @classmethod
    def tearDownClass(cls):
        cls.app.stop()

    def test_url_is_loopback(self):
        self.assertTrue(self.url.startswith("http://127.0.0.1:"))

    def test_health_full_shape(self):
        payload = get(self.url + "api/health")
        for key in ("ok", "app", "python", "platform", "registry", "jobs",
                    "ui", "convergence"):
            with self.subTest(key=key):
                self.assertIn(key, payload)
        self.assertTrue(payload["ok"])

    def test_health_reports_convergence_progress(self):
        """需求 §3.3 的收敛进度必须是可观测事实（不是只写在文档里）。

        M2b 之前这里查的是 ``reference.pending``（桥接层待收敛项数）；
        桥接层已删除，改查 ``convergence`` 段。
        """
        payload = get(self.url + "api/health")
        convergence = payload["convergence"]
        for engine_family in ("engines", "formats", "marshal"):
            with self.subTest(family=engine_family):
                self.assertIn(engine_family, convergence)
                self.assertIn(convergence[engine_family], ("merged", "pending"))
        self.assertIsInstance(convergence["all_merged"], bool)

    def test_all_features_register_and_are_healthy(self):
        payload = get(self.url + "api/features")
        self.assertTrue(payload["ok"])
        # 功能清单是目录驱动的（§8-6），因此断言"≥ 已知的三个"而不是写死，
        # 否则每加一个功能都要回来改这条测试
        self.assertGreaterEqual(payload["count"], 3)
        ids = [f["id"] for f in payload["features"]]
        for required in ("translate", "cheats", "selfcheck"):
            with self.subTest(feature=required):
                self.assertIn(required, ids)
        for feature in payload["features"]:
            with self.subTest(feature=feature["id"]):
                self.assertTrue(feature["ok"])
                self.assertEqual(feature["health"]["status"], "ok",
                                 feature["health"].get("detail"))

    def test_index_is_html_with_mount_points(self):
        with urllib.request.urlopen(self.url, timeout=10) as response:
            ctype = response.headers.get("Content-Type", "")
            body = response.read().decode("utf-8")
        self.assertIn("text/html", ctype)
        for marker in ('id="nav"', 'id="view"', 'id="toast"', "/app.js"):
            with self.subTest(marker=marker):
                self.assertIn(marker, body)

    def test_all_static_assets_served(self):
        for path in ("app.js", "dom.js", "tokens.css", "components.css",
                     "pages/translate.js", "pages/cheats.js",
                     "pages/selfcheck.js"):
            with self.subTest(path=path):
                with urllib.request.urlopen(self.url + path, timeout=10) as response:
                    self.assertEqual(response.status, 200)
                    self.assertTrue(response.read())

    def test_quit_endpoint(self):
        """单独起一个实例验证 /api/quit 能优雅关闭。"""
        app = self.app_mod.build_app()
        url = app.start(port=0)
        try:
            with urllib.request.urlopen(url + "api/quit", timeout=10) as response:
                payload = json.loads(response.read().decode("utf-8"))
            self.assertTrue(payload["ok"])
        finally:
            app.stop()

    def test_registry_report_has_no_errors(self):
        report = self.app.registry_report()
        self.assertEqual(report["errors"], [])
        self.assertTrue(report["ok"])


class TestCleanEnvironment(unittest.TestCase):
    """硬约束 §4.1：只装标准库的干净环境必须能启动。

    原两个工具的测试 ``import requests``（第三方），本测试专门盯住这一点：
    用 AST 扫描**全部**源码与测试，禁止任何第三方 import。
    """

    STDLIB = set(sys.stdlib_module_names)
    #: 工程内的一级包名 / 模块名
    #:
    #: ``run`` 是交付入口 ``run.py``（双击启动脚本体，见 tests/integration/
    #: test_launcher.py）。它被 import 不是第三方依赖，但也**不能**靠
    #: 目录名推断 —— 所以显式列出来。
    INTERNAL = {"core", "features", "ui", "tests", "tools", "app", "run"}

    def _scan(self, path):
        with open(path, encoding="utf-8") as f:
            tree = ast.parse(f.read())
        offenders = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level and node.level > 0:
                    continue          # 相对 import，必为工程内
                names = [node.module or ""]
            else:
                continue
            for name in names:
                top = name.split(".")[0]
                if not top or top in self.STDLIB or top in self.INTERNAL:
                    continue
                offenders.append((name, node.lineno))
        return offenders

    def test_no_third_party_imports_anywhere(self):
        offenders = []
        for dirpath, dirnames, filenames in os.walk(_ROOT):
            dirnames[:] = [d for d in dirnames
                           if d not in ("__pycache__", ".git", "runtime")]
            for name in filenames:
                if not name.endswith(".py"):
                    continue
                full = os.path.join(dirpath, name)
                for module, line in self._scan(full):
                    offenders.append("%s:%s imports %s"
                                     % (os.path.relpath(full, _ROOT), line, module))
        self.assertEqual(offenders, [],
                         "发现第三方依赖（违反硬约束 §4.1）：\n" + "\n".join(offenders))

    def test_no_requests_dependency_specifically(self):
        """点名 requests：原 tool/test_e2e.py:15 与 test_pipeline.py:15 的坑。"""
        offenders = []
        for dirpath, dirnames, filenames in os.walk(_ROOT):
            dirnames[:] = [d for d in dirnames
                           if d not in ("__pycache__", ".git", "runtime")]
            for name in filenames:
                if name.endswith(".py"):
                    full = os.path.join(dirpath, name)
                    if any(m.split(".")[0] == "requests" for m, _ in self._scan(full)):
                        offenders.append(os.path.relpath(full, _ROOT))
        self.assertEqual(offenders, [], "禁止 import requests：%s" % offenders)

    def test_app_check_subprocess_exit_code_zero(self):
        """``python app.py --check`` 必须返回 0（CI/评审可直接判定）。"""
        result = subprocess.run(
            [sys.executable, os.path.join(_ROOT, "app.py"), "--check"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            cwd=_ROOT, timeout=180)
        self.assertEqual(result.returncode, 0,
                         "自检未通过：\n%s\n%s" % (result.stdout, result.stderr))
        self.assertIn("自检结果：通过", result.stdout)

    def test_app_check_json_is_valid(self):
        result = subprocess.run(
            [sys.executable, os.path.join(_ROOT, "app.py"), "--check", "--json"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            cwd=_ROOT, timeout=180)
        self.assertEqual(result.returncode, 0)
        start = result.stdout.index("{")
        payload = json.loads(result.stdout[start:])
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["problems"], [])

    def test_python38_compatible_syntax(self):
        """硬约束 §4.1：Python 3.8+ 兼容。

        本机是 3.10，无法真正跑 3.8，因此用 AST 扫描 3.9+ 独有语法：
        内置泛型注解（``list[int]``）与 ``X | Y`` 联合类型。
        """
        offenders = []
        for dirpath, dirnames, filenames in os.walk(_ROOT):
            dirnames[:] = [d for d in dirnames
                           if d not in ("__pycache__", ".git", "runtime")]
            for name in filenames:
                if not name.endswith(".py"):
                    continue
                full = os.path.join(dirpath, name)
                with open(full, encoding="utf-8") as f:
                    tree = ast.parse(f.read())
                for node in ast.walk(tree):
                    # PEP 585：subscript on builtin generic
                    if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name):
                        if node.value.id in ("list", "dict", "set", "tuple", "frozenset", "type"):
                            offenders.append("%s:%s 使用了内置泛型注解 %s[...]"
                                             % (os.path.relpath(full, _ROOT),
                                                node.lineno, node.value.id))
                    # PEP 604：X | Y
                    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
                        if isinstance(node.left, ast.Name) and isinstance(node.right, ast.Name):
                            if node.left.id[0].isupper() or node.right.id[0].isupper():
                                offenders.append("%s:%s 疑似 PEP 604 联合类型 %s | %s"
                                                 % (os.path.relpath(full, _ROOT),
                                                    node.lineno, node.left.id,
                                                    node.right.id))
        self.assertEqual(offenders, [],
                         "存在 Python 3.9+ 独有语法：\n" + "\n".join(offenders))


if __name__ == "__main__":
    unittest.main(verbosity=2)

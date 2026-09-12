# -*- coding: utf-8 -*-
"""「环境自检」功能的自有测试（+ 需求 §8-6 扩展性演示的**证据**）。

@feature  selfcheck
@layer    tests
@public   TestSelfcheckModule, TestReportEndpoint, TestExtensibilityProof
@depends  features.selfcheck.manifest, core.registry
@tested   (本文件即测试)
@footprint docs/FEATURES.md#selfcheck

需求 §8-6 原文
--------------
「现场新增一个最小功能，只用契约规定的方式即可让它出现在界面上
（可保留在 `docs/DEVLOG.md` 作为演示）。」

本文件把这个"演示"变成**可重复执行的断言**，而不是"我们试过一次，
你看截图"：

* 功能被注册表自动发现，且导航里有它（``/api/nav``）；
* 路由登记在它自己声明的 ``api_prefix`` 下；
* 页面模块存在并导出 ``render``；
* **外壳（app.py / ui/server.py / ui/web/index.html / ui/web/app.js）
  里没有这个功能的名字** —— 这是"零外壳改动"最强的静态证据。
"""

from __future__ import annotations

import os
import re
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

from core import registry as registry_mod  # noqa: E402
from core.context import AppContext  # noqa: E402


class TestSelfcheckModule(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reg = registry_mod.Registry().discover()
        cls.module = cls.reg.get("selfcheck")

    def test_registered(self):
        self.assertIsNotNone(self.module, "selfcheck 功能未被 registry 发现")

    def test_manifest_required_fields(self):
        for field in ("id", "name", "icon", "version", "description"):
            with self.subTest(field=field):
                self.assertTrue(self.module.manifest.get(field))

    def test_api_prefix(self):
        self.assertEqual(self.module.api_prefix, "/api/selfcheck")

    def test_declares_page_and_file_exists(self):
        self.assertTrue(self.module.pages)
        page = self.module.pages[0]
        js = os.path.join(_ROOT, "ui", "web", "pages", "%s.js" % page["module"])
        self.assertTrue(os.path.isfile(js), "缺少页面文件 %s" % js)

    def test_page_exports_render(self):
        page = self.module.pages[0]
        js = os.path.join(_ROOT, "ui", "web", "pages", "%s.js" % page["module"])
        with open(js, encoding="utf-8") as f:
            self.assertIn("export async function render", f.read())

    def test_health_ok(self):
        health = self.module.health()
        self.assertEqual(health["status"], "ok", health.get("detail"))

    def test_feature_appears_in_nav(self):
        """**§8-6 的核心断言**：导航里必须自动出现，不需要改外壳。"""
        items = [m.nav_entry() for m in self.reg.enabled()]
        ids = [item["id"] for item in items]
        self.assertIn("selfcheck", ids, "导航里没有出现新功能：%s" % ids)
        entry = [i for i in items if i["id"] == "selfcheck"][0]
        self.assertTrue(entry["ok"], entry.get("error"))
        self.assertEqual([p["id"] for p in entry["pages"]], ["selfcheck"])


class TestReportEndpoint(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from features.selfcheck import manifest as selfcheck_manifest
        cls.ctx = AppContext()
        selfcheck_manifest.register(cls.ctx)
        route, _params = cls.ctx.router.resolve("GET", "/api/selfcheck/report")
        # staticmethod 包裹再取 __func__ 以避开描述符绑定（见 tests/features/cheats
        # 的说明：裸函数赋成类属性后会变成 bound method，调用时多传一个 self）
        cls.report = staticmethod(route.handler).__func__(None)

    def test_route_registered_under_prefix(self):
        patterns = [r.pattern for r in self.ctx.router.routes()]
        for pattern in patterns:
            with self.subTest(pattern=pattern):
                self.assertTrue(pattern.startswith("/api/selfcheck"))

    def test_report_shape(self):
        payload = self.report
        self.assertTrue(payload["ok"])
        for key in ("python", "paths", "assembly", "convergence", "engines",
                    "safety"):
            with self.subTest(key=key):
                self.assertIn(key, payload)

    def test_report_is_json_serialisable(self):
        import json
        json.dumps(self.report, ensure_ascii=False)

    def test_report_reports_convergence_and_python(self):
        payload = self.report
        self.assertEqual(payload["convergence"]["marshal"], "merged")
        self.assertEqual(payload["convergence"]["formats"], "merged")
        self.assertTrue(payload["python"]["supports_3_8_syntax"])
        self.assertTrue(payload["paths"]["runtime_writable"])

    def test_report_lists_all_features(self):
        payload = self.report
        # 直接 register 时没有 app.registry，功能列表为空 —— 这是允许的
        self.assertIn("features", payload["assembly"])
        self.assertIn("route_count", payload["assembly"])


class TestExtensibilityProof(unittest.TestCase):
    """**§8-6 的静态证据**：外壳里没有这个功能的名字。"""

    #: 外壳文件（不该随功能变化）
    SHELL = ("app.py", "ui/server.py", "ui/web/index.html", "ui/web/app.js")

    def test_shell_never_mentions_the_new_feature(self):
        for rel in self.SHELL:
            path = os.path.join(_ROOT, rel)
            if not os.path.isfile(path):
                continue
            with open(path, encoding="utf-8") as f:
                content = f.read()
            with self.subTest(file=rel):
                self.assertNotIn(
                    "selfcheck", content,
                    "%s 里出现了新功能的名字 —— 那就不再是「零外壳改动」了" % rel)

    def test_new_feature_is_only_three_files(self):
        """新功能的**源码**只有两处 python 文件：包标记 + manifest。

        （页面 js 在 ``ui/web/pages/``，测试与文档不算 —— 需求 §4.1 的
        "变更三连"要求它们同时更新。）
        """
        candidates = []
        for base, dirs, files in os.walk(os.path.join(_ROOT, "features", "selfcheck")):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for name in files:
                if name.endswith(".py"):
                    candidates.append(os.path.relpath(os.path.join(base, name), _ROOT))
        candidates.sort()
        self.assertEqual(candidates,
                         [os.path.join("features", "selfcheck", "__init__.py"),
                          os.path.join("features", "selfcheck", "manifest.py")])

    def test_no_footprint_registration_needed_in_code(self):
        """功能清单来自注册表扫描，不是写死在某个列表里。"""
        text = open(os.path.join(_ROOT, "app.py"), encoding="utf-8").read()
        self.assertNotIn("FEATURES = [", text)
        self.assertNotIn("feature_ids", text)

    def test_registry_scan_is_directory_driven(self):
        text = open(os.path.join(_ROOT, "core", "registry.py"),
                    encoding="utf-8").read()
        self.assertIn("os.listdir", text,
                      "功能发现应当是「列目录」，而不是 pkgutil 的包判定（N-04）")
        self.assertNotIn("REQUIRED_FEATURES", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)

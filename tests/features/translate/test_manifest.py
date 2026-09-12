# -*- coding: utf-8 -*-
"""功能模块自有测试：translate（需求 §5.1 要求每个功能自带测试）。

@feature  translate
@layer    tests
@public   TestTranslateModule
@depends  features.translate.manifest
@tested   (本文件即测试)
@footprint docs/FEATURES.md#translate
"""

from __future__ import annotations

import os
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


class TestTranslateModule(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reg = registry_mod.Registry().discover()
        cls.module = cls.reg.get("translate")

    def test_registered(self):
        self.assertIsNotNone(self.module, "translate 功能未被 registry 发现")

    def test_manifest_required_fields(self):
        for field in ("id", "name", "icon", "version", "description"):
            with self.subTest(field=field):
                self.assertTrue(self.module.manifest.get(field))

    def test_api_prefix(self):
        self.assertEqual(self.module.api_prefix, "/api/translate")

    def test_declares_page_and_file_exists(self):
        self.assertTrue(self.module.pages)
        page = self.module.pages[0]
        js = os.path.join(_ROOT, "ui", "web", "pages", "%s.js" % page["module"])
        self.assertTrue(os.path.isfile(js), "缺少页面文件 %s" % js)

    def test_page_exports_render(self):
        page = self.module.pages[0]
        js = os.path.join(_ROOT, "ui", "web", "pages", "%s.js" % page["module"])
        with open(js, encoding="utf-8") as f:
            content = f.read()
        self.assertIn("export async function render", content)

    def test_core_deps_declared(self):
        deps = self.module.core_deps
        self.assertIn("core.engines", deps)
        self.assertIn("core.textutil", deps)
        self.assertIn("core.safety.backup", deps)

    def test_health_ok(self):
        health = self.module.health()
        self.assertEqual(health["status"], "ok", health.get("detail"))

    def test_providers_endpoint_lists_four_engines(self):
        """四个翻译引擎适配器必须都在（功能等价性：原工具 4 个，不得缩水）。"""
        from features.translate import manifest as translate_manifest
        from core.context import AppContext
        ctx = AppContext()
        translate_manifest.register(ctx)
        route, _ = ctx.router.resolve("GET", "/api/translate/providers")
        self.assertIsNotNone(route)
        payload = route.handler(None)
        ids = {p["id"] for p in payload["providers"]}
        self.assertEqual(ids, {"google", "openai", "ollama", "deepl"})

    def test_translators_module_is_stdlib_only(self):
        """translators 必须只用标准库（出网走 urllib）。"""
        import ast
        path = os.path.join(_ROOT, "features", "translate", "translators.py")
        with open(path, encoding="utf-8") as f:
            tree = ast.parse(f.read())
        allowed_third_party = set()
        stdlib = set(sys.stdlib_module_names)
        offenders = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    if top not in stdlib and top not in ("core", "features"):
                        offenders.append(alias.name)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                top = node.module.split(".")[0]
                if top not in stdlib and top not in ("core", "features"):
                    offenders.append(node.module)
        self.assertEqual(offenders, [],
                         "translators 引入了非标准库依赖：%s" % offenders)


if __name__ == "__main__":
    unittest.main(verbosity=2)

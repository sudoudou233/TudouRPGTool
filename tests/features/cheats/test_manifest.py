# -*- coding: utf-8 -*-
"""功能模块自有测试：cheats（需求 §5.1 要求每个功能自带测试）。

@feature  cheats
@layer    tests
@public   TestCheatsModule, TestDetectEndpoint
@depends  features.cheats.manifest
@tested   (本文件即测试)
@footprint docs/FEATURES.md#cheats
"""

from __future__ import annotations

import os
import sys
import tempfile
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


def make_game(root, files):
    for name in files:
        full = os.path.join(root, name.replace("/", os.sep))
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as f:
            f.write("{}" if name.endswith(".json") else "x")


class TestCheatsModule(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reg = registry_mod.Registry().discover()
        cls.module = cls.reg.get("cheats")

    def test_registered(self):
        self.assertIsNotNone(self.module, "cheats 功能未被 registry 发现")

    def test_manifest_required_fields(self):
        for field in ("id", "name", "icon", "version", "description"):
            with self.subTest(field=field):
                self.assertTrue(self.module.manifest.get(field))

    def test_api_prefix(self):
        self.assertEqual(self.module.api_prefix, "/api/cheats")

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

    def test_core_deps_cover_all_five_engine_families(self):
        """功能等价性：原工具覆盖 MV/MZ/VX Ace/VX/XP + 2000/2003 识别，不得缩水。"""
        deps = set(self.module.core_deps)
        for required in ("core.engines", "core.constants", "core.formats.mv_save",
                         "core.formats.rgss_save", "core.formats.lzstring",
                         "core.marshal.doc_model", "core.safety.atomic"):
            with self.subTest(dep=required):
                self.assertIn(required, deps)

    def test_health_ok(self):
        health = self.module.health()
        self.assertEqual(health["status"], "ok", health.get("detail"))


class TestDetectEndpoint(unittest.TestCase):
    """``/api/cheats/detect`` 在 M1 就已可用，因此必须真的测通。"""

    @classmethod
    def setUpClass(cls):
        from features.cheats import manifest as cheats_manifest
        cls.ctx = AppContext()
        cheats_manifest.register(cls.ctx)
        route, _ = cls.ctx.router.resolve("POST", "/api/cheats/detect")
        # ⚠ 非显然陷阱（M1 实测踩到）：把**普通函数**赋成类属性后，通过
        # self.handler 取会触发描述符协议，变成 bound method —— 于是
        # handler(Request) 会多传一个 self，抛
        # "takes from 0 to 1 positional arguments but 2 were given"。
        # 包一层 staticmethod 即可拿到原函数本身。
        cls.handler = staticmethod(route.handler)

    def call(self, **body):
        from ui.server import Request
        return self.handler(Request("POST", "/api/cheats/detect", {}, body, {}))

    # ⚠ unittest 陷阱（M1 实测踩到）：测试方法的第一个参数是 self，
    # 若写成 def test_x(self, request=None)，unittest 会把 self 当作
    # request 传进去，抛 "takes from 0 to 1 positional arguments but 2 were given"。
    # 因此测试方法里不要出现名为 request 的参数。
    def test_requires_dir(self):
        result = self.call()
        self.assertFalse(result["ok"])
        self.assertIn("dir", result["error"])

    def test_unknown_engine(self):
        with tempfile.TemporaryDirectory(prefix="nogame_") as tmp:
            result = self.call(dir=tmp)
        self.assertFalse(result["ok"])
        self.assertIn("未识别", result["error"])

    def test_detects_vxace_with_saves(self):
        with tempfile.TemporaryDirectory(prefix="ace_") as tmp:
            make_game(tmp, ["Data/Items.rvdata2", "Save01.rvdata2",
                            "Save02.rvdata2"])
            result = self.call(dir=tmp)
        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(result["engine"], "vxace")
        self.assertEqual(result["saves"], ["Save01.rvdata2", "Save02.rvdata2"])
        self.assertEqual(result["save_ext"], ".rvdata2")
        self.assertTrue(result["supported"])

    def test_detects_mv_with_saves(self):
        with tempfile.TemporaryDirectory(prefix="mv_") as tmp:
            make_game(tmp, ["js/rpg_core.js", "data/System.json",
                            "save/file0.rpgsave"])
            result = self.call(dir=tmp)
        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(result["engine"], "mv")
        self.assertEqual(result["saves"], ["file0.rpgsave"])

    def test_detects_mz_with_saves(self):
        with tempfile.TemporaryDirectory(prefix="mz_") as tmp:
            make_game(tmp, ["js/rmmz_core.js", "data/System.json",
                            "save/file0.rmmzsave"])
            result = self.call(dir=tmp)
        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(result["engine"], "mz")
        self.assertEqual(result["saves"], ["file0.rmmzsave"])

    def test_reports_multiple_save_dirs(self):
        """多套存档（自动存档）：必须提示，而不是只处理一个目录。"""
        with tempfile.TemporaryDirectory(prefix="multi_") as tmp:
            make_game(tmp, ["js/rpg_core.js", "data/System.json",
                            "save/file0.rpgsave", "save/auto/file0.rpgsave"])
            result = self.call(dir=tmp)
        self.assertTrue(result["ok"])
        self.assertGreaterEqual(len(result["save_dirs"]), 2)

    def test_2k3_recognized_but_unsupported(self):
        with tempfile.TemporaryDirectory(prefix="2k3_") as tmp:
            make_game(tmp, ["RPG_RT.ini"])
            result = self.call(dir=tmp)
        self.assertTrue(result["ok"])
        self.assertEqual(result["engine"], "2k3")
        self.assertFalse(result["supported"])
        self.assertEqual(result["saves"], [])

    def test_summary_is_human_readable(self):
        with tempfile.TemporaryDirectory(prefix="sum_") as tmp:
            make_game(tmp, ["Data/Items.rxdata"])
            result = self.call(dir=tmp)
        self.assertIn("RPG Maker XP", result["summary"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

# -*- coding: utf-8 -*-
"""参考实现桥接层的专用测试（登记表完整性 + 可用性探测）。

@feature  none
@layer    tests
@public   TestReferenceRegistry, TestLoadReference, TestReferenceStatus
@depends  core._refbridge, core.paths
@tested   (本文件即测试)
@footprint docs/MODULES.md#core_refbridge
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

from core import _refbridge, paths  # noqa: E402


class TestReferenceRegistry(unittest.TestCase):
    def test_entries_are_three_tuples(self):
        for name, entry in _refbridge.REFERENCES.items():
            with self.subTest(name=name):
                self.assertEqual(len(entry), 3,
                                 "登记项必须是 (kind, module, purpose)")
                kind, module, purpose = entry
                self.assertIn(kind, ("translate", "cheats"))
                self.assertTrue(module)
                self.assertTrue(purpose)

    def test_kinds_exist_in_paths(self):
        for name, (kind, _module, _purpose) in _refbridge.REFERENCES.items():
            with self.subTest(name=name):
                self.assertIn(kind, paths.REFERENCE_TOOLS)

    def test_all_entries_have_unique_module_targets_within_kind(self):
        seen = set()
        for kind, module, _purpose in _refbridge.REFERENCES.values():
            key = (kind, module)
            with self.subTest(key=key):
                self.assertNotIn(key, seen, "同一参考模块被登记了两次")
                seen.add(key)


class TestLoadReference(unittest.TestCase):
    def test_unregistered_name_is_rejected(self):
        """登记表的意义：随手 import 参考实现必须失败，否则 M2b 无法逐条收敛。"""
        for bad in ("os", "sys", "requests", "marshal", "not-registered"):
            with self.subTest(name=bad):
                with self.assertRaises(KeyError):
                    _refbridge.load_reference(bad)

    def test_error_message_lists_registered_names(self):
        try:
            _refbridge.load_reference("nope")
        except KeyError as exc:
            self.assertIn("_refbridge", str(exc))
        else:
            self.fail("应抛 KeyError")

    def test_missing_reference_dir_raises_reference_unavailable(self):
        original = os.environ.get(paths.ENV_REFERENCE_ROOT)
        os.environ[paths.ENV_REFERENCE_ROOT] = os.path.join(
            os.path.abspath(os.sep), "no-such-reference-root-xyz")
        try:
            with self.assertRaises(_refbridge.ReferenceUnavailable):
                _refbridge.load_reference("rmarshal")
        finally:
            if original is None:
                os.environ.pop(paths.ENV_REFERENCE_ROOT, None)
            else:
                os.environ[paths.ENV_REFERENCE_ROOT] = original

    def test_loads_registered_module_when_available(self):
        if not paths.reference_available("cheats"):
            self.skipTest("参考工具目录不可用")
        module = _refbridge.load_reference("lzstring")
        self.assertTrue(hasattr(module, "compress"))
        self.assertTrue(hasattr(module, "decompress"))

    @unittest.skipUnless(paths.reference_available("translate"),
                         "翻译工具参考目录不可用")
    def test_loads_package_style_reference(self):
        """翻译工具是包内绝对 import，桥接层必须能把工具目录加进 sys.path。"""
        module = _refbridge.load_reference("tool.textutil")
        self.assertTrue(hasattr(module, "split_text"))


class TestReferenceStatus(unittest.TestCase):
    def test_report_shape(self):
        report = _refbridge.reference_status()
        for key in ("reference_root", "tools", "entries", "pending"):
            with self.subTest(key=key):
                self.assertIn(key, report)

    def test_tools_cover_both_kinds(self):
        report = _refbridge.reference_status()
        self.assertEqual(set(report["tools"]), {"translate", "cheats"})
        for kind, info in report["tools"].items():
            with self.subTest(kind=kind):
                self.assertIn("path", info)
                self.assertIn("available", info)
                self.assertIsInstance(info["available"], bool)

    def test_entries_mirror_registry(self):
        report = _refbridge.reference_status()
        self.assertEqual(len(report["entries"]), len(_refbridge.REFERENCES))
        for entry in report["entries"]:
            with self.subTest(name=entry["name"]):
                self.assertIn(entry["name"], _refbridge.REFERENCES)

    def test_pending_lists_everything(self):
        self.assertEqual(sorted(_refbridge.pending_references()),
                         sorted(_refbridge.REFERENCES))

    def test_pending_count_is_reported(self):
        """pending 数即"还有多少参考实现没收敛"，是 M2b 的进度指标。"""
        report = _refbridge.reference_status()
        self.assertGreater(report["pending"], 0,
                           "M1 阶段必然还有待收敛的参考实现")


if __name__ == "__main__":
    unittest.main(verbosity=2)

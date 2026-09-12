# -*- coding: utf-8 -*-
"""其余 core 模块的单元测试：constants / config / paths / textutil / refbridge。

@feature  none
@layer    tests
@public   TestConstants, TestConfig, TestPaths, TestTextutil, TestRefbridge
@depends  core.constants, core.config, core.paths, core.textutil, core._refbridge
@tested   (本文件即测试)
@footprint docs/MODULES.md#core
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

from core import _refbridge, config as config_mod, constants, paths, textutil  # noqa: E402


class TestConstants(unittest.TestCase):
    def test_params_unique_and_ordered(self):
        self.assertEqual(list(constants.PARAMS),
                         ["最大HP", "最大MP", "攻击", "防御", "魔攻", "魔防",
                          "速度", "幸运"])
        self.assertEqual(len(set(constants.PARAMS)), 8)

    def test_param_labels_consistent(self):
        for index, name in constants.PARAM_LABELS.items():
            self.assertEqual(constants.PARAMS[index], name)

    def test_engine_order_covers_all_engines(self):
        self.assertEqual(set(constants.ENGINE_ORDER), set(constants.ENGINES))

    def test_save_patterns_compile(self):
        import re
        for engine, (pattern, human) in constants.SAVE_PATTERNS.items():
            with self.subTest(engine=engine):
                re.compile(pattern)
                self.assertTrue(human)
                self.assertIn(engine, constants.SAVE_EXTS)

    def test_patterns_match_expected_names(self):
        import re
        samples = {
            "vxace": ("Save01.rvdata2", "file0.rvdata2"),
            "vx": ("Save01.rvdata", "Save01.rvdata2"),
            "xp": ("Save01.rxdata", "Save01.rvdata"),
            "mv": ("file0.rpgsave", "file0.rmmzsave"),
            "mz": ("file0.rmmzsave", "file0.rpgsave"),
        }
        for engine, (good, bad) in samples.items():
            pattern = re.compile(constants.SAVE_PATTERNS[engine][0])
            with self.subTest(engine=engine):
                self.assertTrue(pattern.match(good), "%s 应匹配 %s" % (engine, good))
                self.assertFalse(pattern.match(bad), "%s 不应匹配 %s" % (engine, bad))

    def test_supported_vs_recognize_only_do_not_overlap(self):
        overlap = set(constants.SUPPORTED_ENGINES) & set(constants.RECOGNIZE_ONLY_ENGINES)
        self.assertEqual(overlap, set())


class TestConfig(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="cfg_")
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "config.json")

    def test_defaults_when_missing(self):
        cfg = config_mod.AppConfig.load(self.path)
        self.assertEqual(cfg.engine, config_mod.DEFAULTS["engine"])
        self.assertEqual(cfg.api_key, "")

    def test_missing_keys_filled_with_defaults(self):
        """沿用原 config.py:34 的行为：缺字段用默认值补齐。"""
        config_mod.write_config({"workers": 3}, self.path)
        cfg = config_mod.AppConfig.load(self.path)
        self.assertEqual(cfg.workers, 3)
        self.assertIn("model", cfg.as_dict())

    def test_save_and_reload_roundtrip(self):
        cfg = config_mod.AppConfig.load(self.path)
        cfg["workers"] = 6
        cfg["api_key"] = "secret-key-1234"
        cfg.save()
        again = config_mod.AppConfig.load(self.path)
        self.assertEqual(again.workers, 6)
        self.assertEqual(again.api_key, "secret-key-1234")

    def test_corrupt_file_falls_back_to_defaults(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("{ this is not json")
        cfg = config_mod.AppConfig.load(self.path)
        self.assertEqual(cfg.engine, config_mod.DEFAULTS["engine"])

    def test_non_dict_json_falls_back(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("[1, 2, 3]")
        cfg = config_mod.AppConfig.load(self.path)
        self.assertEqual(cfg.engine, config_mod.DEFAULTS["engine"])

    def test_workers_clamped_and_type_safe(self):
        cfg = config_mod.AppConfig({"workers": 0})
        self.assertGreaterEqual(cfg.workers, 1)
        cfg = config_mod.AppConfig({"workers": "abc"})
        self.assertEqual(cfg.workers, config_mod.DEFAULTS["workers"])

    def test_atomic_write_no_temp_left(self):
        config_mod.write_config({"workers": 2}, self.path)
        leftovers = [n for n in os.listdir(self.tmp.name) if n.endswith(".tmp")]
        self.assertEqual(leftovers, [])

    def test_utf8_content_preserved(self):
        config_mod.write_config({"model": "中文模型·测试"}, self.path)
        with open(self.path, encoding="utf-8") as f:
            self.assertIn("中文模型·测试", f.read())

    def test_redacted_masks_key(self):
        out = config_mod.redacted({"api_key": "sk-abcdefgh", "workers": 4})
        self.assertNotIn("abcdefgh", out["api_key"])
        self.assertEqual(out["workers"], 4)

    def test_redacted_short_key(self):
        self.assertEqual(config_mod.redacted({"api_key": "abc"})["api_key"], "***")

    def test_redacted_leaves_empty_key(self):
        self.assertEqual(config_mod.redacted({"api_key": ""})["api_key"], "")

    def test_redacted_covers_several_secret_names(self):
        for name in ("api_key", "APIKEY", "token", "secret", "password"):
            with self.subTest(name=name):
                out = config_mod.redacted({name: "supersecretvalue"})
                self.assertNotIn("supersecretvalue", out[name])

    def test_functional_api_compat(self):
        config_mod.save_config({"workers": 5}, self.path)
        loaded = config_mod.load_config(self.path)
        self.assertEqual(loaded["workers"], 5)


class TestPaths(unittest.TestCase):
    def test_project_root_contains_expected_entries(self):
        root = paths.project_root()
        for name in ("app.py", "core", "features", "ui", "docs", "tests", "tools"):
            with self.subTest(name=name):
                self.assertTrue(os.path.exists(os.path.join(root, name)),
                                "工程根下缺少 %s" % name)

    def test_subdirs_are_under_root(self):
        root = os.path.abspath(paths.project_root())
        for getter in (paths.core_dir, paths.features_dir, paths.ui_dir,
                       paths.web_dir, paths.tests_dir, paths.tools_dir,
                       paths.docs_dir):
            with self.subTest(getter=getter.__name__):
                self.assertTrue(os.path.abspath(getter()).startswith(root))

    def test_data_dir_is_not_in_git_tracked_sources(self):
        data = os.path.abspath(paths.data_dir())
        self.assertTrue(data.startswith(os.path.abspath(paths.project_root())))

    def test_reference_roots_shape(self):
        roots = paths.reference_roots()
        self.assertEqual(set(roots), {"translate", "cheats"})

    def test_reference_tool_unknown_kind(self):
        with self.assertRaises(KeyError):
            paths.reference_tool("nope")

    def test_reference_tool_known_kinds(self):
        for kind in ("translate", "cheats"):
            with self.subTest(kind=kind):
                self.assertTrue(paths.reference_tool(kind).endswith(
                    paths.REFERENCE_TOOLS[kind]))

    def test_env_override_root(self):
        os.environ[paths.ENV_ROOT] = self.tmp_override = tempfile.mkdtemp(prefix="ov_")
        try:
            self.assertEqual(os.path.abspath(paths.project_root()),
                             os.path.abspath(self.tmp_override))
        finally:
            os.environ.pop(paths.ENV_ROOT, None)
            os.rmdir(self.tmp_override)

    def test_ensure_dir_is_idempotent(self):
        with tempfile.TemporaryDirectory(prefix="ens_") as tmp:
            target = os.path.join(tmp, "a", "b")
            paths.ensure_dir(target)
            paths.ensure_dir(target)
            self.assertTrue(os.path.isdir(target))

    def test_samples_root_env_override(self):
        os.environ[paths.ENV_SAMPLES] = tempfile.gettempdir()
        try:
            self.assertEqual(os.path.abspath(paths.samples_root()),
                             os.path.abspath(tempfile.gettempdir()))
        finally:
            os.environ.pop(paths.ENV_SAMPLES, None)


class TestTextutil(unittest.TestCase):
    """控制码保护：中日韩文本与控制码必须原样保留（硬约束 §9）。"""

    def test_split_keeps_control_codes(self):
        parts = textutil.split_text("你好\\V[1]世界")
        self.assertEqual(parts, [(True, "你好"), (False, "\\V[1]"), (True, "世界")])

    def test_split_newlines(self):
        parts = textutil.split_text("a\nb\r\nc")
        plains = [seg for is_plain, seg in parts if is_plain]
        controls = [seg for is_plain, seg in parts if not is_plain]
        self.assertEqual(plains, ["a", "b", "c"])
        self.assertEqual(controls, ["\n", "\r\n"])

    def test_has_real_text(self):
        self.assertTrue(textutil.has_real_text("hello"))
        self.assertTrue(textutil.has_real_text("中文"))
        self.assertFalse(textutil.has_real_text(""))
        self.assertFalse(textutil.has_real_text("   "))
        self.assertFalse(textutil.has_real_text("\\V[1]"))

    def test_rebuild_restores_control_codes(self):
        text = "\\V[1]你好\\C[2]世界"
        segments, slices = textutil.collect_segments([text])
        self.assertEqual(segments, ["你好", "世界"])
        rebuilt = textutil.rebuild([text], slices, ["HELLO", "WORLD"])
        self.assertEqual(rebuilt[0], "\\V[1]HELLO\\C[2]WORLD")

    def test_rebuild_falls_back_when_translation_missing(self):
        text = "\\V[1]你好"
        segments, slices = textutil.collect_segments([text])
        rebuilt = textutil.rebuild([text], slices, [])
        self.assertEqual(rebuilt[0], text)

    def test_rebuild_multiple_texts(self):
        texts = ["A\\V[1]B", "C\\N[2]D"]
        segments, slices = textutil.collect_segments(texts)
        self.assertEqual(segments, ["A", "B", "C", "D"])
        out = textutil.rebuild(texts, slices, ["a", "b", "c", "d"])
        self.assertEqual(out, ["a\\V[1]b", "c\\N[2]d"])

    def test_pure_control_code_string_untouched(self):
        text = "\\V[1]"
        segments, slices = textutil.collect_segments([text])
        self.assertEqual(segments, [])
        self.assertEqual(textutil.rebuild([text], slices, []), [text])

    def test_known_gap_symbol_escapes_not_matched(self):
        """**记录已知缺口**（M0 §3.5）：符号型转义 \\{ \\} \\^ 等不被匹配。

        这条测试固化"当前行为"而不是"期望行为"，这样 M2a 修好之后
        本测试会失败并提醒我们更新文档与断言。
        """
        parts = textutil.split_text("a\\{b\\}c")
        controls = [seg for is_plain, seg in parts if not is_plain]
        self.assertEqual(controls, [], "符号型转义当前不被识别（已知缺口）")

    def test_empty_input(self):
        self.assertEqual(textutil.split_text(""), [])
        self.assertEqual(textutil.has_real_text(None), False)


class TestRefbridge(unittest.TestCase):
    """参考实现桥接：必须登记才能加载（防止随手 import 绕过收敛登记表）。"""

    def test_unknown_name_rejected(self):
        with self.assertRaises(KeyError):
            _refbridge.load_reference("not_registered")

    def test_references_have_three_tuple_shape(self):
        for name, entry in _refbridge.REFERENCES.items():
            with self.subTest(name=name):
                self.assertEqual(len(entry), 3, "登记项必须是 (kind, module, purpose)")
                kind = entry[0]
                self.assertIn(kind, ("translate", "cheats"))

    def test_status_report_shape(self):
        report = _refbridge.reference_status()
        for key in ("reference_root", "tools", "entries", "pending"):
            self.assertIn(key, report)
        self.assertEqual(report["pending"], len(_refbridge.REFERENCES))

    def test_pending_lists_all(self):
        self.assertEqual(sorted(_refbridge.pending_references()),
                         sorted(_refbridge.REFERENCES))


if __name__ == "__main__":
    unittest.main(verbosity=2)

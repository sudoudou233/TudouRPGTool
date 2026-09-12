# -*- coding: utf-8 -*-
"""全局配置（``core/config.py``）的专用测试。

@feature  none
@layer    tests
@public   TestConfig
@depends  core.config
@tested   (本文件即测试)
@footprint docs/MODULES.md#coreconfig

说明：这些用例原先与其它模块的用例一起放在 ``tests/unit/test_misc.py``，
同时 ``tests/unit/test_config.py`` 只是再导出一次 —— 于是同一批用例被
执行两遍（计数翻倍）。M2b 去重：用例**只**在这里，`test_misc.py` 里已移除。
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

from core import config as config_mod  # noqa: E402
from core import constants  # noqa: E402


class TestConstants(unittest.TestCase):
    """引擎常量的单元测试。

    单独建 `test_constants.py` 更规整，但那会再多一个只有 6 个用例的文件，
    与 `core/constants.py` 的 @tested 指向冲突；M2b 去重时决定统一放在这里
    （`constants` 与 `config` 同属"全局配置/常量"这一类）。
    """

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

    def test_engine_label_and_is_supported(self):
        self.assertEqual(constants.engine_label("mz"), "RPG Maker MZ")
        self.assertEqual(constants.engine_label(None), "未知引擎")
        self.assertTrue(constants.is_supported("vxace"))
        self.assertFalse(constants.is_supported("2k3"))

    def test_data_exts_cover_engines(self):
        for engine in constants.ENGINES:
            with self.subTest(engine=engine):
                self.assertIn(engine, constants.DATA_EXTS)


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

    def test_batch_size_clamped(self):
        self.assertGreaterEqual(config_mod.AppConfig({"batch_size": 0}).batch_size, 1)
        self.assertEqual(config_mod.AppConfig({"batch_size": "x"}).batch_size,
                         config_mod.DEFAULTS["batch_size"])

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

    def test_redacted_keeps_non_secrets(self):
        out = config_mod.redacted({"model": "gpt", "workers": 4})
        self.assertEqual(out, {"model": "gpt", "workers": 4})

    def test_appconfig_redacted_method(self):
        cfg = config_mod.AppConfig({"api_key": "sk-1234567890"})
        self.assertNotIn("1234567890", cfg.redacted()["api_key"])

    def test_functional_api_compat(self):
        config_mod.save_config({"workers": 5}, self.path)
        loaded = config_mod.load_config(self.path)
        self.assertEqual(loaded["workers"], 5)

    def test_default_config_path_under_project_root(self):
        from core import paths
        self.assertTrue(config_mod.default_config_path()
                        .startswith(os.path.abspath(paths.project_root())))


if __name__ == "__main__":
    unittest.main(verbosity=2)

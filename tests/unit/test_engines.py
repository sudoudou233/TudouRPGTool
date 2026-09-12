# -*- coding: utf-8 -*-
"""引擎识别与存档发现的单元测试（含"与两个参考实现判定一致"的回归断言）。

@feature  none
@layer    tests
@public   TestEngineDetection, TestSaveDiscovery, TestReferenceParity
@depends  core.engines, core.constants
@tested   (本文件即测试)
@footprint docs/MODULES.md#coreengines
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

from core import constants, engines  # noqa: E402


def make_game(root, files=(), dirs=()):
    """在 root 下造出给定的文件/目录。``files`` 是相对路径列表。"""
    for name in dirs:
        os.makedirs(os.path.join(root, name.replace("/", os.sep)), exist_ok=True)
    for name in files:
        full = os.path.join(root, name.replace("/", os.sep))
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as f:
            f.write("{}")


class TestEngineDetection(unittest.TestCase):
    """F-01 相关：两套判据都必须保留（需求 §3.3）。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="eng_")
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name

    def _detect(self, files=(), dirs=()):
        make_game(self.root, files, dirs)
        return engines.detect(self.root)

    # ---- MV / MZ：两套判据 ----
    def test_mz_by_managers_js(self):
        """翻译工具的判据：rmmz_managers.js。"""
        info = self._detect(files=["js/rmmz_managers.js", "data/System.json"])
        self.assertEqual(info["engine"], "mz")
        self.assertTrue(info["supported"])

    def test_mz_by_core_js(self):
        """修改工具的判据：rmmz_core.js。"""
        info = self._detect(files=["js/rmmz_core.js", "data/System.json"])
        self.assertEqual(info["engine"], "mz")

    def test_mv_by_managers_js(self):
        info = self._detect(files=["js/rpg_managers.js", "data/System.json"])
        self.assertEqual(info["engine"], "mv")

    def test_mv_by_core_js(self):
        info = self._detect(files=["js/rpg_core.js", "data/System.json"])
        self.assertEqual(info["engine"], "mv")

    def test_mz_www_layout(self):
        """NW.js 打包时资源在 www/ 下。"""
        info = self._detect(files=["www/js/rmmz_core.js", "www/data/System.json"])
        self.assertEqual(info["engine"], "mz")
        self.assertTrue(info["data_dir"].endswith(os.path.join("www", "data")))
        self.assertTrue(info["save_dir"].endswith(os.path.join("www", "save")))

    def test_mz_wins_over_mv_when_both_present(self):
        """两个标记都在时必须判 MZ（更权威的判据优先）。"""
        info = self._detect(files=["js/rmmz_core.js", "js/rpg_core.js",
                                   "data/System.json"])
        self.assertEqual(info["engine"], "mz")

    # ---- System.json 兜底 ----
    def test_system_json_fallback_mz(self):
        """没有 JS 标记时靠 System.json 的 MZ 独有字段判定。"""
        info = self._detect(files=["data/System.json"])
        self.assertIn(info["engine"], ("mv", "mz"))
        self.assertEqual(info["match"], "system.json")

    def test_system_json_detects_mz_fields(self):
        make_game(self.root, dirs=["data"])
        with open(os.path.join(self.root, "data", "System.json"), "w",
                  encoding="utf-8") as f:
            f.write('{"equipTypes": [], "locale": "ja_JP"}')
        info = engines.detect(self.root)
        self.assertEqual(info["engine"], "mz")
        self.assertEqual(info["match"], "system.json")

    def test_system_json_detects_mv_without_mz_fields(self):
        make_game(self.root, dirs=["data"])
        with open(os.path.join(self.root, "data", "System.json"), "w",
                  encoding="utf-8") as f:
            f.write('{"gameTitle": "x"}')
        info = engines.detect(self.root)
        self.assertEqual(info["engine"], "mv")

    # ---- RGSS ----
    def test_vxace(self):
        info = self._detect(files=["Data/Items.rvdata2"])
        self.assertEqual(info["engine"], "vxace")
        self.assertFalse(info["standard"])          # VX Ace 走改造版 marshal
        self.assertEqual(info["layout"], "hash")

    def test_vx(self):
        """⚠ 翻译工具的旧实现识别不出 VX；本实现在 M1 起就支持（B-16）。"""
        info = self._detect(files=["Data/Items.rvdata"])
        self.assertEqual(info["engine"], "vx")
        self.assertTrue(info["standard"])           # VX 走标准 marshal
        self.assertEqual(info["layout"], "contents")

    def test_xp(self):
        info = self._detect(files=["Data/Items.rxdata"])
        self.assertEqual(info["engine"], "xp")
        self.assertTrue(info["standard"])

    def test_rvdata2_takes_priority_over_rvdata(self):
        """``.rvdata2`` 是 ``.rvdata`` 的超集，必须先判 VX Ace。"""
        info = self._detect(files=["Data/A.rvdata", "Data/B.rvdata2"])
        self.assertEqual(info["engine"], "vxace")

    def test_rgss_save_dir_is_game_root(self):
        info = self._detect(files=["Data/Items.rvdata2"])
        self.assertEqual(os.path.abspath(info["save_dir"]),
                         os.path.abspath(self.root))

    # ---- 2000/2003：只识别 ----
    def test_2k3_by_rpg_rt_ini(self):
        info = self._detect(files=["RPG_RT.ini"])
        self.assertEqual(info["engine"], "2k3")
        self.assertFalse(info["supported"])
        self.assertIn("2000", info["error"])

    def test_2k3_by_ldb(self):
        info = self._detect(files=["RPG_RT.ldb"])
        self.assertEqual(info["engine"], "2k3")

    # ---- 边界 ----
    def test_unknown_dir_returns_none(self):
        self.assertIsNone(engines.detect_engine(self.root))

    def test_missing_dir_returns_none(self):
        self.assertIsNone(engines.detect_engine(os.path.join(self.root, "nope")))

    def test_detect_never_returns_none(self):
        """``detect()`` 永远返回带 error 的 info，UI 不必写两套分支。"""
        info = engines.detect(self.root)
        self.assertIsNone(info["engine"])
        self.assertFalse(info["supported"])
        self.assertTrue(info["error"])

    def test_detect_missing_path_error_message(self):
        info = engines.detect(os.path.join(self.root, "missing"))
        self.assertIn("不存在", info["error"])

    def test_empty_input(self):
        self.assertIsNone(engines.detect_engine(""))
        self.assertIsNone(engines.detect_engine(None))

    def test_describe_marks_recognize_only(self):
        info = self._detect(files=["RPG_RT.ini"])
        self.assertIn("仅识别", engines.describe(info))


class TestSaveDiscovery(unittest.TestCase):
    """存档命名规则必须与原修改工具逐字一致（constants.SAVE_PATTERNS）。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="sav_")
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name

    def _game(self, engine, save_files):
        """造一个指定引擎的游戏目录并写入给定存档文件。"""
        if engine in ("mv", "mz"):
            marker = "js/rmmz_core.js" if engine == "mz" else "js/rpg_core.js"
            make_game(self.root, files=[marker, "data/System.json"],
                      dirs=["save"])
            save_dir = os.path.join(self.root, "save")
        else:
            ext = constants.SAVE_EXTS[engine]
            make_game(self.root, files=["Data/Items" + ext])
            save_dir = self.root
        for name in save_files:
            with open(os.path.join(save_dir, name), "w", encoding="utf-8") as f:
                f.write("x")
        return engines.detect(self.root)

    def test_mv_pattern(self):
        info = self._game("mv", ["file0.rpgsave", "file19.rpgsave", "notes.txt"])
        self.assertEqual(engines.list_saves(info, self.root),
                         ["file0.rpgsave", "file19.rpgsave"])

    def test_mz_pattern(self):
        info = self._game("mz", ["file0.rmmzsave", "file1.rmmzsave"])
        self.assertEqual(engines.list_saves(info, self.root),
                         ["file0.rmmzsave", "file1.rmmzsave"])

    def test_mv_does_not_match_mz_extension(self):
        """跨引擎扩展名不得互相匹配。"""
        info = self._game("mv", ["file0.rmmzsave"])
        self.assertEqual(engines.list_saves(info, self.root), [])

    def test_vxace_pattern(self):
        info = self._game("vxace", ["Save01.rvdata2", "Save02.rvdata2", "Save9.rvdata"])
        self.assertEqual(engines.list_saves(info, self.root),
                         ["Save01.rvdata2", "Save02.rvdata2"])

    def test_xp_pattern(self):
        info = self._game("xp", ["Save1.rxdata", "Save2.rxdata"])
        self.assertEqual(engines.list_saves(info, self.root),
                         ["Save1.rxdata", "Save2.rxdata"])

    def test_patterns_are_anchored(self):
        """``^...$`` 锚定：不得匹配带前后缀的名字。"""
        info = self._game("vxace", ["xSave01.rvdata2", "Save01.rvdata2.bak"])
        self.assertEqual(engines.list_saves(info, self.root), [])

    def test_no_save_dir(self):
        info = engines.detect(os.path.join(self.root, "nope"))
        self.assertEqual(engines.list_saves(info, self.root), [])

    def test_unsupported_engine_has_no_saves(self):
        make_game(self.root, files=["RPG_RT.ini"])
        info = engines.detect(self.root)
        self.assertEqual(engines.list_saves(info, self.root), [])

    def test_find_save_dirs_reports_second_location(self):
        """多套存档（如自动存档）必须都能被发现。"""
        info = self._game("mv", ["file0.rpgsave"])
        auto = os.path.join(self.root, "save", "auto")
        os.makedirs(auto, exist_ok=True)
        with open(os.path.join(auto, "file0.rpgsave"), "w", encoding="utf-8") as f:
            f.write("x")
        dirs = engines.find_save_dirs(info, self.root)
        found = {os.path.abspath(d) for d, _ in dirs}
        self.assertIn(os.path.abspath(auto), found)
        self.assertGreaterEqual(len(dirs), 2)


class TestConstants(unittest.TestCase):
    """常量唯一真源（原 rpgdata.py:180 与 mvdata.py:100 的重复已消除）。"""

    def test_params_order(self):
        self.assertEqual(len(constants.PARAMS), 8)
        self.assertEqual(constants.PARAMS[0], "最大HP")
        self.assertEqual(constants.PARAMS[7], "幸运")

    def test_every_pattern_engine_has_ext(self):
        for engine in constants.SAVE_PATTERNS:
            self.assertIn(engine, constants.SAVE_EXTS,
                          "SAVE_PATTERNS 与 SAVE_EXTS 的引擎集合必须一致")

    def test_engine_label(self):
        self.assertEqual(constants.engine_label("mz"), "RPG Maker MZ")
        self.assertEqual(constants.engine_label("unknown"), "unknown")
        self.assertEqual(constants.engine_label(None), "未知引擎")

    def test_is_supported(self):
        self.assertTrue(constants.is_supported("vxace"))
        self.assertFalse(constants.is_supported("2k3"))


class TestReferenceParity(unittest.TestCase):
    """与两个旧实现的判定一致性（需要参考工具目录；缺失则跳过）。

    这是"合并没改变行为"的直接证据：新实现必须与旧实现判定一致。
    """

    def setUp(self):
        from core import _refbridge, paths
        if not paths.reference_available("cheats"):
            self.skipTest("参考工具目录不可用，跳过对照")
        self.refbridge = _refbridge
        self.tmp = tempfile.TemporaryDirectory(prefix="parity_")
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name

    def test_agree_with_cheating_tool_detector(self):
        try:
            ref = self.refbridge.load_reference("engines")
        except Exception as exc:
            self.skipTest("无法加载参考实现：%s" % exc)

        cases = {
            "mz_core": ["js/rmmz_core.js", "data/System.json"],
            "mv_core": ["js/rpg_core.js", "data/System.json"],
            "vxace": ["Data/Items.rvdata2"],
            "xp": ["Data/Items.rxdata"],
            "unknown": [],
        }
        for label, files in cases.items():
            with self.subTest(case=label):
                sub = os.path.join(self.root, label)
                os.makedirs(sub, exist_ok=True)
                make_game(sub, files)
                mine = engines.detect(sub)["engine"]
                theirs = (ref.detect_engine(sub) or {}).get("engine")
                self.assertEqual(mine, theirs,
                                 "与修改工具判定不一致：%s vs %s" % (mine, theirs))

    def test_agree_with_translation_tool_detector(self):
        try:
            ref = self.refbridge.load_reference("tool.engines")
        except Exception as exc:
            self.skipTest("无法加载参考实现：%s" % exc)

        cases = {
            "mz_managers": ["js/rmmz_managers.js", "data/System.json"],
            "mv_managers": ["js/rpg_managers.js", "data/System.json"],
            "vxace": ["Data/Items.rvdata2"],
            "xp": ["Data/Items.rxdata"],
        }
        for label, files in cases.items():
            with self.subTest(case=label):
                sub = os.path.join(self.root, label)
                os.makedirs(sub, exist_ok=True)
                make_game(sub, files)
                mine = engines.detect(sub)["engine"]
                info = ref.detect(sub)
                theirs = info.get("engine") if info.get("engine") else None
                self.assertEqual(mine, theirs,
                                 "与翻译工具判定不一致：%s vs %s" % (mine, theirs))


if __name__ == "__main__":
    unittest.main(verbosity=2)

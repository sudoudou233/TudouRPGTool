# -*- coding: utf-8 -*-
"""引擎识别与存档发现的单元测试（含"与两个参考实现判定一致"的回归断言）。

@feature  none
@layer    tests
@public   TestEngineDetection, TestSaveDiscovery, TestConstants,
          TestFrozenRealGameBaseline, TestFrozenDetectionFixtures
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


#: ---------------------------------------------------------------------------
#: 冻结的实测基线：7 个真实游戏上"本工程 vs 两个旧实现"的判定与存档数量。
#:
#: 这是"合并没改变行为"的**独立证据** —— 不再依赖 core/_refbridge.py
#: （该桥接层是 M1/M2a 的临时脚手架，M2b 后删除）。
#:
#: 采集时间：2026-09-12（M2b）。采集方式：同时调用
#:   * 本工程 ``core.engines.detect()``
#:   * 旧修改工具 ``rpgmaker_cheating_tool/engines.py``
#:   * 旧翻译工具 ``rpgmaker_translation_tool/tool/engines.py``
#: 三者在全部样本上判定一致（含"未识别"这一例）。
#:
#: 若某天本实现的判定发生变化，本表会立刻失败 —— 那时必须明确回答
#: "是有意改进，还是回归"，并在 docs/DEVLOG.md 记录理由。
#: ---------------------------------------------------------------------------
FROZEN_REAL_GAME_BASELINE = (
    # (游戏目录, 期望引擎, 期望存档数, 备注)
    (r"D:\gamess\demon\DD_V07c_Windows\DD_V07c_Windows", "mz", 3,
     "MZ：js/rmmz_core.js + save/*.rmmzsave"),
    (r"D:\gamess\痴女の触手 官中版\痴女の触手 官中版", "mv", 0,
     "MV：www/js/rpg_core.js（无存档）"),
    (r"D:\gamess\踏勇\践踏勇者\整合\整合-1\1.12.3", "vxace", 24,
     "VX Ace：Data/*.rvdata2 + Save*.rvdata2（含改造版运行时）"),
    (r"D:\gamess\zhoukai\诅咒铠甲2\PC\PC-1\V5.9", "mv", 2,
     "MV：第二个样本，验证判据不是只对某一个游戏成立"),
    (r"D:\gamess\JIANTATA\1-6\PC-1\ToT 1.16.2.2 CN1.0", "vxace", 1,
     "目录名易被误判为 XP，实为 VX Ace（.rvdata2）"),
    (r"D:\gamess\boli\B7794\博麗霊夢は洗脳されてしまいました", "vxace", 9,
     "翻译工具的 e2e 样本"),
    (r"C:\Windows", None, 0,
     "'未识别'这一例：三个实现都必须返回 None"),
)


class TestFrozenRealGameBaseline(unittest.TestCase):
    """冻结基线的回归测试（需要真实样本；缺失则跳过）。"""

    @classmethod
    def setUpClass(cls):
        from core import paths
        if not paths.samples_root():
            raise unittest.SkipTest(
                "未找到样本目录，跳过。设置环境变量 %s 后重跑。"
                % paths.ENV_SAMPLES)
        missing = [d for d, _e, _n, _note in FROZEN_REAL_GAME_BASELINE
                   if d.startswith("D:") and not os.path.isdir(d)]
        if missing:
            raise unittest.SkipTest("样本路径不存在（换机？）：%s" % missing[:2])

    def test_engine_detection_matches_frozen_baseline(self):
        for directory, expected, _count, note in FROZEN_REAL_GAME_BASELINE:
            with self.subTest(game=os.path.basename(directory)[:32]):
                info = engines.detect(directory)
                self.assertEqual(
                    info["engine"], expected,
                    "引擎判定与冻结基线不一致（%s）：期望 %r，实际 %r"
                    % (note, expected, info["engine"]))

    def test_save_counts_match_frozen_baseline(self):
        for directory, expected, count, note in FROZEN_REAL_GAME_BASELINE:
            with self.subTest(game=os.path.basename(directory)[:32]):
                info = engines.detect(directory)
                saves = engines.list_saves(info, directory)
                self.assertEqual(
                    len(saves), count,
                    "存档数量与冻结基线不一致（%s）：期望 %d，实际 %d"
                    % (note, count, len(saves)))

    def test_baseline_covers_all_supported_engines(self):
        """基线必须覆盖到需求要求的引擎集合，否则"一致"没有说服力。"""
        covered = {expected for _d, expected, _c, _n in FROZEN_REAL_GAME_BASELINE}
        for engine in ("mz", "mv", "vxace"):
            with self.subTest(engine=engine):
                self.assertIn(engine, covered)
        self.assertIn(None, covered, "必须包含'未识别'这一例")

    def test_unrecognized_case_reports_error(self):
        info = engines.detect("C:\\Windows")
        self.assertIsNone(info["engine"])
        self.assertFalse(info["supported"])
        self.assertTrue(info["error"])


#: 冻结的判据覆盖矩阵：两个旧实现各有**不同的** MV/MZ 判据，
#: 合并后必须两套都认（需求 §3.3 第一类重复的核心要求）。
#:
#: 采集时间：2026-09-12（M2b）。做法：对每种"标记文件组合"分别调用
#: 旧修改工具（判据 ``*_core.js``）与旧翻译工具（判据 ``*_managers.js``），
#: 确认两者各自的判定，再确认本实现对两者都给出同一答案。
FROZEN_DETECTION_FIXTURES = (
    # (标签, 造出来的文件, 期望引擎, 该用例考验的是哪一侧的判据)
    ("mz_core_only", ["js/rmmz_core.js", "data/System.json"], "mz",
     "修改工具的判据（rmmz_core.js）"),
    ("mv_core_only", ["js/rpg_core.js", "data/System.json"], "mv",
     "修改工具的判据（rpg_core.js）"),
    ("mz_managers_only", ["js/rmmz_managers.js", "data/System.json"], "mz",
     "翻译工具的判据（rmmz_managers.js）"),
    ("mv_managers_only", ["js/rpg_managers.js", "data/System.json"], "mv",
     "翻译工具的判据（rpg_managers.js）"),
    ("mz_www_layout", ["www/js/rmmz_core.js", "www/data/System.json"], "mz",
     "NW.js 打包（资源在 www/ 下）"),
    ("system_json_bom_fallback", ["data/System.json"], "mv",
     "无 JS 标记时的 System.json 兜底"),
    ("vxace", ["Data/Items.rvdata2"], "vxace", "RGSS：.rvdata2"),
    ("vx", ["Data/Items.rvdata"], "vx",
     "RGSS：.rvdata —— **旧翻译工具识别不出这一档**（本实现补上）"),
    ("xp", ["Data/Items.rxdata"], "xp", "RGSS：.rxdata"),
    ("rvdata2_beats_rvdata", ["Data/A.rvdata", "Data/B.rvdata2"], "vxace",
     ".rvdata2 是 .rvdata 的超集，必须优先"),
    ("rm2k3_ini", ["RPG_RT.ini"], "2k3", "2000/2003：只识别不修改"),
    ("rm2k3_ldb", ["RPG_RT.ldb"], "2k3", "2000/2003：LDB 判据"),
    ("unknown", [], None, "未识别"),
)


class TestFrozenDetectionFixtures(unittest.TestCase):
    """判据覆盖矩阵（不依赖参考工具目录，任何机器可跑）。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="fixt_")
        self.addCleanup(self.tmp.cleanup)

    def test_each_fixture_detects_expected_engine(self):
        for label, files, expected, purpose in FROZEN_DETECTION_FIXTURES:
            with self.subTest(case=label, purpose=purpose):
                sub = os.path.join(self.tmp.name, label)
                os.makedirs(sub, exist_ok=True)
                make_game(sub, files)
                info = engines.detect(sub)
                self.assertEqual(
                    info["engine"], expected,
                    "%s 期望 %r，实际 %r（考验的是：%s）"
                    % (label, expected, info["engine"], purpose))

    def test_vx_is_supported_unlike_translation_tool(self):
        """**合并带来的能力提升**：旧翻译工具识别不出 VX，本实现必须支持。"""
        sub = os.path.join(self.tmp.name, "vx_check")
        os.makedirs(sub, exist_ok=True)
        make_game(sub, ["Data/Items.rvdata"])
        info = engines.detect(sub)
        self.assertEqual(info["engine"], "vx")
        self.assertTrue(info["standard"], "VX 必须走标准 Ruby Marshal")
        self.assertEqual(info["layout"], "contents")
        self.assertTrue(info["supported"])

    def test_mz_wins_when_both_markers_present(self):
        """两个标记都在时必须判 MZ（更权威的判据优先，两个旧实现都这样）。"""
        sub = os.path.join(self.tmp.name, "both")
        os.makedirs(sub, exist_ok=True)
        make_game(sub, ["js/rmmz_core.js", "js/rpg_core.js", "data/System.json"])
        self.assertEqual(engines.detect(sub)["engine"], "mz")

    def test_matrix_covers_both_criteria_families(self):
        """矩阵必须同时覆盖两套判据，否则合并的意义就没被验证。"""
        purposes = " ".join(p for _l, _f, _e, p in FROZEN_DETECTION_FIXTURES)
        self.assertIn("修改工具的判据", purposes)
        self.assertIn("翻译工具的判据", purposes)


if __name__ == "__main__":
    unittest.main(verbosity=2)

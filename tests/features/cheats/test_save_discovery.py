# -*- coding: utf-8 -*-
"""存档发现能力的回归（用户报告"搜索不到存档所在文件夹"）。

@feature  cheats
@layer    tests
@public   TestSaveNameVariants, TestSaveSearchScope, TestConfigFileReporting,
          TestFindSavesFallback, TestSaveHints
@depends  core.constants, core.engines, features.cheats.routes
@tested   (本文件即测试)
@footprint docs/STATE.md

用户报告
--------
「存档修改板块搜索不到存档所在文件夹，是不是路径限制得太死了」

排查结论：**规则确实太窄**，但那个具体游戏是"还没存过档"（`www/save` 里只有
`config.rpgsave` —— 设置文件，不是进度）。两件事都要处理：

1. **规则放宽**：`^file\d+\.rpgsave$` 只认纯数字槽位，于是真实存在的
   `filegameEnd.rpgsave`（通关存档）、`file_auto.rpgsave` 一个都不认。
2. **搜索范围放宽**：`find_save_dirs(max_depth=2)` 只够到 `<根>/www/save`，
   插件把存档放进 `<根>/www/save/auto` 就搜不到；"暂时为空的存档目录"
   （递归搜索只返回含存档的目录）也不在候选里。
3. **说清楚**：原来只回一句"没有找到存档" —— 用户无从判断是"游戏还没存档"、
   "存档在别处"还是"工具没认出来"。现在把搜索过的目录、看到的非存档文件、
   以及两条兜底（手填路径 / 全盘按扩展名搜）都摊开。

还有两个实测踩到的细节：
* `www/save` 与 `www/Save` 在 Windows 上是**同一个目录** —— 去重必须用
  ``os.path.normcase``，否则界面上出现两条一模一样的记录。
* 去重也不能漏：`config.rpgsave` 曾经因为目录重复而被列两遍。
"""

from __future__ import annotations

import json
import os
import re
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
from core.context import AppContext, Router  # noqa: E402


def make_mv_game(root, saves=(), extra_dirs=(), config=True):
    """合成 MV 游戏。``saves`` 是相对游戏根的路径列表（会写成 1 字节文件）。"""
    web = os.path.join(root, "www")
    os.makedirs(os.path.join(web, "js"), exist_ok=True)
    os.makedirs(os.path.join(web, "data"), exist_ok=True)
    with open(os.path.join(web, "js", "rpg_core.js"), "w") as f:
        f.write("//\n")
    with open(os.path.join(web, "data", "System.json"), "w",
              encoding="utf-8", newline="\n") as f:
        json.dump({"gameTitle": "合成", "locale": "ja_JP"}, f)
    for rel in saves:
        full = os.path.join(root, rel.replace("/", os.sep))
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "wb") as f:
            f.write(b"x")
    if config:
        save_dir = os.path.join(web, "save")
        os.makedirs(save_dir, exist_ok=True)
        with open(os.path.join(save_dir, "config.rpgsave"), "wb") as f:
            f.write(b"settings")
    for rel in extra_dirs:
        os.makedirs(os.path.join(root, rel.replace("/", os.sep)), exist_ok=True)
    return root


class TestSaveNameVariants(unittest.TestCase):
    """命名规则要认真实存在的槽位名，但不能把设置文件当存档。"""

    def test_mv_pattern_accepts_plugin_style_names(self):
        rx = re.compile(constants.SAVE_PATTERNS["mv"][0])
        for name in ("file1.rpgsave", "file12.rpgsave",
                     "filegameEnd.rpgsave", "file_auto.rpgsave",
                     "fileBackup.rpgsave"):
            with self.subTest(name=name):
                self.assertTrue(rx.match(name), "应当被认成存档：%s" % name)

    def test_mz_pattern_accepts_plugin_style_names(self):
        rx = re.compile(constants.SAVE_PATTERNS["mz"][0])
        for name in ("file1.rmmzsave", "filegameEnd.rmmzsave"):
            with self.subTest(name=name):
                self.assertTrue(rx.match(name))

    def test_config_and_global_are_not_saves(self):
        """设置文件不能被列成"可改存档"（否则用户以为改的是进度）。"""
        for engine in ("mv", "mz"):
            rx = re.compile(constants.SAVE_PATTERNS[engine][0])
            ext = constants.SAVE_EXTS[engine]
            for stem in constants.SAVE_CONFIG_PREFIXES:
                name = "%s%s" % (stem, ext)
                with self.subTest(engine=engine, name=name):
                    self.assertFalse(rx.match(name),
                                     "设置文件被当成存档了：%s" % name)

    def test_rgss_patterns_unchanged(self):
        rx = re.compile(constants.SAVE_PATTERNS["vxace"][0])
        self.assertTrue(rx.match("Save01.rvdata2"))
        self.assertFalse(rx.match("config.rvdata2"))


class CheatsCase(unittest.TestCase):
    """带隔离数据目录的路由夹具。"""

    def setUp(self):
        try:
            self.tmp = tempfile.TemporaryDirectory(prefix="saves_",
                                                   ignore_cleanup_errors=True)
        except TypeError:
            self.tmp = tempfile.TemporaryDirectory(prefix="saves_")
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name
        os.environ["TUDOU_RPGTOOL_DATA"] = os.path.join(self.root, "runtime")
        os.makedirs(os.environ["TUDOU_RPGTOOL_DATA"], exist_ok=True)

        from features.cheats import manifest as cheats_manifest
        ctx = AppContext(router=Router())
        cheats_manifest.register(ctx)
        self.ctx = ctx

    def call(self, method, route_path, **body):
        from ui.server import Request
        route, _params = self.ctx.router.resolve(method, route_path)
        self.assertIsNotNone(route, "路由不存在：%s %s" % (method, route_path))
        return staticmethod(route.handler).__func__(
            Request(method, route_path, {}, body, {}))

    def open_game(self, game):
        res = self.call("POST", "/api/cheats/open", dir=game)
        self.assertTrue(res["ok"], res.get("error"))
        return res

    def saves_payload(self, game):
        self.open_game(game)
        return self.call("GET", "/api/cheats/saves")


class TestSaveSearchScope(CheatsCase):
    def test_old_www_layout_finds_saves(self):
        game = make_mv_game(os.path.join(self.root, "a"),
                            saves=["www/save/file1.rpgsave"])
        payload = self.saves_payload(game)
        self.assertEqual([s["name"] for s in payload["saves"]], ["file1.rpgsave"])

    def test_nested_save_dir_is_found(self):
        """插件把存档放进 ``save/auto`` 这类子目录 —— 深度 3 才够到。"""
        game = make_mv_game(os.path.join(self.root, "b"),
                            saves=["www/save/auto/file1.rpgsave"])
        payload = self.saves_payload(game)
        self.assertEqual([s["name"] for s in payload["saves"]], ["file1.rpgsave"],
                         "嵌套的存档目录没搜到（max_depth 太小）")

    def test_plugin_style_save_name_is_found(self):
        game = make_mv_game(os.path.join(self.root, "c"),
                            saves=["www/save/filegameEnd.rpgsave"])
        payload = self.saves_payload(game)
        self.assertEqual([s["name"] for s in payload["saves"]],
                         ["filegameEnd.rpgsave"])

    def test_empty_save_dirs_are_listed_but_not_counted_as_saves(self):
        """目录存在但没有存档时：目录要出现在 search.dirs 里（便于用户去打开看）。"""
        game = make_mv_game(os.path.join(self.root, "d"), saves=[])
        payload = self.saves_payload(game)
        self.assertEqual(payload["saves"], [])
        listed = [os.path.normcase(d["dir"]) for d in payload["search"]["dirs"]]
        self.assertTrue(any(d.endswith(os.path.normcase(os.sep + "save"))
                            for d in listed),
                        "空的存档目录没有列出来：%s" % listed)
        self.assertTrue(all(d["saves"] == 0 for d in payload["search"]["dirs"]))

    def test_dirs_are_deduplicated_case_insensitively(self):
        """``www/save`` 与 ``www/Save`` 在 Windows 上是同一个目录，不能列两遍。"""
        game = make_mv_game(os.path.join(self.root, "e"), saves=[])
        payload = self.saves_payload(game)
        dirs = payload["save_dirs"]
        keys = [os.path.normcase(d) for d in dirs]
        self.assertEqual(len(keys), len(set(keys)),
                         "存档目录重复（同一目录大小写不同）：%s" % dirs)

    def test_save_dirs_include_standard_location_when_empty(self):
        game = make_mv_game(os.path.join(self.root, "f"), saves=[])
        payload = self.saves_payload(game)
        self.assertIn(os.path.normcase(os.path.join(game, "www", "save")),
                      [os.path.normcase(d) for d in payload["save_dirs"]])

    def test_real_saves_are_still_readable(self):
        """放宽规则不能把"读存档"弄坏：列出来的存档要能真的加载。"""
        game = make_mv_game(os.path.join(self.root, "g"),
                            saves=["www/save/file1.rpgsave"])
        payload = self.saves_payload(game)
        path = payload["saves"][0]["path"]
        loaded = self.call("POST", "/api/cheats/load", path=path)
        # 夹具的存档是假字节，读失败是预期的；但**不能是"路径不在存档目录内"**
        self.assertFalse(loaded["ok"])
        self.assertNotIn("存档目录内", loaded.get("error", ""),
                         "合法存档被路径校验拒了：%s" % loaded.get("error"))


class TestConfigFileReporting(CheatsCase):
    """目录里那些"看着像存档但不是"的文件必须被解释清楚。"""

    def test_config_rpgsave_is_reported_with_reason(self):
        game = make_mv_game(os.path.join(self.root, "h"), saves=[])
        payload = self.saves_payload(game)
        names = [o["name"] for o in payload["other_files"]]
        self.assertIn("config.rpgsave", names,
                      "设置文件没有被告知给用户：%s" % payload.get("other_files"))
        entry = [o for o in payload["other_files"]
                 if o["name"] == "config.rpgsave"][0]
        self.assertIn("设置", entry["reason"])

    def test_config_file_not_reported_twice(self):
        """``config.rpgsave`` 曾经因为目录重复而被列两遍。"""
        game = make_mv_game(os.path.join(self.root, "i"), saves=[])
        payload = self.saves_payload(game)
        names = [o["name"] for o in payload["other_files"]]
        self.assertEqual(len(names), len(set(names)),
                         "非存档文件重复：%s" % names)

    def test_config_file_is_not_listed_as_a_save(self):
        game = make_mv_game(os.path.join(self.root, "j"), saves=[])
        payload = self.saves_payload(game)
        self.assertNotIn("config.rpgsave", [s["name"] for s in payload["saves"]])


class TestFindSavesFallback(CheatsCase):
    """兜底搜索：按扩展名全盘找，绕开命名规则。"""

    def test_finds_files_the_rules_reject(self):
        game = make_mv_game(os.path.join(self.root, "k"),
                            saves=["www/save/strange_name.rpgsave"])
        self.open_game(game)
        payload = self.call("GET", "/api/cheats/find_saves")
        self.assertTrue(payload["ok"], payload.get("error"))
        names = [c["name"] for c in payload["candidates"]]
        self.assertIn("strange_name.rpgsave", names,
                      "命名规则不认的文件没被兜底搜索找到：%s" % names)
        entry = [c for c in payload["candidates"]
                 if c["name"] == "strange_name.rpgsave"][0]
        self.assertFalse(entry["by_rule"], "这个文件不该被标记为符合规则")

    def test_rule_matching_files_sort_first(self):
        game = make_mv_game(os.path.join(self.root, "l"),
                            saves=["www/save/file1.rpgsave",
                                   "www/save/zzz_odd.rpgsave"])
        self.open_game(game)
        payload = self.call("GET", "/api/cheats/find_saves")
        flags = [c["by_rule"] for c in payload["candidates"]]
        self.assertEqual(flags, sorted(flags, reverse=True),
                         "符合命名规则的应当排在前面：%s" % flags)
        self.assertTrue(flags[0])

    def test_reports_root_and_extension(self):
        game = make_mv_game(os.path.join(self.root, "m"), saves=[])
        self.open_game(game)
        payload = self.call("GET", "/api/cheats/find_saves")
        self.assertEqual(payload["ext"], ".rpgsave")
        self.assertTrue(os.path.isdir(payload["root"]))

    def test_requires_game(self):
        payload = self.call("GET", "/api/cheats/find_saves")
        self.assertFalse(payload["ok"])
        self.assertIn("游戏目录", payload["error"])


class TestSaveHints(CheatsCase):
    """"找不到存档"必须给出**能指导下一步**的话，而不只是"没找到"。"""

    def test_hint_mentions_config_files_when_present(self):
        game = make_mv_game(os.path.join(self.root, "n"), saves=[])
        payload = self.saves_payload(game)
        self.assertIn("config.rpgsave", payload["hint"])
        self.assertIn("设置文件", payload["hint"])
        self.assertIn("先进游戏存一次", payload["hint"])

    def test_hint_mentions_search_dirs_when_no_config(self):
        game = make_mv_game(os.path.join(self.root, "o"), saves=[], config=False)
        payload = self.saves_payload(game)
        self.assertTrue(payload["hint"])
        self.assertIn("找过", payload["hint"])

    def test_no_hint_when_saves_exist(self):
        game = make_mv_game(os.path.join(self.root, "p"),
                            saves=["www/save/file1.rpgsave"])
        payload = self.saves_payload(game)
        self.assertEqual(payload["hint"], "")

    def test_hint_has_no_markdown_markers(self):
        """提示是**直接显示在界面上的纯文本** —— 不能出现 ``**`` 之类的标记。

        实测踩到：第一版写了 ``但它们**是设置文件**``，页面上原样显示了星号。
        """
        for label, game in (
                ("有设置文件", make_mv_game(os.path.join(self.root, "r"), saves=[])),
                ("空目录", make_mv_game(os.path.join(self.root, "s"), saves=[],
                                       config=False))):
            payload = self.saves_payload(game)
            with self.subTest(case=label):
                self.assertNotIn("**", payload["hint"])
                self.assertNotIn("`", payload["hint"])

    def test_search_block_always_present(self):
        game = make_mv_game(os.path.join(self.root, "q"), saves=[])
        payload = self.saves_payload(game)
        search = payload["search"]
        for key in ("game_dir", "js_root", "save_dir", "pattern", "dirs"):
            with self.subTest(key=key):
                self.assertIn(key, search)
        self.assertEqual(search["pattern"], "file*.rpgsave")


if __name__ == "__main__":
    unittest.main(verbosity=2)

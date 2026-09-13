# -*- coding: utf-8 -*-
"""生成汉化版的**复制范围**（用户报告：副本里只有 www，没有 Game.exe）。

@feature  translate
@layer    tests
@public   TestCopyScope, TestGameRootFor, TestEnginesGameRootVsJsRoot
@depends  core.engines, core.safety.builder, features.translate.session
@tested   (本文件即测试)
@footprint docs/STATE.md

事故经过
--------
用户报告：「生成的汉化版副本只有 /www 的内容啊，外层的 game.exe 之类的
没有一起生成副本吗？」

根因在 ``core/engines.py``：老版 NW.js 打包的 MV 把资源放在
``<游戏根>/www/`` 下，而旧实现把 ``info["game_dir"]`` **直接设成了
``www``**（因为它要拿 `js_root` 去拼 `data_dir`）。而"生成汉化版"复制的是
``info["game_dir"]`` —— 于是副本 = ``www`` 的内容，**没有 Game.exe、
没有 nw.dll**，用户拿到的东西根本启动不了。

修法：把两个概念拆开（``game_dir`` = 用户选的游戏根；``js_root`` = JSON
资源根），并让"用户直接选中 www"的情况也上溯到游戏根。

本文件钉住三件事：
1. ``engines.detect`` 在两种入口下都把 ``game_dir`` 定成**含 Game.exe 的那一层**；
2. ``builder.build(mode="copy")`` 复制的是**整个游戏根**（含运行时文件与 www 子目录）；
3. 数据/存档仍然指向 ``js_root`` 那一层（修 game_dir 不能把数据路径改坏）。
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

import json  # noqa: E402

from core import engines  # noqa: E402


def make_www_layout_mv(root):
    """老版布局：运行时在根、资源在 www/。返回 (game_root, js_root)。"""
    web = os.path.join(root, "www")
    os.makedirs(os.path.join(web, "js"), exist_ok=True)
    os.makedirs(os.path.join(web, "data"), exist_ok=True)
    with open(os.path.join(web, "js", "rpg_core.js"), "w") as f:
        f.write("//\n")
    for fname, payload in (
            ("System.json", {"gameTitle": "合成www", "locale": "ja_JP"}),
            ("Items.json", [None, {"id": 1, "name": "药草", "price": 50}]),
            ("MapInfos.json", [None, {"id": 1, "name": "起始村"}]),
    ):
        with open(os.path.join(web, "data", fname), "w",
                  encoding="utf-8", newline="\n") as f:
            json.dump(payload, f, ensure_ascii=False)
    # 运行时（游戏根）
    for name, blob in (("Game.exe", b"MZ\x90\x00 fake exe"),
                       ("nw.dll", b"\x00" * 32),
                       ("icudtl.dat", b"\x01" * 16),
                       ("Readme.TXT", b"readme")):
        with open(os.path.join(root, name), "wb") as f:
            f.write(blob)
    with open(os.path.join(root, "package.json"), "w", encoding="utf-8") as f:
        f.write('{"main":"www/index.html"}')
    # 存档放在资源层（老版 MV 的实际位置）
    os.makedirs(os.path.join(web, "save"), exist_ok=True)
    with open(os.path.join(web, "save", "file1.rpgsave"), "wb") as f:
        f.write(b"not-a-real-save")
    return root, web


def make_root_layout_mv(root):
    """新版布局：js/ data/ save/ 都在游戏根（js_root == game_dir）。"""
    os.makedirs(os.path.join(root, "js"), exist_ok=True)
    os.makedirs(os.path.join(root, "data"), exist_ok=True)
    with open(os.path.join(root, "js", "rpg_core.js"), "w") as f:
        f.write("//\n")
    with open(os.path.join(root, "data", "System.json"), "w",
              encoding="utf-8", newline="\n") as f:
        json.dump({"gameTitle": "合成新版", "locale": "ja_JP"}, f)
    with open(os.path.join(root, "Game.exe"), "wb") as f:
        f.write(b"MZ\x90\x00 fake exe")
    return root


class TestGameRootFor(unittest.TestCase):
    """``game_root_for``：只在该上溯时才上溯。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="gameroot_")
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name

    def test_www_with_exe_parent_is_retargeted(self):
        game, web = make_www_layout_mv(os.path.join(self.root, "g1"))
        self.assertEqual(engines.game_root_for(web), os.path.abspath(game))

    def test_www_without_runtime_markers_is_kept(self):
        """名字恰好叫 www 的普通目录不能被误当成资源层。"""
        plain = os.path.join(self.root, "plain", "www")
        os.makedirs(os.path.join(plain, "data"))
        self.assertEqual(engines.game_root_for(plain), os.path.abspath(plain))

    def test_non_www_dir_is_returned_as_is(self):
        game = make_root_layout_mv(os.path.join(self.root, "g2"))
        self.assertEqual(engines.game_root_for(game), os.path.abspath(game))


class TestEnginesGameRootVsJsRoot(unittest.TestCase):
    """``detect`` 必须把两个概念分清楚，两种入口都要对。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="detectroots_")
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name
        self.game, self.web = make_www_layout_mv(os.path.join(self.root, "www_game"))

    def test_old_layout_from_game_root(self):
        info = engines.detect(self.game)
        self.assertTrue(info["engine"])
        self.assertEqual(info["game_dir"], os.path.abspath(self.game),
                         "game_dir 应当是含 Game.exe 的那一层")
        self.assertEqual(info["js_root"], os.path.abspath(self.web))
        self.assertEqual(info["data_dir"], os.path.join(os.path.abspath(self.web), "data"))
        self.assertEqual(info["save_dir"], os.path.join(os.path.abspath(self.web), "save"))

    def test_old_layout_from_www_layer(self):
        """用户直接选中 ``www``（资源都在眼前，很像游戏目录）也要指向游戏根。"""
        info = engines.detect(self.web)
        self.assertEqual(info["game_dir"], os.path.abspath(self.game))
        self.assertEqual(info["js_root"], os.path.abspath(self.web))

    def test_game_root_contains_the_runtime(self):
        info = engines.detect(self.game)
        names = os.listdir(info["game_dir"])
        self.assertIn("Game.exe", names)
        self.assertIn("www", names)

    def test_data_and_save_still_point_at_js_root(self):
        """修 game_dir 不能把数据/存档路径改坏 —— 从两个入口进去结果要一致。"""
        from_root = engines.detect(self.game)
        from_web = engines.detect(self.web)
        for key in ("data_dir", "save_dir", "js_root"):
            with self.subTest(key=key):
                self.assertEqual(from_root[key], from_web[key])
        self.assertTrue(os.path.isdir(from_root["data_dir"]),
                        "data_dir 必须真实存在：%s" % from_root["data_dir"])

    def test_saves_found_in_www_layer(self):
        info = engines.detect(self.game)
        found = engines.find_save_dirs(info, info["game_dir"])
        rels = [os.path.relpath(d, info["game_dir"]) for d, _n in found]
        self.assertIn(os.path.join("www", "save"), rels,
                      "老版布局的存档在 www/save 下，必须能找到：%s" % rels)

    def test_root_layout_still_works(self):
        game = make_root_layout_mv(os.path.join(self.root, "root_game"))
        info = engines.detect(game)
        self.assertEqual(info["game_dir"], os.path.abspath(game))
        self.assertEqual(info["js_root"], os.path.abspath(game))
        self.assertEqual(info["data_dir"], os.path.join(os.path.abspath(game), "data"))


class TestCopyScope(unittest.TestCase):
    """**用户报告的缺陷**：写副本时复制的是整个游戏根。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="copyscope_")
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name

    def _build(self, game, target):
        from core.safety import builder
        from features.translate.session import Session

        session = Session(game)
        self.assertTrue(session.info["supported"], session.info.get("error"))
        total = session.scan()
        self.assertGreater(total, 0, "扫描为空，夹具可疑")
        for entry in session.entries.values():
            entry["translated"] = "T-" + entry["original"]
            entry["status"] = "translated"
        return builder.build(session, mode="copy", target_dir=target)

    def test_www_layout_copy_includes_runtime_and_www(self):
        game, web = make_www_layout_mv(os.path.join(self.root, "old"))
        target = os.path.join(self.root, "out")
        result = self._build(game, target)
        self.assertEqual(os.path.abspath(result["target_dir"]), os.path.abspath(target))

        names = sorted(os.listdir(target))
        # 1) 运行时必须一起复制（缺了副本启动不了）—— 这就是用户报的问题
        for required in ("Game.exe", "nw.dll", "package.json"):
            with self.subTest(required=required):
                self.assertIn(required, names,
                              "副本里缺少 %s —— 生成的汉化版无法启动。"
                              "实际内容：%s" % (required, names))
        # 2) 资源层也要在
        self.assertIn("www", names)
        self.assertTrue(os.path.isfile(
            os.path.join(target, "www", "data", "Items.json")))
        # 3) 副本里不能出现"www 的内容被摊平到根"这种形态
        self.assertFalse(os.path.isdir(os.path.join(target, "data")),
                         "www 的内容被摊平到了副本根，说明复制范围错了")

    def test_www_layout_translation_lands_in_the_copy(self):
        game, _web = make_www_layout_mv(os.path.join(self.root, "old2"))
        target = os.path.join(self.root, "out2")
        result = self._build(game, target)
        self.assertGreaterEqual(result["entries"], 1)
        with open(os.path.join(target, "www", "data", "Items.json"),
                  encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data[1]["name"], "T-药草", "译文没有写进副本")

    def test_root_layout_copy_still_correct(self):
        """新版布局回归：复制范围仍然是整个游戏根。"""
        game = make_root_layout_mv(os.path.join(self.root, "new"))
        target = os.path.join(self.root, "out3")
        self._build(game, target)
        names = sorted(os.listdir(target))
        self.assertIn("Game.exe", names)
        self.assertIn("js", names)
        self.assertIn("data", names)

    def test_copy_from_www_entry_also_full_game(self):
        """用户直接选中 ``www`` 时，副本同样必须是完整游戏。"""
        game, web = make_www_layout_mv(os.path.join(self.root, "old3"))
        target = os.path.join(self.root, "out4")
        self._build(web, target)
        self.assertIn("Game.exe", sorted(os.listdir(target)))

    def test_copy_reports_what_it_copied(self):
        """结果里必须能看出**复制范围**。

        用户报这个缺陷时，界面上只有"写回条目 N、文件 M"，看不出复制的是
        哪一层目录 —— 于是一个"副本根本启动不了"的严重问题表现成"成功"。
        现在源码目录与文件数都回传，并附一句"没找到 Game.exe"的提示。
        """
        game, _web = make_www_layout_mv(os.path.join(self.root, "old5"))
        result = self._build(game, os.path.join(self.root, "out6"))
        self.assertEqual(os.path.abspath(result["source_dir"]),
                         os.path.abspath(game))
        self.assertGreaterEqual(result["copied_files"], 6,
                                "复制的文件数太少，看起来没拷全：%s" % result)
        joined = " ".join(result["notes"])
        self.assertIn("已复制游戏目录", joined)
        self.assertIn(os.path.basename(game), joined)

    def test_copy_warns_when_no_game_exe(self):
        """游戏根下没有 Game.exe 时要给出可操作提示（而不是静默成功）。"""
        game = make_root_layout_mv(os.path.join(self.root, "noexe"))
        os.remove(os.path.join(game, "Game.exe"))
        result = self._build(game, os.path.join(self.root, "out7"))
        joined = " ".join(result["notes"])
        self.assertIn("没有 Game.exe", joined,
                      "缺少运行时却没有提示：%s" % result["notes"])

    def test_original_game_untouched(self):
        game, _web = make_www_layout_mv(os.path.join(self.root, "old4"))
        before = {}
        for base, _dirs, files in os.walk(game):
            for name in files:
                full = os.path.join(base, name)
                with open(full, "rb") as f:
                    before[os.path.relpath(full, game)] = f.read()
        self._build(game, os.path.join(self.root, "out5"))
        after = {}
        for base, _dirs, files in os.walk(game):
            for name in files:
                full = os.path.join(base, name)
                with open(full, "rb") as f:
                    after[os.path.relpath(full, game)] = f.read()
        self.assertEqual(after, before, "写副本不该改动原游戏")


if __name__ == "__main__":
    unittest.main(verbosity=2)

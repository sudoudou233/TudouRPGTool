# -*- coding: utf-8 -*-
"""M5 用户报告期发现的缺陷回归（N-25 地图事件对话路径 / N-26 跨盘输出）。

@feature  translate
@layer    tests
@public   TestN25MapEventPaths, TestN26CrossDriveOutput
@depends  core.formats.mv_mz_data, core.safety.builder, features.translate.session
@tested   (本文件即测试)
@footprint docs/STATE.md

N-25：**用户报告「对话文本没有被翻译到」**
------------------------------------------
`mv_mz_data.extract` 给**地图事件**拼路径时漏了 ``list`` 这一层：

    实际产出：events/2/pages/0/1/parameters/0        ← 缺 list
    正确形状：events/2/pages/0/list/1/parameters/0

而 `_walk_event_list` 内部拼的是 ``"%s/%d/parameters/%d"``（下标是**指令在
list 里的位置**）。于是写回时 `_set_by_path` 在 dict 上取键 ``"1"`` 失败 →
``KeyError`` 被上层 `except` 吞掉 → **整张地图的事件对话静默丢失**。

实测（用户那个游戏）：45,037 条里 24,709 条定位失败 = **54.86%**，
而扫描、界面、统计全都正常 —— 与 N-15 完全同一形态。

注意：`CommonEvents` 那条路径是**对的**（`"%d/list"`），只有地图事件漏了 ——
这正说明"两条相似路径只改了一条"是最容易残留的缺陷形态。

N-26：跨盘输出目录直接抛英文栈
------------------------------
游戏在 D:、输出目录留成 C:\Temp 时，`os.path.relpath` 抛
``ValueError: path is on mount 'C:', start on mount 'D:'`` —— 用户看到的是
英文异常，而"换个盘输出"是完全合理的用法。
"""

from __future__ import annotations

import json
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

from core.formats import mv_mz_data  # noqa: E402


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False)


def command(code, params):
    return {"code": code, "indent": 0, "parameters": params}


def make_map_game(root):
    """合成一个 MV 游戏：**地图事件**里有对话与选项（N-25 的现场）。"""
    web = os.path.join(root, "www")
    write_json(os.path.join(web, "data", "System.json"),
               {"gameTitle": "合成地图事件", "locale": "ja_JP"})
    write_json(os.path.join(web, "data", "Map001.json"), {
        "displayName": "起始村",
        "events": [
            None,
            {"id": 1, "name": "EV001", "pages": [
                {"list": [
                    command(101, ["", 0, 0, 2]),
                    command(401, ["おはようございます！"]),
                    command(401, ["今日はいい天気ですね。"]),
                    command(402, [["はい", "いいえ"], 1, 0]),
                    command(0, []),
                ]},
            ]},
            {"id": 2, "name": "EV002", "pages": [
                {"list": [command(401, ["第一页的台词"])]},
                {"list": [command(401, ["第二页的台词"])]},
            ]},
        ],
    })
    write_json(os.path.join(web, "data", "CommonEvents.json"), [
        None,
        {"id": 1, "name": "公共事件", "list": [
            command(401, ["公共事件里的台词"]),
        ]},
    ])
    return root


class TestN25MapEventPaths(unittest.TestCase):
    """地图事件对话的路径必须齐全，且**能定位到原文**。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="n25_")
        self.addCleanup(self.tmp.cleanup)
        self.game = make_map_game(os.path.join(self.tmp.name, "game"))
        self.data_dir = os.path.join(self.game, "www", "data")

    def _entries(self, fname):
        from features.translate.session import ScanOptions
        return mv_mz_data.extract(self.data_dir, ScanOptions())

    def test_map_dialogue_paths_contain_list(self):
        entries = [e for e in self._entries("Map001.json")
                   if e["file"] == "Map001.json"]
        paths = [e["path"] for e in entries]
        self.assertTrue(paths)
        for path in paths:
            with self.subTest(path=path):
                self.assertNotIn("pages/0/1/", path,
                                 "地图事件路径缺少 list 层：%s" % path)
        # 对话必须是 events/i/pages/j/list/k/parameters/0 的形状
        dialog = [p for p in paths if p.endswith("parameters/0")
                  and p.startswith("events/")]
        self.assertTrue(dialog, "没有提取到地图事件对话：%s" % paths)
        for path in dialog:
            with self.subTest(path=path):
                self.assertRegex(path, r"^events/\d+/pages/\d+/list/\d+/parameters/\d+$")

    def test_every_extracted_path_resolves_to_its_original(self):
        """**核心断言**：`extract` 产出的每个 path 都要能在同一份数据里定位到原文。

        这是"扫描与写回用同一套坐标"的机器化校验 —— N-15/N-25 两次都是
        这两套坐标偏了一格，而只有"写回之后打开游戏"才会发现。
        """
        with open(os.path.join(self.data_dir, "Map001.json"),
                  encoding="utf-8") as f:
            data = json.load(f)
        with open(os.path.join(self.data_dir, "CommonEvents.json"),
                  encoding="utf-8") as f:
            common = json.load(f)
        trees = {"Map001.json": data, "CommonEvents.json": common}

        resolved = 0
        for entry in self._entries(None):
            tree = trees.get(entry["file"])
            if tree is None:
                continue
            with self.subTest(file=entry["file"], path=entry["path"]):
                parent, key = mv_mz_data._set_by_path(tree, entry["path"])
                current = parent[int(key)] if isinstance(parent, list) else parent[key]
                self.assertEqual(current, entry["original"],
                                 "路径定位到的不是原文（写回会写错位置或丢失）")
                resolved += 1
        self.assertGreaterEqual(resolved, 5, "提取到的条目太少，断言没覆盖到")

    def test_common_events_paths_still_correct(self):
        """回归：``CommonEvents`` 那条路径本来就是对的，不能被改坏。"""
        entries = [e for e in self._entries(None)
                   if e["file"] == "CommonEvents.json"]
        dialog = [e for e in entries if e["category"] == "对话"]
        self.assertTrue(dialog)
        for e in dialog:
            with self.subTest(path=e["path"]):
                self.assertRegex(e["path"], r"^\d+/list/\d+/parameters/\d+$")

    def test_writeback_lands_in_the_file(self):
        """端到端：写回后文件里真的变成译文（不是只看统计）。"""
        from features.translate.session import Session
        session = Session(self.game)
        total = session.scan()
        self.assertGreater(total, 0)
        for entry in session.entries.values():
            entry["translated"] = "ZH-" + entry["original"]
            entry["status"] = "translated"

        # ⚠ 只把**属于 Map001.json 的**条目交给它 —— ``apply_to_files`` 是按
        # ``{文件名: [条目]}`` 消费的，混入别的文件的条目会（正确地）被跳过，
        # 从而让"skipped == 0"这条断言误报（开发本测试时踩到）。
        mine = [e for e in session.entries.values() if e["file"] == "Map001.json"]
        self.assertGreaterEqual(len(mine), 5, "夹具里的地图条目太少")

        stats = mv_mz_data.apply_to_files(session.info, {"Map001.json": mine})
        self.assertGreaterEqual(stats.get("entries", 0), 5, stats)
        self.assertEqual(stats.get("skipped", 0), 0,
                         "有条目被跳过（路径又对不上了）：%s" % stats)

        with open(os.path.join(self.data_dir, "Map001.json"),
                  encoding="utf-8") as f:
            after = json.load(f)
        self.assertEqual(after["events"][1]["pages"][0]["list"][1]["parameters"][0],
                         "ZH-おはようございます！",
                         "地图事件对话没有写进去")
        self.assertEqual(after["events"][1]["pages"][0]["list"][3]["parameters"][0],
                         ["ZH-はい", "ZH-いいえ"], "选项没有写进去")
        self.assertEqual(after["events"][2]["pages"][1]["list"][0]["parameters"][0],
                         "ZH-第二页的台词", "第二个页面的对话没有写进去")

    def test_no_entries_lost_across_the_whole_game(self):
        """整局游戏：提取到的**每一条**都要能定位（含多页事件、选项）。"""
        from features.translate.session import Session

        session = Session(self.game)
        session.scan()
        self.assertGreater(len(session.entries), 0)
        failed = []
        cache = {}
        for entry in session.entries.values():
            fname = entry["file"]
            if fname not in cache:
                full = os.path.join(self.data_dir, fname)
                cache[fname] = mv_mz_data._load_data_file(full, fname)[0]
            try:
                parent, key = mv_mz_data._set_by_path(cache[fname], entry["path"])
                current = (parent[int(key)] if isinstance(parent, list)
                           else parent[key])
                if current != entry["original"]:
                    failed.append((entry["path"], "内容不匹配"))
            except Exception as exc:
                failed.append((entry["path"], "%s: %s" % (type(exc).__name__, exc)))
        self.assertEqual(failed, [], "以下条目写回时会丢失：%s" % failed[:5])


class TestN26CrossDriveOutput(unittest.TestCase):
    """**N-26**：输出目录与原游戏不同盘时必须能跑（而不是抛英文栈）。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="n26_")
        self.addCleanup(self.tmp.cleanup)
        self.game = make_map_game(os.path.join(self.tmp.name, "game"))

    def _build(self, target):
        from core.safety import builder
        from features.translate.session import Session

        session = Session(self.game)
        self.assertGreater(session.scan(), 0)
        for entry in session.entries.values():
            entry["translated"] = "ZH-" + entry["original"]
            entry["status"] = "translated"
        return builder.build(session, mode="copy", target_dir=target)

    def test_same_drive_target_has_no_cross_drive_note(self):
        result = self._build(os.path.join(self.tmp.name, "out"))
        self.assertEqual(result["copied_files"] > 0, True)
        joined = " ".join(result["notes"])
        self.assertNotIn("不在同一个盘", joined)

    def test_cross_drive_target_does_not_crash(self):
        """把目标盘的判定模拟成另一个盘 —— 不能抛 ``ValueError``。

        真实的跨盘行为（``shutil.copy2`` 在跨盘时可能失败）由
        :func:`copy_tree` 处理；这里验证**编排层**不再因为
        ``os.path.relpath`` 而直接崩掉。
        """
        from unittest import mock
        from core.safety import builder

        real_drive = builder._drive_of

        def fake(path):
            text = real_drive(path)
            # 把 target/staging 所在的输出目录伪装成 "c:"
            if os.path.abspath(str(path)).startswith(
                    os.path.abspath(os.path.join(self.tmp.name, "outx"))):
                return "c:"
            return text

        out = os.path.join(self.tmp.name, "outx")
        with mock.patch.object(builder, "_drive_of", side_effect=fake):
            result = self._build(out)
        self.assertGreater(result["copied_files"], 0)
        _ = real_drive

    def test_copy_tree_handles_cross_drive_without_copy2(self):
        """``copy_tree`` 跨盘时走 ``copyfile``，不调用 ``shutil.copy2``。"""
        from core.safety import builder
        src = os.path.join(self.tmp.name, "src")
        dst = os.path.join(self.tmp.name, "dst")
        os.makedirs(os.path.join(src, "sub"))
        with open(os.path.join(src, "sub", "a.txt"), "w", encoding="utf-8") as f:
            f.write("hello")

        calls = {"copy2": 0, "copyfile": 0}
        real_copy2, real_copyfile = shutil_copy2, shutil_copyfile

        def spy_copy2(*a, **kw):
            calls["copy2"] += 1
            return real_copy2(*a, **kw)

        def spy_copyfile(*a, **kw):
            calls["copyfile"] += 1
            return real_copyfile(*a, **kw)

        import shutil
        with mock.patch.object(builder.shutil, "copy2", side_effect=spy_copy2), \
                mock.patch.object(builder.shutil, "copyfile", side_effect=spy_copyfile), \
                mock.patch.object(builder, "_drive_of", return_value="same"):
            result = builder.copy_tree(src, dst)
        self.assertEqual(result["cross_drive"], False)
        self.assertEqual(calls["copy2"], 1)
        self.assertTrue(os.path.isfile(os.path.join(dst, "sub", "a.txt")))

        calls["copy2"] = calls["copyfile"] = 0
        dst2 = os.path.join(self.tmp.name, "dst2")
        seq = iter(["d:", "c:"])          # src 在 d:、dst 在 c:

        with mock.patch.object(builder.shutil, "copy2", side_effect=spy_copy2), \
                mock.patch.object(builder.shutil, "copyfile", side_effect=spy_copyfile), \
                mock.patch.object(builder, "_drive_of",
                                  side_effect=lambda p: next(seq)):
            result2 = builder.copy_tree(src, dst2)
        self.assertEqual(result2["cross_drive"], True)
        self.assertEqual(calls["copy2"], 0, "跨盘时不该调用 copy2")
        self.assertEqual(calls["copyfile"], 1)
        self.assertTrue(os.path.isfile(os.path.join(dst2, "sub", "a.txt")))


from unittest import mock  # noqa: E402
import shutil as _shutil  # noqa: E402

shutil_copy2 = _shutil.copy2
shutil_copyfile = _shutil.copyfile


if __name__ == "__main__":
    unittest.main(verbosity=2)

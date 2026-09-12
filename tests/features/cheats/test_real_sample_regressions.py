# -*- coding: utf-8 -*-
"""M5 验收期用**真实样本**发现并修复的缺陷的回归测试（N-18 ～ N-20）。

@feature  none
@layer    tests
@public   TestN18VXDataFiles, TestN19MultiStreamSave, TestN20ProxyUnwrap
@depends  core.formats.rgss_data, core.formats.rgss_save,
          features.cheats.data_fields, core.engines
@tested   (本文件即测试)
@footprint docs/STATE.md

背景：真实样本又一次抓出了"读不出来但不报错"
--------------------------------------------
需求 §8-2/§8-3 要求"5 类存档格式各至少 1 个样本走完全链路"。
VX Ace / MV / MZ 有真实游戏，VX / XP 只能合成 —— 而**正是在补合成样本、
并把真实样本接进端到端回归时**，冒出了三个同家族缺陷。它们的共同形态是
**界面显示"没有数据"，而文件本身完好**：

* **N-18** ``rgss_data`` 只认 ``.rvdata2`` / ``.rxdata``，**漏了 VX 的
  ``.rvdata``** → 整个 VX 游戏扫出 0 条。
* **N-19** 改造版 VX Ace 运行时把存档写成 **2 条流**（第一条是启动器元数据
  ``{characters, playtime_s}``，第二条才是游戏状态），而 ``read_party`` /
  ``read_actors`` / ``read_var`` 硬编码 ``streams[0]`` → 真实存档读出来是
  "金币 0、没有角色、没有道具"。
* **N-20** ``rgss_data.load_data_file`` 返回**值层代理**，而
  ``data_fields._to_plain`` 按 doc_model 节点判定类型 → 每个分支都不成立，
  整个文件读出来是 ``None``（界面表现为"一个可编辑字段都没有"）。

三条都不是"新功能没写"，而是"已有路径在真实数据上不成立"。
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

from core import engines  # noqa: E402
from core.formats import rgss_data  # noqa: E402
from core.formats import rgss_save  # noqa: E402
from core.marshal import doc_model as D  # noqa: E402
from features.cheats import data_fields  # noqa: E402


def _sym(name):
    return D.Symbol(name.encode("utf-8"))


def _str(text):
    return D.String(text.encode("utf-8"))


def _obj(class_name, ivars):
    return D.ObjectNode(_sym(class_name), [
        (_sym(k if k.startswith("@") else "@" + k), v) for k, v in ivars.items()])


def _force_standard(node, seen=None):
    """把树里所有 Fixnum 标成标准编码（见 test_acceptance 的同一说明）。"""
    if node is None:
        return
    seen = seen if seen is not None else set()
    if id(node) in seen:
        return
    seen.add(id(node))
    if isinstance(node, D.Fixnum):
        node.std = True
        return
    for child in _children(node):
        _force_standard(child, seen)


def _children(node):
    if isinstance(node, D.Array):
        return list(node.items)
    if isinstance(node, D.Hash):
        out = []
        for k, v in node.entries:
            out.extend((k, v))
        return out
    if isinstance(node, D.ObjectNode):
        return [v for _k, v in node.ivars]
    if isinstance(node, D.Ivar):
        return [node.inner] + [v for _k, v in node.ivars]
    return []


def make_vx_game(root, standard=True, ext=".rvdata"):
    """造一个 VX / XP 游戏目录（数据表 + 存档）。

    ``standard=True`` 用标准整数编码（VX / XP 的真实情况）；
    ``False`` 用来造"变体编码"的对照样本。
    """
    os.makedirs(os.path.join(root, "Data"), exist_ok=True)
    with open(os.path.join(root, "Game.ini"), "w", encoding="utf-8") as f:
        f.write("[Game]\n")

    def dump(fname, node):
        _force_standard(node)
        with open(os.path.join(root, "Data", fname), "wb") as f:
            f.write(D.dumps(node))

    dump("Items" + ext, D.Array([
        D.NilNode(),
        _obj("RPG::Item", {"id": D.Fixnum(1), "name": _str("药草"),
                           "price": D.Fixnum(50),
                           "consumable": D.BoolNode(True),
                           "occasion": D.Fixnum(0)}),
    ]))
    dump("Actors" + ext, D.Array([
        D.NilNode(),
        _obj("RPG::Actor", {"id": D.Fixnum(1), "name": _str("勇者"),
                            "class_id": D.Fixnum(1)}),
    ]))
    return root


def make_two_stream_save(path, standard=False):
    """造一个**两条流**的 VX Ace 存档（改造版运行时的真实形态）。

    第一条流是启动器元数据，第二条才是游戏状态 —— 与真实游戏
    ``boli/B7794`` 的 ``Save01.rvdata2`` 结构一致。
    """
    meta = D.Hash([
        (_sym("characters"), D.Array([D.Array([])])),
        (_sym("playtime_s"), D.Ivar(_str("00:00:42"),
                                    [(_sym("E"), D.BoolNode(True))])),
    ])
    state = D.Hash([
        (_sym("system"), _obj("Game_System", {})),
        (_sym("switches"), _obj("Game_Switches", {
            "data": D.Array([D.BoolNode(False), D.BoolNode(True)])})),
        (_sym("variables"), _obj("Game_Variables", {
            "data": D.Array([D.Fixnum(0), D.Fixnum(10), D.Fixnum(20)])})),
        (_sym("actors"), D.Array([
            D.NilNode(),
            _obj("Game_Actor", {"id": D.Fixnum(1), "name": _str("勇者"),
                                "level": D.Fixnum(7), "hp": D.Fixnum(300)}),
        ])),
        (_sym("party"), _obj("Game_Party", {
            "gold": D.Fixnum(4242), "steps": D.Fixnum(99),
            "items": D.Hash([(D.Fixnum(1), D.Fixnum(5))]),
            "weapons": D.Hash([]), "armors": D.Hash([]),
            "actors": D.Array([D.Fixnum(1)])})),
    ])
    payload = D.dumps(meta) + D.dumps(state)
    with open(path, "wb") as f:
        f.write(payload)
    return path


class TestN18VXDataFiles(unittest.TestCase):
    """**N-18**：``.rvdata``（VX）必须被当作 RGSS 数据文件。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="n18_")
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name

    def test_rvdata_is_recognized_as_data_ext(self):
        self.assertIn(".rvdata", rgss_data.RGSS_DATA_EXTS)
        self.assertIn(".rvdata2", rgss_data.RGSS_DATA_EXTS)
        self.assertIn(".rxdata", rgss_data.RGSS_DATA_EXTS)

    def test_extract_reads_vx_game(self):
        """VX 游戏必须能扫出文本（修复前是 0 条，且不报错）。"""
        from features.translate.session import ScanOptions
        game = make_vx_game(os.path.join(self.root, "vx"))
        entries = rgss_data.extract(os.path.join(game, "Data"),
                                    ScanOptions(), standard=True)
        self.assertTrue(entries, "VX 游戏扫出了 0 条文本（N-18 复发）")
        texts = {e["original"] for e in entries}
        self.assertIn("药草", texts)
        self.assertIn("勇者", texts)

    def test_session_scan_reads_vx_game(self):
        """整条会话链路（``Session.scan``）也要能读 VX。"""
        from features.translate.session import Session
        game = make_vx_game(os.path.join(self.root, "vxsession"))
        session = Session(game)
        self.assertEqual(session.info["engine"], "vx")
        self.assertGreater(session.scan(), 0)

    def test_wrong_encoding_still_parses(self):
        """编码猜错时 ``load_data_file`` 会自动换另一种（而不是静默失败）。"""
        game = make_vx_game(os.path.join(self.root, "xppairs"), standard=True)
        path = os.path.join(game, "Data", "Items.rvdata")
        # 故意给错偏好（说它是变体编码），仍然必须读出来
        node = rgss_data.load_data_file(path, standard=False)
        self.assertIsNotNone(node)
        # 返回的是值层代理（RMArray），长度用 len() 取
        self.assertEqual(len(node), 2, "自动换编码没生效")

    def test_load_data_file_reports_both_failures(self):
        path = os.path.join(self.root, "broken.rvdata")
        with open(path, "wb") as f:
            f.write(b"not a marshal stream at all")
        with self.assertRaises(ValueError) as caught:
            rgss_data.load_data_file(path, standard=True)
        self.assertIn("两种整数编码都失败", str(caught.exception))


class TestN19MultiStreamSave(unittest.TestCase):
    """**N-19**：多流存档必须找到**状态流**，不能一律用 ``streams[0]``。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="n19_")
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name
        self.path = make_two_stream_save(os.path.join(self.root, "Save01.rvdata2"))

    def _save(self):
        return rgss_save.SaveFile(self.path, layout="hash", standard=False)

    def test_two_streams_are_detected(self):
        save = self._save()
        self.assertEqual(len(save.streams), 2, "夹具应当是两条流")

    def test_state_index_points_at_second_stream(self):
        save = self._save()
        self.assertEqual(save.state_index(), 1,
                         "状态流应当是第 2 条（第 1 条是启动器元数据）")

    def test_read_party_finds_gold(self):
        party = self._save().read_party()
        self.assertEqual(party.get("gold"), 4242, "金币读不出来（N-19 复发）")
        self.assertEqual(party.get("steps"), 99)
        self.assertEqual(party.get("items"), {1: 5})
        self.assertEqual(party.get("party_ids"), [1])

    def test_read_actors_finds_actors(self):
        actors = self._save().read_actors()
        self.assertEqual(len(actors), 2)
        self.assertEqual(actors[1]["level"], 7)

    def test_read_var_finds_values(self):
        save = self._save()
        self.assertEqual(save.read_var("variables")[:3], [0, 10, 20])
        self.assertEqual(save.read_var("switches")[:2], [0, 1])

    def test_explicit_stream_index_still_honored(self):
        """显式传下标时要按该流读；``0`` 是"自动探测"的约定值。

        约定（见 ``rgss_save.SaveFile._pick``）：``0``/``None`` = 自动找状态流，
        其它值 = **显式**下标。本夹具里状态流是下标 1，因此两种写法都要读到
        同一份数据；这条断言把两种语义都钉住（只支持一种的话，
        要么单流存档的既有调用全变自动探测，要么多流存档永远读不出东西）。
        """
        save = self._save()
        self.assertEqual(save.read_party(0).get("gold"), 4242,
                         "传 0 应当自动找到状态流")
        self.assertEqual(save.read_party(1).get("gold"), 4242,
                         "显式传状态流下标（1）应当读到金币")

    def test_write_skips_streams_without_state(self):
        """写操作必须跳过没有状态的流（否则在 None 上取 ivar 会崩）。"""
        save = self._save()
        save.set_gold(777)
        save.set_steps(1)
        save.set_item(1, 9)
        save.save()
        again = self._save()
        self.assertEqual(again.read_party()["gold"], 777)
        self.assertEqual(again.read_party()["items"], {1: 9})

    def test_metadata_stream_is_preserved(self):
        """写回后第 1 条元数据流必须原样保留（字节级）。"""
        with open(self.path, "rb") as f:
            before = f.read()
        save = self._save()
        save.set_gold(777)
        save.save()
        with open(self.path, "rb") as f:
            after = f.read()
        meta_len = len(D.dumps(D.Hash([
            (_sym("characters"), D.Array([D.Array([])])),
            (_sym("playtime_s"), D.Ivar(_str("00:00:42"),
                                        [(_sym("E"), D.BoolNode(True))])),
        ])))
        self.assertEqual(after[:meta_len], before[:meta_len],
                         "第一条（元数据）流被改动了")

    @unittest.skipUnless(os.path.isdir(r"D:\gamess\boli"),
                         "缺少真实 VX Ace 样本（boli）")
    def test_real_sample_two_stream_save(self):
        """真实样本上的同一条断言（本机游戏库里的 2 流存档）。"""
        game = r"D:\gamess\boli\B7794\博麗霊夢は洗脳されてしまいました"
        info = engines.detect(game)
        if info.get("engine") != "vxace":
            self.skipTest("样本引擎不是 vxace：%s" % info.get("engine"))
        names = engines.list_saves(info, game)
        if not names:
            self.skipTest("样本里没有存档")
        save = rgss_save.SaveFile(os.path.join(info["save_dir"], names[0]),
                                  standard=info["standard"],
                                  layout=info["layout"])
        self.assertGreaterEqual(len(save.streams), 2,
                                "该样本应当是 2 流存档")
        party = save.read_party()
        self.assertTrue(party, "真实存档读不出队伍（N-19 复发）")
        actors = save.read_actors()
        self.assertTrue(actors, "真实存档读不出角色（N-19 复发）")
        self.assertTrue(any(a for a in actors), "角色全是空的")


class TestN20ProxyUnwrap(unittest.TestCase):
    """**N-20**：``data_fields`` 读 RGSS 数据文件必须先 unwrap 回节点。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="n20_")
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name

    def test_scan_reads_rgss_fields(self):
        game = make_vx_game(os.path.join(self.root, "vx"))
        info = engines.detect(game)
        rows = data_fields.scan_data(info["data_dir"], "vxace",
                                     standard=info.get("standard"))
        self.assertTrue(rows, "VX 的数据字段一个都没扫出来（N-20 复发）")
        paths = {r["path"] for r in rows}
        self.assertIn("1/@price", paths)
        self.assertIn("1/@name", paths)

    def test_scan_values_are_plain_python(self):
        """扫出来的值必须是普通 Python 类型（能直接 JSON 序列化给界面）。"""
        game = make_vx_game(os.path.join(self.root, "vxplain"))
        info = engines.detect(game)
        rows = data_fields.scan_data(info["data_dir"], "vxace",
                                     standard=info.get("standard"))
        for row in rows:
            with self.subTest(path=row["path"]):
                self.assertIsInstance(row["value"], (int, float, bool, str),
                                      "值类型不对：%r" % type(row["value"]))
        json.dumps(rows, ensure_ascii=False)      # 不抛异常即可序列化

    def test_verify_original_sees_rgss_values(self):
        game = make_vx_game(os.path.join(self.root, "vxverify"))
        info = engines.detect(game)
        stale = data_fields.verify_original(info, [{
            "file": "Items.rvdata", "path": "1/@price",
            "value": 1, "original": 12345, "kind": "int"}])
        self.assertEqual(len(stale), 1, "陈旧性校验读不出 RGSS 值")
        self.assertEqual(stale[0]["actual"], 50)

    def test_variant_encoded_file_also_scans(self):
        """变体编码（VX Ace）与标准编码（VX/XP）都要能扫。"""
        game = make_vx_game(os.path.join(self.root, "variant"), standard=False,
                            ext=".rvdata2")
        info = engines.detect(game)
        rows = data_fields.scan_data(info["data_dir"], "vxace",
                                     standard=info.get("standard"))
        self.assertTrue(rows, "变体编码的数据文件扫不出字段")


if __name__ == "__main__":
    unittest.main(verbosity=2)

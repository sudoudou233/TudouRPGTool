# -*- coding: utf-8 -*-
"""合成 VX / XP 样本：让 ``standard=True`` 这条活路径真正被测到。

@feature  none
@layer    tests
@public   build_synthetic_rvdata, build_synthetic_rxdata, TestB10FixnumStandard,
          TestStandardModeRoundtrip
@depends  core.marshal.doc_model, core.formats.rgss_save, core.engines
@tested   (本文件即测试)
@footprint docs/ROADMAP.md

为什么要合成样本
----------------
本机游戏库覆盖 MV / MZ / VX Ace，**没有** VX（``.rvdata``）与纯 XP（``.rxdata``）
游戏（M0 已登记为空白）。而 ``standard=True``（XP/VX 走的 Ruby 1.8 整数编码）
正是 P0 缺陷 **B-10**（``Parser._fixnum`` 重复定义 → 按变体解析、按标准写回）
的活路径 —— 没有样本就等于没有证据。

做法：用文档模型自己构造最小 ``.rvdata`` / ``.rxdata``，形状取自真实存档：
``[header, [system, switches, variables, self_switches, actors, party, troop, map, player]]``
（``contents`` 布局，见 ``core/formats/rgss_save.py`` 的 ``CONTENTS_INDEX``）。
样本由代码生成，**不入库**（与 docs/DECISIONS.md ADR-005 一致）。
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

from core import constants  # noqa: E402
from core.formats import rgss_save  # noqa: E402
from core.marshal import doc_model as M  # noqa: E402


# ---------------------------------------------------------------------------
# 合成游戏数据 / 存档
# ---------------------------------------------------------------------------
def _sym(name):
    return M.Symbol(name.encode("utf-8"))


def _str(text):
    return M.String(text.encode("utf-8"))


def _obj(class_name, ivars):
    return M.ObjectNode(_sym(class_name),
                        [(_sym(k if k.startswith("@") else "@" + k), v)
                         for k, v in ivars.items()])


def build_synthetic_actors(standard):
    """构造一个含 2 个角色的 Actors 表（``Game_Actor`` 形状）。"""
    actors = [M.NilNode()]
    for actor_id in (1, 2):
        actors.append(_obj("Game_Actor", {
            "id": M.Fixnum(actor_id, std=standard),
            "name": _str("角色%d" % actor_id),
            "class_id": M.Fixnum(1, std=standard),
            "level": M.Fixnum(actor_id * 5, std=standard),
            "exp": M.Hash([(M.Fixnum(1, std=standard),
                            M.Fixnum(1000 * actor_id, std=standard))]),
            "hp": M.Fixnum(200 + actor_id, std=standard),
            "mp": M.Fixnum(50 + actor_id, std=standard),
            "param_plus": M.Array([M.Fixnum(0, std=standard) for _ in range(8)]),
            "skills": M.Array([M.Fixnum(1, std=standard),
                               M.Fixnum(2, std=standard)]),
        }))
    return M.Array(actors)


def _party_node(standard):
    return _obj("Game_Party", {
        "gold": M.Fixnum(1000, std=standard),
        "steps": M.Fixnum(500, std=standard),
        "items": M.Hash([(M.Fixnum(1, std=standard), M.Fixnum(3, std=standard)),
                         (M.Fixnum(2, std=standard), M.Fixnum(1, std=standard))]),
        "weapons": M.Hash([]),
        "armors": M.Hash([]),
        "actors": M.Array([M.Fixnum(1, std=standard), M.Fixnum(2, std=standard)]),
    })


def _switches_node(standard):
    return _obj("Game_Switches", {
        "data": M.Array([M.BoolNode(False), M.BoolNode(True), M.BoolNode(False)]),
    })


def _variables_node(standard):
    return _obj("Game_Variables", {
        "data": M.Array([M.Fixnum(0, std=standard),
                         M.Fixnum(0, std=standard),
                         M.Fixnum(10, std=standard),
                         M.Fixnum(20, std=standard)]),
    })


def build_synthetic_save(engine, save_path):
    """生成一个 ``contents`` 布局的存档文件。

    ``engine`` 为 ``'vx'``（.rvdata）或 ``'xp'``（.rxdata）；两者都走
    ``standard=True``。返回写入的字节数。
    """
    standard = True                      # XP / VX 都是标准 Ruby Marshal
    contents = M.Array([
        _obj("Game_System", {"switches": M.Hash([])}),   # 0 system
        _switches_node(standard),                        # 1 switches
        _variables_node(standard),                       # 2 variables
        M.Hash([]),                                      # 3 self_switches
        build_synthetic_actors(standard),                 # 4 actors
        _party_node(standard),                           # 5 party
        M.Hash([]),                                      # 6 troop
        M.Hash([]),                                      # 7 map
        M.Hash([]),                                      # 8 player
    ])
    root = M.Array([_obj("header", {"title": _str("合成%s存档" % engine)}),
                    contents])
    payload = M.VERSION + root.serialize()
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    with open(save_path, "wb") as f:
        f.write(payload)
    return payload


def build_synthetic_data_table(engine, name, records):
    """构造 ``Data/Items.rvdata2`` 之类的数据表（数组，元素为对象）。"""
    arr = M.Array([M.NilNode()] + records)
    return M.VERSION + arr.serialize()


# ---------------------------------------------------------------------------
# B-10：standard 模式的整数编解码必须对称
# ---------------------------------------------------------------------------
class TestB10FixnumStandard(unittest.TestCase):
    """**B-10** 核心断言：``standard=True`` 时读与写必须用**同一套**编码。

    修复前：``Parser._fixnum`` 被重复定义，第二版无条件走变体编码器 →
    ``standard=True`` 的文件会被"按变体解析、按标准写回"，字节漂移。
    """

    #: 覆盖变体与标准两套编码的所有分支边界
    VALUES = (0, 1, 63, 64, 100, 122, 123, 255, 256, 65535, 65536,
              2 ** 20, 2 ** 30, -1, -63, -64, -122, -123, -255, -65536)

    def test_standard_fixnum_roundtrip(self):
        for value in self.VALUES:
            with self.subTest(value=value):
                raw = M.VERSION + M.Fixnum(value, std=True).serialize()
                node = M.loads(raw, standard=True)
                self.assertEqual(node.value, value,
                                 "standard 模式解析结果不对：%s" % value)
                self.assertEqual(M.dumps(node), raw,
                                 "standard 模式往返字节不一致：%s" % value)

    def test_variant_fixnum_roundtrip(self):
        for value in self.VALUES:
            with self.subTest(value=value):
                raw = M.VERSION + M.Fixnum(value, std=False).serialize()
                node = M.loads(raw, standard=False)
                self.assertEqual(node.value, value)
                self.assertEqual(M.dumps(node), raw,
                                 "变体模式往返字节不一致：%s" % value)

    def test_parser_respects_standard_flag(self):
        """两套编码的**字节**不同，且各自必须解出正确值。

        ``standard=True`` 的 0 是 ``0x05``；变体的 0 是 ``0x00``。
        修复前 standard 模式解析走变体分支，于是 ``0x05`` 被读成 0
        （恰好也对）—— 所以不能只看值，必须断言**往返字节**。
        """
        std_zero = M.VERSION + b"\x69\x05"          # 标准编码的 0
        var_zero = M.VERSION + b"\x69\x00"          # 变体编码的 0
        self.assertEqual(M.loads(std_zero, standard=True).value, 0)
        self.assertEqual(M.loads(var_zero, standard=False).value, 0)
        # 关键：各自往返必须**字节一致**（B-10 的可观测判据）
        self.assertEqual(M.dumps(M.loads(std_zero, standard=True)), std_zero)
        self.assertEqual(M.dumps(M.loads(var_zero, standard=False)), var_zero)

    def test_variant_and_standard_encodings_differ(self):
        """0 在两套编码下的字节必须不同（否则 B-10 无从谈起）。"""
        std = M.Fixnum(0, std=True).serialize()
        var = M.Fixnum(0, std=False).serialize()
        self.assertEqual(std, b"\x69\x05")
        self.assertEqual(var, b"\x69\x00")
        self.assertNotEqual(std, var)

    def test_no_duplicate_fixnum_definition(self):
        import inspect
        src = inspect.getsource(M.Parser)
        self.assertEqual(src.count("def _fixnum"), 1,
                         "**B-10**：Parser 里又出现了重复的 _fixnum 定义")


class TestStandardModeRoundtrip(unittest.TestCase):
    """用合成 VX / XP 存档验证整条链路（含多流与 contents 布局）。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="vxxp_")
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name

    def _make_game(self, engine):
        """造一个最小的 VX / XP 游戏目录。"""
        ext = constants.SAVE_EXTS[engine]
        data_dir = os.path.join(self.root, engine, "Data")
        os.makedirs(data_dir, exist_ok=True)
        with open(os.path.join(data_dir, "Items" + ext), "wb") as f:
            f.write(build_synthetic_data_table(engine, "Items", [
                _obj("RPG::Item", {"id": M.Fixnum(1, std=True),
                                   "name": _str("药水")}),
            ]))
        save_dir = os.path.join(self.root, engine)
        save_name = "Save01" + ext
        build_synthetic_save(engine, os.path.join(save_dir, save_name))
        return save_dir, save_name

    def test_engine_detected_as_standard(self):
        from core import engines
        for engine in ("vx", "xp"):
            with self.subTest(engine=engine):
                self._make_game(engine)
                info = engines.detect(os.path.join(self.root, engine))
                self.assertEqual(info["engine"], engine)
                self.assertTrue(info["standard"],
                                "%s 必须被判定为 standard 模式" % engine)
                self.assertEqual(info["layout"], "contents")

    def test_save_roundtrips_byte_exact(self):
        for engine in ("vx", "xp"):
            with self.subTest(engine=engine):
                save_dir, name = self._make_game(engine)
                path = os.path.join(save_dir, name)
                with open(path, "rb") as f:
                    raw = f.read()
                streams = M.load_streams(raw, standard=True)
                rebuilt = b"".join(M.dumps(node) for _off, node in streams)
                self.assertEqual(rebuilt, raw,
                                 "合成 %s 存档往返字节不一致" % engine)

    def test_savefile_reads_and_writes(self):
        """走 ``rgss_save.SaveFile`` 的完整读写（standard + contents 布局）。"""
        for engine in ("vx", "xp"):
            with self.subTest(engine=engine):
                save_dir, name = self._make_game(engine)
                path = os.path.join(save_dir, name)
                data_dir = os.path.join(self.root, engine, "Data")
                gd = rgss_save.GameData(data_dir, standard=True)
                sf = rgss_save.SaveFile(path, gd, standard=True,
                                        layout="contents")
                party = sf.read_party(0)
                self.assertEqual(party["gold"], 1000)
                self.assertEqual(party["steps"], 500)
                self.assertEqual(party["items"].get(1), 3)
                self.assertEqual(party["party_ids"], [1, 2])

                actors = sf.read_actors(0)
                self.assertEqual(actors[1]["level"], 5)
                self.assertEqual(actors[2]["level"], 10)
                self.assertEqual(actors[1]["skills"], [1, 2])

                self.assertEqual(sf.read_var("variables")[2], 10)
                self.assertEqual(sf.read_var("switches")[1], 1)

                # 改 → 存 → 重读
                sf.set_gold(424242)
                sf.set_item(1, 99)
                sf.set_actor_attr(1, "level", 77)
                sf.set_var("variables", 3, 555)
                sf.save(path)

                again = rgss_save.SaveFile(path, gd, standard=True,
                                           layout="contents")
                self.assertEqual(again.read_party(0)["gold"], 424242)
                self.assertEqual(again.read_party(0)["items"].get(1), 99)
                self.assertEqual(again.read_actors(0)[1]["level"], 77)
                self.assertEqual(again.read_var("variables")[3], 555)

    def test_written_file_still_parses_byte_stable(self):
        """改完再存的文件必须仍然可以无损往返（证明写侧编码正确）。"""
        save_dir, name = self._make_game("vx")
        path = os.path.join(save_dir, name)
        gd = rgss_save.GameData(os.path.join(self.root, "vx", "Data"),
                                standard=True)
        sf = rgss_save.SaveFile(path, gd, standard=True, layout="contents")
        sf.set_gold(123456)
        sf.save(path)

        with open(path, "rb") as f:
            raw = f.read()
        streams = M.load_streams(raw, standard=True)
        rebuilt = b"".join(M.dumps(node) for _off, node in streams)
        self.assertEqual(rebuilt, raw, "改后存档的往返不再字节一致")


class TestVxAceStillVariant(unittest.TestCase):
    """反向断言：VX Ace 仍走**变体**编码，不能被 standard 改动牵连。"""

    def test_vxace_not_standard(self):
        from core import engines
        import tempfile
        with tempfile.TemporaryDirectory(prefix="ace_") as tmp:
            os.makedirs(os.path.join(tmp, "Data"), exist_ok=True)
            with open(os.path.join(tmp, "Data", "Items.rvdata2"), "wb") as f:
                f.write(b"\x04\x08")
            info = engines.detect(tmp)
            self.assertEqual(info["engine"], "vxace")
            self.assertFalse(info["standard"])
            self.assertEqual(info["layout"], "hash")

    def test_variant_encoding_differs_from_standard(self):
        """两套编码的字节必须不同，否则 B-10 就无从谈起。"""
        std = M.Fixnum(0, std=True).serialize()
        var = M.Fixnum(0, std=False).serialize()
        self.assertNotEqual(std, var)
        self.assertEqual(std, b"\x69\x05")
        self.assertEqual(var, b"\x69\x00")


if __name__ == "__main__":
    unittest.main(verbosity=2)

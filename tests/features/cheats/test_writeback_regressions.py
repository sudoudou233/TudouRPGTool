# -*- coding: utf-8 -*-
"""M3b 接线期发现并修复的缺陷的回归测试（N-16 / N-17 / B-02 存档侧）。

@feature  cheats
@layer    tests
@public   TestN16ZeroAndFalseWrites, TestN17StaleCheckFieldName,
          TestSaveModulesAreAtomic
@depends  core.formats.mv_mz_data, core.formats.rgss_data,
          core.formats.mv_save, core.formats.rgss_save,
          features.cheats.data_fields
@tested   (本文件即测试)
@footprint docs/STATE.md

背景：又是"静默不生效"这一类
---------------------------
M3a 的 N-12 ～ N-15 都是"扫描/写回静默丢内容"。M3b 接改档时又冒出同一家族
的两个新成员 —— 而且这次连**成功**都是假的（接口返回 ``ok``，文件却没变）：

* **N-16** 写回层用 ``bool(translated)`` 判断"有没有值"，于是把字段改成
  ``0`` / ``false`` 被当成"没有值"而**丢弃**。表现："把道具数量改成 0
  没反应"、"关掉一个开关之后再打开还在"。两条写回路径
  （``mv_mz_data.apply_to_files`` / ``rgss_data.apply_to_files``）都中招。
* **N-17** 陈旧性校验读的是 ``expect``，而界面与路由传的是 ``original``
  → 校验**永远通过**，等于不存在。这类"防线看起来在、实际不生效"的问题
  比没有防线更危险（评审时会以为已经防住了）。

本文件把它们钉死。两处都属于"接口两侧字段名/判据不一致"，
因此断言都直接打在**可观测后果**上（文件里到底有没有变成 0 / 校验到底拦不拦）。
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
from core.formats import mv_mz_data  # noqa: E402
from core.formats import rgss_data  # noqa: E402
from core.marshal import doc_model as D  # noqa: E402
from features.cheats import data_fields  # noqa: E402


def _sym(name):
    return D.Symbol(name.encode("utf-8"))


def _str(text):
    return D.String(text.encode("utf-8"))


def _obj(class_name, ivars):
    return D.ObjectNode(_sym(class_name), [
        (_sym(k if k.startswith("@") else "@" + k), v) for k, v in ivars.items()])


def make_mv_game(root):
    """合成 MV 游戏：一个道具 + 一个 System.json。"""
    os.makedirs(os.path.join(root, "js"), exist_ok=True)
    os.makedirs(os.path.join(root, "data"), exist_ok=True)
    with open(os.path.join(root, "js", "rpg_core.js"), "w") as f:
        f.write("//\n")
    payload = {
        "System.json": {"gameTitle": "合成", "optDisplayTp": True,
                        "currencyUnit": "金币"},
        "Items.json": [None,
                       {"id": 1, "name": "药草", "price": 50,
                        "consumable": True, "occasion": 0, "itypeId": 1},
                       {"id": 2, "name": "解毒草", "price": 20,
                        "consumable": True, "occasion": 0, "itypeId": 1}],
    }
    for fname, data in payload.items():
        with open(os.path.join(root, "data", fname), "w",
                  encoding="utf-8", newline="\n") as f:
            json.dump(data, f, ensure_ascii=False)
    return root


def make_vxace_game(root):
    """合成 VX Ace 游戏：一个道具表（真实 Marshal 字节流）。"""
    os.makedirs(os.path.join(root, "Data"), exist_ok=True)
    with open(os.path.join(root, "Game.ini"), "w", encoding="utf-8") as f:
        f.write("[Game]\n")
    tree = D.Array([
        D.NilNode(),
        _obj("RPG::Item", {"id": D.Fixnum(1), "name": _str("药草"),
                           "price": D.Fixnum(50),
                           "consumable": D.BoolNode(True),
                           "occasion": D.Fixnum(0)}),
        _obj("RPG::Item", {"id": D.Fixnum(2), "name": _str("解毒草"),
                           "price": D.Fixnum(20),
                           "consumable": D.BoolNode(True),
                           "occasion": D.Fixnum(0)}),
    ])
    with open(os.path.join(root, "Data", "Items.rvdata2"), "wb") as f:
        f.write(D.dumps(tree))
    return root


class TestN16ZeroAndFalseWrites(unittest.TestCase):
    """**N-16**：把值改成 ``0`` / ``false`` 必须真的写进去。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="n16_")
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name

    # ---------------------------------------------------------------- MV/MZ
    def test_mv_zero_is_written(self):
        game = make_mv_game(os.path.join(self.root, "mv"))
        info = engines.detect(game)
        stats = mv_mz_data.apply_to_files(info, {"Items.json": [{
            "file": "Items.json", "path": "1/price", "translated": 0,
            "original": "50", "status": "translated", "kind": "int"}]})
        self.assertEqual(stats["entries"], 1, "改成 0 被丢弃了：%s" % stats)
        with open(os.path.join(game, "data", "Items.json"), encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data[1]["price"], 0)

    def test_mv_false_is_written(self):
        game = make_mv_game(os.path.join(self.root, "mv"))
        info = engines.detect(game)
        stats = mv_mz_data.apply_to_files(info, {"Items.json": [{
            "file": "Items.json", "path": "1/consumable", "translated": False,
            "original": "True", "status": "translated", "kind": "bool"}]})
        self.assertEqual(stats["entries"], 1, "改成 false 被丢弃了：%s" % stats)
        with open(os.path.join(game, "data", "Items.json"), encoding="utf-8") as f:
            data = json.load(f)
        self.assertIs(data[1]["consumable"], False)

    def test_mv_pending_still_skipped(self):
        """反向：``status="pending"`` 的条目仍然不能写（翻译链路依赖这条）。"""
        game = make_mv_game(os.path.join(self.root, "mv"))
        info = engines.detect(game)
        stats = mv_mz_data.apply_to_files(info, {"Items.json": [{
            "file": "Items.json", "path": "1/price", "translated": 999,
            "status": "pending"}]})
        self.assertEqual(stats["entries"], 0)
        with open(os.path.join(game, "data", "Items.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)[1]["price"], 50)

    def test_mv_none_is_skipped(self):
        """``translated=None`` 表示"没有值"，仍然跳过（不是 0）。"""
        game = make_mv_game(os.path.join(self.root, "mv"))
        info = engines.detect(game)
        stats = mv_mz_data.apply_to_files(info, {"Items.json": [{
            "file": "Items.json", "path": "1/price", "translated": None,
            "status": "translated", "kind": "int"}]})
        self.assertEqual(stats["entries"], 0)

    # ---------------------------------------------------------------- RGSS
    def test_rgss_zero_is_written(self):
        game = make_vxace_game(os.path.join(self.root, "ace"))
        info = engines.detect(game)
        stats = rgss_data.apply_to_files(info, {"Items.rvdata2": [{
            "file": "Items.rvdata2", "path": "1/@price", "translated": 0,
            "original": "50", "status": "translated", "kind": "int"}]})
        self.assertEqual(stats["entries"], 1, "改成 0 被丢弃了：%s" % stats)
        with open(os.path.join(game, "Data", "Items.rvdata2"), "rb") as f:
            tree = D.loads(f.read())
        price = D.ivar(tree.items[1], "@price")
        self.assertIsInstance(price, D.Fixnum, "类型漂移：%s" % type(price).__name__)
        self.assertEqual(price.value, 0)

    def test_rgss_false_is_written(self):
        game = make_vxace_game(os.path.join(self.root, "ace"))
        info = engines.detect(game)
        stats = rgss_data.apply_to_files(info, {"Items.rvdata2": [{
            "file": "Items.rvdata2", "path": "1/@consumable", "translated": False,
            "original": "True", "status": "translated", "kind": "bool"}]})
        self.assertEqual(stats["entries"], 1, "改成 false 被丢弃了：%s" % stats)
        with open(os.path.join(game, "Data", "Items.rvdata2"), "rb") as f:
            tree = D.loads(f.read())
        node = D.ivar(tree.items[1], "@consumable")
        self.assertIsInstance(node, D.BoolNode)
        self.assertFalse(node.value)

    def test_rgss_text_link_still_works(self):
        """翻译链路（不带 ``kind``）仍然按字符串写回 —— N-16 的修复不能破坏它。"""
        game = make_vxace_game(os.path.join(self.root, "ace"))
        info = engines.detect(game)
        stats = rgss_data.apply_to_files(info, {"Items.rvdata2": [{
            "file": "Items.rvdata2", "path": "1/@name", "translated": "Herb",
            "original": "药草", "status": "translated"}]})
        self.assertEqual(stats["entries"], 1, stats)
        with open(os.path.join(game, "Data", "Items.rvdata2"), "rb") as f:
            tree = D.loads(f.read())
        self.assertEqual(D.ivar(tree.items[1], "@name").to_py(), "Herb")

    def test_rgss_none_is_skipped(self):
        game = make_vxace_game(os.path.join(self.root, "ace"))
        info = engines.detect(game)
        stats = rgss_data.apply_to_files(info, {"Items.rvdata2": [{
            "file": "Items.rvdata2", "path": "1/@price", "translated": None,
            "status": "translated", "kind": "int"}]})
        self.assertEqual(stats["entries"], 0)


class TestN17StaleCheckFieldName(unittest.TestCase):
    """**N-17**：陈旧性校验必须认界面传的 ``original``。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="n17_")
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name
        self.game = make_mv_game(os.path.join(self.root, "mv"))
        self.info = engines.detect(self.game)

    def test_original_field_triggers_mismatch(self):
        stale = data_fields.verify_original(self.info, [{
            "file": "Items.json", "path": "1/price",
            "value": 999, "original": 12345, "kind": "int"}])
        self.assertEqual(len(stale), 1, "过期的 original 没有被校验拦下")
        self.assertEqual(stale[0]["expect"], 12345)
        self.assertEqual(stale[0]["actual"], 50)

    def test_expect_field_still_accepted(self):
        """兼容：写回层用的 ``expect`` 也要认（两侧字段名都支持）。"""
        stale = data_fields.verify_original(self.info, [{
            "file": "Items.json", "path": "1/price",
            "value": 999, "expect": 12345, "kind": "int"}])
        self.assertEqual(len(stale), 1)

    def test_matching_original_passes(self):
        self.assertEqual(data_fields.verify_original(self.info, [{
            "file": "Items.json", "path": "1/price",
            "value": 999, "original": 50, "kind": "int"}]), [])

    def test_string_and_int_compare_equal(self):
        """``"50"`` 与 ``50`` 视为相同（界面上的输入框永远是字符串）。"""
        self.assertEqual(data_fields.verify_original(self.info, [{
            "file": "Items.json", "path": "1/price",
            "value": 999, "original": "50", "kind": "int"}]), [])

    def test_missing_original_skips_check(self):
        """没带原值就不校验（不是"全部拒绝"）—— 也**不是**静默放行错值。"""
        self.assertEqual(data_fields.verify_original(self.info, [{
            "file": "Items.json", "path": "1/price",
            "value": 999, "kind": "int"}]), [])

    def test_expect_is_forwarded_to_write_layer(self):
        """``build_entries`` 必须把 ``original`` 转成写回层要的 ``expect``。"""
        by_file = data_fields.build_entries([{
            "file": "Items.json", "path": "1/price",
            "value": 999, "original": 50, "kind": "int"}], "mv")
        entry = by_file["Items.json"][0]
        self.assertEqual(entry["expect"], 50)
        self.assertEqual(entry["translated"], 999)
        self.assertEqual(entry["kind"], "int")

    def test_write_layer_honors_expect(self):
        """带 ``expect`` 且不一致时，写回层**逐条跳过**而不是照写。"""
        stats = mv_mz_data.apply_to_files(self.info, {"Items.json": [{
            "file": "Items.json", "path": "1/price", "translated": 999,
            "expect": 12345, "status": "translated", "kind": "int"}]})
        self.assertEqual(stats["entries"], 0, stats)
        self.assertEqual(stats["skipped"], 1, stats)
        with open(os.path.join(self.game, "data", "Items.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)[1]["price"], 50, "不一致时不该写")

    def test_write_layer_accepts_matching_expect(self):
        stats = mv_mz_data.apply_to_files(self.info, {"Items.json": [{
            "file": "Items.json", "path": "1/price", "translated": 999,
            "expect": 50, "status": "translated", "kind": "int"}]})
        self.assertEqual(stats["entries"], 1, stats)
        with open(os.path.join(self.game, "data", "Items.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)[1]["price"], 999)


class TestSaveModulesAreAtomic(unittest.TestCase):
    """**B-02 的最后一处**：改存档必须是原子写，且失败时原文件字节不变。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="b02s_")
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name

    def _make_mv_save(self):
        from core.formats import mv_save
        data = {
            "party": {"_gold": 1000, "_steps": 500, "_items": {}, "_weapons": {},
                      "_armors": {}, "_actors": {"@a": [1]}},
            "switches": {"_data": {"@a": [True]}},
            "variables": {"_data": {"@a": [0]}},
            "actors": {"_data": {"@a": [
                None, {"_actorId": 1, "_classId": 1, "_level": 5,
                       "_exp": {"1": 0}, "_hp": 10, "_mp": 5, "_tp": 0,
                       "_paramPlus": {"@a": [0] * 8}, "_skills": {"@a": []}}]}},
        }
        path = os.path.join(self.root, "file0.rpgsave")
        with open(path, "wb") as f:
            f.write(mv_save.SaveFileMV._dump(data, "mv"))
        return path

    def test_mv_save_uses_atomic_write(self):
        import io
        rel = os.path.join("core", "formats", "mv_save.py")
        src = io.open(os.path.join(_ROOT, rel), encoding="utf-8").read()
        self.assertIn("atomic_write", src)
        # ⚠ 不能用字符串匹配 "open(path, 'wb')" 判断违规：**docstring 里会写**
        # "原实现是 open(path, 'wb')" 来解释这次修复，字符串匹配会把说明文字
        # 当成违规（M2a 已经踩过一次，这里用 AST）。
        self.assertEqual(_direct_write_opens(rel), [],
                         "mv_save 仍有直接写模式 open")

    def test_rgss_save_uses_atomic_write(self):
        import io
        rel = os.path.join("core", "formats", "rgss_save.py")
        src = io.open(os.path.join(_ROOT, rel), encoding="utf-8").read()
        self.assertIn("atomic_write", src)
        self.assertEqual(_direct_write_opens(rel), [],
                         "rgss_save 仍有直接写模式 open")

    def test_mv_save_failure_keeps_original(self):
        from core.formats import mv_save
        from core.safety import atomic
        path = self._make_mv_save()
        with open(path, "rb") as f:
            original = f.read()
        save = mv_save.SaveFileMV(path, engine="mv")
        save.set_gold(999999)

        real = atomic.os.replace
        atomic.os.replace = _boom
        try:
            with self.assertRaises(atomic.AtomicWriteError):
                save.save(path)
        finally:
            atomic.os.replace = real
        with open(path, "rb") as f:
            self.assertEqual(f.read(), original, "写入失败后原存档必须字节不变")

    def test_no_leaked_file_handles_in_save_modules(self):
        """回归：``open(path,'rb').read()`` 不关句柄（Windows 上会挡替换/删除）。

        判据：这两个模块里不允许出现"裸 ``open(...).read()``"这种链式调用。
        """
        import ast
        import io
        for rel in ("core/formats/mv_save.py", "core/formats/rgss_save.py"):
            with self.subTest(module=rel):
                tree = ast.parse(io.open(os.path.join(_ROOT, rel),
                                         encoding="utf-8").read())
                offenders = []
                for node in ast.walk(tree):
                    if (isinstance(node, ast.Call)
                            and isinstance(node.func, ast.Attribute)
                            and node.func.attr == "read"
                            and isinstance(node.func.value, ast.Call)
                            and isinstance(node.func.value.func, ast.Name)
                            and node.func.value.func.id == "open"):
                        offenders.append(node.lineno)
                self.assertEqual(offenders, [],
                                 "%s 里仍有 open(...).read() 链式调用（句柄泄漏）：%s"
                                 % (rel, offenders))


def _boom(src, dst):
    raise OSError("模拟 replace 失败")


def _direct_write_opens(rel_path):
    """用 AST 找出模块里真正的 ``open(..., 写模式)`` 调用（与 M2a 同一手法）。"""
    import ast
    import io
    tree = ast.parse(io.open(os.path.join(_ROOT, rel_path),
                             encoding="utf-8").read())
    found = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "open"):
            continue
        mode = None
        if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
            mode = node.args[1].value
        for kw in node.keywords:
            if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
                mode = kw.value.value
        if mode is None:
            continue
        if any(ch in str(mode) for ch in ("w", "a", "x", "+")):
            found.append((node.lineno, mode))
    return found


if __name__ == "__main__":
    unittest.main(verbosity=2)

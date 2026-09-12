# -*- coding: utf-8 -*-
"""MV/MZ 游戏数据与存档编解码的兼容性测试。

@feature  translate
@layer    tests
@public   TestMvMzExtract, TestLzString, TestMvSaveRoundtrip, TestRgssExtract
@depends  core.formats.mv_mz_data, core.formats.mv_save,
          core.formats.rgss_data, core.formats.lzstring
@tested   (本文件即测试)
@footprint docs/MODULES.md#coreformats

移植来源
--------
* ``rpgmaker_cheating_tool/test_mvmz.py`` —— MV/MZ 探测 + 存档读写改回读
* ``rpgmaker_cheating_tool/lzstring.py``  —— MV 存档所用的压缩算法
* ``rpgmaker_translation_tool/tool/mv_mz.py`` —— 游戏数据 JSON 提取与写回
* ``rpgmaker_translation_tool/tool/vxace.py``  —— RGSS 数据提取

本文件用**合成样本**（临时目录里造出的最小游戏结构），因此任何机器都能跑，
不依赖本机游戏库。原测试硬编码 ``D:\\gamess\\...``，这里全部参数化。
"""

from __future__ import annotations

import json
import os
import struct
import sys
import tempfile
import unittest
import zlib

_ROOT = os.path.dirname(os.path.abspath(__file__))
while not os.path.isfile(os.path.join(_ROOT, "app.py")):
    parent = os.path.dirname(_ROOT)
    if parent == _ROOT:
        raise RuntimeError("无法定位工程根（未找到 app.py）")
    _ROOT = parent
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.formats import lzstring, mv_mz_data, mv_save  # noqa: E402


class ScanOptions(object):
    """最小 ScanOptions 替身（真实实现在 features/translate/session.py）。

    注意：这里必须是**实例属性**而非类属性 —— 用类属性会让"改开关"静默失效
    （子类覆盖 ``include_comments = False`` 看起来生效，但 vendored 代码读的是
    实例上的值），M1 实测踩到。真实实现用 ``__init__`` 赋实例属性。
    """

    def __init__(self, include_comments=True, include_notes=True,
                 include_event_names=True, include_animations=True):
        self.include_comments = include_comments
        self.include_notes = include_notes
        self.include_event_names = include_event_names
        self.include_animations = include_animations


def make_mv_game(root):
    """在 root 造一个最小的 MV 游戏目录结构。"""
    data_dir = os.path.join(root, "www", "data")
    os.makedirs(data_dir, exist_ok=True)
    os.makedirs(os.path.join(root, "www", "js"), exist_ok=True)
    with open(os.path.join(root, "www", "js", "rpg_core.js"), "w",
              encoding="utf-8") as f:
        f.write("// marker")
    write_json(os.path.join(data_dir, "System.json"), {
        "gameTitle": "测试游戏",
        "currencyUnit": "金币",
        "elements": ["火", "冰"],
        "terms": {"basic": ["等级", "HP"], "messages": {"actionFailure": "没有效果"}},
    })
    write_json(os.path.join(data_dir, "Items.json"), [
        None,
        {"id": 1, "name": "药水", "description": "回复少量 HP", "note": "备注一"},
        {"id": 2, "name": "解毒草", "description": "", "note": ""},
    ])
    write_json(os.path.join(data_dir, "Map001.json"), {
        "displayName": "起始村",
        "events": [{
            "id": 1,
            "name": "村民",
            "pages": [{
                "list": [
                    {"code": 401, "parameters": ["你好，旅行者。"]},
                    {"code": 401, "parameters": ["\\V[1]欢迎来到这里。"]},
                    {"code": 402, "parameters": [["是", "否"], 1, 0]},
                    {"code": 101, "parameters": ["无关指令"]},
                ]
            }],
        }],
    })
    write_json(os.path.join(data_dir, "CommonEvents.json"), [
        None,
        {"id": 1, "name": "开场", "list": [{"code": 401, "parameters": ["开始了"]}]},
    ])
    write_json(os.path.join(data_dir, "MapInfos.json"), [
        None, {"id": 1, "name": "起始村"},
    ])
    return data_dir


def write_json(path, payload):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)


class TestMvMzExtract(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="mvmz_")
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name
        self.data_dir = make_mv_game(self.root)

    def test_extracts_expected_categories(self):
        entries = mv_mz_data.extract(self.data_dir, ScanOptions())
        self.assertTrue(entries, "未提取到任何条目")
        categories = {e["category"] for e in entries}
        self.assertIn("名称", categories)
        self.assertIn("描述", categories)
        self.assertIn("界面术语", categories)
        self.assertIn("地图名", categories)
        self.assertIn("对话", categories)

    def test_entry_schema(self):
        entries = mv_mz_data.extract(self.data_dir, ScanOptions())
        for entry in entries:
            with self.subTest(path=entry["path"]):
                for field in ("file", "path", "category", "original",
                              "translated", "status", "note"):
                    self.assertIn(field, entry)
                self.assertEqual(entry["status"], "pending")
                self.assertEqual(entry["translated"], "")

    def test_extracts_expected_texts(self):
        entries = mv_mz_data.extract(self.data_dir, ScanOptions())
        originals = {e["original"] for e in entries}
        for expected in ("测试游戏", "金币", "药水", "回复少量 HP", "起始村",
                         "你好，旅行者。", "\\V[1]欢迎来到这里。", "是", "否"):
            with self.subTest(text=expected):
                self.assertIn(expected, originals)

    def test_short_cjk_choices_are_extracted(self):
        """单字选项（如是/否）必须被提取。

        这是 M1 实测发现的行为要点：`是` / `否` / `あ` / `한` 这类
        短 CJK 文本没有 ASCII 字母，但 `str.isalpha()` 对它们返回 True，
        因此不会被 `has_real_text` 误过滤。
        """
        entries = mv_mz_data.extract(self.data_dir, ScanOptions())
        originals = {e["original"] for e in entries}
        self.assertIn("是", originals)
        self.assertIn("否", originals)

    def test_control_code_dialogue_extracted(self):
        """带控制码的对话必须被提取（它是有文本，不能被丢）。"""
        entries = mv_mz_data.extract(self.data_dir, ScanOptions())
        self.assertTrue(any("\\V[1]" in e["original"] for e in entries))

    def test_irrelevant_command_codes_skipped(self):
        entries = mv_mz_data.extract(self.data_dir, ScanOptions())
        self.assertFalse(any("无关指令" in e["original"] for e in entries))

    def test_include_comments_switch(self):
        no_notes = ScanOptions(include_notes=False)
        write_json(os.path.join(self.data_dir, "Items.json"), [
            None,
            {"id": 1, "name": "药水", "description": "d", "note": "备注一"},
        ])
        with_notes = mv_mz_data.extract(self.data_dir, ScanOptions())
        without = mv_mz_data.extract(self.data_dir, no_notes)
        self.assertTrue(any(e["category"] == "备注" for e in with_notes))
        self.assertFalse(any(e["category"] == "备注" for e in without))

    def test_apply_to_files_writes_only_translated(self):
        entries = mv_mz_data.extract(self.data_dir, ScanOptions())
        target = [e for e in entries if e["original"] == "药水"]
        self.assertTrue(target)
        changed = False
        for entry in entries:
            if entry["original"] == "药水":
                entry["translated"] = "Potion"
                entry["status"] = "translated"
                changed = True
        self.assertTrue(changed)
        by_file = {}
        for entry in entries:
            if entry["status"] == "translated":
                by_file.setdefault(entry["file"], []).append(entry)
        stats = mv_mz_data.apply_to_files({"data_dir": self.data_dir}, by_file)
        self.assertGreaterEqual(stats["entries"], 1)
        with open(os.path.join(self.data_dir, "Items.json"), encoding="utf-8-sig") as f:
            data = json.load(f)
        self.assertEqual(data[1]["name"], "Potion")
        # 未翻译的字段必须原样保留
        self.assertEqual(data[2]["name"], "解毒草")

    def test_apply_skips_pending_entries(self):
        entries = mv_mz_data.extract(self.data_dir, ScanOptions())
        by_file = {}
        for entry in entries:
            by_file.setdefault(entry["file"], []).append(entry)
        stats = mv_mz_data.apply_to_files({"data_dir": self.data_dir}, by_file)
        self.assertEqual(stats["entries"], 0, "未翻译的条目不得被写入")


class TestEncryptedWrapper(unittest.TestCase):
    """加密 JSON 包装（``{"uid","bid","data"}``）必须能解也能再加密。"""

    def test_roundtrip_key_derivation_is_deterministic(self):
        self.assertEqual(mv_mz_data._derive_key("Items.json"),
                         mv_mz_data._derive_key("Items.json"))
        self.assertNotEqual(mv_mz_data._derive_key("Items.json"),
                            mv_mz_data._derive_key("Weapons.json"))

    def test_encrypt_decrypt_roundtrip(self):
        plain = json.dumps([None, {"id": 1, "name": "药水"}], ensure_ascii=False)
        wrapped = mv_mz_data._encrypt_wrapped(plain, "Items.json")
        self.assertNotIn("药水", wrapped)
        self.assertEqual(mv_mz_data._decrypt_wrapped(wrapped, "Items.json"), plain)

    def test_load_and_save_wrapped_file(self):
        with tempfile.TemporaryDirectory(prefix="wrap_") as tmp:
            path = os.path.join(tmp, "Items.json")
            original = [None, {"id": 1, "name": "药水"}]
            payload = {
                "uid": "u1",
                "bid": "b1",
                "data": mv_mz_data._encrypt_wrapped(
                    json.dumps(original, ensure_ascii=False), "Items.json"),
            }
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)

            data, wrapped, header = mv_mz_data._load_data_file(path, "Items.json")
            self.assertTrue(wrapped)
            self.assertEqual(data, original)
            self.assertEqual(header["uid"], "u1")

            data[1]["name"] = "Potion"
            mv_mz_data._save_data_file(path, "Items.json", data, wrapped, header)

            again, wrapped2, _header2 = mv_mz_data._load_data_file(path, "Items.json")
            self.assertTrue(wrapped2)
            self.assertEqual(again[1]["name"], "Potion")


class TestLzString(unittest.TestCase):
    """MV 存档所用的 LZString 实现（移植自修改工具，纯 Python）。"""

    def test_text_roundtrip(self):
        samples = [
            "", "a", "hello world",
            "中文文本·测试" * 3,
            json.dumps({"party": {"_gold": 12345}}, ensure_ascii=False),
            "A" * 5000,
            "".join(chr(i) for i in range(32, 127)),
        ]
        for text in samples:
            with self.subTest(sample=text[:24]):
                self.assertEqual(lzstring.decompress(lzstring.compress(text)), text)

    def test_base64_roundtrip(self):
        text = json.dumps({"a": 1, "b": "中文"}, ensure_ascii=False) * 20
        encoded = lzstring.compress_to_base64(text)
        self.assertIsInstance(encoded, str)
        self.assertEqual(lzstring.decompress_from_base64(encoded), text)

    def test_base64_output_is_ascii_safe(self):
        encoded = lzstring.compress_to_base64("中文" * 100)
        encoded.encode("ascii")      # 不得抛异常

    def test_large_payload_compresses(self):
        text = json.dumps({"items": {str(i): 1 for i in range(500)}})
        encoded = lzstring.compress_to_base64(text)
        self.assertLess(len(encoded), len(text))


class TestMvSaveRoundtrip(unittest.TestCase):
    """MV/MZ 存档读写改回读（移植 test_mvmz.py:69-73 的断言）。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="mvsave_")
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name

    def _make_save(self, engine):
        """构造一个最小 MV/MZ 存档（形状与真实 JsonEx 一致）。"""
        data = {
            "system": {"_switches": {"@a": [True, False]}},
            "switches": {"_data": {"@a": [True, False, True]}},
            "variables": {"_data": {"@a": [0, 10, 20]}},
            "party": {
                "_gold": 1000,
                "_steps": 500,
                "_items": {"@c": 1, "1": 3},
                "_weapons": {"1": 1},
                "_armors": {},
                "_actors": {"@a": [1, 2]},
            },
            "actors": {"_data": {"@a": [
                None,
                {"_actorId": 1, "_classId": 1, "_level": 5, "_exp": {"1": 100},
                 "_hp": 200, "_mp": 50, "_tp": 0, "_paramPlus": {"@a": [0] * 8},
                 "_skills": {"@a": [1, 2]}},
                {"_actorId": 2, "_classId": 2, "_level": 3, "_exp": {"2": 50},
                 "_hp": 100, "_mp": 30, "_tp": 0, "_paramPlus": {"@a": [0] * 8},
                 "_skills": {"@a": []}},
            ]}},
        }
        path = os.path.join(self.root, "file0.rmmzsave" if engine == "mz"
                            else "file0.rpgsave")
        with open(path, "wb") as f:
            f.write(mv_save.SaveFileMV._dump(data, engine))
        return path

    def test_mv_encode_decode_roundtrip(self):
        path = self._make_save("mv")
        sf = mv_save.SaveFileMV(path, engine="mv")
        party = sf.read_party(0)
        self.assertEqual(party["gold"], 1000)
        self.assertEqual(party["steps"], 500)
        self.assertEqual(party["items"].get(1), 3)
        self.assertEqual(party["party_ids"], [1, 2])

    def test_mz_encode_decode_roundtrip(self):
        path = self._make_save("mz")
        # MZ 存档以 0x78 开头的 zlib 流经 latin-1 存为 UTF-8 文本
        with open(path, "rb") as f:
            raw = f.read()
        self.assertEqual(raw[0], 0x78, "MZ 存档应是 zlib 流（首字节 0x78）")
        sf = mv_save.SaveFileMV(path, engine="mz")
        self.assertEqual(sf.read_party(0)["gold"], 1000)

    def test_edit_and_reload(self):
        """移植原断言：改金币/物品/角色后重新解析必须看到新值。"""
        path = self._make_save("mv")
        sf = mv_save.SaveFileMV(path, engine="mv")
        sf.set_gold(123456)
        sf.set_item(1, 99)
        sf.set_item(9999, 7)                 # 原本不存在的物品
        sf.set_actor_attr(1, "level", 88)
        sf.set_actor_attr(1, "hp", 7777)
        sf.set_actor_attr(1, "param_plus_0", 300)
        sf.set_var("variables", 5, 555)
        sf.save(path)

        again = mv_save.SaveFileMV(path, engine="mv")
        party = again.read_party(0)
        self.assertEqual(party["gold"], 123456)
        self.assertEqual(party["items"].get(1), 99)
        self.assertEqual(party["items"].get(9999), 7)
        actors = again.read_actors(0)
        self.assertEqual(actors[1]["level"], 88)
        self.assertEqual(actors[1]["hp"], 7777)
        self.assertEqual(actors[1]["param_plus"][0], 300)
        self.assertEqual(again.read_var("variables")[5], 555)

    def test_set_item_zero_removes_entry(self):
        path = self._make_save("mv")
        sf = mv_save.SaveFileMV(path, engine="mv")
        sf.set_item(1, 0)
        self.assertNotIn(1, sf.read_party(0)["items"])

    def test_json_ex_metadata_preserved(self):
        """改数值不得破坏 JsonEx 的 ``@c/@a`` 元数据（否则游戏读不了档）。"""
        path = self._make_save("mv")
        sf = mv_save.SaveFileMV(path, engine="mv")
        sf.set_gold(5)
        sf.save(path)
        with open(path, "rb") as f:
            raw = f.read()
        text = lzstring.decompress_from_base64(raw.decode("utf-8"))
        data = json.loads(text)
        self.assertIn("@c", data["party"]["_items"])
        self.assertEqual(data["party"]["_items"]["@c"], 1)
        self.assertIn("@a", data["party"]["_actors"])

    def test_actor_skills_replace(self):
        path = self._make_save("mv")
        sf = mv_save.SaveFileMV(path, engine="mv")
        sf.set_actor_skills(1, [5, 6, 7])
        sf.save(path)
        again = mv_save.SaveFileMV(path, engine="mv")
        self.assertEqual(again.read_actors(0)[1]["skills"], [5, 6, 7])

    def test_zlib_level_and_engine_dispatch(self):
        data = {"a": 1}
        mv_bytes = mv_save.SaveFileMV._dump(data, "mv")
        mz_bytes = mv_save.SaveFileMV._dump(data, "mz")
        self.assertNotEqual(mv_bytes, mz_bytes)
        self.assertEqual(mz_bytes[0], 0x78)
        self.assertEqual(json.loads(lzstring.decompress_from_base64(
            mv_bytes.decode("utf-8"))), data)
        self.assertEqual(json.loads(zlib.decompress(
            mz_bytes.decode("utf-8").encode("latin-1")).decode("utf-8")), data)


class TestRgssExtract(unittest.TestCase):
    """VX Ace / XP 数据提取：至少验证模块可导入且 API 存在。

    真实 rvdata2 需要 marshal 构造，M2a 会用合成 rvdata2 补完整覆盖。
    """

    def test_module_api(self):
        from core.formats import rgss_data
        self.assertTrue(callable(rgss_data.extract))
        self.assertTrue(callable(rgss_data.apply_to_files))

    def test_text_codes_shared_with_mv_mz(self):
        """RGSS 与 MV/MZ 必须共用同一份事件指令白名单（否则两处规则会漂移）。"""
        from core.formats import rgss_data
        self.assertIs(rgss_data.TEXT_CODES, mv_mz_data.TEXT_CODES)

    def test_extract_on_empty_dir_returns_list(self):
        from core.formats import rgss_data
        with tempfile.TemporaryDirectory(prefix="rgss_") as tmp:
            self.assertEqual(rgss_data.extract(tmp, ScanOptions()), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)

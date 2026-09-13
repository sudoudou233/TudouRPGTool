# -*- coding: utf-8 -*-
"""``core/iconutil.py`` 的单元测试：图集定位 / 解密 / 切片几何。

@feature  none
@layer    tests
@public   make_png, encrypt_png, TestDecrypt, TestPngSize, TestGeometry,
          TestFindSheet, TestEncryptionKey, TestLoad
@depends  core.iconutil, core.engines
@tested   (本文件即测试)
@footprint docs/MODULES.md#coreiconutil

为什么锚点必须包含**真实字节**
------------------------------
如果夹具是"自己写一个 encrypt_png，再断言 decrypt_image 能还原"，
那这条测试只能证明"我的加密与我的解密互为逆运算"，**证明不了算法与
真实游戏一致** —— 算法整体写反了它照样绿。

所以这里额外钉了两组真实样本的**头 32 字节 + System.json 的 key**：

* ``REAL_MV_*`` —— ``D:\\test1\\wdss2`` 的 ``IconSet.rpgmvp``，解出来必须是
  合法 PNG 头（这条锚定了算法本身）；
* ``REAL_BROKEN_*`` —— ``D:\\gamess\\demon\\DD_V07c_Windows`` 的
  ``IconSet.png_``，用 7 个真实游戏的 key 全试过都解不开（被第三方汉化
  注入器改过），必须**抛错**而不是返回乱码。

只留 32 字节，不是偷懒：既足以锚定算法，又不需要把游戏资源放进仓库。
"""

from __future__ import annotations

import json
import os
import shutil
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

from core import engines            # noqa: E402
from core import iconutil           # noqa: E402

# ---------------------------------------------------------------------------
# 真实样本锚点（见模块 docstring：为什么必须是真的）
# ---------------------------------------------------------------------------
#: ``D:\test1\wdss2\www\img\system\IconSet.rpgmvp`` 的头 32 字节
REAL_MV_HEAD = bytes.fromhex(
    "5250474d560000000003010000000000"      # RPGMV 伪头
    "021f46890310a5a543897b0fb62ad33d")     # 真实 PNG 前 16 字节（已异或）
#: 上面那个游戏 ``www/data/System.json`` 的 ``encryptionKey``
REAL_MV_KEY = "8b4f08ce0e1abfaf43897b02ff62976f"
#: 解密后应当得到的东西：PNG 签名 + IHDR 块头
REAL_MV_PNG_HEAD = bytes.fromhex("89504e470d0a1a0a0000000d49484452")

#: ``D:\gamess\demon\DD_V07c_Windows\img\system\IconSet.png_`` 的头 32 字节
REAL_BROKEN_HEAD = bytes.fromhex(
    "5250474d560000000003010000000000"
    "8654ca9f71b8b704bec54bc8baa87a32")
#: 那个游戏 ``data/System.json`` 声明的 key（试过 7 个真实 key 都不对）
REAL_BROKEN_KEY = "d41d8cd98f00b204e9800998ecf8427e"


# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------
def make_png(width, height, rgba=(31, 41, 59, 255)):
    """造一张**真的能解码**的 PNG（8 位 RGBA，filter 0）。

    刻意用真图而不是"只有 IHDR 的假头"：几何推算之外，``load()`` 还要
    确认整条链路拿到的字节是能用的图片。
    """
    row = bytes(rgba) * width
    raw = bytearray()
    for _ in range(height):
        raw.append(0)
        raw.extend(row)

    def chunk(tag, payload):
        return (struct.pack(">I", len(payload)) + tag + payload
                + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(bytes(raw), 6))
            + chunk(b"IEND", b""))


def encrypt_png(png, key_hex):
    """把 PNG 按 MV/MZ 的加壳方式包起来（``decrypt_image`` 的逆运算）。"""
    key = bytes.fromhex(key_hex)
    head = bytes(a ^ b for a, b in zip(png[:16], key))
    return iconutil.MV_HEADER + head + png[16:]


def write_bytes(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(payload)


def write_json(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, ensure_ascii=False)


def make_mv_tree(root, sheet=None, key=None, layout="www", sheet_name="IconSet.png"):
    """造一个最小的 MV 目录树，返回 ``engines.detect`` 的结果。

    ``layout='www'`` 用老版 NW.js 布局（``<root>/www``），``'flat'`` 用
    MZ 那种扁平布局（资源直接在游戏根）—— 两种真实都存在。
    """
    js_root = os.path.join(root, "www") if layout == "www" else root
    with open(os.path.join(_ensure(js_root, "js"), "rpg_core.js"), "w",
              encoding="utf-8") as f:
        f.write("// synthetic\n")
    system = {"gameTitle": "合成MV", "currencyUnit": "金币"}
    if key is not None:
        system["encryptionKey"] = key
        system["hasEncryptedImages"] = True
    write_json(os.path.join(js_root, "data", "System.json"), system)
    if sheet is not None:
        write_bytes(os.path.join(js_root, "img", "system", sheet_name), sheet)
    return engines.detect(root)


def _ensure(*parts):
    path = os.path.join(*parts)
    os.makedirs(path, exist_ok=True)
    return path


class IconTestCase(unittest.TestCase):
    def setUp(self):
        try:
            self.tmp = tempfile.TemporaryDirectory(prefix="icon_",
                                                   ignore_cleanup_errors=True)
        except TypeError:                       # Python 3.8 / 3.9
            self.tmp = tempfile.TemporaryDirectory(prefix="icon_")
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name

    def mv_info(self, **kw):
        root = os.path.join(self.root, "game")
        os.makedirs(root, exist_ok=True)
        return make_mv_tree(root, **kw)


# ---------------------------------------------------------------------------
# 解密
# ---------------------------------------------------------------------------
class TestDecrypt(IconTestCase):

    def test_real_game_bytes_decrypt_to_a_png_header(self):
        """**算法锚点**：真实游戏的加密头 + 真实 key → 真实 PNG 头。"""
        payload = REAL_MV_HEAD + b"\x00" * 32
        out = iconutil.decrypt_image(payload, REAL_MV_KEY)
        self.assertEqual(out[:16], REAL_MV_PNG_HEAD)
        # 16 字节之后的字节必须原样搬过来（不能顺手"解密"整份文件）
        self.assertEqual(out[16:], b"\x00" * 32)

    def test_round_trip_on_synthetic_sheet(self):
        png = make_png(512, 64)
        key = "00112233445566778899aabbccddeeff"
        packed = encrypt_png(png, key)
        self.assertEqual(iconutil.decrypt_image(packed, key), png)

    def test_real_broken_sample_raises_instead_of_garbage(self):
        """**反向锚点**：解不开的真实样本必须报错，不能画出乱码。"""
        payload = REAL_BROKEN_HEAD + b"\x00" * 32
        with self.assertRaises(ValueError) as ctx:
            iconutil.decrypt_image(payload, REAL_BROKEN_KEY)
        self.assertIn("解不开", str(ctx.exception))

    def test_missing_key_is_reported_as_such(self):
        payload = REAL_MV_HEAD + b"\x00" * 32
        with self.assertRaises(ValueError) as ctx:
            iconutil.decrypt_image(payload, "")
        self.assertIn("encryptionKey", str(ctx.exception))

    def test_non_hex_key(self):
        payload = REAL_MV_HEAD + b"\x00" * 32
        with self.assertRaises(ValueError) as ctx:
            iconutil.decrypt_image(payload, "zz" * 16)
        self.assertIn("十六进制", str(ctx.exception))

    def test_wrong_length_key(self):
        payload = REAL_MV_HEAD + b"\x00" * 32
        with self.assertRaises(ValueError) as ctx:
            iconutil.decrypt_image(payload, "00" * 8)
        self.assertIn("32 位十六进制", str(ctx.exception))

    def test_too_short_file(self):
        with self.assertRaises(ValueError) as ctx:
            iconutil.decrypt_image(iconutil.MV_HEADER, REAL_MV_KEY)
        self.assertIn("太小", str(ctx.exception))


# ---------------------------------------------------------------------------
# PNG 尺寸
# ---------------------------------------------------------------------------
class TestPngSize(unittest.TestCase):

    def test_reads_ihdr(self):
        self.assertEqual(iconutil.png_size(make_png(512, 640)), (512, 640))
        self.assertEqual(iconutil.png_size(make_png(384, 1032)), (384, 1032))

    def test_rejects_non_png(self):
        self.assertIsNone(iconutil.png_size(b"not a png at all............"))
        self.assertIsNone(iconutil.png_size(b""))
        self.assertIsNone(iconutil.png_size(REAL_MV_HEAD + b"\x00" * 32))

    def test_rejects_truncated(self):
        self.assertIsNone(iconutil.png_size(make_png(8, 8)[:20]))

    def test_rejects_non_ihdr_first_chunk(self):
        bad = bytearray(make_png(8, 8))
        bad[12:16] = b"XXXX"
        self.assertIsNone(iconutil.png_size(bytes(bad)))


# ---------------------------------------------------------------------------
# 切片几何
# ---------------------------------------------------------------------------
class TestGeometry(unittest.TestCase):

    def test_mv_is_32px_16_columns(self):
        """真实 MV 图集 512x640 -> 32px/16 列/20 行/320 格。"""
        geo = iconutil.geometry(512, 640, "mv")
        self.assertEqual(geo, {"cell": 32, "columns": 16, "rows": 20, "count": 320})

    def test_mz_same_as_mv(self):
        self.assertEqual(iconutil.geometry(512, 640, "mz")["cell"], 32)

    def test_vxace_is_24px_16_columns(self):
        """真实 VX Ace 图集 384x1032 -> 24px/16 列/43 行/688 格。"""
        geo = iconutil.geometry(384, 1032, "vxace")
        self.assertEqual(geo, {"cell": 24, "columns": 16, "rows": 43, "count": 688})

    def test_vxace_prefers_24_over_32(self):
        """384x1248 用 24 和 32 都能整除 —— 必须选引擎标准的 24。

        用 32 会得到"12 列、39 行、468 格"，格子全部错位（而且看着还挺合理）。
        选 24 才是"16 列、52 行、832 格"。
        """
        geo = iconutil.geometry(384, 1248, "vxace")
        self.assertEqual(geo, {"cell": 24, "columns": 16, "rows": 52, "count": 832})

    def test_mv_prefers_32_over_24(self):
        geo = iconutil.geometry(512, 640, "mv")
        self.assertEqual(geo["cell"], 32)

    def test_falls_back_to_another_cell_for_weird_sheets(self):
        """魔改图集（列数不是 16）也要能用，只是列数不同。"""
        geo = iconutil.geometry(480, 480, "mv")     # 480/32=15 列
        self.assertEqual(geo["cell"], 32)
        self.assertEqual(geo["columns"], 15)
        self.assertEqual(geo["count"], 225)

    def test_returns_none_when_nothing_divides(self):
        self.assertIsNone(iconutil.geometry(511, 640, "mv"))

    def test_unknown_engine_uses_32(self):
        self.assertEqual(iconutil.geometry(512, 640, None)["cell"], 32)


# ---------------------------------------------------------------------------
# 定位
# ---------------------------------------------------------------------------
class TestFindSheet(IconTestCase):

    def _touch(self, info, rel, payload=b"x"):
        write_bytes(os.path.join(info["js_root"], *rel), payload)

    def test_prefers_plain_png_over_encrypted(self):
        info = self.mv_info()
        self._touch(info, ("img", "system", "IconSet.rpgmvp"))
        self._touch(info, ("img", "system", "IconSet.png"))
        found = iconutil.find_sheet(info)
        self.assertTrue(found["path"].endswith("IconSet.png"))

    def test_finds_mv_encrypted_sheet(self):
        info = self.mv_info()
        self._touch(info, ("img", "system", "IconSet.rpgmvp"))
        self.assertTrue(iconutil.find_sheet(info)["path"].endswith(".rpgmvp"))

    def test_finds_mz_encrypted_sheet(self):
        info = self.mv_info(layout="flat")
        self._touch(info, ("img", "system", "IconSet.png_"))
        self.assertTrue(iconutil.find_sheet(info)["path"].endswith(".png_"))

    def test_none_when_absent(self):
        self.assertIsNone(iconutil.find_sheet(self.mv_info()))

    def test_rgss_looks_under_graphics_system(self):
        """RGSS 系没有 www 分层，图集在 <游戏根>/Graphics/System。"""
        root = _ensure(self.root, "vxgame")
        with open(os.path.join(root, "Game.ini"), "w", encoding="utf-8") as f:
            f.write("[Game]\nTitle=合成\n")
        data = _ensure(root, "Data")
        # 让 engines 认出 vxace：需要 Data 目录里有 .rvdata2
        with open(os.path.join(data, "System.rvdata2"), "wb") as f:
            f.write(b"\x04\x08")
        write_bytes(os.path.join(root, "Graphics", "System", "IconSet.png"),
                    make_png(384, 96))
        info = engines.detect(root)
        self.assertEqual(info.get("engine"), "vxace", info)
        found = iconutil.find_sheet(info)
        self.assertIsNotNone(found)
        self.assertTrue(found["path"].endswith(os.path.join("Graphics", "System",
                                                            "IconSet.png")))


# ---------------------------------------------------------------------------
# key 读取
# ---------------------------------------------------------------------------
class TestEncryptionKey(IconTestCase):

    def test_reads_from_data_dir(self):
        info = self.mv_info(key=REAL_MV_KEY)
        self.assertEqual(iconutil.encryption_key(info), REAL_MV_KEY)

    def test_empty_when_absent(self):
        self.assertEqual(iconutil.encryption_key(self.mv_info()), "")

    def test_blank_counted_as_absent(self):
        info = self.mv_info(key="   ")
        self.assertEqual(iconutil.encryption_key(info), "")

    def test_non_string_counted_as_absent(self):
        root = os.path.join(self.root, "g2")
        os.makedirs(root, exist_ok=True)
        info = make_mv_tree(root)
        write_json(os.path.join(info["data_dir"], "System.json"),
                   {"gameTitle": "x", "encryptionKey": 12345})
        self.assertEqual(iconutil.encryption_key(info), "")

    def test_broken_system_json_does_not_raise(self):
        info = self.mv_info()
        with open(os.path.join(info["data_dir"], "System.json"), "w",
                  encoding="utf-8") as f:
            f.write("{ this is not json")
        self.assertEqual(iconutil.encryption_key(info), "")


# ---------------------------------------------------------------------------
# 总入口
# ---------------------------------------------------------------------------
class TestLoad(IconTestCase):

    def test_plain_png_sheet(self):
        info = self.mv_info(sheet=make_png(512, 640))
        meta, data = iconutil.load(info)
        self.assertTrue(meta["available"], meta["reason"])
        self.assertFalse(meta["encrypted"])
        self.assertEqual(meta["cell"], 32)
        self.assertEqual(meta["count"], 320)
        self.assertTrue(data.startswith(b"\x89PNG"))

    def test_encrypted_sheet_is_decrypted(self):
        png = make_png(512, 640)
        info = self.mv_info(sheet=encrypt_png(png, REAL_MV_KEY),
                            sheet_name="IconSet.rpgmvp", key=REAL_MV_KEY)
        meta, data = iconutil.load(info)
        self.assertTrue(meta["available"], meta["reason"])
        self.assertTrue(meta["encrypted"])
        self.assertEqual(data, png)
        self.assertEqual(meta["engine"], "mv")

    def test_encrypted_without_key_explains_why(self):
        info = self.mv_info(sheet=encrypt_png(make_png(512, 64), REAL_MV_KEY),
                            sheet_name="IconSet.rpgmvp")
        meta, data = iconutil.load(info)
        self.assertFalse(meta["available"])
        self.assertIsNone(data)
        self.assertIn("encryptionKey", meta["reason"])

    def test_wrong_key_reports_cannot_decrypt(self):
        info = self.mv_info(sheet=encrypt_png(make_png(512, 64), REAL_MV_KEY),
                            sheet_name="IconSet.rpgmvp",
                            key="00" * 16)
        meta, data = iconutil.load(info)
        self.assertFalse(meta["available"])
        self.assertIn("解不开", meta["reason"])

    def test_no_sheet_reports_where_it_looked(self):
        meta, data = iconutil.load(self.mv_info())
        self.assertFalse(meta["available"])
        self.assertIn("IconSet.png", meta["reason"])
        self.assertIn("Graphics", meta["reason"])

    def test_not_a_png_reports_clearly(self):
        info = self.mv_info(sheet=b"definitely not a png" + b"\x00" * 40)
        meta, _data = iconutil.load(info)
        self.assertFalse(meta["available"])
        self.assertIn("不是有效的 PNG", meta["reason"])

    def test_no_game(self):
        meta, data = iconutil.load(None)
        self.assertFalse(meta["available"])
        self.assertIsNone(data)
        self.assertEqual(meta["reason"], "还没有打开游戏")

    def test_recognize_only_engine(self):
        meta, _data = iconutil.load({"engine": "2k3", "game_dir": self.root})
        self.assertFalse(meta["available"])
        self.assertIn("只识别不支持修改", meta["reason"])

    def test_unsupported_geometry_is_reported(self):
        info = self.mv_info(sheet=make_png(511, 640))
        meta, _data = iconutil.load(info)
        self.assertFalse(meta["available"])
        self.assertIn("不符合已知布局", meta["reason"])

    def test_content_overrides_extension(self):
        """扩展名是 .png 但内容是加壳的 —— 也要按加密处理。

        真实游戏里存在被汉化/破解工具改名或重新打包的资源。
        """
        png = make_png(512, 64)
        info = self.mv_info(sheet=encrypt_png(png, REAL_MV_KEY),
                            sheet_name="IconSet.png", key=REAL_MV_KEY)
        meta, data = iconutil.load(info)
        self.assertTrue(meta["available"], meta["reason"])
        self.assertTrue(meta["encrypted"])
        self.assertEqual(data, png)

    def test_meta_is_json_serialisable(self):
        info = self.mv_info(sheet=make_png(512, 64))
        meta, _data = iconutil.load(info)
        json.dumps(meta)                     # 不抛即通过


if __name__ == "__main__":
    unittest.main(verbosity=2)

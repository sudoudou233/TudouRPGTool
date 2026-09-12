# -*- coding: utf-8 -*-
"""`core/formats/jsoncodec.py` 的单元测试（MV/MZ 共享编解码层）。

@feature  none
@layer    tests
@public   TestTextAndJson, TestMetaKeys, TestWrapper, TestSaveCompression,
          TestConvergence
@depends  core.formats.jsoncodec
@tested   (本文件即测试)
@footprint docs/MODULES.md#coreformats
"""

from __future__ import annotations

import io
import json
import json as _json
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

from core.formats import jsoncodec  # noqa: E402


class TestTextAndJson(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="codec_")
        self.addCleanup(self.tmp.cleanup)

    def _write(self, name, text, encoding="utf-8"):
        path = os.path.join(self.tmp.name, name)
        with open(path, "w", encoding=encoding, newline="") as f:
            f.write(text)
        return path

    def test_reads_bom(self):
        """RPG Maker 的 JSON 常带 BOM，必须能读。"""
        path = self._write("bom.json", '\ufeff{"a": 1}')
        self.assertEqual(jsoncodec.read_json_file(path), {"a": 1})

    def test_reads_plain_utf8(self):
        path = self._write("plain.json", '{"中文": "值"}')
        self.assertEqual(jsoncodec.read_json_file(path), {"中文": "值"})

    def test_broken_json_raises_with_path(self):
        """坏 JSON 必须抛错并带上路径 —— 不能静默返回 None。"""
        path = self._write("bad.json", "{not json")
        with self.assertRaises(ValueError) as ctx:
            jsoncodec.read_json_file(path)
        self.assertIn("bad.json", str(ctx.exception))

    def test_dumps_pretty_is_indented_and_unescaped(self):
        text = jsoncodec.dumps_pretty([None, {"name": "药水"}])
        self.assertIn("\n", text, "游戏数据文件需要缩进")
        self.assertIn("药水", text, "不应转义非 ASCII")

    def test_dumps_compact_has_no_padding(self):
        text = jsoncodec.dumps_compact({"a": 1, "b": [1, 2], "中文": "值"})
        self.assertNotIn(": ", text)
        self.assertNotIn(", ", text)
        self.assertIn("中文", text, "不应转义非 ASCII")

    def test_pretty_and_compact_both_reparse(self):
        payload = {"a": [1, 2, {"b": "中文"}], "c": None}
        for text in (jsoncodec.dumps_pretty(payload),
                     jsoncodec.dumps_compact(payload)):
            with self.subTest(starts=text[:12]):
                self.assertEqual(json.loads(text), payload)

    def test_write_text_file_normalizes_newlines(self):
        path = os.path.join(self.tmp.name, "nl.json")
        jsoncodec.write_text_file(path, "a\r\nb")
        with open(path, "rb") as f:
            self.assertEqual(f.read(), b"a\nb")

    def test_write_bytes_file_roundtrip(self):
        path = os.path.join(self.tmp.name, "b.bin")
        jsoncodec.write_bytes_file(path, b"\x00\x01\xff")
        with open(path, "rb") as f:
            self.assertEqual(f.read(), b"\x00\x01\xff")


class TestMetaKeys(unittest.TestCase):
    def test_meta_keys_exact(self):
        self.assertEqual(set(jsoncodec.META_KEYS), {"@c", "@a", "@", "@r"})

    def test_is_meta_key(self):
        for key in ("@c", "@a", "@", "@r"):
            self.assertTrue(jsoncodec.is_meta_key(key))
        for key in ("_gold", "1", "@x", ""):
            self.assertFalse(jsoncodec.is_meta_key(key))

    def test_strip_meta_keys(self):
        self.assertEqual(
            jsoncodec.strip_meta_keys({"@c": 1, "1": 3, "@a": []}),
            {"1": 3})
        self.assertEqual(jsoncodec.strip_meta_keys(None), {})

    def test_int_map_from_string_and_int_keys(self):
        self.assertEqual(
            jsoncodec.int_map_from({"@c": 1, "1": 3, 2: "5", "@a": []}),
            {1: 3, 2: 5})

    def test_int_map_from_skips_garbage(self):
        self.assertEqual(
            jsoncodec.int_map_from({"x": "abc", "3": 1, None: 2}),
            {3: 1})

    def test_int_map_from_non_dict(self):
        for value in (None, [], "x", 3):
            with self.subTest(value=value):
                self.assertEqual(jsoncodec.int_map_from(value), {})

    def test_meta_keys_is_frozenset(self):
        """元数据键集合必须不可变，避免被调用方误改。"""
        self.assertIsInstance(jsoncodec.META_KEYS, frozenset)


class TestWrapper(unittest.TestCase):
    def test_is_wrapped(self):
        self.assertTrue(jsoncodec.is_wrapped(
            {"uid": "u", "bid": "b", "data": "x"}))
        self.assertFalse(jsoncodec.is_wrapped({"uid": "u", "bid": "b"}))
        self.assertFalse(jsoncodec.is_wrapped([]))
        self.assertFalse(jsoncodec.is_wrapped(None))

    def test_split_and_join_roundtrip(self):
        original = {"uid": "U1", "bid": "B1", "data": "PAYLOAD"}
        header, payload = jsoncodec.split_wrapper(original)
        self.assertEqual(header, {"uid": "U1", "bid": "B1"})
        self.assertEqual(payload, "PAYLOAD")
        self.assertEqual(jsoncodec.join_wrapper(header, payload), original)

    def test_join_preserves_key_order(self):
        """包装键顺序保持 uid/bid/data（与原实现一致，便于人工比对）。"""
        self.assertEqual(list(jsoncodec.join_wrapper({}, "x")),
                         ["uid", "bid", "data"])

    def test_derive_key_is_deterministic_and_name_dependent(self):
        a = jsoncodec.derive_wrapper_key("Items.json")
        self.assertEqual(a, jsoncodec.derive_wrapper_key("Items.json"))
        self.assertNotEqual(a, jsoncodec.derive_wrapper_key("Weapons.json"))
        self.assertTrue(0 <= a <= 255)

    def test_derive_key_ignores_directory(self):
        self.assertEqual(jsoncodec.derive_wrapper_key(r"a\b\Items.json"),
                         jsoncodec.derive_wrapper_key("Items.json"))

    def test_payload_encrypt_decrypt_roundtrip(self):
        plain = json.dumps([None, {"name": "药水"}], ensure_ascii=False)
        encrypted = jsoncodec.encrypt_wrapper_payload(plain, "Items.json")
        self.assertNotIn("药水", encrypted)
        self.assertEqual(
            jsoncodec.decrypt_wrapper_payload(encrypted, "Items.json"), plain)

    def test_encrypted_payload_is_ascii(self):
        encrypted = jsoncodec.encrypt_wrapper_payload("中文" * 50, "Map1.json")
        encrypted.encode("ascii")      # 不得抛异常

    def test_crypt_is_its_own_inverse(self):
        data = bytes(range(256)) * 3
        key = jsoncodec.derive_wrapper_key("X.json")
        enc = jsoncodec.crypt_wrapper_bytes(data, key, encrypt=True)
        dec = jsoncodec.crypt_wrapper_bytes(enc, key, encrypt=False)
        self.assertEqual(dec, data)
        self.assertNotEqual(enc, data)


class TestSaveCompression(unittest.TestCase):
    def test_is_zlib_stream(self):
        import zlib
        self.assertTrue(jsoncodec.is_zlib_stream(zlib.compress(b"x")))
        self.assertFalse(jsoncodec.is_zlib_stream(b""))
        self.assertFalse(jsoncodec.is_zlib_stream(b"abc"))

    def test_mv_roundtrip(self):
        text = json.dumps({"a": 1, "中文": "值"}, ensure_ascii=False)
        raw = jsoncodec.compress_save(text, "mv")
        self.assertNotEqual(raw[0], 0x78)
        self.assertEqual(jsoncodec.decompress_save(raw), text)

    def test_mz_roundtrip(self):
        text = json.dumps({"a": 1, "中文": "值"}, ensure_ascii=False)
        raw = jsoncodec.compress_save(text, "mz")
        self.assertEqual(raw[0], 0x78, "zlib 流首字节应为 0x78")
        self.assertEqual(jsoncodec.decompress_save(raw), text)

    def test_decompress_autodetects_regardless_of_label(self):
        """内容优先：给错 engine 也必须能解出来。"""
        text = '{"x": 1}'
        self.assertEqual(jsoncodec.decompress_save(
            jsoncodec.compress_save(text, "mv")), text)
        self.assertEqual(jsoncodec.decompress_save(
            jsoncodec.compress_save(text, "mz")), text)

    def test_save_engine_inference(self):
        self.assertEqual(
            jsoncodec.save_engine(jsoncodec.compress_save("{}", "mz")), "mz")
        self.assertEqual(
            jsoncodec.save_engine(jsoncodec.compress_save("{}", "mv")), "mv")
        self.assertEqual(jsoncodec.save_engine(b"", default="mv"), "mv")

    def test_compress_is_smaller_for_repetitive_data(self):
        text = json.dumps({"items": {str(i): 1 for i in range(300)}})
        for engine in ("mv", "mz"):
            with self.subTest(engine=engine):
                self.assertLess(len(jsoncodec.compress_save(text, engine)),
                                len(text))


class TestConvergence(unittest.TestCase):
    """M2b 收敛断言：两条 MV/MZ 路径必须共用同一份实现。"""

    def _module_source(self, rel):
        with io.open(os.path.join(_ROOT, rel), encoding="utf-8") as f:
            return f.read()

    def test_mv_mz_data_uses_codec(self):
        src = self._module_source("core/formats/mv_mz_data.py")
        self.assertIn("jsoncodec", src)

    def test_mv_save_uses_codec(self):
        src = self._module_source("core/formats/mv_save.py")
        self.assertIn("jsoncodec", src)

    def test_no_duplicate_wrapper_implementation(self):
        """加密包装只能有一份实现（不能在 mv_mz_data 里再写一遍）。"""
        src = self._module_source("core/formats/mv_mz_data.py")
        self.assertNotIn("base64.b64decode", src,
                         "mv_mz_data 不应自己实现包装解密（应转发 jsoncodec）")
        self.assertNotIn("205 ^", src,
                         "mv_mz_data 不应自己实现密钥派生（应转发 jsoncodec）")

    def test_no_duplicate_meta_keys_definition(self):
        """JsonEx 元数据键集合只能有一处定义。"""
        hits = []
        for dirpath, dirnames, filenames in os.walk(os.path.join(_ROOT, "core")):
            dirnames[:] = [d for d in dirnames if d != "__pycache__"]
            for name in filenames:
                if not name.endswith(".py"):
                    continue
                full = os.path.join(dirpath, name)
                with io.open(full, encoding="utf-8") as f:
                    text = f.read()
                # 只看真正的集合字面量赋值，不看注释/文档
                if '"@c"' in text and "@a" in text and "'@a'" in text:
                    if "META_KEYS = " in text or "= frozenset" in text:
                        hits.append(
                            os.path.relpath(full, _ROOT).replace(os.sep, "/"))
        # jsoncodec 是唯一真源；mv_save 只做别名转发（META_KEYS = jsoncodec.META_KEYS）
        self.assertIn("core/formats/jsoncodec.py", hits)
        self.assertEqual(len(hits), 1,
                         "JsonEx 元数据键出现了多处定义：%s" % hits)

    def test_no_duplicate_compression_logic(self):
        """zlib / LZString 的调用只应出现在 jsoncodec 与 lzstring 自身。"""
        offenders = []
        for rel in ("core/formats/mv_mz_data.py", "core/formats/mv_save.py"):
            src = self._module_source(rel)
            if "zlib." in src or "lzstring.compress" in src or \
                    "lzstring.decompress" in src:
                offenders.append(rel)
        self.assertEqual(offenders, [],
                         "压缩调用应集中在 jsoncodec：%s" % offenders)

    def test_public_api_declared(self):
        """jsoncodec 的公开 API 必须能被 import（防止只写在文档里）。"""
        for name in ("read_json_file", "dumps_pretty", "dumps_compact",
                     "is_wrapped", "split_wrapper", "join_wrapper",
                     "derive_wrapper_key", "crypt_wrapper_bytes",
                     "is_zlib_stream", "decompress_save", "compress_save",
                     "save_engine", "int_map_from", "strip_meta_keys",
                     "is_meta_key", "write_text_file", "write_bytes_file"):
            with self.subTest(name=name):
                self.assertTrue(hasattr(jsoncodec, name),
                                "jsoncodec 缺少 %s" % name)


if __name__ == "__main__":
    unittest.main(verbosity=2)

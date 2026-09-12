# -*- coding: utf-8 -*-
"""textutil 模块的专用测试（控制码切分/还原与"纯控制码"判定修正）。

@feature  translate
@layer    tests
@public   TestSplitText, TestHasRealText, TestSegmentsRoundtrip
@depends  core.textutil
@tested   (本文件即测试)
@footprint docs/MODULES.md#coretextutil
"""

from __future__ import annotations

import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.abspath(__file__))
while not os.path.isfile(os.path.join(_ROOT, "app.py")):
    parent = os.path.dirname(_ROOT)
    if parent == _ROOT:
        raise RuntimeError("无法定位工程根（未找到 app.py）")
    _ROOT = parent
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core import textutil  # noqa: E402


class TestSplitText(unittest.TestCase):
    """控制码必须原样保留、不被送去翻译（硬约束 §9）。"""

    def test_variable_code(self):
        self.assertEqual(textutil.split_text("你好\\V[1]世界"),
                         [(True, "你好"), (False, "\\V[1]"), (True, "世界")])

    def test_name_code(self):
        parts = textutil.split_text("\\N[3]你好")
        self.assertEqual(parts, [(False, "\\N[3]"), (True, "你好")])

    def test_color_code(self):
        parts = textutil.split_text("\\C[2]红字\\C[0]")
        self.assertEqual(parts, [(False, "\\C[2]"), (True, "红字"), (False, "\\C[0]")])

    def test_icon_code(self):
        parts = textutil.split_text("\\I[64]治疗药水")
        self.assertEqual(parts, [(False, "\\I[64]"), (True, "治疗药水")])

    def test_bare_control_no_bracket(self):
        """``\\G`` 这类无参数控制码也要被识别。"""
        parts = textutil.split_text("\\G你好")
        self.assertEqual(parts, [(False, "\\G"), (True, "你好")])

    def test_newlines_are_controls(self):
        parts = textutil.split_text("a\nb\r\nc")
        self.assertEqual([s for p, s in parts if p], ["a", "b", "c"])
        self.assertEqual([s for p, s in parts if not p], ["\n", "\r\n"])

    def test_literal_backslash_pair(self):
        parts = textutil.split_text("a\\\\b")
        self.assertEqual(parts, [(True, "a"), (False, "\\\\"), (True, "b")])

    def test_no_control_codes(self):
        self.assertEqual(textutil.split_text("纯中文"), [(True, "纯中文")])

    def test_empty(self):
        self.assertEqual(textutil.split_text(""), [])


class TestHasRealText(unittest.TestCase):
    """修正行为（相对原实现）：纯控制码不算"有文本"。

    原实现 ``rpgmaker_translation_tool/tool/textutil.py:33-40`` 只做
    ``any(ch.isalpha())``，于是 ``"\\V[1]"`` 因其中的 ``V`` 被判定为有文本，
    会被送去翻译 —— 翻译接口改写 ``\\V[1]`` 会破坏游戏变量引用。
    """

    def test_plain_text(self):
        self.assertTrue(textutil.has_real_text("hello"))
        self.assertTrue(textutil.has_real_text("中文"))

    def test_blank(self):
        for value in ("", "   ", "\t\n", None, 12345):
            with self.subTest(value=value):
                self.assertFalse(textutil.has_real_text(value))

    def test_pure_control_codes_are_not_text(self):
        """**核心修正断言** —— 这条在原实现下会失败。"""
        for value in ("\\V[1]", "\\N[3]", "\\C[2]", "\\G", "\\V[1]\\C[2]",
                      "\\I[64]", "\\V[1]\\V[2]\\V[3]"):
            with self.subTest(value=value):
                self.assertFalse(textutil.has_real_text(value),
                                 "%r 是纯控制码，不应被判为有文本" % value)

    def test_control_code_plus_text_is_text(self):
        self.assertTrue(textutil.has_real_text("\\V[1]你好"))
        self.assertTrue(textutil.has_real_text("\\C[2]HP"))

    def test_control_code_plus_whitespace_is_not_text(self):
        self.assertFalse(textutil.has_real_text("\\V[1]   "))


class TestSegmentsRoundtrip(unittest.TestCase):
    def test_rebuild_restores_control_codes(self):
        text = "\\V[1]你好\\C[2]世界"
        segments, slices = textutil.collect_segments([text])
        self.assertEqual(segments, ["你好", "世界"])
        self.assertEqual(textutil.rebuild([text], slices, ["HELLO", "WORLD"])[0],
                         "\\V[1]HELLO\\C[2]WORLD")

    def test_rebuild_falls_back_when_translation_missing(self):
        text = "\\V[1]你好"
        _segments, slices = textutil.collect_segments([text])
        self.assertEqual(textutil.rebuild([text], slices, [])[0], text)

    def test_rebuild_multiple_texts_keeps_order(self):
        texts = ["A\\V[1]B", "C\\N[2]D"]
        segments, slices = textutil.collect_segments(texts)
        self.assertEqual(segments, ["A", "B", "C", "D"])
        self.assertEqual(textutil.rebuild(texts, slices, ["a", "b", "c", "d"]),
                         ["a\\V[1]b", "c\\N[2]d"])

    def test_pure_control_code_string_untouched(self):
        text = "\\V[1]"
        segments, slices = textutil.collect_segments([text])
        self.assertEqual(segments, [])
        self.assertEqual(textutil.rebuild([text], slices, []), [text])

    def test_cjk_and_control_codes_survive_together(self):
        text = "\\C[2]\\N[1]\\C[0]：\\V[10] 已获得\\I[64]！"
        segments, _slices = textutil.collect_segments([text])
        self.assertEqual(segments, ["：", " 已获得", "！"])

    def test_known_gap_symbol_escapes_not_matched(self):
        """固化**已知缺口**（M0 §3.5）：符号型转义 ``\\{`` ``\\}`` 等不被匹配。

        这条断言记录的是"当前行为"而非"期望行为"。M2a 修好之后本用例会失败，
        从而强制我们同步更新文档与这里的断言（有意为之）。
        """
        parts = textutil.split_text("a\\{b\\}c")
        self.assertEqual([s for p, s in parts if not p], [],
                         "符号型转义当前不被识别（已知缺口，M2a 处置）")


if __name__ == "__main__":
    unittest.main(verbosity=2)

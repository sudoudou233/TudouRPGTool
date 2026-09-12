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

    def test_symbol_escapes_now_matched(self):
        """N-08 已修（M2a）：符号型转义 ``\\{`` ``\\}`` 等现在被正确识别。

        这条测试原先固化的是"已知缺口"（当时正则不匹配它们）。
        M2a 补齐正则后，断言随之翻转为"必须匹配" —— 这正是当初写
        "固化当前行为"的目的：修复时它会失败，强制我们同步更新文档与断言。
        """
        # 注意 "\\G" 在 Python 字面量里是「反斜杠 + G」；而 "\\{" 等也同理。
        # 这里显式用 chr(92) 拼接，避免读者误以为 \\G 是换行转义。
        backslash = chr(92)
        for code in ("{", "}", "^", "|", ".", "!", ">", "<", "$"):
            with self.subTest(code=code):
                token = backslash + code
                parts = textutil.split_text("a" + token + "b")
                controls = [seg for is_plain, seg in parts if not is_plain]
                self.assertIn(token, controls,
                              "%r 应被识别为控制码（N-08 修复后）" % token)
        # \G 是字母型控制码（货币单位），单独断言。
        # 注意用分隔符而不是紧接英文字母：`\Gb` 会被字母型分支读成 `\Gb`
        # （\G 后面恰好跟英文字母时无法区分控制码与正文，这是 RPG Maker
        #  文本本身固有的歧义；真实用法里 \G 后面跟的是标点或中文）。
        parts = textutil.split_text("共" + backslash + "G 100")
        controls = [seg for is_plain, seg in parts if not is_plain]
        self.assertIn(backslash + "G", controls, r"\G 应被识别为控制码")


if __name__ == "__main__":
    unittest.main(verbosity=2)

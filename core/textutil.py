# -*- coding: utf-8 -*-
"""
Helpers for splitting RPG Maker text into translatable chunks.

@feature  translate
@layer    core
@public   CONTROL_RE, split_text, has_real_text, collect_segments, rebuild
@depends  (stdlib only)
@tested   tests/unit/test_textutil.py
@footprint docs/MODULES.md#coretextutil
@note     vendored：来自 rpgmaker_translation_tool/tool/textutil.py。
@note     已知问题见 docs/M0-现状测绘.md section 3.5：原注释声称支持
@note     \{ \} \^ \| \. \! \> \< \$ 这些符号型转义，但 CONTROL_RE
@note     要求反斜杠后必须是字母，因此它们从不被匹配（M2a 处置）。
@note     原 translate_segments() 是全仓零调用的死代码，未搬入。
"""

from __future__ import annotations

import re

# RPG Maker MV/MZ/VX-Ace style escape codes: \V[1], \N[name], \C[2],
# \I[icon], \{ \} \^ \| \. \! \> \< \$ \G, plus literal line breaks.
CONTROL_RE = re.compile(r"\\[A-Za-z]{1,3}(?:\[[^\]\r\n]*\])?|\r\n|\n|\\\\")


def split_text(text):
    """Split a game string into (is_plain_text, segment) pairs.

    Control sequences (variable references, icons, newlines...) are kept
    untouched and are not translated.
    """
    if not text:
        return []
    parts = []
    pos = 0
    for m in CONTROL_RE.finditer(text):
        if m.start() > pos:
            parts.append((True, text[pos:m.start()]))
        parts.append((False, m.group(0)))
        pos = m.end()
    if pos < len(text):
        parts.append((True, text[pos:]))
    return parts


def has_real_text(text):
    """判断字符串是否含**真正可翻译**的文本。

    修正行为（相对原实现 rpgmaker_translation_tool/tool/textutil.py:33-40）
    --------------------------------------------------------------------
    原实现只做 ``any(ch.isalpha())``，因此 ``"\\V[1]"`` 这类**纯控制码**字符串
    会被判为"有文本"（因为控制码里的 ``V`` 是字母），从而被送去翻译——翻译
    接口会把 ``\\V[1]`` 改写成别的形式，破坏游戏变量引用。

    本实现先剥离控制码再判断：只有剥离后仍含字母才算有文本。
    这条修正已被 tests/unit/test_misc.py 的用例锁定。
    """
    if not text:
        return False
    if not isinstance(text, str):
        return False
    # 用 split_text 复用同一套控制码定义，避免两处规则漂移
    plain = "".join(seg for is_plain, seg in split_text(text) if is_plain)
    stripped = plain.strip()
    if not stripped:
        return False
    return any(ch.isalpha() for ch in stripped)


def translate_segments(text, seg_translations):
    """Rejoin translated plain segments with the original control codes."""
    if not text:        return ""
    parts = split_text(text)
    out = []
    i = 0
    for is_plain, seg in parts:
        if is_plain:
            if i < len(seg_translations):
                out.append(seg_translations[i])
            else:
                out.append(seg)
            i += 1
        else:
            out.append(seg)
    return "".join(out)


def collect_segments(texts):
    """Return (segments list, per-text slice info, rebuild fn data)."""
    segments = []
    slices = []
    for text in texts:
        parts = split_text(text)
        plain = [(j, seg) for j, (is_p, seg) in enumerate(parts) if is_p]
        slices.append(plain)
        for _, seg in plain:
            segments.append(seg)
    return segments, slices


def rebuild(texts, slices, translated_segments):
    out = []
    idx = 0
    for text, plain in zip(texts, slices):
        if not plain:
            out.append(text)
            continue
        parts = split_text(text)
        trans = []
        j = 0
        for is_plain, seg in parts:
            if is_plain:
                trans.append(translated_segments[idx] if idx < len(translated_segments) else seg)
                idx += 1
                j += 1
            else:
                trans.append(seg)
        out.append("".join(trans))
    return out

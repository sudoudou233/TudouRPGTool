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
@note     M2a 修复 N-08：原 CONTROL_RE 只匹配"反斜杠 + 字母"与换行，
@note     注释里声称支持的 \{ \} \^ \| \. \! \> \< \$ 从不被匹配。
@note     现已补齐符号型转义分支，并用 tests/compat/test_m2a_regressions.py
@note     的 TestN08SymbolEscapes 锁定。
@note     原 translate_segments() 是全仓零调用的死代码，未搬入。
"""

from __future__ import annotations

import re

# RPG Maker MV/MZ/VX Ace 的控制码。四类，必须**全部**匹配，
# 否则控制码会被当成普通文本送去翻译，译文回来时游戏变量/图标/换行就坏了。
#
#   1. `\` + 1~3 个字母 + 可选 `[...]` 参数：\V[1] \N[name] \C[2] \I[3] \G
#   2. `\` + 一个符号型转义：\{ \} \^ \| \. \! \> \< \$ \\
#      （2026-09-12 M2a 修复 N-08：原正则要求 `\` 后必须是字母，因此这一整类
#       从不被匹配 —— 注释写着支持、实现却没有，属于"注释与实现不符"。
#       `\\` 也归入本分支，语义与原来一致。）
#   3. CRLF
#   4. LF
#
# 注意字符类里 `-` 放在末尾、`]` 紧跟 `^` 之后，避免被当成区间或提前闭合。
CONTROL_RE = re.compile(
    # 1) 字母型：\V[1] \N[name] \C[2] \I[3] \G
    #    限 {1,2} 且**不允许带方括号参数**：RPG Maker 的控制码字母最多 2 个
    #    （V/N/C/I/P/PI/PX/PY/NC/NW/NE/FS…），而 \G 这类单字母码后面
    #    直接跟正文。原实现写 {1,3} 且无参数约束，会把 `\G你好` 里的
    #    `\G你` 当成一个控制码吃掉（M2a 实测发现），因此收紧。
    r"\\[A-Za-z]{1,2}(?!\[)"                  # 不接 [ 的字母型
    r"|\\[A-Za-z]{1,2}\[[^\]\r\n]*\]"         # 接 [参数] 的字母型
    r"|\\\\"                                  # 2) 字面双反斜杠（须排在符号型之前）
    r"|\\[{}^|.!><$]"                         # 3) 符号型：\{ \} \^ \| \. \! \> \< \$
    r"|\r\n"                                  # 4) CRLF
    r"|\n"                                    # 5) LF
)


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
    这条修正已被 tests/unit/test_textutil.py 的用例锁定。
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

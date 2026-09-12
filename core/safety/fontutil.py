# -*- coding: utf-8 -*-
"""
Minimal TrueType/OpenType font helpers (stdlib only).

@feature  translate
@layer    core
@public   extract_family, safe_filename
@depends  (stdlib only)
@tested   tests/compat/test_build_backup.py
@footprint docs/MODULES.md#coresafety
@note     vendored：来自 rpgmaker_translation_tool/tool/fontutil.py。
"""

from __future__ import annotations

import os
import re
import struct


def _read_u16(buf, off):
    return struct.unpack_from(">H", buf, off)[0]


def _read_u32(buf, off):
    return struct.unpack_from(">I", buf, off)[0]


def _decode_name(raw, platform_id, encoding_id):
    if platform_id == 3 and encoding_id in (1, 10):
        try:
            return raw.decode("utf-16-be")
        except UnicodeDecodeError:
            return None
    if platform_id == 1:
        try:
            return raw.decode("mac_roman", "replace")
        except LookupError:
            return None
    if platform_id == 0:
        try:
            return raw.decode("utf-16-be")
        except UnicodeDecodeError:
            return None
    return None


def _font_offset(buf):
    if len(buf) < 12:
        return None
    tag = buf[:4]
    if tag == b"ttcf":
        num = _read_u32(buf, 4)
        if num == 0 or len(buf) < 12 + 4:
            return None
        return _read_u32(buf, 12)
    if tag in (b"\x00\x01\x00\x00", b"OTTO", b"true", b"typ1"):
        return 0
    return None


def extract_family(path):
    """Return the font family name (str) or None."""
    try:
        with open(path, "rb") as f:
            buf = f.read()
    except OSError:
        return None
    base = _font_offset(buf)
    if base is None or base + 12 > len(buf):
        return None
    num_tables = _read_u16(buf, base + 4)
    name_off = None
    name_len = 0
    for i in range(num_tables):
        rec = base + 12 + i * 16
        if rec + 16 > len(buf):
            break
        tag = buf[rec:rec + 4]
        if tag == b"name":
            name_off = _read_u32(buf, rec + 8)
            name_len = _read_u32(buf, rec + 12)
            break
    if name_off is None:
        return None
    if name_off + name_len > len(buf):
        name_len = len(buf) - name_off
    nb = buf[name_off:name_off + name_len]
    if len(nb) < 6:
        return None
    count = _read_u16(nb, 2)
    str_off = _read_u16(nb, 4)
    candidates = []
    for i in range(count):
        rec = 6 + i * 12
        if rec + 12 > len(nb):
            break
        platform_id = _read_u16(nb, rec)
        encoding_id = _read_u16(nb, rec + 2)
        language_id = _read_u16(nb, rec + 4)
        name_id = _read_u16(nb, rec + 6)
        length = _read_u16(nb, rec + 8)
        offset = _read_u16(nb, rec + 10)
        if name_id not in (1, 16):
            continue
        start = str_off + offset
        if start + length > len(nb):
            continue
        text = _decode_name(nb[start:start + length], platform_id, encoding_id)
        if text is None or not text.strip():
            continue
        text = text.strip()
        # strip common subfamily suffixes
        text = re.sub(r"\s*(Regular|Book|Roman|Normal)\s*$", "", text, flags=re.I)
        candidates.append((name_id, language_id, text))
    if not candidates:
        return None
    # prefer typographic family (16), then family (1); prefer English (0x409)
    def key(c):
        return (0 if c[0] == 16 else 1, 0 if c[1] == 0x409 else 1)
    candidates.sort(key=key)
    return candidates[0][2]


def safe_filename(path):
    """Sanitize a font file name for copying into a game."""
    name = os.path.basename(path)
    name = re.sub(r'[^\w.\-]', "_", name)
    if not name.lower().endswith((".ttf", ".otf", ".ttc")):
        name += ".ttf"
    return name

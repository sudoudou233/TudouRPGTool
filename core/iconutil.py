# -*- coding: utf-8 -*-
"""游戏内图标图集（IconSet）的定位、解密与切片元数据。

@feature  none
@layer    core
@public   MV_HEADER, PNG_HEADER, decrypt_image, encryption_key, find_sheet,
          geometry, load, png_size
@depends  core.constants, core.engines
@tested   tests/unit/test_iconutil.py
@footprint docs/MODULES.md#coreiconutil

为什么会需要这么一层
--------------------
修改道具时，列表里只显示名字是不够的（用户报告）：

> 有些物品基本是文本乱码、编号数字、或者干脆没名字，
> 如果在前方加入一个小图标，那么找到相对应的物体会更简单

数据表里本来就有 ``iconIndex``（RGSS 是 ``@icon_index``）—— 它就是
"IconSet 图集里的第几个格子"。所以这个功能不需要任何图像处理：

1. 本模块负责**找到**、必要时**解密**图集，并算出 ``cell/columns/rows``；
2. 界面拿这几个数做 CSS sprite（``background-position``）裁出单个图标。

于是零依赖、零图像编码，也不需要把图集拆成一个个文件。

加密格式（用真实样本实测确认，见 `docs/STATE.md`）
--------------------------------------------------
MV 的 ``.rpgmvp`` 与 MZ 的 ``.png_`` 是**同一套**加壳方式：

    偏移 0..15    恒为伪头 52 50 47 4D 56 00 00 00 00 03 01 00 00 00 00 00
    偏移 16..31   真实 PNG 前 16 字节 **逐字节异或** encryptionKey
    偏移 32..     原样（就是 PNG 剩余部分）

``encryptionKey`` 是 ``data/System.json`` 里的 32 位十六进制串。
实测：``IconSet.rpgmvp`` 偏移 16..31 是 ``02 1F 46 89 03 10 A5 A5 …``，
异或 key ``8b4f08ce0e1abfaf43897b02ff62976f`` 后正好得到
``89 50 4E 47 0D 0A 1A 0A 00 00 00 0D 49 48 44 52``（PNG 签名 + IHDR）。

⚠ **解不开是常态之一**：破解版/第三方汉化注入器会改掉图集或 key。
实测 ``D:\gamess\demon\DD_V07c_Windows`` 的 ``IconSet.png_`` 用本机 7 个
游戏的 key 全试过都解不开。此时本模块**如实报错**而不是画出一堆乱码
（见 :func:`load` 的 ``reason``），界面据此把图标开关置灰并说明原因。
"""

from __future__ import annotations

import binascii
import json
import os
import struct

from . import constants
from . import engines

#: MV/MZ 加密图片的 16 字节伪头（``.rpgmvp`` 与 ``.png_`` 完全一致）。
MV_HEADER = b"RPGMV\x00\x00\x00\x00\x03\x01\x00\x00\x00\x00\x00"

#: PNG 文件头 —— 解密是否成功的**唯一判据**（不能只看扩展名）。
PNG_HEADER = b"\x89PNG\r\n\x1a\n"

#: 引擎 -> 图集相对路径（相对各自的资源根）。
#:
#: MV/MZ 的资源根是 ``www``（老版布局）/ 游戏根（MZ 扁平布局）；
#: RGSS 系没有 www 分层，资源根就是游戏根。
_SHEET_RELPATH = {
    "mv": ("img", "system", "IconSet"),
    "mz": ("img", "system", "IconSet"),
    "vxace": ("Graphics", "System", "IconSet"),
    "vx": ("Graphics", "System", "IconSet"),
    "xp": ("Graphics", "System", "IconSet"),
}

#: 图集可能的文件名后缀，按优先级：明文 -> MV 加壳 -> MZ 加壳。
_SHEET_EXTS = (".png", ".rpgmvp", ".png_")

#: 推 ``cell`` 时按顺序试的边长（引擎首选值排最前）。
_CELL_FALLBACKS = (32, 24, 16, 48)


def _norm(path):
    return os.path.normcase(os.path.abspath(path))


def _is_encrypted(data):
    """按**内容**判断是不是 MV/MZ 加壳（不看扩展名）。"""
    return data[:16] == MV_HEADER


def _candidate_roots(info):
    """图集可能在哪些根目录下（资源根优先，去重）。"""
    out = []
    for root in (engines.js_root(info), engines.game_root(info)):
        if root and os.path.isdir(root):
            real = os.path.abspath(root)
            if _norm(real) not in [_norm(p) for p in out]:
                out.append(real)
    return out


def find_sheet(info):
    """定位图标图集文件。

    返回 ``{'path', 'root', 'engine'}``；找不到返回 None。
    **先按扩展名优先级找，再按内容判断是否加密** —— 真实游戏里存在
    扩展名与内容不一致的情况（例如把 ``.png`` 改名成 ``.png_``）。
    """
    info = info or {}
    engine = info.get("engine")
    rel = _SHEET_RELPATH.get(engine)
    if not rel:
        return None
    for root in _candidate_roots(info):
        base = os.path.join(root, *rel)
        for ext in _SHEET_EXTS:
            path = base + ext
            if os.path.isfile(path):
                return {"path": path, "root": root, "engine": engine}
    return None


def encryption_key(info):
    """读 ``System.json`` 的 ``encryptionKey``；没有则返回 ``''``。

    只找**资源根/data**下的那一份 —— 那是引擎真正读的位置。找不到就
    返回空串，由 :func:`decrypt_image` 报"没有 key"。
    """
    data_dir = engines.data_dir(info)
    candidates = []
    if data_dir:
        candidates.append(os.path.join(data_dir, "System.json"))
    root = engines.js_root(info)
    if root:
        candidates.append(os.path.join(root, "data", "System.json"))
        candidates.append(os.path.join(root, "System.json"))
    for path in candidates:
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                payload = json.load(f)
        except (OSError, ValueError):
            continue
        if isinstance(payload, dict):
            key = payload.get("encryptionKey")
            if isinstance(key, str) and key.strip():
                return key.strip()
    return ""


def decrypt_image(data, key_hex):
    """解开 MV/MZ 的图片加壳，返回完整 PNG 字节。

    **解不开一律抛 ``ValueError``**（消息是给用户看的中文），
    绝不返回"解了一半"的字节 —— 否则界面会把乱码当成图标画出来。
    """
    if len(data) < 32:
        raise ValueError("文件太小，不像是加密图集")
    if not key_hex:
        raise ValueError("图集是加密的，但这个游戏的 System.json 里没有 encryptionKey")
    try:
        key = binascii.unhexlify(key_hex.strip())
    except (binascii.Error, TypeError, ValueError):
        raise ValueError("encryptionKey 不是合法的十六进制串")
    if len(key) != 16:
        raise ValueError("encryptionKey 长度应为 32 位十六进制（16 字节），实际 %d 位"
                         % (len(key) * 2))
    head = bytes(a ^ b for a, b in zip(data[16:32], key))
    if head[:8] != PNG_HEADER:
        raise ValueError("用 System.json 里的 encryptionKey 解不开"
                         "（该图集可能被第三方汉化/破解工具改过）")
    return head + data[32:]


def png_size(data):
    """取 PNG 的 ``(宽, 高)``；不是合法 PNG 返回 None。"""
    if not data or len(data) < 24 or data[:8] != PNG_HEADER:
        return None
    if data[12:16] != b"IHDR":
        return None
    try:
        width, height = struct.unpack(">II", data[16:24])
    except struct.error:
        return None
    if width <= 0 or height <= 0:
        return None
    return (width, height)


def geometry(width, height, engine, columns=None):
    """由像素尺寸推出切片参数。

    返回 ``{'cell', 'columns', 'rows', 'count'}``；推不出来返回 None。

    判据是 ``宽 % cell == 0``（能整除才敢切）。**优先引擎的标准值**
    （MV/MZ 32，RGSS 24），命中标准的 16 列就直接采用；否则退而求其次，
    用第一个能整除的边长 —— 这样魔改过的图集也能显示，只是列数不同。
    """
    want = int(columns or constants.ICON_COLUMNS)
    default = constants.ICON_CELLS.get(engine) or 32
    order = [default] + [c for c in _CELL_FALLBACKS if c != default]
    fallback = None
    for cell in order:
        if cell <= 0 or width % cell or height % cell:
            continue
        cols = width // cell
        rows = height // cell
        found = {"cell": cell, "columns": cols, "rows": rows, "count": cols * rows}
        if cols == want:
            return found
        if fallback is None:
            fallback = found
    return fallback


def load(info, columns=None):
    """读取图集**明文** + 切片元数据。

    返回 ``(meta, data)``：

    * 可用 —— ``meta['available'] is True``，``data`` 是完整 PNG 字节；
    * 不可用 —— ``data is None``，``meta['reason']`` 是**给用户看的中文原因**。

    调用方（``features/cheats``）直接把 ``meta`` 塞进 JSON 给界面，
    界面据此决定"图标开关能不能打开、为什么不能"。
    """
    meta = {
        "available": False,
        "reason": "",
        "path": None,
        "encrypted": False,
        "engine": (info or {}).get("engine"),
        "width": None,
        "height": None,
        "cell": None,
        "columns": None,
        "rows": None,
        "count": None,
    }
    engine = meta["engine"]
    if not engine:
        meta["reason"] = "还没有打开游戏"
        return meta, None
    if engine in constants.RECOGNIZE_ONLY_ENGINES:
        meta["reason"] = "%s 只识别不支持修改，图标也不支持" % constants.engine_label(engine)
        return meta, None

    sheet = find_sheet(info)
    if sheet is None:
        meta["reason"] = ("游戏目录里找不到图标图集（img/system/IconSet.png "
                          "或 Graphics/System/IconSet.png）")
        return meta, None
    meta["path"] = sheet["path"]
    try:
        with open(sheet["path"], "rb") as f:
            raw = f.read()
    except OSError as exc:
        meta["reason"] = "读不了图标图集：%s" % exc
        return meta, None

    if _is_encrypted(raw):
        meta["encrypted"] = True
        try:
            raw = decrypt_image(raw, encryption_key(info))
        except ValueError as exc:
            meta["reason"] = "图标图集已加密，解不开：%s" % exc
            return meta, None

    size = png_size(raw)
    if size is None:
        meta["reason"] = "图标图集不是有效的 PNG（可能仍是加密格式或文件已损坏）"
        return meta, None
    width, height = size
    geo = geometry(width, height, engine, columns)
    if geo is None:
        meta["reason"] = ("图标图集尺寸 %dx%d 不符合已知布局，没法切片"
                          % (width, height))
        return meta, None
    meta.update(available=True, reason="", width=width, height=height)
    meta.update(geo)
    return meta, raw

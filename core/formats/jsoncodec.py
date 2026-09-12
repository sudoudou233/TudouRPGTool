# -*- coding: utf-8 -*-
"""MV / MZ 的 JSON 编解码共享层 —— 游戏数据与存档共用一份实现。

@feature  none
@layer    core
@public   read_text, read_json_file, dumps_pretty, dumps_compact, write_text_file,
          is_meta_key, strip_meta_keys, int_map_from, META_KEYS,
          WRAPPER_KEYS, is_wrapped, split_wrapper, join_wrapper,
          derive_wrapper_key, crypt_wrapper_bytes,
          is_zlib_stream, decompress_save, compress_save, save_engine
@depends  core.formats.lzstring, core.safety.atomic
@tested   tests/unit/test_jsoncodec.py, tests/compat/test_formats_compat.py
@footprint docs/MODULES.md#coreformats

收敛背景（需求 §3.3 第三类重复）
------------------------------
M1/M2a 阶段，MV/MZ 的两条路径各写了一套 JSON 与压缩约定：

| 职责 | `mv_mz_data.py`（游戏数据） | `mv_save.py`（存档） |
| --- | --- | --- |
| 读 JSON | ``open(encoding='utf-8-sig')`` + ``json.load`` | 同 |
| 写 JSON | ``json.dumps(..., ensure_ascii=False, indent=2)`` | ``json.dumps(..., separators=(',',':'))`` |
| 加密包装 | ``{"uid","bid","data"}`` + 自研异或变体 | 无 |
| 压缩 | 无 | MV: LZString(base64)；MZ: zlib(level 1) |
| JsonEx 元数据 | 无 | ``META_KEYS = {'@c','@a','@','@r'}`` |

本模块把**共同的约定**收敛到这里（BOM 处理、两种 marshal 风格、元数据键、
包装格式、压缩判别），两侧业务层各自保留"提取什么字段 / 改哪个键"的业务规则。

为什么压缩判别用 ``is_zlib_stream`` 而不是靠 engine 参数
-------------------------------------------------------
真实游戏里存在"扩展名与内容不一致"的情况（改包、工具生成、汉化版重打包），
所以 :func:`decompress_save` **先看字节再决定算法**（0x78 开头视为 zlib），
``engine`` 参数只作为写回时的偏好。这与原 ``mv_save._load`` 的判别方式一致，
但把它显式化并加了注释，避免后来者以为それは多余。
"""

from __future__ import annotations

import base64
import json
import zlib

from ..safety.atomic import atomic_write_bytes, atomic_write_text
from . import lzstring

#: MV/MZ JsonEx 给对象/数组附带的元数据键（JsonEx 序列化的标记）。
#:
#: * ``@``  普通对象
#: * ``@a`` 数组
#: * ``@c`` 循环引用编号
#: * ``@r`` 引用
#:
#: 读存档时**必须忽略**这些键，否则会把元数据当成道具 id 之类的东西。
META_KEYS = frozenset(["@c", "@a", "@", "@r"])

#: 加密 JSON 包装（部分商业素材/加密发行版）的外层键。
WRAPPER_KEYS = ("uid", "bid", "data")

#: 默认压缩级别：与原 ``mv_save._dump`` 一致（级别 1 换速度，存档体积本就不大）
ZLIB_LEVEL = 1


# ---------------------------------------------------------------------------
# 文本 / JSON 读写
# ---------------------------------------------------------------------------
def read_text(path, encoding="utf-8-sig"):
    """读文本文件（默认 ``utf-8-sig``：容忍 BOM，RPG Maker 的 JSON 常带 BOM）。"""
    with open(path, encoding=encoding) as f:
        return f.read()


def read_json_file(path, encoding="utf-8-sig"):
    """读 JSON 文件并解析。

    读失败时抛 ``ValueError``（带文件路径），**不静默返回 None** ——
    调用方需要区分"文件不存在"与"文件坏了"。
    """
    text = read_text(path, encoding=encoding)
    try:
        return json.loads(text)
    except ValueError as exc:
        raise ValueError("JSON 解析失败：%s（%s）" % (path, exc))


def dumps_pretty(data):
    """人类可读的 JSON（缩进 2、不转义非 ASCII）。

    用于**游戏数据文件**（``data/*.json``）：原实现即用
    ``json.dumps(data, ensure_ascii=False, indent=2)``，
    保持可读性便于用户与后续 AI 排查。
    """
    return json.dumps(data, ensure_ascii=False, indent=2)


def dumps_compact(data):
    """紧凑 JSON（无空格、不转义非 ASCII）。

    用于**存档**：原实现即用 ``separators=(',', ':')``。
    存档会被压缩，紧凑写法能明显减小体积，且与游戏引擎的写法一致。
    """
    return json.dumps(data, ensure_ascii=False, separators=(',', ':'))


def write_text_file(path, text, backup=False):
    """原子写文本（换行按原实现规范化为 ``\\n``）。"""
    return atomic_write_text(path, text, backup=backup)


def write_bytes_file(path, data, backup=False):
    """原子写字节（MZ 存档等二进制内容用）。"""
    return atomic_write_bytes(path, data, backup=backup)


# ---------------------------------------------------------------------------
# JsonEx 元数据
# ---------------------------------------------------------------------------
def is_meta_key(key):
    """该键是否为 JsonEx 元数据键。"""
    return key in META_KEYS


def strip_meta_keys(mapping):
    """返回去掉元数据键的浅拷贝（非 dict 输入返回空 dict）。"""
    if not isinstance(mapping, dict):
        return {}
    return {k: v for k, v in mapping.items() if k not in META_KEYS}


def int_map_from(mapping):
    """把 ``{id: count}`` 归一化成 ``{int: int}``，忽略元数据键与非法项。

    道具/武器/防具的数量表在 MV 里是 ``{"@c": 1, "1": 3}`` 这种形状，
    既可能带元数据、键也可能是字符串。
    """
    out = {}
    if not isinstance(mapping, dict):
        return out
    for key, value in mapping.items():
        if key in META_KEYS:
            continue
        try:
            out[int(key)] = int(value)
        except (TypeError, ValueError):
            continue
    return out


# ---------------------------------------------------------------------------
# 加密 JSON 包装（{"uid","bid","data"}）
# ---------------------------------------------------------------------------
def is_wrapped(data):
    """该 dict 是否是加密包装的外层结构。"""
    return isinstance(data, dict) and all(k in data for k in WRAPPER_KEYS)


def split_wrapper(data):
    """拆出 ``(header, payload_b64)``；``header`` 只保留 uid/bid。"""
    header = {"uid": data.get("uid", ""), "bid": data.get("bid", "")}
    return header, data.get("data", "")


def join_wrapper(header, payload_b64):
    """按原顺序组装包装结构（``uid`` / ``bid`` / ``data``）。"""
    header = header or {}
    return {"uid": header.get("uid", ""), "bid": header.get("bid", ""),
            "data": payload_b64}


def derive_wrapper_key(fname):
    """由文件名派生包装密钥（与游戏内 ``window._K`` 逻辑一致）。

    用的是 JS 里 ``((t << 5) - t + c)`` 这个 32 位滚动哈希，
    ``Math.sqrt(42025) == 205`` 是各发行版共用的常量。
    """
    import os
    name = os.path.splitext(os.path.basename(fname))[0]
    t = 0
    for ch in name:
        t = ((t << 5) - t + ord(ch)) & 0xFFFFFFFF
    return 205 ^ (t & 255)


def crypt_wrapper_bytes(data, key, encrypt):
    """包装体的异或流加密/解密（同一函数，``encrypt`` 决定正向/逆向）。

    从**尾部向前**处理，且把"上一个原始字节"滚入密钥流 ——
    因此解密时必须用解出来的字节继续滚，顺序不能颠倒。
    """
    buf = bytearray(data)
    rolling = key
    for i in range(len(buf) - 1, -1, -1):
        c = key ^ 72
        m = i % 128
        p = ((rolling << 2) ^ (rolling >> 4))
        k = ((((c + m + p) ^ 160) + 18)) & 255
        if encrypt:
            original = buf[i]
            buf[i] = original ^ k
            rolling = original
        else:
            value = buf[i] ^ k
            buf[i] = value
            rolling = value
    return bytes(buf)


def decrypt_wrapper_payload(payload_b64, fname):
    """解密包装体内的文本（base64 → 异或 → utf-8）。"""
    raw = base64.b64decode(payload_b64)
    return crypt_wrapper_bytes(raw, derive_wrapper_key(fname), encrypt=False) \
        .decode("utf-8")


def encrypt_wrapper_payload(plain_text, fname):
    """把文本加密成包装体内层（utf-8 → 异或 → base64）。"""
    raw = crypt_wrapper_bytes(plain_text.encode("utf-8"),
                              derive_wrapper_key(fname), encrypt=True)
    return base64.b64encode(raw).decode("ascii")


# ---------------------------------------------------------------------------
# 存档压缩：LZString（MV） / zlib（MZ）
# ---------------------------------------------------------------------------
def is_zlib_stream(raw):
    """该字节串是否是 zlib 流（MZ 存档的特征）。

    MZ 把 zlib 输出以小端 latin-1 形式塞进 UTF-8 文本；zlib 头的首字节
    固定是 ``0x78``，因此用它判别。比"看扩展名"可靠 —— 真实游戏里存在
    扩展名与内容不一致的情况（改包 / 工具生成 / 汉化版重打包）。
    """
    return bool(raw) and raw[0] == 0x78


def decompress_save(raw):
    """存档字节 → JSON 文本。自动判别 zlib 与 LZString。"""
    if is_zlib_stream(raw):
        latin = raw.decode("utf-8")
        return zlib.decompress(latin.encode("latin-1")).decode("utf-8")
    return lzstring.decompress_from_base64(raw.decode("utf-8", "replace"))


def compress_save(text, engine="mv"):
    """JSON 文本 → 存档字节。``engine`` 决定用哪种压缩。"""
    if engine == "mz":
        zbytes = zlib.compress(text.encode("utf-8"), ZLIB_LEVEL)
        return zbytes.decode("latin-1").encode("utf-8")
    return lzstring.compress_to_base64(text).encode("utf-8")


def save_engine(raw, default="mv"):
    """按内容推断存档引擎；无法确定时返回 ``default``。"""
    return "mz" if is_zlib_stream(raw) else default

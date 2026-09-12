# -*- coding: utf-8 -*-
"""
Pure-Python LZString (classic variant) for RPG Maker MV saves.

@feature  cheats
@layer    core
@public   compress, decompress, compress_to_base64, decompress_from_base64
@depends  (stdlib only)
@tested   tests/compat/test_formats_compat.py
@footprint docs/MODULES.md#coreformats
@note     vendored：来自 rpgmaker_cheating_tool/lzstring.py。


Faithful port of the lz-string.js implementation shipped with this game
(www/js/libs/lz-string.js):

  compressToBase64(text) = base64( bytes of LZString.compress(text) )
  decompressFromBase64(base64) = LZString.decompress( bytes -> 16-bit chars )

The core compress/decompress is the classic 16-bit-bitstream LZ77 variant.
All values are UTF-16 code units, exactly like the JS original.
"""
import re

_KEY_BASE64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/="
_BASE64_MAP = {c: i for i, c in enumerate(_KEY_BASE64)}


def _to_units(s):
    """Python str -> list of UTF-16 code units (ints)."""
    b = s.encode("utf-16-le", errors="surrogatepass")
    return [b[i] | (b[i + 1] << 8) for i in range(0, len(b), 2)]


def _from_units(units):
    """list of UTF-16 code units (ints) -> Python str."""
    if not units:
        return ""
    raw = b"".join((u & 0xFFFF).to_bytes(2, "little") for u in units)
    return raw.decode("utf-16-le", errors="replace")


# ---------------------------------------------------------------------------
# core compress / decompress (classic 16-bit bitstream variant)
# ---------------------------------------------------------------------------

def compress(uncompressed):
    """Compress a Python str to a list of 16-bit code-unit ints."""
    units = _to_units(uncompressed)
    r = {}                 # dictionary: str -> code
    i = {}                 # to_create
    s = ""                 # current c
    o = ""                 # wc
    u = ""                 # w
    a = 2                  # enlargeIn
    f = 3                  # dictSize
    l = 2                  # numBits
    c = []                 # output chars
    h = 0                  # bit buffer
    p = 0                  # bit position

    def wb(v, n):
        nonlocal h, p
        for _ in range(n):
            h = (h << 1) | (v & 1)
            if p == 15:
                p = 0
                c.append(h)
                h = 0
            else:
                p += 1
            v >>= 1

    for d in range(len(units)):
        s = chr(units[d])
        if s not in r:
            r[s] = f
            f += 1
            i[s] = True
        o = u + s
        if o in r:
            u = o
        else:
            if u in i:
                if ord(u[0]) < 256:
                    wb(0, l)
                    wb(ord(u[0]), 8)
                else:
                    wb(1, l)
                    wb(ord(u[0]), 16)
                a -= 1
                if a == 0:
                    a = 1 << l
                    l += 1
                del i[u]
            else:
                wb(r[u], l)
            a -= 1
            if a == 0:
                a = 1 << l
                l += 1
            r[o] = f
            f += 1
            u = s

    if u != "":
        if u in i:
            if ord(u[0]) < 256:
                wb(0, l)
                wb(ord(u[0]), 8)
            else:
                wb(1, l)
                wb(ord(u[0]), 16)
            a -= 1
            if a == 0:
                a = 1 << l
                l += 1
            del i[u]
        else:
            wb(r[u], l)
        a -= 1
        if a == 0:
            a = 1 << l
            l += 1

    wb(2, l)
    while True:
        h <<= 1
        if p == 15:
            c.append(h)
            break
        p += 1
    return c


def decompress(chars):
    """Decompress a list of 16-bit code-unit ints back to a Python str."""
    if not chars:
        return ""
    t = [0, 1, 2, ""]      # dictionary
    r = 4                  # enlargeIn
    i = 4                  # dictSize
    s = 3                  # numBits
    o = ""                 # entry
    u = ""                 # accumulated result
    m = {"val": chars[0], "position": 32768, "index": 1}

    def read_bits(n):
        l = 0
        power = 1
        for _ in range(n):
            c = m["val"] & m["position"]
            m["position"] >>= 1
            if m["position"] == 0:
                m["position"] = 32768
                m["val"] = chars[m["index"]] if m["index"] < len(chars) else 0
                m["index"] += 1
            l |= (1 if c > 0 else 0) * power
            power <<= 1
        return l

    d = read_bits(2)
    if d == 0:
        d = chr(read_bits(8))
    elif d == 1:
        d = chr(read_bits(16))
    else:
        return ""
    t[3] = d
    f = u = d
    while True:
        if m["index"] > len(chars):
            return ""
        d = read_bits(s)
        if d == 0:
            t.append(chr(read_bits(8)))
            d = i
            i += 1
            r -= 1
        elif d == 1:
            t.append(chr(read_bits(16)))
            d = i
            i += 1
            r -= 1
        elif d == 2:
            return u
        if r == 0:
            r = 1 << s
            s += 1
        if d < len(t) and t[d]:
            o = t[d]
        else:
            if d == i:
                o = f + f[0]
            else:
                return ""
        u += o
        t.append(f + o[0])
        i += 1
        r -= 1
        f = o
        if r == 0:
            r = 1 << s
            s += 1


# ---------------------------------------------------------------------------
# base64 wrappers (this game's variant: bytes of the 16-bit chars)
# ---------------------------------------------------------------------------

def compress_to_base64(uncompressed):
    """Compress a Python str to the base64 string stored in .rpgsave files."""
    chars = compress(uncompressed)
    length = len(chars)
    out = []
    f = 0
    while f < length * 2:
        if f % 2 == 0:
            n = chars[f // 2] >> 8
            r = chars[f // 2] & 255
            i = chars[f // 2 + 1] >> 8 if f // 2 + 1 < length else None
        else:
            n = chars[(f - 1) // 2] & 255
            if (f + 1) // 2 < length:
                r = chars[(f + 1) // 2] >> 8
                i = chars[(f + 1) // 2] & 255
            else:
                r = i = None
        f += 3
        b = lambda v: 0 if v is None else v
        s = b(n) >> 2
        o = ((b(n) & 3) << 4) | (b(r) >> 4)
        if r is None:
            u = a = 64
        elif i is None:
            u = (r & 15) << 2
            a = 64
        else:
            u = ((r & 15) << 2) | (i >> 6)
            a = i & 63
        out.append(_KEY_BASE64[s])
        out.append(_KEY_BASE64[o])
        out.append(_KEY_BASE64[u])
        out.append(_KEY_BASE64[a])
    return "".join(out)


def decompress_from_base64(compressed):
    """Decompress the base64 string stored in .rpgsave files."""
    if compressed is None:
        return ""
    cleaned = re.sub(r"[^A-Za-z0-9+/=]", "", compressed)
    L = len(cleaned)
    if L == 0:
        return ""
    chars = []
    n = 0
    c = 0
    r = 0
    while c < L:
        u = _BASE64_MAP.get(cleaned[c], 0)
        a = _BASE64_MAP.get(cleaned[c + 1], 0) if c + 1 < L else 0
        f = _BASE64_MAP.get(cleaned[c + 2], 0) if c + 2 < L else 0
        l = _BASE64_MAP.get(cleaned[c + 3], 0) if c + 3 < L else 0
        c += 4
        i = (u << 2) | (a >> 4)
        s = ((a & 15) << 4) | (f >> 2)
        o = ((f & 3) << 6) | l
        if n % 2 == 0:
            r = i << 8
            if f != 64:
                chars.append(r | s)
            if l != 64:
                r = o << 8
        else:
            chars.append(r | i)
            if f != 64:
                r = s << 8
            if l != 64:
                chars.append(r | o)
        n += 3
    return decompress(chars)

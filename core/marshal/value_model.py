# -*- coding: utf-8 -*-
"""
Self-contained Ruby Marshal (version 4.8) reader/writer.

@feature  none
@layer    core
@public   loads, dumps, RMStr, RMIvar, RMObject, RMDict, RMSymbol,
@public   RMStruct, RMUserDefined, RMUserMarshal, RMRegexp, RMData,
@public   RMClass, RMModule, RMFloat
@depends  (stdlib only)
@tested   tests/compat/test_marshal_compat.py
@footprint docs/MODULES.md#coremarshal
@note     vendored：来自 rpgmaker_translation_tool/tool/marshal.py（原样搬入）。
@note     已知缺陷 B-12（bignum 写回崩溃）、B-13、B-28（gbk→cp932 误映射）
@note     在 M2b 收敛时随门面层一并处置。


RPG Maker VX Ace (Data/*.rvdata2) and XP (Data/*.rxdata) store their
database files in Ruby's Marshal binary format.  This module parses the
format into plain Python objects (with light wrappers for Ruby-only
concepts) and serialises the same object graph back to bytes.

The reader and writer both walk the graph in exactly the same order, so
symbol links and object links are rebuilt consistently and an untouched
file round-trips byte-for-byte.
"""

from __future__ import annotations

MAGIC = b"\x04\x08"


class MarshalError(Exception):
    pass


class RMStr(str):
    """A string that remembers its original byte encoding.

    ``enc`` is 'utf-8', 'cp932' (Shift_JIS / Windows-31J) or 'latin-1'.
    Equality and hashing behave exactly like ``str``.
    """

    __slots__ = ("enc",)

    def __new__(cls, value, enc="utf-8"):
        obj = str.__new__(cls, value)
        obj.enc = enc
        return obj


class RMSymbol(str):
    """A Ruby symbol (Marshal ``:`` / ``;``)."""

    __slots__ = ()


class RMFloat:
    __slots__ = ("value", "raw")

    def __init__(self, value, raw):
        self.value = value
        self.raw = raw


class RMIvar:
    """An object with instance variables (the Marshal ``I`` prefix)."""

    __slots__ = ("value", "ivars")

    def __init__(self, value, ivars):
        self.value = value
        self.ivars = ivars

    def __repr__(self):
        return "RMIvar(%r, %r)" % (self.value, self.ivars)


class RMObject:
    """A Ruby object of an arbitrary class (Marshal ``o``)."""

    __slots__ = ("class_name", "ivars", "modules")

    def __init__(self, class_name, ivars=None, modules=None):
        self.class_name = class_name
        self.ivars = ivars if ivars is not None else {}
        self.modules = modules if modules is not None else []

    def get(self, name, default=None):
        return self.ivars.get(name, default)

    def __repr__(self):
        return "RMObject(%s, %d ivars)" % (self.class_name, len(self.ivars))


class RMStruct:
    __slots__ = ("class_name", "members")

    def __init__(self, class_name, members):
        self.class_name = class_name
        self.members = members


class RMUserDefined:
    """Class with ``_dump``/``_load`` (Marshal ``u``)."""

    __slots__ = ("class_name", "data")

    def __init__(self, class_name, data):
        self.class_name = class_name
        self.data = data


class RMUserMarshal:
    """Class with ``marshal_dump``/``marshal_load`` (Marshal ``U``)."""

    __slots__ = ("class_name", "value")

    def __init__(self, class_name, value):
        self.class_name = class_name
        self.value = value


class RMRegexp:
    __slots__ = ("pattern", "options")

    def __init__(self, pattern, options):
        self.pattern = pattern
        self.options = options


class RMData:
    __slots__ = ("class_name", "value")

    def __init__(self, class_name, value):
        self.class_name = class_name
        self.value = value


class RMClass:
    __slots__ = ("name",)

    def __init__(self, name):
        self.name = name


class RMModule:
    __slots__ = ("name",)

    def __init__(self, name):
        self.name = name


class RMDict(dict):
    """A Hash with a default value (Marshal ``}``)."""

    __slots__ = ("default_value",)

    def __init__(self, *args, default_value=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.default_value = default_value


def _decode_bytes(raw, hint_enc=None):
    """Decode raw string bytes, preferring the hinted encoding."""
    if hint_enc:
        try:
            return RMStr(raw.decode(hint_enc), enc=hint_enc)
        except (UnicodeDecodeError, LookupError):
            pass
    try:
        return RMStr(raw.decode("utf-8"), enc="utf-8")
    except UnicodeDecodeError:
        pass
    try:
        return RMStr(raw.decode("cp932"), enc="cp932")
    except UnicodeDecodeError:
        return RMStr(raw.decode("latin-1"), enc="latin-1")


def _enc_for_symbol(sym):
    low = str(sym).lower().replace("-", "_").replace(" ", "_")
    if low in ("utf_8", "utf8"):
        return "utf-8"
    if low in ("shift_jis", "sjis", "windows_31j", "cp932", "gbk", "gb2312"):
        return "cp932"
    if low in ("ascii", "us_ascii", "binary", "ascii_8bit"):
        return "ascii"
    return None


class MarshalReader:
    def __init__(self, data):
        if not data.startswith(MAGIC):
            raise MarshalError("Not a Ruby Marshal stream (bad magic header)")
        self.buf = memoryview(data)
        self.pos = 2
        self.objects = [None]  # object links are one-indexed
        self.symbols = []

    # -- low level -----------------------------------------------------

    def _byte(self):
        if self.pos >= len(self.buf):
            raise MarshalError("Unexpected end of stream")
        b = self.buf[self.pos]
        self.pos += 1
        return b

    def _read(self, n):
        if self.pos + n > len(self.buf):
            raise MarshalError("Unexpected end of stream")
        b = bytes(self.buf[self.pos:self.pos + n])
        self.pos += n
        return b

    def _fixnum(self):
        b = self._byte()
        if b == 0:
            return 0
        if b == 1:
            return int.from_bytes(self._read(1), "little")
        if b == 2:
            return int.from_bytes(self._read(2), "little")
        if b == 3:
            return int.from_bytes(self._read(3), "little")
        if b == 4:
            return int.from_bytes(self._read(4), "little")
        if b == 0xFF:
            return int.from_bytes(self._read(1), "little", signed=True)
        if b == 0xFE:
            return int.from_bytes(self._read(2), "little", signed=True)
        if b == 0xFD:
            return int.from_bytes(self._read(3), "little", signed=True)
        if b == 0xFC:
            return int.from_bytes(self._read(4), "little", signed=True)
        if b < 0x80:
            return b - 5
        if b < 0xFB:
            return b - 251
        raise MarshalError("Invalid fixnum byte 0x%02X" % b)

    def _symbol_ref(self):
        b = self._byte()
        if b == 0x3A:  # ':'
            length = self._fixnum()
            name = self._read(length).decode("utf-8", "replace")
            self.symbols.append(name)
            return RMSymbol(name)
        if b == 0x3B:  # ';'
            idx = self._fixnum()
            try:
                return RMSymbol(self.symbols[idx])
            except IndexError:
                raise MarshalError("Bad symbol link %d" % idx)
        raise MarshalError("Expected symbol, got byte 0x%02X at offset %d" % (b, self.pos - 1))

    def _string_bytes(self):
        length = self._fixnum()
        return self._read(length)

    def _string(self, hint_enc=None):
        return _decode_bytes(self._string_bytes(), hint_enc)

    def _ivars(self):
        """Read an ivar block: count + (symbol, value) pairs."""
        count = self._fixnum()
        ivars = {}
        for _ in range(count):
            name = self._symbol_ref()
            ivars[name] = self.read_token()
        return ivars

    # -- object graph --------------------------------------------------

    def read_token(self):
        b = self._byte()
        if b == 0x30:  # '0'
            return None
        if b == 0x54:  # 'T'
            return True
        if b == 0x46:  # 'F'
            return False
        if b == 0x69:  # 'i'
            return self._fixnum()
        if b == 0x3A or b == 0x3B:  # ':' ';'
            self.pos -= 1
            return self._symbol_ref()
        if b == 0x22:  # '"'
            s = self._string()
            self.objects.append(s)
            return s
        if b == 0x49:  # 'I'
            value = self.read_token()
            ivars = self._ivars()
            # Use the encoding ivar, if any, to improve text decoding.
            enc = None
            for k, v in ivars.items():
                if str(k) == "encoding" and isinstance(v, RMSymbol):
                    enc = _enc_for_symbol(v)
            if isinstance(value, RMStr) and enc and value.enc != enc:
                value = RMStr(value, enc=enc)
            return RMIvar(value, ivars)
        if b == 0x5B:  # '['
            count = self._fixnum()
            arr = []
            self.objects.append(arr)
            for _ in range(count):
                arr.append(self.read_token())
            return arr
        if b == 0x7B:  # '{'
            count = self._fixnum()
            d = {}
            self.objects.append(d)
            for _ in range(count):
                k = self.read_token()
                v = self.read_token()
                d[k] = v
            return d
        if b == 0x7D:  # '}'
            count = self._fixnum()
            d = RMDict()
            self.objects.append(d)
            for _ in range(count):
                k = self.read_token()
                v = self.read_token()
                d[k] = v
            d.default_value = self.read_token()
            return d
        if b == 0x6F:  # 'o'
            obj = RMObject(None)
            self.objects.append(obj)
            class_name = self._symbol_ref()
            obj.class_name = str(class_name)
            count = self._fixnum()
            for _ in range(count):
                name = self._symbol_ref()
                obj.ivars[str(name)] = self.read_token()
            return obj
        if b == 0x65:  # 'e' extended: module symbol first, then object
            module_name = str(self._symbol_ref())
            obj = self.read_token()
            if isinstance(obj, RMObject):
                obj.modules.append(module_name)
            return obj
        if b == 0x43:  # 'C' user class (subclass of String/Array/Hash/...)
            class_name = str(self._symbol_ref())
            wrapped = self.read_token()
            uc = RMObject(class_name, {"__wrapped__": wrapped})
            self.objects.append(uc)
            return uc
        if b == 0x53:  # 'S'
            st = RMStruct(None, {})
            self.objects.append(st)
            st.class_name = str(self._symbol_ref())
            count = self._fixnum()
            for _ in range(count):
                name = self._symbol_ref()
                st.members[str(name)] = self.read_token()
            return st
        if b == 0x75:  # 'u'
            ud = RMUserDefined(None, b"")
            self.objects.append(ud)
            ud.class_name = str(self._symbol_ref())
            length = self._fixnum()
            ud.data = self._read(length)
            return ud
        if b == 0x55:  # 'U'
            um = RMUserMarshal(None, None)
            self.objects.append(um)
            um.class_name = str(self._symbol_ref())
            um.value = self.read_token()
            return um
        if b == 0x6C:  # 'l' bignum
            sign = self._byte()
            units = self._fixnum()
            raw = self._read(units * 2)
            value = int.from_bytes(raw, "little")
            if sign == 0x2D:  # '-'
                value = -value
            self.objects.append(value)
            return value
        if b == 0x63:  # 'c'
            cls = RMClass(str(self._symbol_ref()))
            self.objects.append(cls)
            return cls
        if b == 0x6D:  # 'm'
            mod = RMModule(str(self._symbol_ref()))
            self.objects.append(mod)
            return mod
        if b == 0x4D:  # 'M' old module
            mod = RMModule(str(self._symbol_ref()))
            self.objects.append(mod)
            return mod
        if b == 0x2F:  # '/'
            pattern = self._string()
            options = self._fixnum()
            rx = RMRegexp(pattern, options)
            self.objects.append(rx)
            return rx
        if b == 0x64:  # 'd'
            class_name = str(self._symbol_ref())
            value = self.read_token()
            data = RMData(class_name, value)
            self.objects.append(data)
            return data
        if b == 0x66:  # 'f'
            length = self._fixnum()
            raw = self._read(length)
            if length == 1:
                fval = float("nan")
            elif length == 2:
                fval = float("inf") if raw == b"inf" else float("-inf")
            elif length == 3 and raw in (b"-0", b"-0.0"):
                fval = -0.0
            elif length == 1 and raw == b"0":
                fval = 0.0
            else:
                try:
                    fval = float(raw.decode("ascii", "replace"))
                except ValueError:
                    fval = 0.0
            obj = RMFloat(fval, raw)
            self.objects.append(obj)
            return obj
        if b == 0x40:  # '@'
            idx = self._fixnum()
            try:
                return self.objects[idx]
            except IndexError:
                raise MarshalError("Bad object link %d" % idx)
        raise MarshalError("Unknown Marshal token 0x%02X at offset %d" % (b, self.pos - 1))

    def load(self):
        return self.read_token()


def loads(data):
    return MarshalReader(data).load()


class MarshalWriter:
    def __init__(self):
        self.buf = bytearray(MAGIC)
        self.objects = {}  # id -> one-indexed link
        self.symbols = {}  # name -> zero-indexed link

    def _w(self, data):
        self.buf.extend(data)

    def _byte(self, b):
        self.buf.append(b)

    def _fixnum(self, n):
        n = int(n)
        if n == 0:
            self._byte(0)
        elif 0 < n < 123:
            self._byte(n + 5)
        elif -123 <= n < 0:
            self._byte((n - 5) & 0xFF)
        elif n > 0:
            for length in range(1, 5):
                if n < (1 << (8 * length)):
                    self._byte(length)
                    self._w(n.to_bytes(length, "little"))
                    return
            raise MarshalError("Fixnum too large")
        else:
            for length in range(1, 5):
                if n >= -(1 << (8 * length)):
                    self._byte((256 - length) & 0xFF)
                    self._w((n & ((1 << (8 * length)) - 1)).to_bytes(length, "little"))
                    return
            raise MarshalError("Fixnum too small")

    def _symbol(self, name):
        name = str(name)
        idx = self.symbols.get(name)
        if idx is not None:
            self._byte(0x3B)
            self._fixnum(idx)
            return
        self.symbols[name] = len(self.symbols)
        self._byte(0x3A)
        raw = name.encode("utf-8")
        self._fixnum(len(raw))
        self._w(raw)

    def _string_bytes(self, value, enc):
        raw = value.encode(enc)
        self._fixnum(len(raw))
        self._w(raw)

    def _write_string(self, value):
        enc = getattr(value, "enc", None) or "utf-8"
        if enc in ("cp932", "latin-1"):
            raw = value.encode(enc)
        else:
            raw = value.encode("utf-8")
        self._fixnum(len(raw))
        self._w(raw)

    def _ivars(self, ivars):
        self._fixnum(len(ivars))
        for name, value in ivars.items():
            self._symbol(name)
            self._write_token(value)

    def _write_token(self, v):
        if v is None:
            self._byte(0x30)
            return
        if v is True:
            self._byte(0x54)
            return
        if v is False:
            self._byte(0x46)
            return
        if isinstance(v, int) and not isinstance(v, bool):
            self._byte(0x69)
            self._fixnum(v)
            return
        if isinstance(v, RMFloat):
            self._byte(0x66)
            raw = v.raw
            self._fixnum(len(raw))
            self._w(raw)
            return
        if isinstance(v, float):
            self._byte(0x66)
            if v != v:
                raw = b"nan"
            elif v == float("inf"):
                raw = b"inf"
            elif v == float("-inf"):
                raw = b"-inf"
            elif v == 0.0:
                raw = b"-0" if str(v).startswith("-") else b"0"
            else:
                raw = repr(v).encode("ascii")
            self._fixnum(len(raw))
            self._w(raw)
            return
        if isinstance(v, RMIvar):
            self._byte(0x49)
            self._write_token(v.value)
            self._ivars(v.ivars)
            return
        if isinstance(v, RMSymbol):
            self._symbol(v)
            return
        if isinstance(v, str):
            oid = id(v)
            idx = self.objects.get(oid)
            if idx is not None:
                self._byte(0x40)
                self._fixnum(idx)
                return
            self.objects[oid] = len(self.objects)  # one-indexed
            self._byte(0x22)
            self._write_string(v)
            return
        if isinstance(v, list):
            oid = id(v)
            idx = self.objects.get(oid)
            if idx is not None:
                self._byte(0x40)
                self._fixnum(idx)
                return
            self.objects[oid] = len(self.objects)
            self._byte(0x5B)
            self._fixnum(len(v))
            for item in v:
                self._write_token(item)
            return
        if isinstance(v, RMDict):
            oid = id(v)
            idx = self.objects.get(oid)
            if idx is not None:
                self._byte(0x40)
                self._fixnum(idx)
                return
            self.objects[oid] = len(self.objects)
            self._byte(0x7D)
            self._fixnum(len(v))
            for k, val in v.items():
                self._write_token(k)
                self._write_token(val)
            self._write_token(v.default_value)
            return
        if isinstance(v, dict):
            oid = id(v)
            idx = self.objects.get(oid)
            if idx is not None:
                self._byte(0x40)
                self._fixnum(idx)
                return
            self.objects[oid] = len(self.objects)
            self._byte(0x7B)
            self._fixnum(len(v))
            for k, val in v.items():
                self._write_token(k)
                self._write_token(val)
            return
        if isinstance(v, RMObject):
            oid = id(v)
            idx = self.objects.get(oid)
            if idx is not None:
                self._byte(0x40)
                self._fixnum(idx)
                return
            self.objects[oid] = len(self.objects)
            if "__wrapped__" in v.ivars and len(v.ivars) == 1:
                # user class 'C' -- wrapped content is a separate token
                self._byte(0x43)
                self._symbol(v.class_name)
                self._write_token(v.ivars["__wrapped__"])
                return
            self._byte(0x6F)
            self._symbol(v.class_name)
            self._fixnum(len(v.ivars))
            for name, val in v.ivars.items():
                self._symbol(name)
                self._write_token(val)
            return
        if isinstance(v, RMStruct):
            oid = id(v)
            idx = self.objects.get(oid)
            if idx is not None:
                self._byte(0x40)
                self._fixnum(idx)
                return
            self.objects[oid] = len(self.objects)
            self._byte(0x53)
            self._symbol(v.class_name)
            self._fixnum(len(v.members))
            for name, val in v.members.items():
                self._symbol(name)
                self._write_token(val)
            return
        if isinstance(v, RMUserDefined):
            oid = id(v)
            idx = self.objects.get(oid)
            if idx is not None:
                self._byte(0x40)
                self._fixnum(idx)
                return
            self.objects[oid] = len(self.objects)
            self._byte(0x75)
            self._symbol(v.class_name)
            self._fixnum(len(v.data))
            self._w(v.data)
            return
        if isinstance(v, RMUserMarshal):
            oid = id(v)
            idx = self.objects.get(oid)
            if idx is not None:
                self._byte(0x40)
                self._fixnum(idx)
                return
            self.objects[oid] = len(self.objects)
            self._byte(0x55)
            self._symbol(v.class_name)
            self._write_token(v.value)
            return
        if isinstance(v, RMRegexp):
            oid = id(v)
            idx = self.objects.get(oid)
            if idx is not None:
                self._byte(0x40)
                self._fixnum(idx)
                return
            self.objects[oid] = len(self.objects)
            self._byte(0x2F)
            self._write_token(v.pattern)
            self._fixnum(v.options)
            return
        if isinstance(v, RMData):
            oid = id(v)
            idx = self.objects.get(oid)
            if idx is not None:
                self._byte(0x40)
                self._fixnum(idx)
                return
            self.objects[oid] = len(self.objects)
            self._byte(0x64)
            self._symbol(v.class_name)
            self._write_token(v.value)
            return
        if isinstance(v, RMClass):
            self._byte(0x63)
            self._symbol(v.name)
            return
        if isinstance(v, RMModule):
            self._byte(0x6D)
            self._symbol(v.name)
            return
        raise MarshalError("Cannot serialise value %r" % (type(v),))

    def dump(self, root):
        self._write_token(root)
        return bytes(self.buf)


def dumps(root):
    return MarshalWriter().dump(root)

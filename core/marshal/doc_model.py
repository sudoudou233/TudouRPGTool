# -*- coding: utf-8 -*-
"""


@feature  none
@layer    core
@public   Node, Parser, loads, dumps, load_streams, mark_dirty, VERSION
@depends  (stdlib only)
@tested   tests/compat/test_marshal_compat.py
@footprint docs/MODULES.md#coremarshal
@note     vendored：来自 rpgmaker_cheating_tool/rmarshal.py（原样搬入）。
@note     已知缺陷 B-10（Parser._fixnum 重复定义，XP/VX 写回漂移）
@note     在 M2a 修复；M2b 收敛后本文件删除。

Pure-Python reader/writer for the Ruby Marshal format (as used by
RPG Maker VX Ace .rvdata2 files, Ruby 1.9 / RGSS3).

Design goal: byte-for-byte round-trip fidelity.  Every node keeps the raw
bytes it was parsed from.  When a leaf integer is modified, only the node
(and its ancestors) are re-serialized; unmodified subtrees are emitted
verbatim, so untouched data is guaranteed byte-identical.
"""

import struct

VERSION = b'\x04\x08'

# type tokens
NIL      = 0x30  # '0'
TRUE     = 0x54  # 'T'
FALSE    = 0x46  # 'F'
FIXNUM   = 0x69  # 'i'
FLOAT    = 0x66  # 'f'
BIGNUM   = 0x6C  # 'l'
STRING   = 0x22  # '"'
REGEXP   = 0x2F  # '/'
ARRAY    = 0x5B  # '['
HASH     = 0x7B  # '{'
HASH_DEF = 0x7D  # '}'
STRUCT   = 0x53  # 'S'
USERDEF  = 0x75  # 'u'
USERMARSHAL = 0x55  # 'U'
OBJECT   = 0x6F  # 'o'
CLASS    = 0x63  # 'c'
MODULE   = 0x6D  # 'm'
SYMBOL   = 0x3A  # ':'
SYMLINK  = 0x3B  # ';'
IVAR     = 0x49  # 'I'
LINK     = 0x40  # '@'
ENC      = 0x45  # 'E'


def _fixnum_to_bytes(v):
    if v == 0:
        return b'\x00'
    if 1 <= v <= 122:
        return bytes([v + 5])
    if -123 <= v <= -1:
        return bytes([(v - 5) & 0xFF])
    if v > 0:
        # larger positive: length-prefixed little-endian unsigned
        nb = (v.bit_length() + 7) // 8
        b = v.to_bytes(nb, 'little')
        return bytes([nb]) + b
    # larger negative: signed length byte (0xFC..0xFF) + LE signed bytes
    nb = max(1, (abs(v).bit_length() + 7) // 8)
    if not (-(1 << (8 * nb - 1)) <= v):
        nb += 1
    b = v.to_bytes(nb, 'little', signed=True)
    return bytes([0x100 - nb]) + b


def _parse_fixnum(buf, pos):
    c = buf[pos]
    pos += 1
    if c <= 0x04:
        # 0x00..0x04 -> length-prefixed little-endian unsigned (n=0 -> 0)
        n = c
        if n == 0:
            return 0, pos
        return int.from_bytes(buf[pos:pos + n], 'little', signed=False), pos + n
    if c <= 0x7F:
        # 0x05..0x7F -> 0..122
        return c - 5, pos
    if c <= 0xFA:
        # 0x80..0xFA -> -123..-1
        return c - 0x100 + 5, pos
    # 0xFB..0xFF -> negative long form: length = c - 0x100 (-5..-1),
    # value bytes follow little-endian signed
    n = 0x100 - c
    return int.from_bytes(buf[pos:pos + n], 'little', signed=True), pos + n


def _fixnum_to_bytes_std(v):
    """Standard Ruby Marshal fixnum encoding (XP/VX, Ruby 1.8/1.9 stock)."""
    if v == 0:
        return b'\x05'
    if 1 <= v <= 122:
        return bytes([v + 5])
    if -122 <= v <= -1:
        return bytes([(v - 5) & 0xFF])
    return b'\x7b' + struct.pack('>i', v)


def _parse_fixnum_std(buf, pos):
    c = buf[pos]
    pos += 1
    if c >= 0x80:
        return c - 0x100 + 5, pos
    if c <= 0x7A:
        return c - 5, pos
    return struct.unpack('>i', buf[pos:pos + 4])[0], pos + 4


class Node:
    __slots__ = ('raw', 'dirty', '_parser')

    def __init__(self):
        self.raw = b''
        self.dirty = False

    def mark_dirty(self):
        self.dirty = True

    def serialize(self):
        if not self.dirty and self.raw:
            return self.raw
        return self.write_self()

    def write_self(self):
        raise NotImplementedError

    def to_py(self):
        raise NotImplementedError


class NilNode(Node):
    def write_self(self):
        return b'\x30'

    def to_py(self):
        return None


class BoolNode(Node):
    __slots__ = ('value',)

    def __init__(self, value):
        Node.__init__(self)
        self.value = value
        self.raw = b'\x54' if value else b'\x46'

    def write_self(self):
        return b'\x54' if self.value else b'\x46'

    def to_py(self):
        return self.value


class Fixnum(Node):
    __slots__ = ('value', 'std')

    def __init__(self, value, std=False):
        Node.__init__(self)
        self.value = value
        self.std = std
        self.dirty = True  # cheap: always recompute (deterministic)

    def set_value(self, v):
        if self.value != v:
            self.value = v
            self.dirty = True
        return self

    def write_self(self):
        enc = _fixnum_to_bytes_std if self.std else _fixnum_to_bytes
        return b'\x69' + enc(self.value)

    def to_py(self):
        return self.value


class Float(Node):
    __slots__ = ('value', 'tail')

    def __init__(self, value, tail=b''):
        Node.__init__(self)
        self.value = value
        self.tail = tail
        self.raw = b'\x66' + _fixnum_to_bytes(len(value)) + value + tail

    def write_self(self):
        return b'\x66' + _fixnum_to_bytes(len(self.value)) + self.value + self.tail

    def to_py(self):
        try:
            return float(self.value)
        except Exception:
            return self.value


class Bignum(Node):
    __slots__ = ('sign', 'digits', 'value')

    def __init__(self, sign, digits):
        Node.__init__(self)
        self.sign = sign      # b'+' or b'-'
        self.digits = digits  # list of 16-bit ints, little-endian
        n = len(digits)
        payload = sign + _fixnum_to_bytes(n) + b''.join(
            struct.pack('<H', d) for d in digits)
        self.raw = b'\x6c' + payload
        base = 1
        total = 0
        for d in digits:
            total += d * base
            base <<= 16
        self.value = -total if sign == b'-' else total

    def write_self(self):
        n = len(self.digits)
        return b'\x6c' + self.sign + _fixnum_to_bytes(n) + b''.join(
            struct.pack('<H', d) for d in self.digits)

    def to_py(self):
        return self.value


class Symbol(Node):
    __slots__ = ('name',)

    def __init__(self, name):
        Node.__init__(self)
        self.name = name
        self.raw = b'\x3a' + _fixnum_to_bytes(len(name)) + name

    def write_self(self):
        return b'\x3a' + _fixnum_to_bytes(len(self.name)) + self.name

    def to_py(self):
        return self.name.decode('utf-8', 'replace')


class SymLink(Node):
    __slots__ = ('index',)

    def __init__(self, index):
        Node.__init__(self)
        self.index = index
        self.raw = b'\x3b' + _fixnum_to_bytes(index)

    def write_self(self):
        return b'\x3b' + _fixnum_to_bytes(self.index)

    def to_py(self):
        return self.index


class Link(Node):
    __slots__ = ('index',)

    def __init__(self, index):
        Node.__init__(self)
        self.index = index
        self.raw = b'\x40' + _fixnum_to_bytes(index)

    def write_self(self):
        return b'\x40' + _fixnum_to_bytes(self.index)

    def to_py(self):
        return ('@link', self.index)


class String(Node):
    __slots__ = ('value',)

    def __init__(self, value):
        Node.__init__(self)
        self.value = value
        self.raw = b'\x22' + _fixnum_to_bytes(len(value)) + value

    def set_value(self, v):
        if self.value != v:
            self.value = v
            self.dirty = True
        return self

    def write_self(self):
        return b'\x22' + _fixnum_to_bytes(len(self.value)) + self.value

    def to_py(self):
        return self.value.decode('utf-8', 'replace')


class Array(Node):
    __slots__ = ('items',)

    def __init__(self, items):
        Node.__init__(self)
        self.items = items

    def mark_dirty(self):
        self.dirty = True

    def write_self(self):
        out = bytearray(b'\x5b' + _fixnum_to_bytes(len(self.items)))
        for it in self.items:
            out += it.serialize()
        return bytes(out)

    def to_py(self):
        return [it.to_py() for it in self.items]


class Hash(Node):
    __slots__ = ('entries',)

    def __init__(self, entries):
        Node.__init__(self)
        self.entries = entries  # list of (key_node, value_node)

    def write_self(self):
        out = bytearray(b'\x7b' + _fixnum_to_bytes(len(self.entries)))
        for k, v in self.entries:
            out += k.serialize()
            out += v.serialize()
        return bytes(out)

    def to_py(self):
        return {k.to_py(): v.to_py() for k, v in self.entries}


class HashDef(Node):
    __slots__ = ('entries', 'default')

    def __init__(self, entries, default):
        Node.__init__(self)
        self.entries = entries
        self.default = default

    def write_self(self):
        out = bytearray(b'\x7d' + _fixnum_to_bytes(len(self.entries)))
        for k, v in self.entries:
            out += k.serialize()
            out += v.serialize()
        out += self.default.serialize()
        return bytes(out)


class Struct(Node):
    __slots__ = ('classsym', 'members')

    def __init__(self, classsym, members):
        Node.__init__(self)
        self.classsym = classsym
        self.members = members

    def write_self(self):
        out = bytearray(b'\x53')
        out += self.classsym.serialize()
        out += _fixnum_to_bytes(len(self.members))
        for k, v in self.members:
            out += k.serialize()
            out += v.serialize()
        return bytes(out)


class Userdef(Node):
    __slots__ = ('classsym', 'data')

    def __init__(self, classsym, data):
        Node.__init__(self)
        self.classsym = classsym
        self.data = data
        self.raw = b'\x75' + classsym.serialize() + \
            _fixnum_to_bytes(len(data)) + data

    def write_self(self):
        return b'\x75' + self.classsym.serialize() + \
            _fixnum_to_bytes(len(self.data)) + self.data


class Usermarshal(Node):
    __slots__ = ('classsym', 'inner')

    def __init__(self, classsym, inner):
        Node.__init__(self)
        self.classsym = classsym
        self.inner = inner

    def write_self(self):
        return b'\x55' + self.classsym.serialize() + self.inner.serialize()


class UsermarshalRaw(Node):
    """Standard Ruby 'U': class + length + opaque marshaled bytes."""

    __slots__ = ('classsym', 'data')

    def __init__(self, classsym, data):
        Node.__init__(self)
        self.classsym = classsym
        self.data = data
        self.raw = b'\x55' + classsym.serialize() + \
            _fixnum_to_bytes_std(len(data)) + data

    def write_self(self):
        return b'\x55' + self.classsym.serialize() + \
            _fixnum_to_bytes_std(len(self.data)) + self.data


class ObjectNode(Node):
    __slots__ = ('classsym', 'ivars')

    def __init__(self, classsym, ivars):
        Node.__init__(self)
        self.classsym = classsym
        self.ivars = ivars  # list of (sym_node, value_node)

    def write_self(self):
        out = bytearray(b'\x6f')
        out += self.classsym.serialize()
        out += _fixnum_to_bytes(len(self.ivars))
        for k, v in self.ivars:
            out += k.serialize()
            out += v.serialize()
        return bytes(out)


class Ivar(Node):
    __slots__ = ('inner', 'ivars')

    def __init__(self, inner, ivars):
        Node.__init__(self)
        self.inner = inner
        self.ivars = ivars

    def write_self(self):
        out = bytearray(b'\x49')
        out += self.inner.serialize()
        out += _fixnum_to_bytes(len(self.ivars))
        for k, v in self.ivars:
            out += k.serialize()
            out += v.serialize()
        return bytes(out)


class Regexp(Node):
    __slots__ = ('value', 'options')

    def __init__(self, value, options):
        Node.__init__(self)
        self.value = value
        self.options = options
        self.raw = b'\x2f' + _fixnum_to_bytes(len(value)) + value + \
            _fixnum_to_bytes(options)

    def write_self(self):
        return b'\x2f' + _fixnum_to_bytes(len(self.value)) + self.value + \
            _fixnum_to_bytes(self.options)


class ClassNode(Node):
    __slots__ = ('name',)

    def __init__(self, name):
        Node.__init__(self)
        self.name = name
        self.raw = b'\x63' + _fixnum_to_bytes(len(name)) + name

    def write_self(self):
        return b'\x63' + _fixnum_to_bytes(len(self.name)) + self.name


class ModuleNode(Node):
    __slots__ = ('name',)

    def __init__(self, name):
        Node.__init__(self)
        self.name = name
        self.raw = b'\x6d' + _fixnum_to_bytes(len(name)) + name

    def write_self(self):
        return b'\x6d' + _fixnum_to_bytes(len(self.name)) + self.name


class Parser:
    def __init__(self, buf, standard=False):
        self.buf = buf
        self.pos = 0
        self.standard = standard
        self.symbols = []     # list of symbol name bytes (for display only)
        self.objects = []     # linkable nodes parsed so far
        self.trail = []       # (pos, desc) for error debugging

    def parse(self):
        if self.buf[:2] != VERSION:
            raise ValueError('Not a Ruby Marshal stream (bad header)')
        self.pos = 2
        node = self._object()
        return node

    def _fixnum(self):
        if self.standard:
            v, self.pos = _parse_fixnum_std(self.buf, self.pos)
        else:
            v, self.pos = _parse_fixnum(self.buf, self.pos)
        return v

    def _byte(self):
        b = self.buf[self.pos]
        self.pos += 1
        return b

    def _bytes(self, n):
        b = self.buf[self.pos:self.pos + n]
        self.pos += n
        return b

    def _fixnum(self):
        v, self.pos = _parse_fixnum(self.buf, self.pos)
        return v

    def _register(self, node):
        self.objects.append(node)

    def _object(self):
        t = self._byte()
        self.trail.append((self.pos - 1, '0x%02x %r' % (t, bytes([t]))))
        if len(self.trail) > 60:
            del self.trail[0]
        if t == NIL:
            return NilNode()
        if t == TRUE:
            return BoolNode(True)
        if t == FALSE:
            return BoolNode(False)
        if t == FIXNUM:
            return Fixnum(self._fixnum(), std=self.standard)
        if t == FLOAT:
            n = self._fixnum()
            raw = self._bytes(n)
            tail = b''
            # This game's runtime appends "\x00" + the double's low 16 bits
            # (big-endian) after the float string when they are non-zero.
            if raw:
                try:
                    val = float(raw)
                    bits = struct.unpack('>Q', struct.pack('>d', val))[0]
                    low16 = struct.pack('>H', bits & 0xFFFF)
                    if self.buf[self.pos:self.pos + 3] == b'\x00' + low16:
                        tail = self._bytes(3)
                except (ValueError, struct.error):
                    pass
            node = Float(raw, tail)
            self._register(node)
            return node
        if t == BIGNUM:
            sign = self._bytes(1)
            n = self._fixnum()
            digits = []
            for _ in range(n):
                digits.append(struct.unpack('<H', self._bytes(2))[0])
            return Bignum(sign, digits)
        if t == STRING:
            n = self._fixnum()
            value = self._bytes(n)
            node = String(value)
            self._register(node)
            return node
        if t == SYMBOL:
            n = self._fixnum()
            name = self._bytes(n)
            self.symbols.append(name)
            return Symbol(name)
        if t == SYMLINK:
            idx = self._fixnum()
            return SymLink(idx)
        if t == ARRAY:
            n = self._fixnum()
            items = [self._object() for _ in range(n)]
            node = Array(items)
            self._register(node)
            return node
        if t == HASH:
            n = self._fixnum()
            entries = [(self._object(), self._object()) for _ in range(n)]
            node = Hash(entries)
            self._register(node)
            return node
        if t == HASH_DEF:
            n = self._fixnum()
            entries = [(self._object(), self._object()) for _ in range(n)]
            dflt = self._object()
            node = HashDef(entries, dflt)
            self._register(node)
            return node
        if t == OBJECT:
            cls = self._object()
            n = self._fixnum()
            ivars = [(self._object(), self._object()) for _ in range(n)]
            node = ObjectNode(cls, ivars)
            self._register(node)
            return node
        if t == IVAR:
            inner = self._object()
            n = self._fixnum()
            ivars = [(self._object(), self._object()) for _ in range(n)]
            node = Ivar(inner, ivars)
            self._register(node)
            return node
        if t == STRUCT:
            cls = self._object()
            n = self._fixnum()
            members = [(self._object(), self._object()) for _ in range(n)]
            node = Struct(cls, members)
            self._register(node)
            return node
        if t == USERDEF:
            cls = self._object()
            n = self._fixnum()
            data = self._bytes(n)
            node = Userdef(cls, data)
            self._register(node)
            return node
        if t == USERMARSHAL:
            if self.standard:
                # stock Ruby: 'U' <class> <len> <marshaled bytes>
                cls = self._object()
                n = self._fixnum()
                data = self._bytes(n)
                node = UsermarshalRaw(cls, data)
                self._register(node)
                return node
            # modified runtime: 'U' embeds a nested marshal (no length,
            # no version header) directly after the class symbol
            cls = self._object()
            inner = self._object()
            node = Usermarshal(cls, inner)
            self._register(node)
            return node
        if t == REGEXP:
            n = self._fixnum()
            value = self._bytes(n)
            opts = self._fixnum()
            node = Regexp(value, opts)
            self._register(node)
            return node
        if t == CLASS:
            name = self._bytes(self._fixnum())
            node = ClassNode(name)
            self._register(node)
            return node
        if t == MODULE:
            name = self._bytes(self._fixnum())
            node = ModuleNode(name)
            self._register(node)
            return node
        if t == LINK:
            idx = self._fixnum()
            return Link(idx)
        if t == ENC:
            idx = self._fixnum()
            # encoding descriptor (rarely used); treat as opaque leaf
            return EncodingNode(idx)
        raise ValueError('Unknown marshal type byte 0x%02x at pos %d | trail: %s' % (
            t, self.pos - 1, ' '.join('%d:%s' % (p, d) for p, d in self.trail)))
class EncodingNode(Node):
    __slots__ = ('index',)

    def __init__(self, index):
        Node.__init__(self)
        self.index = index
        self.raw = b'\x45' + _fixnum_to_bytes(index)

    def write_self(self):
        return b'\x45' + _fixnum_to_bytes(self.index)

    def to_py(self):
        return ('encoding', self.index)


def dumps(node):
    return VERSION + node.serialize()


def loads(buf, standard=False):
    return Parser(buf, standard=standard).parse()


def load_streams(buf, standard=False):
    """Parse one or more concatenated Marshal streams. Returns list of
    (offset, node) tuples. Each node gets ._parser set so symbol links can
    be resolved against the originating stream's symbol table."""
    nodes = []
    pos = 0
    while True:
        i = buf.find(VERSION, pos)
        if i < 0:
            break
        p = Parser(buf[i:], standard=standard)
        node = p.parse()
        node._parser = p
        nodes.append((i, node))
        pos = i + p.pos
    return nodes


def mark_dirty(node):
    """Mark a node and all its ancestors dirty (after a value change)."""
    node.dirty = True

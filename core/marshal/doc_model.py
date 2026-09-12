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
    """标准 Ruby Marshal fixnum 编码（XP/VX，stock Ruby 1.8/1.9）。

    ⚠ 2026-09-12 M2a 修复 **B-10 的第二处**：原实现写 ``1 <= v <= 122``
    一律用单字节（``v + 5``），但**单字节的可表示范围实际只到 117**：

    * 解析侧 ``_parse_fixnum_std`` 把 ``0x7B`` 当作"长格式标记"；
    * 编码侧若对 122 输出 ``122 + 5 = 127 = 0x7B``，
      解析侧就会去读后面 4 个字节 —— **恰好把 118..122 这五个值解成垃圾，
      并让后续流错位**。

    合成 VX/XP 样本测试（tests/compat/test_standard_mode.py）正是抓到了
    这一点：``struct.error: unpack requires a buffer of 4 bytes``。

    修正后：单字节只覆盖 ``1..117`` 与 ``-117..-1``（即 ``0x06..0x7A`` 与
    ``0x81..0xFA``），其余一律走长格式 ``0x7B`` + 大端 int32。
    这样编码侧输出的任何字节，解析侧都能正确还原（见同文件的往返测试）。
    """
    if v == 0:
        return b'\x05'
    if 1 <= v <= 117:
        return bytes([v + 5])
    if -117 <= v <= -1:
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
        """转成 Python 内建结构。

        ⚠ 2026-09-12 M2a 修复 **B-11**：原先有 10 个类未实现本方法，而
        ``Array.to_py`` / ``Hash.to_py`` 会递归调用子节点 —— 对真实 RPG 数据
        （Array 里几乎必然套着 ObjectNode）调用 ``to_py()`` 必然抛
        ``NotImplementedError``。现已全部实现，约定见 :meth:`HashDef.to_py`。
        """
        raise NotImplementedError(
            "%s 未实现 to_py()（这是缺陷，请按 HashDef.to_py 的约定补上）"
            % type(self).__name__)


# ---------------------------------------------------------------------------
# to_py() 辅助：符号名 / 实例变量名的统一解码
# ---------------------------------------------------------------------------
#: 解析器登记表（``id(parser) -> parser``）。
#:
#: 为什么需要：``SymLink`` 只存符号下标，解析名字必须回查符号表，
#: 而**只有根节点**带 ``._parser``（``load_streams`` 回填），深层
#: ``SymLink`` 拿不到。原实现因此退化成 ``"symbol#6"``，
#: 导致 VX Ace 事件文本被静默丢弃（N-14）。
#:
#: 做成模块级登记表而不是给每个节点挂 ``_parser``：后者要遍历整棵树，
#: 对大存档（数万节点）是明显开销，而且 22 个 Node 类都要改 ``__slots__``。
#:
#: 有界：超过 :data:`_PARSER_REGISTRY_LIMIT` 就整体清空（极保守的回收策略）。
#: 清空只影响"已失去根引用但仍存活"的节点，正常解析流程中符号表始终可达。
_PARSERS = {}
_PARSER_REGISTRY_LIMIT = 4096


def register_parser(parser):
    """登记一个解析器，供 ``SymLink`` 回查符号表。"""
    if len(_PARSERS) >= _PARSER_REGISTRY_LIMIT:
        _PARSERS.clear()
    _PARSERS[id(parser)] = parser
    return parser


def _sym_name(node):
    """从 Symbol / SymLink 节点取名字（bytes 按 utf-8 容错解码）。

    ⚠ 2026-09-12 M2b 修复 **N-14**：``SymLink``（``;``）是 Ruby Marshal 的
    **符号表引用**，自身只存下标。原实现拿到 ``SymLink`` 时直接返回
    ``"symbol#6"`` 这种占位串 —— 于是所有依赖"符号名比较"的判断全部失效：

    * ``obj.class_name == "RPG::EventCommand"`` 永远为假
    * ``_rmobject_key`` 找不到 ``@code`` / ``@parameters``
    → **VX Ace 的事件文本被静默丢弃**（本机实测：从 6 千余条掉到 115 条，
      而且不报错。这正是"静默丢功能"最危险的一类。）

    现在回查 ``node._parser.symbols``，取不到时退回模块级登记表
    :data:`_PARSERS`。两者都拿不到才保留可辨认的占位串（便于排查，
    也避免把"解析失败"伪装成"没有这个字段"）。
    """
    if node is None:
        return None
    if isinstance(node, SymLink):
        for parser in (getattr(node, '_parser', None), _PARSERS.get(id(node))):
            symbols = getattr(parser, 'symbols', None)
            if symbols and 0 <= node.index < len(symbols):
                raw = symbols[node.index]
                return raw.decode('utf-8', 'replace') if isinstance(raw, bytes) \
                    else str(raw)
        return "symbol#%d" % node.index
    name = getattr(node, 'name', None)
    if isinstance(name, bytes):
        return name.decode('utf-8', 'replace')
    if name is not None:
        return str(name)
    index = getattr(node, 'index', None)
    if index is not None:
        return "symbol#%d" % index
    return None


def _ivar_name(node):
    """实例变量名统一带 ``@`` 前缀（与 Ruby 源码写法一致，便于人工核对）。"""
    name = _sym_name(node)
    if name and not name.startswith('@'):
        return '@' + name
    return name


def _sym_or_key(node):
    """字典键：符号转成普通字符串，其余走 to_py()。

    注意不能直接用 ``Node.to_py``：Fixnum 会变成 int、String 会变成 str，
    作为 dict 键都可以用，但会丢失"这是符号"的信息；而 RPG 数据的
    Hash 键绝大多数是 Fixnum（道具 id）。因此这里对 Symbol 取名字，
    其余一律 ``to_py()`` 后直接当键。
    """
    if isinstance(node, (Symbol, SymLink)):
        return _sym_name(node)
    return node.to_py()


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

    def to_py(self):
        """带默认值的 Hash。

        ⚠ 2026-09-12 M2a 修复 **B-11**：本方法（连同下面 9 个类）原先未实现，
        基类会抛 ``NotImplementedError``；而 ``Array.to_py`` / ``Hash.to_py``
        会**递归**调用子节点的 ``to_py`` —— 因此对真实 RPG 数据（Array 里套
        ObjectNode）调用 ``to_py()`` 必然抛异常。``core/formats/rgss_save.py``
        当初就是因为这个自己另写了一套遍历（见其 ``_children``）。

        返回值约定（M2a 统一）：能无损对应 Python 内建类型的就返回内建类型；
        Ruby 独有结构返回**带标记的 dict**，标记键统一为 ``"__ruby__"``。
        这样 ``to_py()`` 既能当通用遍历入口用，也不会丢失类型信息。
        """
        return {
            "__ruby__": "HashDef",
            "entries": {_sym_or_key(k): v.to_py() for k, v in self.entries},
            "default": self.default.to_py(),
        }


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

    def to_py(self):
        return {
            "__ruby__": "Struct",
            "class": _sym_name(self.classsym),
            "members": {_sym_or_key(k): v.to_py() for k, v in self.members},
        }


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

    def to_py(self):
        return {
            "__ruby__": "UserDef",
            "class": _sym_name(self.classsym),
            # 不透明字节：保留原文，调用方需要时自行解码
            "data": self.data,
        }


class Usermarshal(Node):
    __slots__ = ('classsym', 'inner')

    def __init__(self, classsym, inner):
        Node.__init__(self)
        self.classsym = classsym
        self.inner = inner

    def write_self(self):
        return b'\x55' + self.classsym.serialize() + self.inner.serialize()

    def to_py(self):
        return {
            "__ruby__": "UserMarshal",
            "class": _sym_name(self.classsym),
            "value": self.inner.to_py(),
        }


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

    def to_py(self):
        return {
            "__ruby__": "UserMarshalRaw",
            "class": _sym_name(self.classsym),
            "data": self.data,
        }


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

    def to_py(self):
        """任意 Ruby 对象 → 带标记的 dict。

        这是修复 B-11 的**关键**一项：真实 RPG 数据里 Array/Hash 里几乎总是
        套着 ObjectNode，只要它没实现 ``to_py``，整个 ``to_py()`` 链就不可用。
        实例变量名统一带 ``@`` 前缀（与 Ruby 源码一致），便于人工核对。
        """
        return {
            "__ruby__": "Object",
            "class": _sym_name(self.classsym),
            "ivars": {_ivar_name(k): v.to_py() for k, v in self.ivars},
        }


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

    def to_py(self):
        """``I`` 前缀：语义上是"给内层值额外挂实例变量"。

        对 RPG 数据最常见的用途是字符串的编码标记（``E`` / ``encoding``），
        因此这里**优先返回内层值本身**，把附加属性放在带标记的 dict 里
        —— 这样 ``to_py()`` 的结果对调用方最有用（直接拿到文本）。
        """
        return {
            "__ruby__": "Ivar",
            "value": self.inner.to_py(),
            "ivars": {_ivar_name(k): v.to_py() for k, v in self.ivars},
        }


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

    def to_py(self):
        return {
            "__ruby__": "Regexp",
            "source": self.value.decode('utf-8', 'replace'),
            "options": self.options,
        }

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

    def to_py(self):
        return {"__ruby__": "Class", "name": self.name.decode('utf-8', 'replace')}


class ModuleNode(Node):
    __slots__ = ('name',)

    def __init__(self, name):
        Node.__init__(self)
        self.name = name
        self.raw = b'\x6d' + _fixnum_to_bytes(len(name)) + name

    def write_self(self):
        return b'\x6d' + _fixnum_to_bytes(len(self.name)) + self.name

    def to_py(self):
        return {"__ruby__": "Module", "name": self.name.decode('utf-8', 'replace')}


#: ---------------------------------------------------------------------------
#: 节点访问辅助：直接操作节点树时用（``core/formats/rgss_save.py`` 与测试都要）
#:
#: ``ObjectNode.ivars`` 是 ``(Symbol 节点, 值节点)`` 的**列表**而不是 dict，
#: 因此按名字取字段需要这个小工具。收敛到值层（``value_layer``）的调用方
#: 不必用它 —— 值层的 ``_IvarMap`` 已经做了 dict 视图。
#: ---------------------------------------------------------------------------
def ivar(node, name, default=None):
    """按名字取 ``ObjectNode`` 的实例变量值（容忍 ``@`` 前缀可有可无）。

    例如 ``ivar(obj, "name")`` 与 ``ivar(obj, "@name")`` 等价。
    """
    pairs = getattr(node, "ivars", None)
    if not pairs:
        return default
    candidates = (name, name[1:]) if name.startswith("@") else ("@" + name, name)
    for sym, value in pairs:
        if _sym_name(sym) in candidates:
            return value
    return default


def ivar_names(node):
    """列出 ``ObjectNode`` 的实例变量名（已解码，带 ``@``）。"""
    return [_sym_name(sym) for sym, _value in (getattr(node, "ivars", None) or [])]


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
        """读一个定长整数。

        ⚠ 2026-09-12 M2a 修复 **B-10**：本方法原先在本类中**定义两次** ——
        第一版尊重 ``self.standard``，第二版（在本方法之后定义）无条件走变体
        编码器并覆盖了第一版。后果是 ``standard=True``（XP/VX 的活路径，
        见 core/engines.py 的 ``standard`` 字段）**按变体解析、按标准写回**，
        回写字节漂移（例如 0 会被写成 0x05）。

        现在只保留尊重 ``self.standard`` 的这一版，并对齐写侧
        （``Fixnum.write_self`` 同样按 ``self.standard`` 选择编码器）。
        回归测试：tests/compat/test_m2a_regressions.py::TestB10FixnumStandard。
        """
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
            node = SymLink(idx)
            # N-14：登记解析器，使 _sym_name 能回查符号表（见 _PARSERS 说明）
            register_parser(self)
            node._parser = self
            return node
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

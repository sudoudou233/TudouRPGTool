# -*- coding: utf-8 -*-
"""值层门面：在**文档模型**之上提供"像 Python 对象一样读写"的视图。

@feature  none
@layer    core
@public   RMObject, RMIvar, RMStr, RMSymbol, RMDict, RMStruct, RMUserDefined,
          RMUserMarshal, RMRegexp, RMData, RMClass, RMModule, RMFloat,
          wrap, unwrap, loads, dumps, is_ruby_object
@depends  core.marshal.doc_model
@tested   tests/unit/test_marshal_value.py
@footprint docs/MODULES.md#coremarshal

为什么需要门面层（M2b 收敛策略，见 ADR-004）
-------------------------------------------
`core/marshal/` 曾有两份独立实现：

* `doc_model` —— 文档模型（Node 树 + `Node.raw` 增量字节保真）→ **保留为二进制层**
* `value_model` —— 值模型（`RM*` 类 + 直接读写 Python 值）→ **本文件取代它**

合并方式**不是**"把值模型搬到文档模型上跑两遍编解码"，而是让值层对象
**直接持有并改写 Node**：

* 读：``wrap(node)`` 把 Node 包成 `RMObject` / `RMStr` / `RMIvar` 等代理
* 写：代理上的任何修改**立刻落到 Node 上**（通过 `_IvarMap` / 列表视图）
* 存：``doc_model.dumps(root)`` 序列化 —— 因为改的就是 Node 本身，
  未触碰的子树仍然吐出原始字节（增量保真天然成立）

这样一来"值模型的便利"和"文档模型的字节保真"同时成立，且**只有一份解析器**。

ivar 键的两种约定（这是本任务唯一的真难点）
------------------------------------------
* 文档模型的 ``ObjectNode.ivars`` 是 **``(Symbol 节点, 值节点)`` 的列表**，
  符号名带 ``@``（如 ``@name``）
* 旧值模型与所有调用方（``core/formats/rgss_data.py``）用的是
  **普通 dict**，键是 ``str``，且**允许省略 ``@``**（``rgss_data`` 两者都写）

:class:`_IvarMap` 因此做成"双向容忍"的映射视图：读的时候先试原样、再试加/去
``@``；写的时候复用已存在的键名，不存在则按传入的名字新建 Symbol 节点。
"""

from __future__ import annotations

from . import doc_model as D


class MarshalValueError(TypeError):
    """值层使用错误（例如在不支持的结构上取 ivars）。"""


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------
def _sym_name(node):
    """取符号节点的名字（``Symbol`` / ``SymLink`` 都支持）。

    ``SymLink``（``;``）是 Ruby Marshal 的符号表引用 —— 它只存**下标**，
    真正的名字在解析器的符号表里。若不解析下标，会得到 ``"symbol#6"``
    这种占位串，于是 ``obj.class_name == "RPG::EventCommand"`` 永远为假，
    **所有事件文本会被静默丢弃**（M2b 实测：VX Ace 从 6 千余条掉到 115 条）。
    所以这里必须回查符号表。
    """
    if node is None:
        return None
    if isinstance(node, D.SymLink):
        index = node.index
        parser = _parser_of(node)
        symbols = getattr(parser, "symbols", None) if parser else None
        if symbols and 0 <= index < len(symbols):
            name = symbols[index]
            return name.decode("utf-8", "replace") if isinstance(name, bytes) \
                else str(name)
        # 拿不到符号表：保留可辨认的占位（便于排查），而不是返回 None
        return "symbol#%d" % index
    name = getattr(node, "name", None)
    if isinstance(name, bytes):
        return name.decode("utf-8", "replace")
    if name is not None:
        return str(name)
    return None


def _parser_of(node):
    """尽力找到节点所属的解析器（用于解析 SymLink 的下标）。

    两个来源：节点自身的 ``_parser``，或同一棵树里任意节点的 ``_parser``
    （``doc_model.load_streams`` 会回填 ``_parser``）。
    """
    parser = getattr(node, "_parser", None)
    if parser is not None and getattr(parser, "symbols", None):
        return parser
    return parser


def _sym_node(name):
    """把字符串或 Symbol 节点统一成 Symbol 节点。"""
    if isinstance(name, (D.Symbol, D.SymLink)):
        return name
    return D.Symbol(str(name).encode("utf-8"))


def _key_candidates(name):
    """一个键在文档模型里可能的写法（原样 / 加 @ / 去 @）。"""
    name = str(name)
    if name.startswith("@"):
        return (name, name[1:])
    return ("@" + name, name)


def is_ruby_object(value):
    """该值是否是值层代理对象。"""
    return isinstance(value, _Proxy)


# ---------------------------------------------------------------------------
# 代理基类
# ---------------------------------------------------------------------------
class _Proxy(object):
    """所有值层代理的基类：持有一个 Node，``node`` 是唯一真相。"""

    __slots__ = ("_node", "_enc")

    def __init__(self, node, enc=None):
        object.__setattr__(self, "_node", node)
        object.__setattr__(self, "_enc", enc)

    @property
    def node(self):
        """底层 Node（需要直接操作文档模型时用）。"""
        return self._node

    def __repr__(self):
        return "<%s %s>" % (type(self).__name__, self._node)


class _ValueProxy(_Proxy):
    """有"标量值"的代理（整数/浮点/字符串/布尔）。"""

    __slots__ = ()

    def _get(self):
        raise NotImplementedError

    def _set(self, value):
        raise NotImplementedError


class _IvarMap(object):
    """``ObjectNode.ivars`` 的 dict 视图（可读可写，容忍 ``@`` 前缀差异）。

    写操作**直接落到 Node 上**，因此宿主对象的 ``dirty`` 标志与
    ``doc_model.dumps`` 的字节保真都自动成立 —— 这是本门面层的核心机制。
    """

    __slots__ = ("_obj",)

    def __init__(self, obj):
        self._obj = obj

    # ---- 内部 ----
    def _pairs(self):
        return self._obj.ivars

    def _find_index(self, key):
        """返回 (下标, 真实键名)；找不到返回 (None, None)。"""
        pairs = self._pairs()
        candidates = _key_candidates(key)
        for index, (sym, _value) in enumerate(pairs):
            name = _sym_name(sym)
            if name in candidates:
                return index, name
        return None, None

    # ---- 读 ----
    def __getitem__(self, key):
        index, _name = self._find_index(key)
        if index is None:
            raise KeyError(key)
        return wrap(self._pairs()[index][1])

    def get(self, key, default=None):
        index, _name = self._find_index(key)
        if index is None:
            return default
        return wrap(self._pairs()[index][1])

    def __contains__(self, key):
        index, _name = self._find_index(key)
        return index is not None

    def __len__(self):
        return len(self._pairs())

    def __iter__(self):
        for sym, _value in self._pairs():
            yield _sym_name(sym)

    def keys(self):
        return list(iter(self))

    def items(self):
        for sym, value in self._pairs():
            yield _sym_name(sym), wrap(value)

    def values(self):
        for _sym, value in self._pairs():
            yield wrap(value)

    def __repr__(self):
        return "IvarMap(%r)" % (self.keys(),)

    # ---- 写 ----
    def __setitem__(self, key, value):
        self._assign(key, value)

    def _assign(self, key, value):
        node = unwrap_to_node(value)
        index, name = self._find_index(key)
        if index is not None:
            self._pairs()[index] = (self._pairs()[index][0], node)
        else:
            # 新键：优先尊重该对象已有的前缀习惯，否则加 @
            prefix = self._preferred_prefix()
            new_name = str(key) if str(key).startswith("@") else prefix + str(key)
            self._pairs().append((D.Symbol(new_name.encode("utf-8")), node))
        self._obj.dirty = True

    def _preferred_prefix(self):
        """看该对象现有键是否习惯带 ``@``，用于新建键时保持一致。"""
        for sym, _value in self._pairs():
            name = _sym_name(sym) or ""
            return "" if not name.startswith("@") else "@"
        return "@"

    def __delitem__(self, key):
        index, _name = self._find_index(key)
        if index is None:
            raise KeyError(key)
        del self._pairs()[index]
        self._obj.dirty = True

    def setdefault(self, key, default=None):
        if key in self:
            return self[key]
        self[key] = default
        return self[key]

    def update(self, other=None, **kwargs):
        if other:
            items = other.items() if hasattr(other, "items") else other
            for key, value in items:
                self[key] = value
        for key, value in kwargs.items():
            self[key] = value

    # ---- 数值视图（rgss_data 的读路径要遍历）----
    def __eq__(self, other):
        """与普通 dict 比较时**递归转成 Python 内建值**。

        注意不能直接 ``dict(self.items()) == other``：``items()`` 给出的是
        列表/哈希的**代理**（`RMArray`/`RMDict`），与 ``[1,2,3]`` / ``{1: 2}``
        比较必然不等。这里用 :func:`to_plain` 递归展开后再比。
        """
        if isinstance(other, _IvarMap):
            other = dict(other.items())
        if isinstance(other, dict):
            return {k: to_plain(v) for k, v in self.items()} == other
        return NotImplemented

    def __hash__(self):
        return id(self)


# ---------------------------------------------------------------------------
# 具体代理
# ---------------------------------------------------------------------------
class RMObject(_Proxy):
    """任意 Ruby 对象（``o``）。``ivars`` 是 :class:`_IvarMap`。"""

    __slots__ = ()

    @property
    def class_name(self):
        return _sym_name(self._node.classsym)

    @property
    def ivars(self):
        return _IvarMap(self._node)

    @property
    def modules(self):
        """``e`` 扩展模块列表（本门面层不修改它，只暴露）。"""
        return [_sym_name(m) for m in getattr(self._node, "modules", []) or []]

    def get(self, name, default=None):
        return self.ivars.get(name, default)

    def __getitem__(self, name):
        return self.ivars[name]

    def __setitem__(self, name, value):
        self.ivars[name] = value

    def __contains__(self, name):
        return name in self.ivars

    def __repr__(self):
        return "RMObject(%s, %d ivars)" % (self.class_name, len(self.ivars))


class RMIvar(_Proxy):
    """``I`` 前缀包装：内层值 + 附加实例变量（最常见是字符编码标记）。"""

    __slots__ = ()

    @property
    def value(self):
        """内层值（若内层是字符串，会带上 Ivar 里声明的编码）。"""
        return wrap(self._node.inner, enc=self._enc)

    @value.setter
    def value(self, new_value):
        self._node.inner = unwrap_to_node(new_value)
        self._node.dirty = True

    @property
    def encoding(self):
        """本包装声明的编码（没有则 None）。"""
        return self._enc

    @property
    def ivars(self):
        return _IvarMap(self._node)

    def __repr__(self):
        return "RMIvar(%r)" % (self._node.inner,)


class _StrProxy(_Proxy):
    """字符串代理：``str`` 子类会丢掉 Node 关联，因此这里显式暴露 ``.value``。

    编码从哪来：文档模型是**纯字节**的（这正是它能字节保真的原因），
    字符串的编码信息藏在它的 ``Ivar`` 包装里（``@encoding = :UTF_8`` /
    ``:Windows_31J`` …）。:func:`wrap` 在把 ``Ivar`` 内层字符串包成代理时
    会把解析出的编码顺手带上，于是 :attr:`enc` 能反映**原文件的编码**。

    为什么必须保留：XP 的文本是 cp932、VX Ace 是 UTF-8。写回时若一律用
    UTF-8，cp932 的旧文本会被重新编码，字节数变化 —— 轻则文件"看起来变了"，
    重则游戏读到的字符串长度不对。所以 ``rgss_data._set_value`` 一直
    是"跟随原编码写回"，门面层必须支撑这一点。
    """

    __slots__ = ()

    @property
    def value(self):
        raw = self._node.value
        return raw.decode(self.encoding, "replace") if isinstance(raw, bytes) \
            else str(raw)

    @value.setter
    def value(self, text):
        self._node.value = str(text).encode(self.encoding, "replace")
        self._node.dirty = True

    @property
    def encoding(self):
        """原始编码：优先用 Ivar 带来的，其次节点自带的，最后回落到 utf-8。"""
        enc = self._enc or getattr(self._node, "enc", None)
        return enc or "utf-8"

    #: 旧 API 兼容：``RMStr.enc``
    @property
    def enc(self):
        return self.encoding

    def __str__(self):
        return self.value

    def __eq__(self, other):
        if isinstance(other, _StrProxy):
            return self.value == other.value
        if isinstance(other, str):
            return self.value == other
        return NotImplemented

    def __hash__(self):
        return hash(self.value)

    def __contains__(self, item):
        return item in self.value

    def __repr__(self):
        return "%s(%r)" % (type(self).__name__, self.value)


class RMStr(_StrProxy):
    """字符串（``"``）。"""

    __slots__ = ()


class RMSymbol(_StrProxy):
    """符号（``:``）。"""

    __slots__ = ()


class _ListProxy(_Proxy):
    """列表代理（``Array`` / ``Hash.entries`` 之类的序列视图）。"""

    __slots__ = ()

    def _items(self):
        raise NotImplementedError

    def __len__(self):
        return len(self._items())

    def __getitem__(self, index):
        return wrap(self._items()[index])

    def __setitem__(self, index, value):
        self._items()[index] = unwrap_to_node(value)
        self._node.dirty = True

    def __iter__(self):
        for item in list(self._items()):
            yield wrap(item)

    def __delitem__(self, index):
        del self._items()[index]
        self._node.dirty = True

    def append(self, value):
        self._items().append(unwrap_to_node(value))
        self._node.dirty = True

    def __contains__(self, value):
        target = value.value if isinstance(value, _StrProxy) else value
        return any(item == target for item in self)

    def __repr__(self):
        return "%s(%d)" % (type(self).__name__, len(self._items()))


class RMArray(_ListProxy):
    """数组（``[``）。"""

    __slots__ = ()

    def _items(self):
        return self._node.items


class RMDict(_Proxy):
    """带默认值的 Hash（``}``）。

    值模型的旧 ``RMDict`` 是 ``dict`` 子类；本门面层改为"持有 Hash 节点"，
    因为改键值必须落到 Node 上才能保持字节保真。
    """

    __slots__ = ()

    def _entries(self):
        return self._node.entries

    def __getitem__(self, key):
        for k, v in self._entries():
            if _key_matches(k, key):
                return wrap(v)
        if getattr(self._node, "default", None) is not None:
            return wrap(self._node.default)
        raise KeyError(key)

    def __setitem__(self, key, value):
        node = unwrap_to_node(value)
        for index, (k, _v) in enumerate(self._entries()):
            if _key_matches(k, key):
                self._entries()[index] = (k, node)
                self._node.dirty = True
                return
        self._entries().append((_hash_key_node(key), node))
        self._node.dirty = True

    def __contains__(self, key):
        return any(_key_matches(k, key) for k, _v in self._entries())

    def __len__(self):
        return len(self._entries())

    def keys(self):
        for k, _v in self._entries():
            yield _hash_key_value(k)

    def values(self):
        for _k, v in self._entries():
            yield wrap(v)

    def items(self):
        for k, v in self._entries():
            yield _hash_key_value(k), wrap(v)

    def get(self, key, default=None):
        try:
            return self[key]
        except KeyError:
            return default

    def __eq__(self, other):
        """与普通 dict 比较时递归展开（与 `_IvarMap.__eq__` 同一套规则）。"""
        if isinstance(other, RMDict):
            other = dict(other.items())
        if isinstance(other, dict):
            return {k: to_plain(v) for k, v in self.items()} == other
        return NotImplemented

    def __repr__(self):
        return "RMDict(%d entries)" % len(self._entries())


class RMStruct(_Proxy):
    """``S``：类 + 成员（成员名是符号）。"""

    __slots__ = ()

    @property
    def class_name(self):
        return _sym_name(self._node.classsym)

    def members(self):
        return {_sym_name(k): wrap(v) for k, v in self._node.members}

    def __getitem__(self, name):
        for k, v in self._node.members:
            if _sym_name(k) == name:
                return wrap(v)
        raise KeyError(name)

    def __repr__(self):
        return "RMStruct(%s)" % self.class_name


class RMUserDefined(_Proxy):
    """``u``：类符号 + 不透明字节。"""

    __slots__ = ()

    @property
    def class_name(self):
        return _sym_name(self._node.classsym)

    @property
    def data(self):
        return self._node.data


class RMUserMarshal(_Proxy):
    """``U``：类符号 + 内嵌值（或原始字节）。"""

    __slots__ = ()

    @property
    def class_name(self):
        return _sym_name(self._node.classsym)

    @property
    def value(self):
        if isinstance(self._node, D.UsermarshalRaw):
            return self._node.data
        return wrap(self._node.inner)


class RMRegexp(_Proxy):
    """``/``：正则。"""

    __slots__ = ()

    @property
    def pattern(self):
        return self._node.value.decode("utf-8", "replace")

    @property
    def options(self):
        return self._node.options


class RMData(_Proxy):
    """``d``：类符号 + 不透明字节。"""

    __slots__ = ()

    @property
    def class_name(self):
        return _sym_name(self._node.classsym)

    @property
    def value(self):
        return self._node.value


class RMClass(_Proxy):
    """``c``：类引用。"""

    __slots__ = ()

    @property
    def name(self):
        return self._node.name.decode("utf-8", "replace")


class RMModule(_Proxy):
    """``m`` / ``M``：模块引用。"""

    __slots__ = ()

    @property
    def name(self):
        return self._node.name.decode("utf-8", "replace")


class RMFloat(_Proxy):
    """``f``：浮点。``value`` 是 float，``raw`` 是原始字节（字节保真靠它）。"""

    __slots__ = ()

    @property
    def value(self):
        return self._node.to_py().get("value") if isinstance(
            self._node.to_py(), dict) else self._node.to_py()

    def __float__(self):
        return float(self.value)

    def __repr__(self):
        return "RMFloat(%r)" % (self.value,)


# ---------------------------------------------------------------------------
# Hash 键匹配
# ---------------------------------------------------------------------------
def _hash_key_value(node):
    """Hash 键的"用户可见"形态：整数就是 int，符号是名字，其余走值层。"""
    if isinstance(node, D.Fixnum):
        return node.value
    if isinstance(node, D.Bignum):
        return node.value
    if isinstance(node, (D.Symbol, D.SymLink)):
        return _sym_name(node)
    if isinstance(node, (D.String,)):
        return wrap(node)
    return wrap(node)


def _hash_key_node(key):
    """把用户给的键变成 Node。"""
    if isinstance(key, int):
        return D.Fixnum(key)
    if isinstance(key, (D.Symbol, D.SymLink)):
        return key
    if isinstance(key, _StrProxy):
        return key.node
    if isinstance(key, str):
        return D.RMSymbol if False else D.Symbol(key.encode("utf-8"))
    return unwrap_to_node(key)


def _key_matches(node, key):
    """Hash 键是否匹配用户给的值。

    字符串键与 :class:`_IvarMap` 保持同一套容忍规则（原样 / 加 ``@`` / 去 ``@``）——
    RPG 数据的 Hash 里符号键有的带 ``@`` 有的不带，调用方不该被迫记住哪一个。
    """
    if isinstance(key, int):
        return isinstance(node, (D.Fixnum, D.Bignum)) and node.value == key
    if isinstance(key, _StrProxy):
        key = key.value
    if isinstance(key, str):
        if isinstance(node, (D.Symbol, D.SymLink)):
            name = _sym_name(node)
            return name in _key_candidates(key)
        if isinstance(node, D.String):
            raw = node.value
            text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) \
                else str(raw)
            return text in _key_candidates(key)
        return False
    return False


def to_plain(value):
    """把值层对象递归转成 Python 内建值（**只用于比较/展示**，不保留 Node 关联）。

    用途：``assertEqual(ivars, {...})`` 这类断言、以及日志/诊断输出。
    **不要**用它做写回 —— 那会丢掉 Node，字节保真随之失效（要写回请用
    :func:`unwrap` / :func:`unwrap_to_node`）。
    """
    if isinstance(value, _IvarMap):
        return dict(value.items())
    if isinstance(value, RMObject):
        return {k: to_plain(v) for k, v in value.ivars.items()}
    if isinstance(value, RMIvar):
        return to_plain(value.value)
    if isinstance(value, _ListProxy):
        return [to_plain(v) for v in value]
    if isinstance(value, RMDict):
        return {k: to_plain(v) for k, v in value.items()}
    if isinstance(value, RMStruct):
        return to_plain(value.members())
    if isinstance(value, (RMStr, RMSymbol)):
        return value.value
    if isinstance(value, RMFloat):
        return value.value
    if isinstance(value, RMUserDefined):
        return value.data
    if isinstance(value, RMUserMarshal):
        return to_plain(value.value)
    if isinstance(value, RMRegexp):
        return {"__ruby__": "Regexp", "source": value.pattern,
                "options": value.options}
    if isinstance(value, RMData):
        return value.value
    if isinstance(value, (RMClass, RMModule)):
        return value.name
    if isinstance(value, _Proxy):
        return value.node.to_py()
    return value


#: Ruby 编码符号名 → Python 编码名。
#:
#: 只覆盖 RPG Maker 实际会用到的三种（VX Ace 用 UTF-8、XP 用 cp932、
#: 少数场景用 ascii/latin-1）。识别不出来时返回 None，由调用方回落 utf-8。
_ENCODING_ALIASES = {
    "utf_8": "utf-8", "utf8": "utf-8", "utf-8": "utf-8",
    "windows_31j": "cp932", "shift_jis": "cp932", "sjis": "cp932",
    "cp932": "cp932", "windows-31j": "cp932",
    "ascii": "ascii", "us_ascii": "ascii", "binary": "ascii",
    "ascii_8bit": "ascii",
    "iso_8859_1": "latin-1", "latin_1": "latin-1", "latin1": "latin-1",
}


def encoding_from_ivars(pairs):
    """从 ``Ivar`` 的 ivar 列表里解析出编码名（没有就返回 None）。

    只认两种写法，都是 Ruby Marshal 的标准形状：

    * ``@encoding = :UTF_8``（VX Ace 常见）
    * ``@E = true`` 且另有 ``@encoding``（老写法，值本身不携带编码名）
    """
    found = None
    for sym, value in pairs or ():
        name = _sym_name(sym)
        if name not in ("@encoding", "encoding"):
            continue
        if isinstance(value, (D.Symbol, D.SymLink)):
            key = (_sym_name(value) or "").lower().replace("-", "_")
            found = _ENCODING_ALIASES.get(key)
        elif isinstance(value, D.String):
            raw = value.value
            text = raw.decode("ascii", "replace") if isinstance(raw, bytes) \
                else str(raw)
            found = _ENCODING_ALIASES.get(text.lower().replace("-", "_"))
    return found


# ---------------------------------------------------------------------------
# wrap / unwrap
# ---------------------------------------------------------------------------
_NODE_TO_PROXY = {}


def _build_proxy_table():
    """Node 类型 → 代理类型（延迟构建，避免类定义顺序问题）。"""
    _NODE_TO_PROXY.update({
        D.ObjectNode: RMObject,
        D.Ivar: RMIvar,
        D.String: RMStr,
        D.Symbol: RMSymbol,
        D.SymLink: RMSymbol,
        D.Array: RMArray,
        D.Hash: RMDict,
        D.HashDef: RMDict,
        D.Struct: RMStruct,
        D.Userdef: RMUserDefined,
        D.Usermarshal: RMUserMarshal,
        D.UsermarshalRaw: RMUserMarshal,
        D.Regexp: RMRegexp,
        D.EncodingNode: RMStr,
        D.Float: RMFloat,
    })


_build_proxy_table()

#: 标量节点的取值方式（读成 Python 原生值而不是代理）
_SCALAR_NODES = (D.NilNode, D.BoolNode, D.Fixnum, D.Bignum)


def wrap(node, enc=None):
    """Node → 值层对象。

    * ``None`` → ``None``；标量（nil/bool/int/bignum）→ Python 原生值；
    * ``Ivar`` → 把编码信息解析出来传给内层字符串代理，再返回代理本身
      （``RMIvar.value`` 也能拿到带编码的字符串）；
    * 其他 → 对应的 ``RM*`` 代理（持有同一个 Node，因此改它就是改文档）

    ``enc`` 参数供内部递归时传递已解析出的编码，调用方一般不用传。
    """
    if node is None:
        return None
    if isinstance(node, D.NilNode):
        return None
    if isinstance(node, D.BoolNode):
        return bool(node.value)
    if isinstance(node, (D.Fixnum, D.Bignum)):
        return node.value
    if isinstance(node, D.Link):
        return node.to_py()
    if isinstance(node, D.Ivar):
        # 编码藏在 Ivar 的 ivar 里；把它带上，内层字符串写回时才知道用哪种编码
        resolved = enc or encoding_from_ivars(node.ivars)
        return RMIvar(node, resolved)
    proxy_cls = _NODE_TO_PROXY.get(type(node))
    if proxy_cls is None:
        return node.to_py()
    return proxy_cls(node, enc)


def unwrap(value):
    """值层对象 → Node（已是 Node 则原样返回）。"""
    return unwrap_to_node(value)


def unwrap_to_node(value):
    """把用户给的值转成 Node。"""
    if isinstance(value, _Proxy):
        return value.node
    if isinstance(value, D.Node):
        return value
    if value is None:
        return D.NilNode()
    if isinstance(value, bool):
        return D.BoolNode(value)
    if isinstance(value, int):
        return D.Fixnum(value)
    if isinstance(value, float):
        import struct
        return D.Float(struct.pack(">d", value))
    if isinstance(value, str):
        return D.String(value.encode("utf-8"))
    if isinstance(value, bytes):
        return D.String(value)
    if isinstance(value, (list, tuple)):
        return D.Array([unwrap_to_node(v) for v in value])
    if isinstance(value, dict):
        return D.Hash([(_hash_key_node(k), unwrap_to_node(v))
                       for k, v in value.items()])
    raise MarshalValueError("无法转换的值类型：%s" % type(value).__name__)


# ---------------------------------------------------------------------------
# loads / dumps
# ---------------------------------------------------------------------------
def loads(data, standard=False):
    """解析单流 Marshal，返回值层对象。

    ⚠ 实现细节：走 ``doc_model.load_streams`` 而不是直接 ``Parser.parse``。
    原因是 ``SymLink``（符号表引用）只存下标，解析时**必须**能回查
    ``parser.symbols``；而 ``load_streams`` 会把 ``_parser`` 回填到根节点上，
    直接 ``Parser.parse`` 则不会。少了这一步，``class_name`` 会退化成
    ``"symbol#6"`` 这种占位串 —— 依赖 ``class_name == "RPG::EventCommand"``
    的判断全部失效，事件文本被静默丢弃（M2b 实测）。
    """
    streams = D.load_streams(data, standard=standard)
    if not streams:
        raise MarshalValueError("解析结果为空：这是缺陷，请检查字节流与 standard 参数")
    return wrap(streams[0][1])


def load_streams(data, standard=False):
    """解析多流 Marshal，返回 ``[(offset, 值层对象), ...]``。"""
    return [(offset, wrap(node))
            for offset, node in D.load_streams(data, standard=standard)]


def dumps(value):
    """序列化值层对象（改过的 Node 会重编，未触碰的子树吐原始字节）。"""
    return D.dumps(unwrap_to_node(value))

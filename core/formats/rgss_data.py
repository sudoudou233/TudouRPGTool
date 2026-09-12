# -*- coding: utf-8 -*-
"""
Extraction and patching for RPG Maker VX Ace / XP rxdata files.

@feature  translate
@layer    core
@public   extract, apply_to_files
@depends  core.textutil, core.marshal.value_layer, core.formats.mv_mz_data
@tested   tests/compat/test_formats_compat.py
@footprint docs/MODULES.md#coreformats
@note     vendored：来自 rpgmaker_translation_tool/tool/vxace.py。
@note     已知缺陷 B-02（非原子写）、B-13（original 参数未用于校验）。
"""

from __future__ import annotations

import os

from ..marshal import doc_model as _doc_model
from ..marshal import value_layer as marshal
from ..safety.atomic import atomic_write_bytes
from ..textutil import has_real_text
from .mv_mz_data import TEXT_CODES


def _iv(obj, name):
    if _is_object_proxy(obj):
        return obj.ivars.get(name)
    if isinstance(obj, dict):
        return obj.get(name)
    return None


def _text_of(v):
    """把"可能是 RMIvar / 字符串代理 / 原生 str"的值归一化成 ``str``（否则 None）。

    ⚠ 2026-09-12 M2b 发现并修复 **N-13**：切到 ``value_layer`` 之后，字符串
    不再以 Python ``str`` 出现，而是 **``RMStr`` 代理**（``Ivar`` 包装里的
    还会先经过 ``RMIvar``）。原实现只 ``isinstance(v, str)``，于是
    **VX Ace 全平台提取结果为 0 条**（静默丢功能，不报错）——
    本机两个 VX Ace 真实样本上 100% 复现。

    现在按"代理 → 原生"的层次逐个剥开：先剥 ``Ivar``，再剥带 ``.value``
    的字符串代理，最后才判断类型。
    """
    v = _unwrap(v)
    if v is None:
        return None
    if isinstance(v, str):
        return v
    value = getattr(v, "value", None)
    if isinstance(value, str):
        return value
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return None


def _walk_event_list(entries, fname, ev_list, path_prefix, note_prefix, include_comments):
    for i, cmd in enumerate(_pairs_of_values(ev_list)):
        if not _is_object_proxy(cmd) or cmd.class_name != "RPG::EventCommand":
            continue
        code = _iv(cmd, "@code")
        rule = TEXT_CODES.get(code)
        if not rule:
            continue
        idx, category = rule
        if category == "注释" and not include_comments:
            continue
        # ⚠ N-13 的第二处：VX Ace 的 @parameters 是 **Ivar 包装的数组**
        # （"parameters" 方法名本身被当作 ivar 名用），必须剥掉包装才能按下标取。
        # 不剥的话 len() 为 0 → 所有 401/402 对话被静默丢弃（本机实测：
        # VX Ace 从 6511 条掉到 115 条）。
        params = _unwrap(_iv(cmd, "@parameters")) or []
        if type(params).__name__ == "RMArray":
            if idx >= len(params):
                continue
            text = _text_of(params[idx])
        elif isinstance(params, (list, tuple)):
            if idx >= len(params):
                continue
            text = _text_of(params[idx])
        else:
            continue
        if text is not None and has_real_text(text):
            entries.append({
                "file": fname,
                "path": "%s/%d/parameters/%d" % (path_prefix, i, idx),
                "category": category,
                "original": text,
                "translated": "",
                "status": "pending",
                "note": note_prefix,
            })


def _add(entries, fname, path, category, original, note=""):
    text = _text_of(original)
    if text is not None and has_real_text(text):
        entries.append({
            "file": fname,
            "path": path,
            "category": category,
            "original": text,
            "translated": "",
            "status": "pending",
            "note": note,
        })


def _extract_array_fields(entries, fname, data, rules, include_notes):
    for i, obj in _pairs_of(data):
        if not _is_object_proxy(obj):
            continue
        for field, category, label in rules:
            v = _text_of(_iv(obj, field))
            if v is not None:
                _add(entries, fname, "%d/%s" % (i, field), category, v, "%s %d" % (label, i + 1))
        if include_notes:
            v = _text_of(_iv(obj, "@note"))
            if v:
                _add(entries, fname, "%d/@note" % i, "备注", v, "备注 %d" % (i + 1))


def _extract_system(entries, fname, obj):
    def arr_field(name, category, label):
        arr = _iv(obj, name)
        # N-12：这些字段通常是 Array，但统一用 _pairs_of 兼容 Hash 形态
        for i, v in _pairs_of(arr):
            v = _text_of(v)
            if v is not None:
                _add(entries, fname, "%s/%d" % (name, i), category, v, "%s %d" % (label, i + 1))
    _add(entries, fname, "@game_title", "名称", _iv(obj, "@game_title"), "游戏标题")
    _add(entries, fname, "@currency_unit", "界面术语", _iv(obj, "@currency_unit"), "货币单位")
    arr_field("@elements", "界面术语", "属性")
    arr_field("@skill_types", "界面术语", "技能类型")
    arr_field("@weapon_types", "界面术语", "武器类型")
    arr_field("@armor_types", "界面术语", "防具类型")
    arr_field("@switches", "界面术语", "开关")
    arr_field("@variables", "界面术语", "变量")
    terms = _iv(obj, "@terms")
    if _is_object_proxy(terms):
        for group in ("@basic", "@params", "@commands"):
            arr = _iv(terms, group)
            for i, v in _pairs_of(arr):
                v = _text_of(v)
                if v is not None:
                    _add(entries, fname, "@terms/%s/%d" % (group, i), "界面术语", v,
                         "术语 %s %d" % (group, i + 1))
        msgs = _iv(terms, "@messages")
        if isinstance(msgs, dict):
            for k, v in msgs.items():
                v = _text_of(v)
                if v is not None:
                    _add(entries, fname, "@terms/@messages/%s" % k, "界面术语", v, "界面消息")


def _pairs_of(container):
    """把"像列表的 Ruby 容器"归一化成 ``[(key, value), ...]``。

    ⚠ 2026-09-12 M2b 发现并修复 **N-12**：RPG 数据里同一个字段可能是
    **Array** 也可能是 **Hash**，而 vendored 代码一律当成列表处理：

    * ``RPG::Map#@events`` → Hash（键是事件 id）→ 原代码用 ``enumerate()``
      遍历，而 :meth:`RMDict.__getitem__` 的键是 Fixnum，
      于是 ``enumerate`` 请求下标 0 时抛 ``KeyError: 0``
      （本机 VX Ace 样本上 100% 复现）
    * ``Troops#@pages``、``CommonEvents`` 等 → Array

    本函数统一两种容器：Array 用整数下标当 key，Hash 用真实键当 key。
    调用方拿到的 key 可以直接拼进翻译条目的 ``path``。
    """
    container = _unwrap(container)
    if isinstance(container, dict):
        return list(container.items())
    if isinstance(container, (list, tuple)):
        return list(enumerate(container))
    if type(container).__name__ == "RMArray":
        return list(enumerate(container))
    if type(container).__name__ == "RMDict":
        return list(container.items())
    return []


def _values_of(container):
    """同 :func:`_pairs_of`，只要值（放弃键）。"""
    return [value for _key, value in _pairs_of(container)]


def _pairs_of_values(container):
    """归一化成"可安全迭代的值序列"。

    与 :func:`_values_of` 的区别：本函数**先剥 Ivar 包装**。
    VX Ace 的 ``@list`` / ``@pages`` / ``@parameters`` 常常是
    ``Ivar(Array(...))`` 形状，不剥的话迭代会得到空序列。
    """
    return _values_of(_unwrap(container))


def extract(data_dir, opts):
    entries = []
    for fname in sorted(os.listdir(data_dir)):
        if not (fname.endswith(".rvdata2") or fname.endswith(".rxdata")):
            continue
        full = os.path.join(data_dir, fname)
        try:
            with open(full, "rb") as f:
                data = marshal.loads(f.read())
        except Exception:
            continue
        base = fname.rsplit(".", 1)[0]
        if base == "System":
            if _is_object_proxy(data):
                _extract_system(entries, fname, data)
        elif base == "Actors":
            _extract_array_fields(entries, fname, data,
                                  (("@name", "名称", "角色"), ("@nickname", "名称", "角色昵称"),
                                   ("@profile", "描述", "角色简介")), opts.include_notes)
        elif base == "Classes":
            _extract_array_fields(entries, fname, data, (("@name", "名称", "职业"),), opts.include_notes)
        elif base == "Skills":
            _extract_array_fields(entries, fname, data,
                                  (("@name", "名称", "技能"), ("@message1", "战斗信息", "技能信息"),
                                   ("@message2", "战斗信息", "技能信息"), ("@message3", "战斗信息", "技能信息"),
                                   ("@message4", "战斗信息", "技能信息"), ("@description", "描述", "技能描述")),
                                  opts.include_notes)
        elif base == "Items":
            _extract_array_fields(entries, fname, data,
                                  (("@name", "名称", "物品"), ("@description", "描述", "物品描述")),
                                  opts.include_notes)
        elif base == "Weapons":
            _extract_array_fields(entries, fname, data,
                                  (("@name", "名称", "武器"), ("@description", "描述", "武器描述")),
                                  opts.include_notes)
        elif base == "Armors":
            _extract_array_fields(entries, fname, data,
                                  (("@name", "名称", "防具"), ("@description", "描述", "防具描述")),
                                  opts.include_notes)
        elif base == "Enemies":
            _extract_array_fields(entries, fname, data, (("@name", "名称", "敌人"),), opts.include_notes)
        elif base == "States":
            _extract_array_fields(entries, fname, data,
                                  (("@name", "名称", "状态"), ("@message1", "战斗信息", "状态信息"),
                                   ("@message2", "战斗信息", "状态信息"), ("@message3", "战斗信息", "状态信息"),
                                   ("@message4", "战斗信息", "状态信息")), opts.include_notes)
        elif base == "Troops":
            _extract_array_fields(entries, fname, data, (("@name", "名称", "队伍"),), opts.include_notes)
            for i, troop in _pairs_of(data):
                if not _is_object_proxy(troop):
                    continue
                for pg_i, page in _pairs_of(_iv(troop, "@pages")):
                    if _is_object_proxy(page):
                        _walk_event_list(entries, fname, _iv(page, "@list"),
                                         "%d/@pages/%d/@list" % (i, pg_i),
                                         "队伍 %d 页面 %d" % (i + 1, pg_i + 1), opts.include_comments)
        elif base == "CommonEvents":
            for i, obj in _pairs_of(data):
                if not _is_object_proxy(obj):
                    continue
                _add(entries, fname, "%d/@name" % i, "名称", _iv(obj, "@name"), "公共事件 %d" % (i + 1))
                _walk_event_list(entries, fname, _iv(obj, "@list"), "%d/@list" % i,
                                 "公共事件 %d" % (i + 1), opts.include_comments)
        elif base == "MapInfos":
            for k, obj in _pairs_of(data):
                if _is_object_proxy(obj):
                    _add(entries, fname, "%s/@name" % k, "地图名", _iv(obj, "@name"), "地图 %s" % k)
        elif base.startswith("Map") and base[3:].isdigit():
            map_id = base[3:]
            _add(entries, fname, "@display_name", "地图名", _iv(data, "@display_name"), "地图 %s" % map_id)
            # N-12：@events 是 Hash（键为事件 id），必须按 pairs 遍历而不是当列表
            for ev_i, ev in _pairs_of(_iv(data, "@events")):
                if not _is_object_proxy(ev):
                    continue
                ev_name = _text_of(_iv(ev, "@name"))
                if opts.include_event_names and ev_name is not None:
                    _add(entries, fname, "@events/%d/@name" % ev_i, "事件名", ev_name,
                         "地图 %s 事件 %d" % (map_id, ev_i + 1))
                for pg_i, page in _pairs_of(_iv(ev, "@pages")):
                    if _is_object_proxy(page):
                        _walk_event_list(entries, fname, _iv(page, "@list"),
                                         "@events/%d/@pages/%d/@list" % (ev_i, pg_i),
                                         "地图 %s 事件 %d" % (map_id, ev_i + 1), opts.include_comments)
    return entries


def _unwrap(value):
    """剥掉 RMIvar 包装，返回内层值。

    注意 `value_layer.RMIvar.value` 每次访问都返回**新的代理实例**
    （它只是把同一个 Node 重新包一次），因此这里用 while 循环是安全的：
    内层不再是 RMIvar 时自然退出。原编码信息由代理携带（见 value_layer 说明）。
    """
    seen = 0
    while _is_ivar_proxy(value):
        value = value.value
        seen += 1
        if seen > 16:      # 防御：异常数据造成的自引用
            break
    return value


def _navigate(root, path):
    """Return (parent, last segment, is_rmivar) for a path.

    ⚠ 2026-09-12 M2a 修复 **N-07**：多值条目（402 显示选择项的
    ``parameters/0/1`` 这类"列表里的列表"路径）原先落不下去 ——
    ``_navigate`` 对 list 用 ``int(seg)``，段不是数字时抛 ``ValueError``，
    被 ``apply_to_files`` 静默跳过（不写坏文件，但译文丢失）。

    现在分两层处理：
    * list + 整数段 → 正常下标；
    * list + 非整数段 → 抛 ``KeyError``（**明确的"这条不支持"**，
      而不是让 ``int()`` 的 ValueError 混在其它错误里）；
    * dict → 先试原样字符串键，再试整数键（RPG 数据的 Hash 键常是 Fixnum）；
    * 其它类型（含 str）→ 抛 ``KeyError``。
    """
    segs = path.split("/")
    cur = root
    for seg in segs[:-1]:
        cur = _step(cur, seg, path)
    last = segs[-1]
    if _is_string_proxy(cur):
        # 字符串上取"下标"会取到字符而不是元素 —— 明确拒绝，避免写错位置
        raise KeyError(path)
    if _is_object_proxy(cur):
        return cur, _rmobject_key(cur, last), False
    if isinstance(cur, (list, tuple)) or _is_array_proxy(cur):
        # 最后一段也要校验：非整数段说明这条路径不被支持（N-07 的明确失败）
        return cur, _index(last, path), False
    return cur, last, False


def _rmobject_key(cur, seg):
    """在 RMObject 的 ivars 里找出 ``seg`` 对应的**真实键名**。

    ⚠ 两份 marshal 实现的实例变量键名不同，必须都支持：
    * 文档模型（``doc_model``）：键是 Symbol **节点**，那条路径由
      ``core/formats/rgss_save.py`` 直接按符号名比较，不走本函数。
    * 值模型（``value_model``，本模块用的就是它）：键是普通 ``str``，
      既可能是 ``'@list'``（与 Ruby 源码写法一致），也可能是 ``'list'``
      （调用方省掉了 ``@``）。

    M2a 实测：原实现只试 ``'@' + seg``，于是用无前缀键构造的对象一律
    ``KeyError`` → 整批写回被静默跳过。现在两种都试。
    """
    if seg.startswith("@"):
        candidates = (seg, seg[1:])
    else:
        candidates = ("@" + seg, seg)
    for name in candidates:
        if name in cur.ivars:
            return name
    raise KeyError(seg)


def _is_ivar_proxy(node):
    """是否是值层的 ``Ivar`` 代理（``RMIvar``）。"""
    return type(node).__name__ == "RMIvar"


def _is_object_proxy(node):
    """是否是值层的 Ruby 对象代理（``RMObject``：有 ``class_name`` 与 ``ivars``）。"""
    return hasattr(node, "ivars") and hasattr(node, "class_name")


def _is_string_proxy(node):
    """是否是值层的字符串/符号代理（``RMStr`` / ``RMSymbol``）。

    这两种在写回时语义不同于数组：**不能**对它们取整数下标
    （那会取到字符而不是元素，把 402 选择项的路径写错位置）。
    """
    return type(node).__name__ in ("RMStr", "RMSymbol")


def _rmobject_key(cur, seg):
    """在 RMObject 的 ivars 里找出 ``seg`` 对应的**真实键名**。

    M2b 之前有两份 marshal 实现，实例变量键名约定不同（一份是带 ``@`` 的
    Symbol 节点、一份是普通 ``str`` 且可省 ``@``）。收敛到 ``value_layer``
    之后，``_IvarMap`` 已经自带"原样 / 加 @ / 去 @"三级容忍，因此这里直接
    委派给它即可 —— 这也正是收敛带来的简化。
    """
    ivars = cur.ivars
    for candidate in _key_candidates(seg):
        if candidate in ivars:
            return candidate
    raise KeyError(seg)


def _key_candidates(seg):
    if seg.startswith("@"):
        return (seg, seg[1:])
    return ("@" + seg, seg)


def _step(cur, seg, path):
    """走一层路径。

    ⚠ M2b 注意：``marshal`` 现在是 ``core.marshal.value_layer``，
    ``wrap()`` 把 ``Array`` 包成 ``RMArray`` 代理、``ObjectNode`` 包成
    ``RMObject`` 代理、字符串包成 ``RMStr`` 代理。因此判据改为**鸭子类型**：
    认"有 class_name + ivars"的当对象，认"RMArray"的当数组，字符串代理则
    明确排除（否则会给它取整数下标）。
    """
    if _is_string_proxy(cur):
        raise KeyError(path)
    if isinstance(cur, (list, tuple)) or _is_array_proxy(cur):
        return cur[_index(seg, path)]
    if _is_object_proxy(cur):
        return cur.ivars[_rmobject_key(cur, seg)]
    if isinstance(cur, dict):
        if seg in cur:
            return cur[seg]
        return cur[_index(seg, path)]
    raise KeyError(path)


def _is_array_proxy(node):
    """该对象是否是值层的数组代理（``RMArray``）。"""
    return type(node).__name__ == "RMArray"


def _index(seg, path):
    """把路径段转成列表下标；不是整数就抛 KeyError（明确不支持）。"""
    try:
        return int(seg)
    except (TypeError, ValueError):
        raise KeyError("路径段 %r 不是整数下标（path=%s）" % (seg, path))


def _set_value(parent, key, value, original):
    """写回**字符串**译文，跟随原值的编码。

    ⚠ 只想改数字/布尔时请用 :func:`_set_scalar` —— 本函数会把值编码成
    字符串节点（``Fixnum(888888)`` 会被写成 ``"888888"`` 字符串），
    因为它的调用方（翻译链路）改的永远是文本。

    ``original`` 参数保留在签名里（调用方一直传），留给后续的
    "陈旧性校验"（数据变了就不盲写）。当前行为与原实现一致：只按 path 定位后写入。

    编码处理（M2b 起由 ``value_layer`` 支撑）
    ----------------------------------------
    原实现用 ``marshal.RMStr(value, enc=enc)`` 构造带编码的字符串。
    收敛到 ``value_layer`` 后，字符串的编码来自它的 ``Ivar`` 包装
    （``@encoding = :Windows_31J`` 之类），代理会把它带在 ``.enc`` 上。
    因此这里：

    * 原值是字符串代理 → **直接用它的 ``.enc``**，把新文本按该编码写回；
    * 其余情况 → 回落 utf-8。

    这一步不能省：XP 文本是 cp932、VX Ace 是 UTF-8。若一律按 UTF-8 写回，
    cp932 的旧文本会被重新编码，字节数变化 —— 游戏读到的字符串长度可能不对。
    """
    enc = _encoding_of(_current_value(parent, key))
    node = _string_node(value, enc)
    _assign_value(parent, key, node)


def _current_value(parent, key):
    """取 ``parent[key]`` 的当前值（读不到返回 None，不抛）。"""
    if _is_object_proxy(parent):
        return parent.ivars.get(key)
    if isinstance(parent, (list, tuple)) or _is_array_proxy(parent):
        index = _index(key, "current_value")
        return parent[index] if -len(parent) <= index < len(parent) else None
    if isinstance(parent, dict):
        if key in parent:
            return parent[key]
        index = _index(key, "current_value")
        return parent.get(index)
    raise KeyError("无法在不支持的类型上取值：%s" % type(parent).__name__)


def _assign_value(parent, key, node):
    """把节点写回 ``parent[key]``，兼容 RMObject / 数组代理 / dict。"""
    if _is_object_proxy(parent):
        parent.ivars[key] = node
        return
    if isinstance(parent, (list, tuple)) or _is_array_proxy(parent):
        parent[_index(key, "assign_value")] = node
        return
    if isinstance(parent, dict):
        if key in parent:
            parent[key] = node
        else:
            parent[_index(key, "assign_value")] = node
        return
    raise KeyError("无法在不支持的类型上写值：%s" % type(parent).__name__)


def _set_scalar(parent, key, value):
    """写回**数字 / 布尔 / 字符串**，并跟随原值的类型。

    为什么需要它（M3b 新增）
    ------------------------
    "修改游戏数据"要改的是开关（bool）、变量（int）、价格/攻击力之类（int），
    而 :func:`_set_value` 只写字符串节点。直接把数字塞进去会产生
    ``Fixnum(888888)`` → ``String("888888")`` 的类型漂移：游戏里读到的类型变了，
    轻则显示异常，重则脚本报错。

    取值规则：

    * 原值是 ``Fixnum`` / ``Bignum`` → 写数字（布尔按 0/1）；
    * 原值是 ``BoolNode`` → 写布尔；
    * 原值是字符串 → **转成文本**（保持它声明的编码）；
    * 原值读不到 → 按新值的 Python 类型决定。

    ``Float`` 节点（Ruby 的浮点，占 8 字节）暂不支持 —— 真实游戏数据里
    开关/变量/属性都是整数，遇到浮点时明确报错比静默写坏好。
    """
    old = _current_value(parent, key)
    inner = _unwrap(old)

    if isinstance(inner, _doc_model.Float):
        raise TypeError("暂不支持改写浮点字段：%s（原值 %r）" % (key, old))

    if isinstance(inner, _doc_model.BoolNode):
        node = _doc_model.BoolNode(bool(value))
    elif value is None:
        node = _doc_model.NilNode()
    elif isinstance(value, bool):
        node = _doc_model.BoolNode(value)
    elif isinstance(value, int):
        node = _doc_model.Fixnum(value)
    elif isinstance(value, float):
        node = _doc_model.Fixnum(int(value))
    elif isinstance(inner, (_doc_model.Fixnum, _doc_model.Bignum)):
        # 原值是数字但新值是文本（例如把"数量"改成"很多"）—— 明确拒绝，
        # 免得把数字字段写成字符串让游戏读崩
        raise TypeError("字段 %s 原本是数字，不能写入文本 %r" % (key, value))
    else:
        return _set_value(parent, key, value, None)

    # 原值被 Ivar 包装（带 encoding 标记）时，要**改内层**而不是替换外层，
    # 否则会丢掉包装（RGSS 里开关数组的元素就常带包装）。
    # ``RMIvar.value`` 的 setter 接受节点，内部会 unwrap_to_node 并标脏。
    if _is_ivar_proxy(old):
        old.value = node
        return
    _assign_value(parent, key, marshal.wrap(node))


def _encoding_of(node):
    """取原值声明的编码（没有则 None，由调用方回落 utf-8）。"""
    if node is None:
        return None
    enc = getattr(node, "enc", None)
    if enc:
        return enc
    inner = _unwrap(node)
    return getattr(inner, "enc", None)


def _string_node(text, enc):
    """构造一个按指定编码存放的字符串节点（值层代理可直接赋给 ivars）。

    为什么不用 ``value_layer.unwrap_to_node(str)``：那个一律按 UTF-8 编码，
    而这里必须**跟随原编码**（XP 的 cp932 文本重新按 UTF-8 写回会变长）。
    """
    return marshal.wrap(_doc_model.String(str(text).encode(enc or "utf-8")))


def _assign_string(ivar_proxy, text, enc):
    """在 ``Ivar`` 代理上原地改内层字符串（保留 Ivar 包装，含 encoding 标记）。"""
    inner = ivar_proxy.value
    if hasattr(inner, "value"):
        inner.value = text
        return
    ivar_proxy.value = _string_node(text, enc)


def _entry_get(entry, key, default=None):
    """从条目取字段（兼容 dict 与对象两种形态）。"""
    if isinstance(entry, dict):
        return entry.get(key, default)
    return getattr(entry, key, default)


def _entry_has(entry, key):
    """条目里是否**存在**该字段（区别于"值是否为真"）。"""
    if isinstance(entry, dict):
        return key in entry
    return hasattr(entry, key)


def _entry_ready(entry):
    """条目是否可写回：状态为 translated，且**有** translated 字段。

    ⚠ **M3b 修复**：原判据是 ``bool(translated)``，于是
    ``translated=0``（把价格改成 0）、``translated=False``（关掉一个开关）
    都被当成"没有译文"而**静默丢弃** —— 界面看起来"保存成功"，
    游戏里却没变。现在改成"字段存在且不是 None"。

    翻译链路不受影响：它的条目要么 ``status="pending"``（跳过），
    要么有非空译文；空译文本来就该跳过。
    """
    if _entry_get(entry, "status") != "translated":
        return False
    if not _entry_has(entry, "translated"):
        return False
    return _entry_get(entry, "translated") is not None


def _same_value(a, b):
    """``expect`` 比较：``"3"``/``3``、``True``/``1`` 都视为相同。"""
    if isinstance(a, bool) or isinstance(b, bool):
        return (1 if a else 0) == (1 if b else 0)
    try:
        return int(a) == int(b)
    except (TypeError, ValueError):
        return str(a) == str(b)


def _plain(value):
    """把节点/代理转成普通 Python 值（供 ``expect`` 比较与界面展示）。

    只处理基本类型：文本走 :func:`_text_of`（它会剥编码包装），
    数字/布尔取原生值，其余返回 ``None``（调用方按"不参与比较"处理）。
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return value
    text = _text_of(value)
    if text is not None:
        return text
    for attr in ("value", "to_py"):
        try:
            got = getattr(value, attr)
        except Exception:
            continue
        if callable(got):
            try:
                got = got()
            except Exception:
                continue
        if isinstance(got, (bool, int, float, str)):
            return got
    return None


def apply_to_files(game_info, entries_by_file, progress=None):
    """把条目写回 rvdata2 / rxdata。

    两类条目共用本函数（与 ``mv_mz_data.apply_to_files`` 对称）：

    * **翻译**：``translated`` 是译文文本，按 ``_set_value`` 跟随原编码写入；
    * **游戏数据修改**（M3b）：条目带 ``kind``（``int``/``bool``/``text``），
      走 :func:`_set_scalar` 按原值类型写入（数字保持数字）。

    ``expect``（可选）：带"我以为的原值"，只有当前值一致时才写 —— 数据在
    别处被改过时宁可跳过（B-13 的同类防线）。

    ⚠ 2026-09-12 M2a 修复 **B-02**：原实现 ``open(full, "wb")`` 直接截断重写，
    写一半被中断就留下半写的存档/数据文件，游戏直接损坏。现走
    :mod:`core.safety.atomic`（临时文件 + fsync + ``os.replace``）。

    另外把异常捕获放宽到 ``TypeError``：多值路径（如 402 选择项）在某些形状下
    会走到非整数段，原实现只捕获 ``(KeyError, ValueError, IndexError)``，
    遇到 ``TypeError`` 会**中断整个写回**。现在统一按"这条跳过"处理，
    并在返回值里给出计数，便于发现"没写进去"而不是静默成功。
    """
    stats = {"files": 0, "entries": 0, "skipped": 0}
    data_dir = game_info["data_dir"]
    for fname, entries in entries_by_file.items():
        if not (fname.endswith(".rvdata2") or fname.endswith(".rxdata")):
            continue
        full = os.path.join(data_dir, fname)
        if not os.path.isfile(full):
            continue
        try:
            with open(full, "rb") as f:
                root = marshal.loads(f.read())
        except Exception:
            continue
        changed = False
        for entry in entries:
            if not _entry_ready(entry):
                continue
            path = _entry_get(entry, "path")
            value = _entry_get(entry, "translated")
            try:
                parent, key, _ = _navigate(root, path)
            except (KeyError, ValueError, IndexError, TypeError):
                stats["skipped"] += 1
                continue
            if _entry_has(entry, "expect"):
                try:
                    current = _current_value(parent, key)
                except (KeyError, ValueError, TypeError):
                    current = None
                if not _same_value(_plain(current), _entry_get(entry, "expect")):
                    stats["skipped"] += 1
                    continue
            try:
                if _entry_has(entry, "kind"):
                    _set_scalar(parent, key, value)
                else:
                    _set_value(parent, key, value, _entry_get(entry, "original"))
            except (KeyError, ValueError, IndexError, TypeError):
                stats["skipped"] += 1
                continue
            changed = True
            stats["entries"] += 1
        if changed:
            atomic_write_bytes(full, marshal.dumps(root))
            stats["files"] += 1
        if progress:
            progress(fname)
    return stats

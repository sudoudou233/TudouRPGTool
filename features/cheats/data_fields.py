# -*- coding: utf-8 -*-
"""游戏数据表里"可编辑字段"的唯一规则表（MV/MZ 与 RGSS 共用一份）。

@feature  cheats
@layer    features
@public   MV_FIELD_RULES, RGSS_FIELD_RULES, rules_for_file, build_entries,
          set_in_data, KIND_OF
@depends  core.formats.mv_mz_data, core.formats.rgss_data
@tested   tests/features/cheats/test_routes.py
@footprint docs/FEATURES.md#cheats

为什么要单独抽一份规则表
------------------------
翻译功能已经有一份"哪些字段是文本"的规则（`mv_mz_data._extract_db` 的
`field_rules` / `rgss_data.extract` 的分支）。修改功能要改的是**数字与开关**
（价格、攻击力、初始等级、开关初值…），与文本规则**不重叠但同构**。

抽成一张显式表的好处：

* 页面的"可编辑字段"清单与实际写回用的 path **由同一份数据生成**，
  不会出现"界面上有这一栏、写回却定位不到"（这类不一致在 M1 的
  UI 原型里出现过）；
* 新增一个可改字段 = 在表里加一行，而不是散落改三处；
* 表本身可以被测试逐个断言"能读出来、能写回去、类型不变"。

写回**复用现成的两条编排**（不新写第三条写回路径）：

* MV/MZ → :func:`core.formats.mv_mz_data.apply_to_files`（JSON + 加密包装）
* RGSS  → :func:`core.formats.rgss_data.apply_to_files`（Marshal + 编码跟随）

两条都走 ``core/safety/atomic``，因此"未修改的内容字节原样保留"自动成立。
"""

from __future__ import annotations

import os

from core.formats import mv_mz_data
from core.formats import rgss_data

#: 字段类型 → 显示名。决定 HTML 控件与写回时的值转换。
KIND_OF = {
    "int": "整数",
    "bool": "开关",
    "text": "文本",
}

#: MV/MZ：``data/<文件名>`` → ``[(字段路径模板, 显示名, 类型)]``
#:
#: 路径模板里的 ``%d`` 是**数组下标**（与 ``mv_mz_data.apply_to_files`` 的
#: ``a/b/0/c`` 约定一致；下标 0 是 MV/MZ 的 nil 占位）。
#:
#: ⚠ 名称字段（``name`` / ``@name``）也在表里：它既是"这条记录是什么"的
#: 标注来源，也让改名与改数值走**同一条**路径 —— 否则"读名字"与"写名字"
#: 会变成两套坐标，很容易只改对一边。
MV_FIELD_RULES = {
    "Items.json": (
        ("%d/name", "名称", "text"),
        ("%d/description", "描述", "text"),
        ("%d/price", "价格", "int"),
        ("%d/occasion", "使用场合", "int"),
        ("%d/itypeId", "道具类型", "int"),
        ("%d/consumable", "消耗品", "bool"),
    ),
    "Weapons.json": (
        ("%d/name", "名称", "text"),
        ("%d/description", "描述", "text"),
        ("%d/price", "价格", "int"),
        ("%d/params/0", "攻击力", "int"),
        ("%d/params/1", "防御力", "int"),
        ("%d/params/2", "魔攻", "int"),
        ("%d/params/3", "魔防", "int"),
        ("%d/params/4", "敏捷", "int"),
        ("%d/params/5", "幸运", "int"),
    ),
    "Armors.json": (
        ("%d/name", "名称", "text"),
        ("%d/description", "描述", "text"),
        ("%d/price", "价格", "int"),
        ("%d/etypeId", "装备类型", "int"),
        ("%d/params/0", "防御力", "int"),
        ("%d/params/1", "魔防", "int"),
    ),
    "Actors.json": (
        ("%d/name", "名称", "text"),
        ("%d/nickname", "昵称", "text"),
        ("%d/profile", "简介", "text"),
        ("%d/initialLevel", "初始等级", "int"),
        ("%d/maxLevel", "等级上限", "int"),
    ),
    "Classes.json": (
        ("%d/name", "名称", "text"),
        ("%d/params/0/0", "初始最大HP", "int"),
        ("%d/params/1/0", "初始最大MP", "int"),
        ("%d/params/2/0", "初始攻击", "int"),
        ("%d/params/3/0", "初始防御", "int"),
    ),
    "Enemies.json": (
        ("%d/name", "名称", "text"),
        ("%d/params/0", "最大HP", "int"),
        ("%d/params/1", "最大MP", "int"),
        ("%d/params/2", "攻击", "int"),
        ("%d/params/3", "防御", "int"),
        ("%d/exp", "经验值", "int"),
        ("%d/gold", "掉落金币", "int"),
    ),
    "Skills.json": (
        ("%d/name", "名称", "text"),
        ("%d/description", "描述", "text"),
        ("%d/mpCost", "MP 消耗", "int"),
        ("%d/tpCost", "TP 消耗", "int"),
        ("%d/scope", "作用范围", "int"),
        ("%d/occasion", "使用场合", "int"),
    ),
    "States.json": (
        ("%d/name", "名称", "text"),
        ("%d/priority", "优先级", "int"),
        ("%d/restriction", "行动限制", "int"),
    ),
    "System.json": (
        ("gameTitle", "游戏标题", "text"),
        ("currencyUnit", "货币单位", "text"),
        ("optDisplayTp", "显示 TP", "bool"),
        ("optExtraExp", "额外经验", "bool"),
        ("optSideView", "侧视战斗", "bool"),
    ),
}

#: RGSS（XP / VX / VX Ace）：``Data/<文件名>`` → 规则表
#:
#: 路径用 RGSS 约定（``@`` 前缀 + ``/`` 分段），与
#: ``rgss_data._navigate`` 一致。
RGSS_FIELD_RULES = {
    "Items.rvdata2": (
        ("%d/@name", "名称", "text"),
        ("%d/@description", "描述", "text"),
        ("%d/@price", "价格", "int"),
        ("%d/@consumable", "消耗品", "bool"),
        ("%d/@occasion", "使用场合", "int"),
    ),
    "Weapons.rvdata2": (
        ("%d/@name", "名称", "text"),
        ("%d/@description", "描述", "text"),
        ("%d/@price", "价格", "int"),
        ("%d/@params/0", "攻击力", "int"),
        ("%d/@params/1", "防御力", "int"),
        ("%d/@params/2", "魔攻", "int"),
        ("%d/@params/3", "魔防", "int"),
        ("%d/@params/4", "敏捷", "int"),
        ("%d/@params/5", "幸运", "int"),
    ),
    "Armors.rvdata2": (
        ("%d/@name", "名称", "text"),
        ("%d/@description", "描述", "text"),
        ("%d/@price", "价格", "int"),
        ("%d/@params/0", "防御力", "int"),
        ("%d/@params/1", "魔防", "int"),
        ("%d/@params/2", "回避", "int"),
    ),
    "Actors.rvdata2": (
        ("%d/@name", "名称", "text"),
        ("%d/@nickname", "昵称", "text"),
        ("%d/@description", "简介", "text"),
        ("%d/@initial_level", "初始等级", "int"),
        ("%d/@final_level", "等级上限", "int"),
    ),
    "Classes.rvdata2": (
        ("%d/@name", "名称", "text"),
        ("%d/@params/0/0", "初始最大HP", "int"),
        ("%d/@params/1/0", "初始最大MP", "int"),
        ("%d/@params/2/0", "初始攻击", "int"),
        ("%d/@params/3/0", "初始防御", "int"),
    ),
    "Enemies.rvdata2": (
        ("%d/@name", "名称", "text"),
        ("%d/@params/0", "最大HP", "int"),
        ("%d/@params/1", "最大MP", "int"),
        ("%d/@params/2", "攻击", "int"),
        ("%d/@params/3", "防御", "int"),
        ("%d/@exp", "经验值", "int"),
        ("%d/@gold", "掉落金币", "int"),
    ),
    "Skills.rvdata2": (
        ("%d/@name", "名称", "text"),
        ("%d/@description", "描述", "text"),
        ("%d/@mp_cost", "MP 消耗", "int"),
        ("%d/@tp_cost", "TP 消耗", "int"),
        ("%d/@scope", "作用范围", "int"),
        ("%d/@occasion", "使用场合", "int"),
    ),
    "States.rvdata2": (
        ("%d/@name", "名称", "text"),
        ("%d/@priority", "优先级", "int"),
        ("%d/@restriction", "行动限制", "int"),
    ),
}

#: MGBA 名称字段（用于给条目加"这是哪个道具"的可读标注）
_NAME_FIELD = {"mv": "name", "rgss": "@name"}


def rules_for_file(engine, fname):
    """按引擎与文件名取规则表；没有规则返回 ``()``。"""
    table = MV_FIELD_RULES if engine in ("mv", "mz") else RGSS_FIELD_RULES
    if fname in table:
        return table[fname]
    # RGSS 的表用 .rvdata2 作键；XP 是 .rxdata / VX 是 .rvdata，统一归一化
    if engine not in ("mv", "mz"):
        base = fname.rsplit(".", 1)[0]
        for key, rules in table.items():
            if key.rsplit(".", 1)[0] == base:
                return rules
    return ()


def _candidates(engine, fname):
    """返回该逻辑文件的可能文件名（RGSS 三种扩展名都试）。"""
    if engine in ("mv", "mz"):
        return (fname,)
    base = fname.rsplit(".", 1)[0]
    return ("%s.rvdata2" % base, "%s.rvdata" % base, "%s.rxdata" % base)


def _read_file(engine, data_dir, fname):
    """读数据文件为 Python 结构；读不到返回 ``None``。

    MV/MZ 走 :func:`core.formats.mv_mz_data._load_data_file`（含加密包装与
    BOM 处理）；RGSS 走 ``doc_model`` 解析成节点树，再用 ``to_plain()``
    转成普通结构 —— **只用于展示**，写回仍走节点树，不会因此丢字节保真。
    """
    for name in _candidates(engine, fname):
        path = os.path.join(data_dir, name)
        if not os.path.isfile(path):
            continue
        if engine in ("mv", "mz"):
            data, _wrapped, _header = mv_mz_data._load_data_file(path, name)
            return name, data
        from core.marshal import doc_model as D
        with open(path, "rb") as f:
            raw = f.read()
        tree = D.loads(raw)
        return name, _to_plain(tree)
    return None, None


def _to_plain(node):
    """把 doc_model 节点树转成普通 Python 结构（展示用）。

    刻意**不**复用 ``value_layer.to_plain``：那条路要先包代理，对只读展示是浪费。
    这里只处理基本类型 + 数组 + 对象（ivars 变成 ``@名`` 键的 dict），
    与 RGSS 的路径约定（``@price``）一致。
    """
    from core.marshal import doc_model as D

    if node is None or isinstance(node, D.NilNode):
        return None
    if isinstance(node, D.BoolNode):
        return bool(node.value)
    if isinstance(node, (D.Fixnum, D.Bignum)):
        return node.value
    if isinstance(node, D.Float):
        return None            # 浮点不参与编辑（见 rgss_data._set_scalar）
    if isinstance(node, D.String):
        return node.value.decode("utf-8", "replace")
    if isinstance(node, D.Symbol):
        return node.name.decode("utf-8", "replace")
    if isinstance(node, D.Array):
        return [_to_plain(x) for x in node.items]
    if isinstance(node, D.ObjectNode):
        out = {}
        for key, value in node.ivars:
            out[_sym(key)] = _to_plain(value)
        return out
    if isinstance(node, D.Ivar):
        return _to_plain(node.inner)
    return None


def _sym(node):
    """取符号节点的名字（``@price`` 这种）。"""
    from core.marshal import doc_model as D
    if isinstance(node, D.Symbol):
        return node.name.decode("utf-8", "replace")
    if isinstance(node, D.SymLink):
        return D._sym_name(node)
    return str(node)


def _dig(data, path):
    """按 ``a/b/0/c`` 取值；任一段缺失返回 ``None``。"""
    cur = data
    for seg in path.split("/"):
        if isinstance(cur, list):
            try:
                cur = cur[int(seg)]
            except (ValueError, IndexError):
                return None
        elif isinstance(cur, dict):
            if seg in cur:
                cur = cur[seg]
            elif seg.lstrip("-").isdigit() and int(seg) in cur:
                cur = cur[int(seg)]
            else:
                return None
        else:
            return None
    return cur


#: 显示时可读的字段（上限，避免几万条全塞给浏览器）
MAX_ENTRIES_PER_SCAN = 4000


def scan_data(data_dir, engine, files=None, limit=MAX_ENTRIES_PER_SCAN):
    """扫描可编辑字段，返回 ``[{file, path, label, kind, value, name}, ...]``。

    ``path`` 是**最终路径**（``%d`` 已替换成真实下标），可以直接交给
    :func:`set_in_data`。
    """
    out = []
    table = MV_FIELD_RULES if engine in ("mv", "mz") else RGSS_FIELD_RULES
    for fname in sorted(files or table.keys()):
        rules = rules_for_file(engine, fname)
        if not rules:
            continue
        real_name, data = _read_file(engine, data_dir, fname)
        if data is None:
            continue
        name_field = _NAME_FIELD["mv" if engine in ("mv", "mz") else "rgss"]
        for index in range(len(data) if isinstance(data, list) else 0):
            row = data[index]
            if not isinstance(row, dict):
                continue
            label_row = row.get(name_field)
            if label_row is None:
                label_row = row.get(name_field.lstrip("@"))
            for template, label, kind in rules:
                path = template % index
                value = _dig(data, path)
                if value is None:
                    continue
                out.append({
                    "file": real_name,
                    "path": path,
                    "label": label,
                    "kind": kind,
                    "value": value,
                    "name": label_row if isinstance(label_row, str) else "",
                })
                if len(out) >= limit:
                    return out
        # System.json 这类是对象而不是数组：规则里没有 %d
        if not isinstance(data, list) and isinstance(data, dict):
            for template, label, kind in rules:
                if "%d" in template:
                    continue
                value = _dig(data, template)
                if value is None:
                    continue
                out.append({"file": real_name, "path": template, "label": label,
                            "kind": kind, "value": value, "name": ""})
                if len(out) >= limit:
                    return out
    return out


def build_entries(edits, engine):
    """把界面提交的改动转成 ``apply_to_files`` 要的 ``{文件: [条目]}``。

    ``edits`` 是 ``[{file, path, value, original, kind}, ...]``。

    **陈旧性校验（B-13）**：带 ``original`` 且与当前值不一致的改动会被拒绝 ——
    这是"按 path 盲写"的防线：如果用户在别处改过同一字段，或路径指到了
    另一个对象，这里就会拦住，而不是安静地改错数据。
    """
    by_file = {}
    for edit in edits or ():
        fname = str(edit.get("file") or "").strip()
        path = str(edit.get("path") or "").strip()
        if not fname or not path:
            continue
        kind = edit.get("kind") or "int"
        value = _coerce(edit.get("value"), kind)
        entry = {
            "file": fname,
            "path": path,
            "category": edit.get("label") or "游戏数据",
            "original": str(edit.get("original", "")),
            "translated": value,
            "status": "translated",
            "kind": kind,
        }
        if edit.get("original") is not None:
            entry["expect"] = edit.get("original")
        elif edit.get("expect") is not None:
            entry["expect"] = edit.get("expect")
        by_file.setdefault(fname, []).append(entry)
    return by_file


def _coerce(value, kind):
    """把界面传来的值转成正确类型（前端永远是字符串或 JSON 值）。"""
    if kind == "bool":
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on", "是")
        return bool(value)
    if kind == "text":
        return "" if value is None else str(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return 0
        return int(float(text)) if ("." in text or "e" in text.lower()) else int(text)
    return int(value or 0)


def set_in_data(game_info, edits):
    """把改动写回游戏数据文件。返回 ``apply_to_files`` 的统计。

    ⚠ 调用方**必须**先备份（``core/safety/backup.backup_files``）——
    本函数只负责写，不做备份与确认，那是路由层的职责（硬约束 §4.2）。
    """
    if not edits:
        return {"files": 0, "entries": 0}
    engine = game_info.get("engine")
    by_file = build_entries(edits, engine)
    if engine in ("mv", "mz"):
        return mv_mz_data.apply_to_files(game_info, by_file)
    return rgss_data.apply_to_files(game_info, by_file)


def verify_original(game_info, edits):
    """校验"我以为的原值"：返回 ``[{file, path, expect, actual}, ...]``。

    空列表 = 全部一致，可以安全写回。非空说明界面看到的值**已经过期**
    （别人改过、或会话是上次启动留下的），这时应该中止并让用户重新读取。

    ⚠ 字段名有两种叫法，都要接受（M3b 实测踩到）：界面/路由用的是
    ``original``（与翻译功能的条目字段同名），而写回层
    （``mv_mz_data.apply_to_files`` / ``rgss_data.apply_to_files``）用的
    是比较用的 ``expect``。**只认一个的话，另一边的校验会静默失效** ——
    这正是"陈旧性校验被绕过"最隐蔽的形态。
    """
    mismatched = []
    by_file = {}
    for edit in edits or ():
        by_file.setdefault(edit.get("file"), []).append(edit)
    engine = game_info.get("engine")
    data_dir = game_info.get("data_dir")
    for fname, items in by_file.items():
        if not fname:
            continue
        real_name, data = _read_file(engine, data_dir, fname)
        if data is None:
            continue
        for edit in items:
            expected = expected_value(edit)
            if expected is None:
                continue
            actual = _dig(data, str(edit.get("path")))
            if _norm(actual) != _norm(expected):
                mismatched.append({
                    "file": real_name or fname,
                    "path": edit.get("path"),
                    "expect": expected,
                    "actual": actual,
                })
    return mismatched


def expected_value(edit):
    """取"我以为的原值"：优先 ``original``，兼容 ``expect``。"""
    if edit.get("original") is not None:
        return edit.get("original")
    return edit.get("expect")


def _norm(value):
    """比较用的归一化：``"3"`` 与 ``3`` 视为相同，``True`` 与 ``1`` 相同。"""
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        text = value.strip()
        if text.lower() in ("true", "false"):
            return 1 if text.lower() == "true" else 0
        try:
            return int(text)
        except ValueError:
            return text
    return value

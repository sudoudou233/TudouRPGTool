# -*- coding: utf-8 -*-
"""
RPG Maker MV / MZ 游戏数据（``data/*.json``）的文本提取与写回。

@feature  translate
@layer    core
@public   extract, apply_to_files, TEXT_CODES, WRAPPER_KEYS
@depends  core.textutil, core.formats.jsoncodec
@tested   tests/compat/test_formats_compat.py
@footprint docs/MODULES.md#coreformats
@note     vendored：来自 rpgmaker_translation_tool/tool/mv_mz.py。
@note     M2b 已把 JSON / 压缩 / 加密包装的**共同约定**收敛到
@note     core/formats/jsoncodec.py，本文件只保留"提取哪些字段、
@note     改哪个键"这类业务规则。
@note     B-02 修复：写回走 core.safety.atomic（jsoncodec 转发的原子写）。
"""

from __future__ import annotations

import json
import os

from ..textutil import has_real_text
from . import jsoncodec

#: 加密包装的外层键（真源在 jsoncodec，这里保留别名以免破坏调用方）
WRAPPER_KEYS = jsoncodec.WRAPPER_KEYS


# ---------------------------------------------------------------------------
# 加密包装（实现已移到 jsoncodec，这里保留同名薄封装）
#
# 为什么保留私有名：这两组函数名（_derive_key / _crypt_bytes / _decrypt_wrapped
# / _encrypt_wrapped）已被 tests/compat/test_formats_compat.py 的
# TestEncryptedWrapper 使用，且它们是"包装格式"的稳定接口。真正的实现只有
# jsoncodec 一份，这里只是转发，避免出现第二份实现（需求 §3.3 的要求）。
# ---------------------------------------------------------------------------
def _derive_key(fname):
    """（转发）由文件名派生包装密钥。"""
    return jsoncodec.derive_wrapper_key(fname)


def _crypt_bytes(data, fk, encrypt):
    """（转发）包装体的异或流加解密。"""
    return jsoncodec.crypt_wrapper_bytes(data, fk, encrypt)


def _decrypt_wrapped(data_b64, fname):
    """（转发）解密包装体内层文本。"""
    return jsoncodec.decrypt_wrapper_payload(data_b64, fname)


def _encrypt_wrapped(plain_text, fname):
    """（转发）加密包装体内层文本。"""
    return jsoncodec.encrypt_wrapper_payload(plain_text, fname)


def _load_data_file(full, fname):
    """读一个数据文件，透明地解开加密包装。

    返回 ``(data, wrapped, header)``。
    """
    data = jsoncodec.read_json_file(full)
    if jsoncodec.is_wrapped(data):
        header, payload = jsoncodec.split_wrapper(data)
        plain = jsoncodec.decrypt_wrapper_payload(payload, fname)
        return json.loads(plain), True, header
    return data, False, None


def _save_data_file(full, fname, data, wrapped, header):
    """写回 JSON 数据文件（**原子写**）。

    ⚠ M2a 修复 **B-02**：原实现直接 ``open(full, "w")`` 截断重写，
    写一半被中断就留下**半写的 JSON**，游戏直接读不了档。现在走
    :mod:`core.safety.atomic`（临时文件 + fsync + ``os.replace``）。

    M2b：JSON 风格（缩进 2 / 不转义非 ASCII）统一由
    :func:`core.formats.jsoncodec.dumps_pretty` 提供，两条 MV/MZ 路径共用。

    ``atomic_write_text`` 把 ``\\r\\n`` 规范化为 ``\\n``，与原实现的
    ``newline="\\n"`` 行为一致（原实现的刻意选择：数据文件不需要 CRLF）。
    """
    if wrapped:
        plain = jsoncodec.dumps_pretty(data)
        payload = jsoncodec.join_wrapper(
            header, jsoncodec.encrypt_wrapper_payload(plain, fname))
        # 保留原行为：wrapped 分支的 uid/bid/加密 data 都是 ASCII，
        # 用默认 ensure_ascii=True 输出（与原 json.dump 调用一致）
        jsoncodec.write_text_file(full, json.dumps(payload))
        return
    jsoncodec.write_text_file(full, jsoncodec.dumps_pretty(data))


# Event command codes whose parameters contain player-visible text.
# value = (parameter index, category)
TEXT_CODES = {
    401: (0, "对话"),      # message line
    402: (0, "选择项"),    # choice text
    405: (0, "对话"),      # scroll text line
    408: (0, "对话"),      # scroll text continuation
    108: (0, "注释"),      # comment
    320: (1, "名称"),      # change name
    324: (1, "名称"),      # change nickname
    325: (1, "描述"),      # change profile
}

#: 参数值是"**多值列表**"的指令码：需要展开成多条翻译条目。
#:
#: 目前只有 402（显示选择项）。真实 MV/MZ 的形状是
#: ``[[ "是", "否" ], cancelType, defaultType]``，即 ``parameters[0]`` 是
#: 选项文本列表；少数导出工具写成扁平 ``["是", "否"]``。两种都要支持。
#:
#: 与原实现的差异：原实现把 402 当单值处理，导致**选择项全部或部分丢失**
#: （见 docs/DEVLOG.md M1 条目）。这是"功能等价性"上必须修的缺陷。
_MULTI_VALUE_CODES = frozenset([402])


def _choice_texts(value):
    """把 402 的参数值归一化成"选项文本列表"；无法识别时返回 None。

    支持两种形状::

        [["是", "否"], 1, 0]   -> ["是", "否"]   （标准 MV/MZ）
        ["是", "否"]           -> ["是", "否"]   （扁平变体）
    """
    if isinstance(value, list):
        if value and isinstance(value[0], list):
            return [v for v in value[0] if isinstance(v, str)]
        if all(isinstance(v, str) for v in value):
            return list(value)
        # 混合形状：挑出开头的连续字符串段
        out = []
        for item in value:
            if isinstance(item, str):
                out.append(item)
            else:
                break
        return out or None
    if isinstance(value, str):
        return [value]
    return None


def _walk_event_list(entries, fname, ev_list, path_prefix, note_prefix, include_comments):
    """遍历事件指令列表，登记可翻译文本。

    ⚠ ``path_prefix`` **已经包含 ``list`` 这一层**（调用方传的是
    ``"1/list"`` / ``"events/0/pages/0/list"``），因此这里的路径必须写成
    ``"%s/%d/parameters/%d"``。

    **N-15（M3a 接线实测发现）**：M2b 重构时这里多拼了一层 ``/list/``，
    于是产出的路径是 ``1/list/list/1/parameters/0``。扫描、统计、界面
    显示全部正常（所以不会有人注意到），但 ``apply_to_files`` 按路径写回时
    定位失败 → **MV/MZ 的所有事件对话与选择项都写不进汉化版，且不报错**。
    表现就是"生成成功、数据库名词翻译了、剧情对话还是原文"。
    该缺陷与 N-12/13/14 同一性质（静默丢功能），已由
    ``tests/features/translate/test_routes.py`` 的构建用例钉死。
    """
    for i, cmd in enumerate(ev_list or []):
        if not isinstance(cmd, dict) or "code" not in cmd:
            continue
        code = cmd.get("code")
        rule = TEXT_CODES.get(code)
        if not rule:
            continue
        idx, category = rule
        if category == "注释" and not include_comments:
            continue
        params = cmd.get("parameters") or []
        if idx >= len(params):
            continue
        text = params[idx]

        # ------------------------------------------------------------------
        # 修正：402（显示选择项）的参数是"选项文本的列表"，而不是单个字符串。
        #
        # 真实 MV/MZ 的形状是 ``[[ "是", "否" ], cancelType, defaultType]``
        # —— 即 ``parameters[0]`` 本身就是列表；少数导出工具会写成扁平的
        # ``["是", "否"]``。原实现只取 ``params[idx]``：
        #   * 扁平形状 → 直接拿到 str "是"，后续选项全丢
        #   * 嵌套形状 → 拿到的是 list，``isinstance(text, str)`` 为假，
        #     于是**整个选择项全部丢失**（比丢一半更严重）
        # M1 实测发现；见 docs/DEVLOG.md 的 M1 条目。
        #
        # 这里对两种形状都做展开，并以多值形式登记（见 mv_mz_data 的
        # _MULTI_VALUE_CODES 说明）。
        # ------------------------------------------------------------------
        values = None
        if code in _MULTI_VALUE_CODES:
            values = _choice_texts(text)
        if values is not None:
            for sub_i, sub_text in enumerate(values):
                if not isinstance(sub_text, str) or not has_real_text(sub_text):
                    continue
                path = "%s/%d/parameters/%d/%d" % (path_prefix, i, idx, sub_i)
                entries.append({
                    "file": fname,
                    "path": path,
                    "category": category,
                    "original": sub_text,
                    "translated": "",
                    "status": "pending",
                    "note": note_prefix,
                    "multi": True,
                })
            continue

        if isinstance(text, str) and has_real_text(text):
            path = "%s/%d/parameters/%d" % (path_prefix, i, idx)
            entries.append({
                "file": fname,
                "path": path,
                "category": category,
                "original": text,
                "translated": "",
                "status": "pending",
                "note": note_prefix,
            })


def _add(entries, fname, path, category, original, note=""):
    if isinstance(original, str) and has_real_text(original):        entries.append({
            "file": fname,
            "path": path,
            "category": category,
            "original": original,
            "translated": "",
            "status": "pending",
            "note": note,
        })


def _extract_system(entries, fname, data):
    _add(entries, fname, "gameTitle", "名称", data.get("gameTitle", ""), "游戏标题")
    _add(entries, fname, "currencyUnit", "界面术语", data.get("currencyUnit", ""), "货币单位")
    for i, v in enumerate(data.get("elements") or []):
        _add(entries, fname, "elements/%d" % i, "界面术语", v, "属性 %d" % (i + 1))
    for key, label in (("skillTypes", "技能类型"), ("weaponTypes", "武器类型"),
                       ("armorTypes", "防具类型"), ("equipTypes", "装备类型")):
        for i, v in enumerate(data.get(key) or []):
            name = v.get("name", "") if isinstance(v, dict) else v
            _add(entries, fname, "%s/%d/name" % (key, i) if isinstance(v, dict) else "%s/%d" % (key, i),
                 "界面术语", name, "%s %d" % (label, i + 1))
    for i, v in enumerate(data.get("switches") or []):
        _add(entries, fname, "switches/%d" % i, "界面术语", v, "开关 %d" % (i + 1))
    for i, v in enumerate(data.get("variables") or []):
        _add(entries, fname, "variables/%d" % i, "界面术语", v, "变量 %d" % (i + 1))
    terms = data.get("terms") or {}
    for group in ("basic", "commands", "params"):
        for i, v in enumerate(terms.get(group) or []):
            _add(entries, fname, "terms/%s/%d" % (group, i), "界面术语", v, "术语 %s %d" % (group, i + 1))
    for i, (k, v) in enumerate((terms.get("messages") or {}).items()):
        _add(entries, fname, "terms/messages/%s" % k, "界面术语", v, "界面消息")


def _extract_db(entries, fname, data, include_notes, include_animations):
    if fname == "System.json":
        _extract_system(entries, fname, data)
        return
    if not isinstance(data, list):
        return
    field_rules = {
        "Actors.json": (("name", "名称", "角色"), ("nickname", "名称", "角色昵称"),
                        ("profile", "描述", "角色简介")),
        "Classes.json": (("name", "名称", "职业"),),
        "Skills.json": (("name", "名称", "技能"), ("message1", "战斗信息", "技能信息"),
                        ("message2", "战斗信息", "技能信息"), ("message3", "战斗信息", "技能信息"),
                        ("message4", "战斗信息", "技能信息"), ("description", "描述", "技能描述")),
        "Items.json": (("name", "名称", "物品"), ("message1", "战斗信息", "物品信息"),
                       ("description", "描述", "物品描述")),
        "Weapons.json": (("name", "名称", "武器"), ("description", "描述", "武器描述")),
        "Armors.json": (("name", "名称", "防具"), ("description", "描述", "防具描述")),
        "Enemies.json": (("name", "名称", "敌人"),),
        "States.json": (("name", "名称", "状态"), ("message1", "战斗信息", "状态信息"),
                        ("message2", "战斗信息", "状态信息"), ("message3", "战斗信息", "状态信息"),
                        ("message4", "战斗信息", "状态信息")),
        "Troops.json": (("name", "名称", "队伍"),),
        "Animations.json": (("name", "名称", "动画"),) if include_animations else (),
        "Tilesets.json": (("name", "名称", "图块组"),),
    }
    rules = field_rules.get(fname, ())
    for i, obj in enumerate(data):
        if not isinstance(obj, dict):
            continue
        for field, category, label in rules:
            if field in obj:
                _add(entries, fname, "%d/%s" % (i, field), category, obj.get(field), "%s %d" % (label, i + 1))
        if include_notes and obj.get("note"):
            _add(entries, fname, "%d/note" % i, "备注", obj["note"], "备注 %d" % (i + 1))


def extract(data_dir, opts):
    entries = []
    fnames = sorted(os.listdir(data_dir))
    for fname in fnames:
        if not fname.endswith(".json"):
            continue
        full = os.path.join(data_dir, fname)
        try:
            data, _, _ = _load_data_file(full, fname)
        except Exception:
            continue
        if fname.startswith("Map") and fname[3:-5].isdigit():
            map_id = fname[3:-5]
            _add(entries, fname, "displayName", "地图名", data.get("displayName", ""),
                 "地图 %s" % map_id)
            for ev_i, ev in enumerate(data.get("events") or []):
                if not isinstance(ev, dict):
                    continue
                if opts.include_event_names and ev.get("name"):
                    _add(entries, fname, "events/%d/name" % ev_i, "事件名", ev["name"],
                         "地图 %s 事件 %d" % (map_id, ev_i + 1))
                for pg_i, pg in enumerate(ev.get("pages") or []):
                    if not isinstance(pg, dict):
                        continue
                    # ⚠ 路径必须带上 ``list`` 这一层：``_walk_event_list`` 内部拼的是
                    # ``"%s/%d/parameters/%d"``（下标是**指令在 list 里的位置**），
                    # 因此这里的前缀要以 ``/list`` 结尾。漏掉的表现和 N-15 一样：
                    # 扫描/界面全都正常，写回时定位失败 → **整张地图的对话静默丢失**
                    # （实测某游戏 45,037 条里丢了 24,709 条 = 54.86%）。
                    _walk_event_list(entries, fname, pg.get("list"),
                                     "events/%d/pages/%d/list" % (ev_i, pg_i),
                                     "地图 %s 事件 %d" % (map_id, ev_i + 1),
                                     opts.include_comments)
        elif fname == "CommonEvents.json":
            for i, obj in enumerate(data or []):
                if not isinstance(obj, dict):
                    continue
                _add(entries, fname, "%d/name" % i, "名称", obj.get("name"), "公共事件 %d" % (i + 1))
                _walk_event_list(entries, fname, obj.get("list"), "%d/list" % i,
                                 "公共事件 %d" % (i + 1), opts.include_comments)
        elif fname == "MapInfos.json":
            for i, obj in enumerate(data or []):
                if isinstance(obj, dict) and obj.get("name"):
                    _add(entries, fname, "%d/name" % i, "地图名", obj["name"], "地图信息 %d" % i)
        else:
            _extract_db(entries, fname, data, opts.include_notes, opts.include_animations)
    return entries


def _set_by_path(data, path):
    """Navigate path segments ('a/b/0/c') and return (parent, key).

    ⚠ **N-15 的第二处**：末段的键必须**按父容器的类型**归一化 ——
    路径段永远是从字符串 ``split("/")`` 来的，但父容器是 ``list`` 时键必须
    是 ``int``。原实现只在**中间段**做了 ``int(seg)``，末段原样返回字符串，
    于是 ``list[str]`` 抛 ``TypeError: list indices must be integers``。
    这类异常在旧代码里会被上层 ``except`` 吞掉 → 该条目静默丢失。

    返回的键类型与容器一致后，调用方可以放心地 ``parent[key] = value``，
    也方便测试直接断言"定位到的就是原文"。
    """
    segs = path.split("/")
    cur = data
    for seg in segs[:-1]:
        if isinstance(cur, list):
            cur = cur[int(seg)]
        elif isinstance(cur, dict):
            cur = cur[seg if seg in cur else int(seg)]
        else:
            raise KeyError(path)
    key = segs[-1]
    if isinstance(cur, list):
        key = int(key)
    return cur, key


def _entry_field(entry, name, default=None):
    """从条目取字段（兼容 dict 与对象两种形态）。"""
    if isinstance(entry, dict):
        return entry.get(name, default)
    return getattr(entry, name, default)


def _has_field(entry, name):
    """条目里是否**存在**该字段（区别于"值是否为真"）。"""
    if isinstance(entry, dict):
        return name in entry
    return hasattr(entry, name)


#: ``expect`` 字段的比较：``"3"``/``3``、``True``/``1`` 都视为相同
def _same_value(a, b):
    if isinstance(a, bool) or isinstance(b, bool):
        return (1 if a else 0) == (1 if b else 0)
    try:
        return int(a) == int(b)
    except (TypeError, ValueError):
        return str(a) == str(b)


def apply_to_files(game_info, entries_by_file, progress=None):
    """把条目写回 JSON 数据文件（就地；调用方负责先备份/复制）。

    两种用途共用本函数：

    * **翻译**：条目的 ``translated`` 是译文，``status`` 决定是否写；
    * **游戏数据修改**（M3b）：``translated`` 是新的数字/布尔值。

    因此这里的判据是"**有没有这个键**"而不是"值真不真" ——
    否则把价格改成 ``0``、把开关改成 ``false`` 都会被当成"没有译文"而 **静默丢弃**
    （M3b 实测踩到：这类"想设成 0 却改不了"的 bug 极难从界面看出来）。

    ``expect``（可选）：条目可以带上"我以为的原值"，只有当前值与它一致时才写。
    这是 ``rgss_data`` 的 B-13 同类防线 —— 数据在别处被改过时宁可跳过，
    也不要按 path 盲写。
    """
    stats = {"files": 0, "entries": 0, "skipped": 0}
    data_dir = game_info["data_dir"]
    for fname, entries in entries_by_file.items():
        if not fname.endswith(".json"):
            continue
        full = os.path.join(data_dir, fname)
        if not os.path.isfile(full):
            continue
        try:
            data, wrapped, header = _load_data_file(full, fname)
        except Exception:
            continue
        changed = False
        for entry in entries:
            if entry is None:
                continue
            status = _entry_field(entry, "status")
            if status is not None and status != "translated":
                continue
            if not _has_field(entry, "translated"):
                continue
            value = _entry_field(entry, "translated")
            if value is None:
                continue
            try:
                parent, key = _set_by_path(data, _entry_field(entry, "path"))
            except (KeyError, ValueError, IndexError):
                stats["skipped"] += 1
                continue
            if _has_field(entry, "expect"):
                current = parent[int(key)] if isinstance(parent, list) else parent[key]
                if not _same_value(current, _entry_field(entry, "expect")):
                    stats["skipped"] += 1
                    continue
            if isinstance(parent, list):
                parent[int(key)] = value
            else:
                parent[key] = value
            changed = True
            stats["entries"] += 1
        if changed:
            _save_data_file(full, fname, data, wrapped, header)
            stats["files"] += 1
        if progress:
            progress(fname)
    return stats

# -*- coding: utf-8 -*-
"""
Extraction and patching for RPG Maker MV / MZ JSON data files.

@feature  translate
@layer    core
@public   extract, apply_to_files, TEXT_CODES, WRAPPER_KEYS
@depends  core.textutil
@tested   tests/compat/test_formats_compat.py
@footprint docs/MODULES.md#coreformats
@note     vendored：来自 rpgmaker_translation_tool/tool/mv_mz.py。
@note     M2b 抽出 core/formats/jsoncodec.py 后本文件只保留业务规则。
"""

from __future__ import annotations

import json
import os
import base64

from ..textutil import has_real_text


WRAPPER_KEYS = ("uid", "bid", "data")


def _derive_key(fname):
    """Key derivation used by wrapped (encrypted) MV/MZ JSON data files."""
    name = os.path.splitext(os.path.basename(fname))[0]
    t = 0
    for ch in name:
        t = ((t << 5) - t + ord(ch)) & 0xFFFFFFFF
    return 205 ^ (t & 255)  # window._K = Math.sqrt(42025) = 205


def _crypt_bytes(data, fk, encrypt):
    b = bytearray(data)
    ls = fk
    for i in range(len(b) - 1, -1, -1):
        _c = fk ^ 72
        _m = i % 128
        _p = ((ls << 2) ^ (ls >> 4))
        _k = ((((_c + _m + _p) ^ 160) + 18)) & 255
        if encrypt:
            orig = b[i]
            b[i] = orig ^ _k
            ls = orig
        else:
            v = b[i] ^ _k
            b[i] = v
            ls = v
    return bytes(b)


def _decrypt_wrapped(data_b64, fname):
    fk = _derive_key(fname)
    raw = base64.b64decode(data_b64)
    return _crypt_bytes(raw, fk, encrypt=False).decode("utf-8")


def _encrypt_wrapped(plain_text, fname):
    fk = _derive_key(fname)
    raw = _crypt_bytes(plain_text.encode("utf-8"), fk, encrypt=True)
    return base64.b64encode(raw).decode("ascii")


def _load_data_file(full, fname):
    """Load a JSON data file, transparently unwrapping encrypted files."""
    with open(full, encoding="utf-8-sig") as f:
        data = json.load(f)
    if isinstance(data, dict) and all(k in data for k in WRAPPER_KEYS):
        header = {"uid": data.get("uid", ""), "bid": data.get("bid", "")}
        plain = _decrypt_wrapped(data["data"], fname)
        return json.loads(plain), True, header
    return data, False, None


def _save_data_file(full, fname, data, wrapped, header):
    if wrapped:
        header = header or {"uid": "", "bid": ""}
        plain = json.dumps(data, ensure_ascii=False, indent=2)
        payload = {"uid": header["uid"], "bid": header["bid"],
                   "data": _encrypt_wrapped(plain, fname)}
        with open(full, "w", encoding="utf-8", newline="\n") as f:
            json.dump(payload, f, ensure_ascii=False)
        return
    with open(full, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

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
                path = "%s/list/%d/parameters/%d/%d" % (path_prefix, i, idx, sub_i)
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
            path = "%s/list/%d/parameters/%d" % (path_prefix, i, idx)
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
    if isinstance(original, str) and has_real_text(original):
        entries.append({
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
                    _walk_event_list(entries, fname, pg.get("list"),
                                     "events/%d/pages/%d" % (ev_i, pg_i),
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
    """Navigate path segments ('a/b/0/c') and return (parent, key)."""
    segs = path.split("/")
    cur = data
    for seg in segs[:-1]:
        if isinstance(cur, list):
            cur = cur[int(seg)]
        elif isinstance(cur, dict):
            cur = cur[seg if seg in cur else int(seg)]
        else:
            raise KeyError(path)
    return cur, segs[-1]


def apply_to_files(game_info, entries_by_file, progress=None):
    """Patch JSON data files in place (in a copy made beforehand)."""
    stats = {"files": 0, "entries": 0}
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
            if not entry.get("translated") or entry.get("status") != "translated":
                continue
            try:
                parent, key = _set_by_path(data, entry["path"])
                if isinstance(parent, list):
                    parent[int(key)] = entry["translated"]
                else:
                    parent[key] = entry["translated"]
                changed = True
                stats["entries"] += 1
            except (KeyError, ValueError, IndexError):
                continue
        if changed:
            _save_data_file(full, fname, data, wrapped, header)
            stats["files"] += 1
        if progress:
            progress(fname)
    return stats

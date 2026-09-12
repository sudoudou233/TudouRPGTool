# -*- coding: utf-8 -*-
"""
Extraction and patching for RPG Maker VX Ace / XP rxdata files.

@feature  translate
@layer    core
@public   extract, apply_to_files
@depends  core.textutil, core.marshal.value_model, core.formats.mv_mz_data
@tested   tests/compat/test_formats_compat.py
@footprint docs/MODULES.md#coreformats
@note     vendored：来自 rpgmaker_translation_tool/tool/vxace.py。
@note     已知缺陷 B-02（非原子写）、B-13（original 参数未用于校验）。
"""

from __future__ import annotations

import os

from ..marshal import value_model as marshal
from ..textutil import has_real_text
from .mv_mz_data import TEXT_CODES


def _iv(obj, name):
    if isinstance(obj, marshal.RMObject):
        return obj.ivars.get(name)
    if isinstance(obj, dict):
        return obj.get(name)
    return None


def _text_of(v):
    """Unwrap RMIvar so wrapped strings compare as plain strings."""
    if isinstance(v, marshal.RMIvar):
        v = v.value
    return v if isinstance(v, str) else None


def _walk_event_list(entries, fname, ev_list, path_prefix, note_prefix, include_comments):
    for i, cmd in enumerate(ev_list or []):
        if not isinstance(cmd, marshal.RMObject) or cmd.class_name != "RPG::EventCommand":
            continue
        code = _iv(cmd, "@code")
        rule = TEXT_CODES.get(code)
        if not rule:
            continue
        idx, category = rule
        if category == "注释" and not include_comments:
            continue
        params = _iv(cmd, "@parameters") or []
        if idx >= len(params):
            continue
        text = _text_of(params[idx])
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
    for i, obj in enumerate(data or []):
        if not isinstance(obj, marshal.RMObject):
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
        for i, v in enumerate(arr or []):
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
    if isinstance(terms, marshal.RMObject):
        for group in ("@basic", "@params", "@commands"):
            arr = _iv(terms, group)
            for i, v in enumerate(arr or []):
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
            if isinstance(data, marshal.RMObject):
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
            for i, troop in enumerate(data or []):
                if not isinstance(troop, marshal.RMObject):
                    continue
                for pg_i, page in enumerate(_iv(troop, "@pages") or []):
                    if isinstance(page, marshal.RMObject):
                        _walk_event_list(entries, fname, _iv(page, "@list"),
                                         "%d/@pages/%d/@list" % (i, pg_i),
                                         "队伍 %d 页面 %d" % (i + 1, pg_i + 1), opts.include_comments)
        elif base == "CommonEvents":
            for i, obj in enumerate(data or []):
                if not isinstance(obj, marshal.RMObject):
                    continue
                _add(entries, fname, "%d/@name" % i, "名称", _iv(obj, "@name"), "公共事件 %d" % (i + 1))
                _walk_event_list(entries, fname, _iv(obj, "@list"), "%d/@list" % i,
                                 "公共事件 %d" % (i + 1), opts.include_comments)
        elif base == "MapInfos":
            for k, obj in (data or {}).items():
                if isinstance(obj, marshal.RMObject):
                    _add(entries, fname, "%s/@name" % k, "地图名", _iv(obj, "@name"), "地图 %s" % k)
        elif base.startswith("Map") and base[3:].isdigit():
            map_id = base[3:]
            _add(entries, fname, "@display_name", "地图名", _iv(data, "@display_name"), "地图 %s" % map_id)
            for ev_i, ev in enumerate(_iv(data, "@events") or []):
                if not isinstance(ev, marshal.RMObject):
                    continue
                ev_name = _text_of(_iv(ev, "@name"))
                if opts.include_event_names and ev_name is not None:
                    _add(entries, fname, "@events/%d/@name" % ev_i, "事件名", ev_name,
                         "地图 %s 事件 %d" % (map_id, ev_i + 1))
                for pg_i, page in enumerate(_iv(ev, "@pages") or []):
                    if isinstance(page, marshal.RMObject):
                        _walk_event_list(entries, fname, _iv(page, "@list"),
                                         "@events/%d/@pages/%d/@list" % (ev_i, pg_i),
                                         "地图 %s 事件 %d" % (map_id, ev_i + 1), opts.include_comments)
    return entries


def _unwrap(value):
    """Unwrap RMIvar to the inner value."""
    while isinstance(value, marshal.RMIvar):
        value = value.value
    return value


def _navigate(root, path):
    """Return (parent, last segment, is_rmivar) for a path."""
    segs = path.split("/")
    cur = root
    for seg in segs[:-1]:
        if isinstance(cur, list):
            # 防御：段必须是整数下标。若上游（如 402 选择项）把"字符串列表"
            # 的文本当成 path 段传下来，``int("是")`` 会抛 ValueError，
            # 而 apply_to_files 只捕获 (KeyError, ValueError, IndexError)，
            # 于是静默跳过——不写坏文件，但译文也落不下去。
            # M1 已记录该缺陷（见 docs/DEVLOG.md），M2a 统一处置多值条目的写回。
            cur = cur[int(seg)]
        elif isinstance(cur, marshal.RMObject):
            name = seg if seg.startswith("@") else "@" + seg
            cur = cur.ivars[name]
        elif isinstance(cur, dict):
            key = seg
            if key not in cur:
                key = int(seg)
            cur = cur[key]
        else:
            raise KeyError(path)
    last = segs[-1]
    if isinstance(cur, marshal.RMObject):
        name = last if last.startswith("@") else "@" + last
        return cur, name, False
    return cur, last, False


def _set_value(parent, key, value, original):
    """Set a translated string, preserving the original's encoding wrapper."""
    if isinstance(parent, marshal.RMObject):
        old = parent.ivars[key]
    elif isinstance(parent, dict):
        old = parent.get(key, parent.get(int(key)))
    else:
        old = parent[int(key)]
    enc = getattr(_unwrap(old), "enc", None) or "utf-8"
    new = marshal.RMStr(value, enc=enc)
    if isinstance(old, marshal.RMIvar):
        old.value = new
        return
    if isinstance(parent, marshal.RMObject):
        parent.ivars[key] = new
    elif isinstance(parent, dict):
        if key in parent:
            parent[key] = new
        else:
            parent[int(key)] = new
    else:
        parent[int(key)] = new


def apply_to_files(game_info, entries_by_file, progress=None):
    stats = {"files": 0, "entries": 0}
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
            if not entry.get("translated") or entry.get("status") != "translated":
                continue
            try:
                parent, key, _ = _navigate(root, entry["path"])
                _set_value(parent, key, entry["translated"], entry["original"])
                changed = True
                stats["entries"] += 1
            except (KeyError, ValueError, IndexError):
                continue
        if changed:
            with open(full, "wb") as f:
                f.write(marshal.dumps(root))
            stats["files"] += 1
        if progress:
            progress(fname)
    return stats

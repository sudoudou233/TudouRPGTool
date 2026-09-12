# -*- coding: utf-8 -*-
"""
Copy a game folder, write translations, apply a custom font, and

@feature  translate
@layer    core
@public   build, backup_files, restore_backup, list_backups, apply_font,
@public   default_target_dir, resolve_target_dir, next_free_dir, BACKUP_PREFIX
@depends  core.marshal.value_model, core.safety.fontutil
@tested   tests/compat/test_build_backup.py
@footprint docs/MODULES.md#coresafety
@note     vendored：来自 rpgmaker_translation_tool/tool/build.py。
@note     已知缺陷（M2a 必修）：B-01（rmtree 先删后拷）、B-03（字体兜底
@note     覆盖不可还原）、B-04（还原不完整）、B-05（覆盖无二次确认）、
@note     B-06（无回滚）、B-26（模块顶层 import winreg，非 Windows 失败）。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import time
import winreg

from . import fontutil
from ..marshal import value_model as marshal
from ..formats import mv_mz_data as mv_mz
from ..formats import rgss_data as vxace


BACKUP_PREFIX = "汉化备份_"


def _copy_tree(src, dst, progress_cb=None):
    os.makedirs(dst, exist_ok=True)
    total = sum(len(files) for _, _, files in os.walk(src))
    done = 0
    for root, dirs, files in os.walk(src):
        rel = os.path.relpath(root, src)
        target = dst if rel == "." else os.path.join(dst, rel)
        os.makedirs(target, exist_ok=True)
        for name in files:
            shutil.copy2(os.path.join(root, name), os.path.join(target, name))
            done += 1
            if progress_cb:
                progress_cb(done, total)


def default_target_dir(game_dir):
    parent = os.path.dirname(os.path.abspath(game_dir))
    base = os.path.basename(os.path.abspath(game_dir).rstrip("\\/"))
    out = os.path.join(parent, base + "_汉化")
    n = 1
    while os.path.exists(out):
        out = os.path.join(parent, "%s_汉化%d" % (base, n))
        n += 1
    return out


def resolve_target_dir(game_dir, target_dir=None):
    """Return the absolute output path (auto-generating when empty)."""
    return os.path.abspath(target_dir or default_target_dir(game_dir))


def next_free_dir(base):
    """Return base, base2, base3... whichever does not exist yet."""
    candidate = base
    n = 2
    while os.path.exists(candidate):
        candidate = "%s%d" % (base, n)
        n += 1
    return candidate


def _assert_safe_target(dst):
    """Reject obviously dangerous output paths before deleting/recreating."""
    drive, tail = os.path.splitdrive(os.path.abspath(dst))
    if tail in ("\\", "/", ""):
        raise ValueError("输出目录不能是磁盘根目录")
    user = os.environ.get("USERPROFILE", "")
    if user and os.path.abspath(dst).lower() == os.path.abspath(user).lower():
        raise ValueError("输出目录不能是用户主目录")


def _group_entries(session):
    by_file = {}
    for e in session.entries.values():
        if e["status"] == "translated" and e.get("translated"):
            by_file.setdefault(e["file"], []).append(e)
    return by_file


# ---------------------------------------------------------------------------
# font support
# ---------------------------------------------------------------------------

def _find_fonts_dir(game_root, engine):
    for rel in ("www/fonts", "fonts"):
        p = os.path.join(game_root, rel)
        if os.path.isdir(p):
            return p, rel
    rel = "www/fonts" if engine == "mv" else "fonts"
    return os.path.join(game_root, rel), rel


def _find_core_js(game_root):
    for rel in ("www/js/rpg_core.js", "www/js/rmmz_core.js", "js/rpg_core.js", "js/rmmz_core.js"):
        p = os.path.join(game_root, rel)
        if os.path.isfile(p):
            return p, rel
    return None, None


def _patch_core_js(core_path, font_name):
    with open(core_path, encoding="utf-8-sig") as f:
        src = f.read()
    pattern = re.compile(
        r"(FontManager\.load\(\s*['\"](?:GameFont|GameFont2)['\"]\s*,\s*['\"])[^'\"]+(['\"]\s*\))"
    )
    new_src, n = pattern.subn(lambda m: m.group(1) + font_name + m.group(2), src)
    if n == 0:
        return False
    with open(core_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(new_src)
    return True


def _font_touched_paths(game_root, engine, font_path):
    """Return the game-relative files that applying a font will modify."""
    touched = []
    fonts_dir, fonts_rel = _find_fonts_dir(game_root, engine)
    name = fontutil.safe_filename(font_path)
    touched.append(os.path.join(fonts_rel, name).replace("\\", "/"))
    core, core_rel = _find_core_js(game_root)
    if core:
        touched.append(core_rel.replace("\\", "/"))
    if engine in ("vxace", "xp"):
        touched.append("Fonts/" + name)
        for cand in ("Scripts.rvdata2", "Scripts.rxdata"):
            if os.path.isfile(os.path.join(game_root, "Data", cand)):
                touched.append("Data/" + cand)
    return touched


def _apply_font_mv_mz(game_root, engine, font_path, touched_log=None):
    fonts_dir, fonts_rel = _find_fonts_dir(game_root, engine)
    os.makedirs(fonts_dir, exist_ok=True)
    name = fontutil.safe_filename(font_path)
    dest = os.path.join(fonts_dir, name)
    if os.path.abspath(dest) != os.path.abspath(font_path):
        shutil.copy2(font_path, dest)
    if touched_log is not None:
        touched_log.append(os.path.join(fonts_rel, name).replace("\\", "/"))

    core, core_rel = _find_core_js(game_root)
    notes = []
    if core:
        ok = _patch_core_js(core, name)
        if touched_log is not None:
            touched_log.append(core_rel.replace("\\", "/"))
        if ok:
            notes.append("已修改 %s：游戏字体指向 %s" % (core_rel, name))
        else:
            notes.append("未找到 FontManager.load 配置，游戏可能仍使用原字体")
            # last-resort: overwrite the common default font files
            for fallback in ("gamefont.ttf", "mplus-1m-regular.ttf"):
                fb = os.path.join(fonts_dir, fallback)
                if os.path.isfile(fb):
                    shutil.copy2(font_path, fb)
                    if touched_log is not None:
                        touched_log.append(os.path.join(fonts_rel, fallback).replace("\\", "/"))
                    notes.append("已覆盖默认字体文件 %s" % fallback)
    else:
        notes.append("未找到 rpg_core.js / rmmz_core.js，字体文件已复制到 %s" % fonts_rel)
    return notes


def _install_user_font(font_path, family, name):
    """Install a font for the current Windows user (no admin needed)."""
    try:
        dst_dir = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Windows", "Fonts")
        if not dst_dir:
            return False
        os.makedirs(dst_dir, exist_ok=True)
        dst = os.path.join(dst_dir, name)
        shutil.copy2(font_path, dst)
        key = winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows NT\CurrentVersion\Fonts",
            0, winreg.KEY_SET_VALUE)
        value_name = "%s (TrueType)" % (family or os.path.splitext(name)[0])
        winreg.SetValueEx(key, value_name, 0, winreg.REG_SZ, dst)
        winreg.CloseKey(key)
        return True
    except OSError:
        return False


def _inject_font_script(scripts_path, family, engine):
    """Append Font.default_name to Scripts.rvdata2 / Scripts.rxdata."""
    with open(scripts_path, "rb") as f:
        root = marshal.loads(f.read())
    if not isinstance(root, list):
        return False
    max_id = 0
    for item in root:
        if isinstance(item, list) and item and isinstance(item[0], int):
            max_id = max(max_id, item[0])
    family_safe = family.replace("\\", "\\\\").replace('"', '\\"')
    code = 'Font.default_name = "%s"' % family_safe
    if engine == "xp":
        try:
            code_bytes = code.encode("cp932")
            code_str = marshal.RMStr(code_bytes.decode("cp932"), enc="cp932")
        except UnicodeEncodeError:
            return False
    else:
        code_str = marshal.RMIvar(
            marshal.RMStr(code, enc="utf-8"),
            {marshal.RMSymbol("E"): True, marshal.RMSymbol("encoding"): marshal.RMSymbol("UTF_8")},
        )
    name_str = marshal.RMIvar(
        marshal.RMStr("TranslationFont", enc="utf-8"),
        {marshal.RMSymbol("E"): True, marshal.RMSymbol("encoding"): marshal.RMSymbol("UTF_8")},
    )
    root.append([max_id + 1, name_str, code_str])
    with open(scripts_path, "wb") as f:
        f.write(marshal.dumps(root))
    return True


def _apply_font_rgss(game_root, font_path, engine, touched_log=None):
    """VX Ace / XP: copy font into the game and make the game use it."""
    fonts_dir = os.path.join(game_root, "Fonts")
    os.makedirs(fonts_dir, exist_ok=True)
    name = fontutil.safe_filename(font_path)
    dest = os.path.join(fonts_dir, name)
    if os.path.abspath(dest) != os.path.abspath(font_path):
        shutil.copy2(font_path, dest)
    if touched_log is not None:
        touched_log.append("Fonts/" + name)
    family = fontutil.extract_family(font_path)
    notes = []
    installed = _install_user_font(font_path, family, name)
    notes.append("已复制字体到 Fonts/%s；%s" % (
        name,
        "已安装到当前用户字体库" if installed else "未能写入用户字体库（可能需要手动安装字体）"))
    if family:
        scripts = None
        for cand in ("Scripts.rvdata2", "Scripts.rxdata"):
            p = os.path.join(game_root, "Data", cand)
            if os.path.isfile(p):
                scripts = p
                break
        if scripts:
            if _inject_font_script(scripts, family, engine):
                if touched_log is not None:
                    touched_log.append("Data/" + os.path.basename(scripts))
                notes.append("已注入字体设置脚本（Font.default_name = %s）" % family)
            else:
                notes.append("无法注入字体脚本（引擎兼容性限制），请手动设置游戏字体")
        else:
            notes.append("未找到 Scripts 数据文件，未注入字体设置")
    return notes


def apply_font(game_root, engine, font_path, touched_log=None):
    """Apply a font to a game root.  Returns human-readable notes."""
    if engine in ("mv", "mz"):
        return _apply_font_mv_mz(game_root, engine, font_path, touched_log)
    if engine in ("vxace", "xp"):
        return _apply_font_rgss(game_root, font_path, engine, touched_log)
    return ["该引擎暂不支持自动应用字体"]


# ---------------------------------------------------------------------------
# build / backup / restore
# ---------------------------------------------------------------------------

def _write_manifest(backup_dir, rel_files):
    with open(os.path.join(backup_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump({"created": time.strftime("%Y-%m-%d %H:%M:%S"), "files": rel_files},
                  f, ensure_ascii=False, indent=1)


def backup_files(game_dir, rel_files, backup_dir=None):
    """Copy the given game-relative files into a backup folder."""
    backup_dir = backup_dir or os.path.join(
        game_dir, BACKUP_PREFIX + time.strftime("%Y%m%d_%H%M%S"))
    os.makedirs(backup_dir, exist_ok=True)
    copied = []
    for rel in rel_files:
        rel = rel.replace("\\", "/")
        src = os.path.join(game_dir, rel)
        if not os.path.isfile(src):
            continue
        dst = os.path.join(backup_dir, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        copied.append(rel)
    _write_manifest(backup_dir, copied)
    return backup_dir, copied


def restore_backup(game_dir, backup_dir):
    """Restore game files from a backup folder.  Returns restored count."""
    backup_dir = os.path.abspath(backup_dir)
    manifest = os.path.join(backup_dir, "manifest.json")
    files = []
    if os.path.isfile(manifest):
        with open(manifest, encoding="utf-8") as f:
            files = json.load(f).get("files") or []
    else:
        # legacy backups: flat copies of data files
        data_dir = os.path.join(game_dir, "Data")
        for fname in os.listdir(backup_dir):
            if fname.endswith((".rvdata2", ".rxdata", ".json")):
                files.append(os.path.join("Data", fname).replace("\\", "/"))
    n = 0
    for rel in files:
        src = os.path.join(backup_dir, rel.replace("/", os.sep))
        dst = os.path.join(game_dir, rel.replace("/", os.sep))
        if not os.path.isfile(src):
            continue
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        n += 1
    return n


def list_backups(game_dir):
    out = []
    if not os.path.isdir(game_dir):
        return out
    for name in sorted(os.listdir(game_dir), reverse=True):
        if name.startswith(BACKUP_PREFIX):
            p = os.path.join(game_dir, name)
            if os.path.isdir(p):
                out.append({
                    "dir": p,
                    "name": name,
                    "files": sum(len(fs) for _, _, fs in os.walk(p)),
                    "time": time.strftime("%Y-%m-%d %H:%M:%S",
                                          time.localtime(os.path.getmtime(p))),
                })
    return out


def build(session, mode="copy", target_dir=None, backup=True, font_path=None,
          overwrite=False, progress_cb=None):
    """Write translations (and optionally a font) to a copy or in place."""
    info = session.info
    if not info["supported"]:
        raise ValueError("不支持的引擎")
    game_dir = info["game_dir"]
    data_dir = info["data_dir"]
    rel_data = os.path.relpath(data_dir, game_dir)
    engine = info["engine"]
    entries_by_file = _group_entries(session)
    font_path = (font_path or "").strip() or None
    if font_path and not os.path.isfile(font_path):
        raise ValueError("字体文件不存在: %s" % font_path)

    notes = []
    if mode == "copy":
        dst = resolve_target_dir(game_dir, target_dir)
        game_abs = os.path.abspath(game_dir)
        if dst == game_abs:
            raise ValueError("输出目录不能与原游戏目录相同")
        rel = os.path.relpath(dst, game_abs)
        if rel == "." or not rel.startswith(".."):
            raise ValueError("输出目录不能位于游戏目录内部: %s" % dst)
        _assert_safe_target(dst)
        if os.path.exists(dst) and os.listdir(dst):
            if not overwrite:
                raise ValueError("目标目录已存在: %s" % dst)
            shutil.rmtree(dst)
        _copy_tree(game_dir, dst, progress_cb)
        target_root = dst
        fake_info = dict(info)
        fake_info["data_dir"] = os.path.join(dst, rel_data)
        if engine in ("mv", "mz"):
            stats = mv_mz.apply_to_files(fake_info, entries_by_file)
        else:
            stats = vxace.apply_to_files(fake_info, entries_by_file)
        if font_path:
            notes.extend(apply_font(target_root, engine, font_path))
        result = {"mode": mode, "target_dir": dst,
                  "files": stats["files"], "entries": stats["entries"], "notes": notes}
    else:
        # in-place: figure out everything that will change, back it up first
        touched = set()
        for fname in entries_by_file:
            touched.add(os.path.join(rel_data, fname).replace("\\", "/"))
        if font_path:
            touched.update(_font_touched_paths(game_dir, engine, font_path))
        backup_dir = None
        if backup:
            backup_dir, _ = backup_files(game_dir, sorted(touched))
            if progress_cb:
                progress_cb(0, 1, "已备份 %d 个原文件到 %s" % (len(touched), backup_dir))
        if engine in ("mv", "mz"):
            stats = mv_mz.apply_to_files(info, entries_by_file)
        else:
            stats = vxace.apply_to_files(info, entries_by_file)
        if font_path:
            notes.extend(apply_font(game_dir, engine, font_path))
        result = {"mode": mode, "target_dir": game_dir, "backup_dir": backup_dir,
                  "files": stats["files"], "entries": stats["entries"], "notes": notes}
    return result

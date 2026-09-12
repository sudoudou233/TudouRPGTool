# -*- coding: utf-8 -*-
"""生成汉化版的编排层：复制/覆盖、字体应用、写回、失败回滚。

@feature  translate
@layer    core
@public   build, apply_font, default_target_dir, resolve_target_dir,
          font_touched_paths, patch_core_js, inject_font_script,
          install_user_font, copy_tree
@depends  core.safety.backup, core.safety.atomic, core.safety.fontutil,
          core.formats.mv_mz_data, core.formats.rgss_data,
          core.marshal.value_layer
@tested   tests/compat/test_build_backup.py, tests/compat/test_m2a_regressions.py
@footprint docs/MODULES.md#coresafety

职责边界
--------
* :mod:`core.safety.backup` —— 备份 / 还原 / 清单（不依赖 formats）
* **本文件** —— 编排：拷贝游戏、写回译文、应用字体、失败回滚（依赖 formats）
* :mod:`core.safety.fontutil` —— 字体族名解析

M2a 修复的缺陷（见 docs/STATE.md §5）
------------------------------------
* **B-01** 覆盖已有输出目录时，旧版**先 rmtree 再拷贝** → 中途失败旧输出永久丢失。
  现在改为"拷贝到同父目录下的暂存目录 → 成功后原子换名 → 最后删旧目录"；
  任一步失败只清理暂存目录，旧输出完好。回归：
  ``tests/compat/test_m2a_regressions.py::TestB01CopyFailureKeepsOldOutput``。
* **B-03** 字体兜底会覆盖 ``gamefont.ttf`` / ``mplus-1m-regular.ttf``，但这两个
  路径不在 touched 清单里 → 覆盖后无法还原。现已纳入
  :func:`font_touched_paths`。
* **B-05** 覆盖原游戏/已有输出目录缺少**显式确认参数**。现在
  ``confirm_overwrite=True`` 是必需项，否则抛 :class:`OverwriteNotConfirmed`。
* **B-06** ``build()`` 原先无 try/except、无回滚。现在 inplace 模式失败会
  **自动从刚做的备份还原**，并把失败原因一起抛出。
* **B-26** ``winreg`` 改为函数内 import（非 Windows 上模块可正常导入）。
"""

from __future__ import annotations

import os
import re
import shutil
import time

from ..formats import mv_mz_data, rgss_data
from ..marshal import doc_model as _doc_model
from ..marshal import value_layer as marshal
from . import backup as backup_mod
from . import fontutil
from .atomic import AtomicWriteError, assert_safe_target, atomic_write_text, next_free_dir


class OverwriteNotConfirmed(ValueError):
    """覆盖既有输出需要显式确认（B-05：破坏性操作必须二次确认）。"""


class BuildFailed(RuntimeError):
    """构建失败；``.rollback`` 记录回滚结果。"""

    def __init__(self, message, rollback=None):
        RuntimeError.__init__(self, message)
        self.rollback = rollback


# ---------------------------------------------------------------------------
# 目标目录
# ---------------------------------------------------------------------------
def default_target_dir(game_dir):
    """``<父目录>/<游戏名>_汉化``，冲突时追加序号（沿用原命名）。"""
    parent = os.path.dirname(os.path.abspath(game_dir))
    name = os.path.basename(os.path.abspath(game_dir).rstrip("\\/")) or "Game"
    return next_free_dir(os.path.join(parent, name + "_汉化"))


def resolve_target_dir(game_dir, target_dir=None):
    """返回规范化后的输出目录绝对路径（未指定时自动生成）。"""
    return os.path.abspath(target_dir or default_target_dir(game_dir))


# ---------------------------------------------------------------------------
# 复制
# ---------------------------------------------------------------------------
def copy_tree(src, dst, progress_cb=None, ignore=None):
    """逐文件复制目录树。

    ``progress_cb(done, total, message=None)`` —— 与原实现 ``_copy_tree`` 的
    ``progress_cb(done, total)`` 兼容（第三个参数可选）。
    """
    src = os.path.abspath(src)
    dst = os.path.abspath(dst)
    ignore = set(ignore or ())

    def _ignored(name):
        return name in ignore or name.startswith(backup_mod.BACKUP_PREFIX)

    total = 0
    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if not _ignored(d)]
        total += len([f for f in files if not _ignored(f)])
    done = 0
    os.makedirs(dst, exist_ok=True)
    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if not _ignored(d)]
        rel = os.path.relpath(root, src)
        target = dst if rel == "." else os.path.join(dst, rel)
        os.makedirs(target, exist_ok=True)
        for name in files:
            if _ignored(name):
                continue
            shutil.copy2(os.path.join(root, name), os.path.join(target, name))
            done += 1
            if progress_cb:
                try:
                    progress_cb(done, total, "复制 %s" % name)
                except TypeError:
                    progress_cb(done, total)
    return {"files": done}


# ---------------------------------------------------------------------------
# 字体
# ---------------------------------------------------------------------------
def _find_fonts_dir(game_root, engine):
    for rel in ("www/fonts", "fonts"):
        path = os.path.join(game_root, rel)
        if os.path.isdir(path):
            return path, rel
    rel = "www/fonts" if engine in ("mv", "mz") else "fonts"
    return os.path.join(game_root, rel), rel


def _find_core_js(game_root):
    for rel in ("www/js/rpg_core.js", "www/js/rmmz_core.js",
                "js/rpg_core.js", "js/rmmz_core.js"):
        path = os.path.join(game_root, rel)
        if os.path.isfile(path):
            return path, rel
    return None, None


#: FontManager.load 的字体名占位（MV/MZ 默认字体在这两处配置）
_CORE_JS_RE = re.compile(
    r"(FontManager\.load\(\s*['\"](?:GameFont|GameFont2)['\"]\s*,\s*['\"])[^'\"]+(['\"]\s*\))"
)

#: 字体兜底会覆盖的默认字体文件名（**必须**进 touched 清单，见 B-03）
FONT_FALLBACK_NAMES = ("gamefont.ttf", "mplus-1m-regular.ttf")


def patch_core_js(core_path, font_name):
    """改写 ``rpg_core.js`` / ``rmmz_core.js`` 里的字体名。

    返回 ``True`` 表示找到并改写了占位；``False`` 表示没有可改的占位
    （调用方走兜底覆盖）。
    **原子写**（B-02：原实现直接 ``open("w")`` 截断重写）。
    """
    with open(core_path, encoding="utf-8-sig") as f:
        src = f.read()
    new_src, count = _CORE_JS_RE.subn(
        lambda m: m.group(1) + font_name + m.group(2), src)
    if count == 0:
        return False
    atomic_write_text(core_path, new_src)
    return True


def font_touched_paths(game_root, engine, font_path):
    """应用字体会改动/新建的游戏内文件清单。

    **B-03 修复点**：兜底覆盖的默认字体文件（``gamefont.ttf`` /
    ``mplus-1m-regular.ttf``）若已存在，必须出现在这里，否则被覆盖后无法还原。
    """
    touched = []
    fonts_dir, fonts_rel = _find_fonts_dir(game_root, engine)
    name = fontutil.safe_filename(font_path)
    touched.append((fonts_rel + "/" + name).replace("\\", "/"))

    core, core_rel = _find_core_js(game_root)
    if core:
        touched.append(core_rel.replace("\\", "/"))
    if engine in ("vxace", "xp"):
        touched.append("Fonts/" + name)
        for candidate in ("Scripts.rvdata2", "Scripts.rxdata"):
            if os.path.isfile(os.path.join(game_root, "Data", candidate)):
                touched.append("Data/" + candidate)
    # B-03：兜底覆盖的默认字体文件必须进 touched 清单。
    # 这里**无条件登记**（而不是"存在才登记"），理由：
    #   * 该清单表达的是"这次操作**可能**改动哪些文件"，作为备份范围的契约；
    #   * backup_files 会跳过不存在的文件，因此多登记不会产生多余备份；
    #   * 若写成"存在才登记"，调用方就得在同一次操作里两次判断存在性，
    #     一旦中间状态变化（比如字体是本次才被创建的）就会漏备。
    for fallback in FONT_FALLBACK_NAMES:
        touched.append((fonts_rel + "/" + fallback).replace("\\", "/"))
    # 去重但保持顺序
    seen = set()
    out = []
    for rel in touched:
        if rel not in seen:
            seen.add(rel)
            out.append(rel)
    return out


def install_user_font(font_path, family, name):
    """把字体装进当前用户的字体库（写 HKCU，不需要管理员权限）。

    **B-26**：``winreg`` 在函数内 import —— 非 Windows 平台上本模块可正常导入，
    调用本函数时会得到 ``{'installed': False, 'reason': ...}`` 而不是 ImportError。
    """
    try:
        import winreg
    except ImportError:
        return {"installed": False, "reason": "当前平台不支持用户字体安装（非 Windows）"}
    try:
        dst_dir = os.path.join(os.environ.get("LOCALAPPDATA", ""),
                               "Microsoft", "Windows", "Fonts")
        if not dst_dir or not os.environ.get("LOCALAPPDATA"):
            return {"installed": False, "reason": "找不到 %LOCALAPPDATA%"}
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
        return {"installed": True, "path": dst, "value_name": value_name}
    except OSError as exc:
        return {"installed": False, "reason": str(exc)}


def inject_font_script(scripts_path, family, engine):
    """往 ``Scripts.rvdata2`` / ``Scripts.rxdata`` 追加一条 ``Font.default_name`` 脚本。

    **原子写**（B-02）。返回 ``True`` 表示已写入。

    M2b：由 ``value_model`` 切到 ``core.marshal.value_layer``（前者已收敛删除）。
    这里刻意**直接构造 ``doc_model`` 节点**而不是先做 Python 值再转换，原因：

    * XP 的脚本要用 **cp932** 编码写回，而 ``value_layer.unwrap_to_node(str)``
      一律按 UTF-8 编码 —— 会把 cp932 文本写错；
    * VX Ace 需要 ``Ivar`` 包装携带 ``@encoding = :UTF_8``，这是 Ruby 侧
      识别字符串编码的标记，不是普通字符串能表达的。

    也就是说："用值层做**读写**，用节点层做**精确构造**"。
    """
    with open(scripts_path, "rb") as f:
        root = marshal.loads(f.read())
    items = _array_items(root)
    if items is None:
        return False         # Scripts 的顶层不是数组 → 不是我们能改的形状
    max_id = 0
    for item in items:
        values = _array_items(item)
        if values and isinstance(values[0], int):
            max_id = max(max_id, values[0])

    family_safe = family.replace("\\", "\\\\").replace('"', '\\"')
    code = 'Font.default_name = "%s"' % family_safe
    if engine == "xp":
        try:
            code_bytes = code.encode("cp932")
            name_bytes = "TranslationFont".encode("cp932")
        except UnicodeEncodeError:
            return False
        entry = [max_id + 1,
                 _doc_model.String(name_bytes),
                 _doc_model.String(code_bytes)]
    else:
        entry = [max_id + 1,
                 _utf8_ivar("TranslationFont"),
                 _utf8_ivar(code)]

    items.append(_doc_model.Array([_to_node(v) for v in entry]))
    root.dirty = True
    payload = marshal.dumps(root)
    from .atomic import atomic_write_bytes
    atomic_write_bytes(scripts_path, payload)
    return True


def _utf8_ivar(text):
    """构造 ``I`` 包装的 UTF-8 字符串（VX Ace 的 Scripts 需要这个形状）。"""
    return _doc_model.Ivar(
        _doc_model.String(text.encode("utf-8")),
        [(_doc_model.Symbol(b"E"), _doc_model.BoolNode(True)),
         (_doc_model.Symbol(b"encoding"),
          _doc_model.Symbol(b"UTF_8"))])


def _to_node(value):
    """把 Python 值转成节点（已构造好的节点原样返回）。"""
    if isinstance(value, _doc_model.Node):
        return value
    return marshal.unwrap_to_node(value)


def _array_items(node):
    """若是个数组（值层代理或原生 list）就返回其**可变元素列表**，否则 None。

    返回的是底层 list 对象本身，因此 ``items.append(...)`` 会真的改到节点树
    （``RMArray.items`` 是 ``doc_model.Array.items`` 的引用）。
    """
    if isinstance(node, list):
        return node
    inner = getattr(node, "node", None)
    if inner is not None and isinstance(getattr(inner, "items", None), list):
        return inner.items
    return None


def apply_font(game_root, engine, font_path, touched_log=None, created_log=None):
    """按引擎应用字体，返回人读 notes 列表。

    MV/MZ：拷进 fonts 目录 + 改写 core.js 的 FontManager 配置；
           找不到占位时兜底覆盖默认字体文件（这些文件会被记入 touched_log，
           因此可还原 —— B-03）。
    VX Ace/XP：拷进 ``Fonts/`` + 装用户字体库 + 往 Scripts 注入脚本。
    """
    font_path = os.path.abspath(font_path)
    if not os.path.isfile(font_path):
        raise ValueError("字体文件不存在: %s" % font_path)
    notes = []
    if engine in ("mv", "mz"):
        fonts_dir, fonts_rel = _find_fonts_dir(game_root, engine)
        existed = os.path.isdir(fonts_dir)
        os.makedirs(fonts_dir, exist_ok=True)
        name = fontutil.safe_filename(font_path)
        dest = os.path.join(fonts_dir, name)
        dest_existed = os.path.isfile(dest)
        if os.path.abspath(dest) != font_path:
            shutil.copy2(font_path, dest)
        rel_dest = (fonts_rel + "/" + name).replace("\\", "/")
        if touched_log is not None and dest_existed:
            touched_log.append(rel_dest)
        if created_log is not None and not dest_existed:
            created_log.append(rel_dest)

        core, core_rel = _find_core_js(game_root)
        if not core:
            notes.append("未找到 rpg_core.js / rmmz_core.js，"
                         "字体文件已复制到 %s" % fonts_rel)
            return notes
        ok = patch_core_js(core, name)
        if touched_log is not None:
            touched_log.append(core_rel.replace("\\", "/"))
        if ok:
            notes.append("已修改 %s：游戏字体指向 %s" % (core_rel, name))
            return notes

        notes.append("未找到 FontManager.load 配置，游戏可能仍使用原字体")
        for fallback in FONT_FALLBACK_NAMES:
            candidate = os.path.join(fonts_dir, fallback)
            if not os.path.isfile(candidate):
                continue
            shutil.copy2(font_path, candidate)
            rel_fb = (fonts_rel + "/" + fallback).replace("\\", "/")
            # 关键：兜底覆盖的是**已存在**的文件，必须进 touched（B-03）
            if touched_log is not None:
                touched_log.append(rel_fb)
            notes.append("已覆盖默认字体文件 %s（已纳入备份，可还原）" % fallback)
        return notes

    # ---- RGSS ----
    fonts_dir = os.path.join(game_root, "Fonts")
    os.makedirs(fonts_dir, exist_ok=True)
    name = fontutil.safe_filename(font_path)
    dest = os.path.join(fonts_dir, name)
    dest_existed = os.path.isfile(dest)
    if os.path.abspath(dest) != font_path:
        shutil.copy2(font_path, dest)
    rel_dest = "Fonts/" + name
    if touched_log is not None and dest_existed:
        touched_log.append(rel_dest)
    if created_log is not None and not dest_existed:
        created_log.append(rel_dest)

    family = fontutil.extract_family(font_path)
    install = install_user_font(font_path, family, name)
    if install.get("installed"):
        notes.append("已安装字体到当前用户字体库：%s" % family)
    else:
        notes.append("未能安装到用户字体库（%s），"
                     "若游戏内文字不显示请手动安装该字体"
                     % install.get("reason", "未知原因"))

    for candidate in ("Scripts.rvdata2", "Scripts.rxdata"):
        scripts = os.path.join(game_root, "Data", candidate)
        if not os.path.isfile(scripts):
            continue
        rel_scripts = "Data/" + candidate
        if touched_log is not None:
            touched_log.append(rel_scripts)
        try:
            if inject_font_script(scripts, family, engine):
                notes.append("已向 %s 注入 Font.default_name" % candidate)
        except Exception as exc:
            notes.append("注入字体脚本失败（%s）：%s" % (candidate, exc))
        break
    return notes


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------
def _group_entries(session):
    """按文件聚合"已翻译且有译文"的条目。"""
    by_file = {}
    entries = getattr(session, "entries", None) or {}
    values = entries.values() if isinstance(entries, dict) else entries
    for entry in values:
        status = getattr(entry, "status", None) or entry.get("status")
        translated = getattr(entry, "translated", None) or entry.get("translated")
        if status == "translated" and translated:
            name = getattr(entry, "file", None) or entry.get("file")
            by_file.setdefault(name, []).append(entry)
    return by_file


def _apply_entries(info, entries_by_file):
    engine = info.get("engine")
    if engine in ("mv", "mz"):
        return mv_mz_data.apply_to_files(info, entries_by_file)
    return rgss_data.apply_to_files(info, entries_by_file)


def build(session, mode="copy", target_dir=None, backup=True, font_path=None,
          overwrite=False, progress_cb=None, confirm_overwrite=False):
    """生成汉化版。

    参数
    ----
    mode : 'copy' | 'inplace'
        ``copy``（默认，推荐）复制到新目录；``inplace`` 直接写回原游戏。
    overwrite : bool
        目标目录已存在且非空时是否允许覆盖。
    confirm_overwrite : bool
        **B-05**：覆盖既有内容必须显式确认。``overwrite=True`` 而未给
        ``confirm_overwrite=True`` 时抛 :class:`OverwriteNotConfirmed`。
        ``inplace`` 模式同样要求本参数为 True（覆盖的是用户原游戏）。
    backup : bool
        inplace 模式是否备份（默认 True；界面路径下不应关掉）。
    progress_cb : callable
        ``progress_cb(done, total, message=None)``。

    返回 dict（含 ``mode`` / ``target_dir`` / ``files`` / ``entries`` /
    ``notes`` / ``backup_dir`` / ``rollback``）。

    异常
    ----
    OverwriteNotConfirmed  需要确认但没给
    BuildFailed            构建失败（``.rollback`` 记录回滚结果）
    """
    info = dict(session.info)
    if not info.get("supported"):
        raise ValueError("不支持的引擎：%s" % info.get("label") or info.get("engine"))
    game_dir = os.path.abspath(info["game_dir"])
    data_dir = info["data_dir"]
    rel_data = os.path.relpath(data_dir, game_dir)
    engine = info["engine"]
    entries_by_file = _group_entries(session)
    font_path = (font_path or "").strip() or None
    if font_path and not os.path.isfile(font_path):
        raise ValueError("字体文件不存在: %s" % font_path)

    if mode == "copy":
        return _build_copy(session, info, game_dir, rel_data, engine,
                           entries_by_file, target_dir, font_path,
                           overwrite, progress_cb, confirm_overwrite)
    return _build_inplace(session, info, game_dir, rel_data, engine,
                          entries_by_file, font_path, backup, progress_cb,
                          confirm_overwrite)


def _build_copy(session, info, game_dir, rel_data, engine, entries_by_file,
                target_dir, font_path, overwrite, progress_cb,
                confirm_overwrite):
    dst = resolve_target_dir(game_dir, target_dir)
    if os.path.abspath(dst) == game_dir:
        raise ValueError("输出目录不能与原游戏目录相同")
    rel = os.path.relpath(dst, game_dir)
    if rel == "." or not rel.startswith(".."):
        raise ValueError("输出目录不能位于游戏目录内部: %s" % dst)
    assert_safe_target(dst)

    dst_exists = os.path.isdir(dst)
    if dst_exists and os.listdir(dst):
        if not overwrite:
            raise ValueError("目标目录已存在: %s" % dst)
        if not confirm_overwrite:
            raise OverwriteNotConfirmed(
                "覆盖已有输出目录需要显式确认（confirm_overwrite=True）：%s" % dst)

    # ---- B-01：先拷到暂存目录，成功后再换名 ----
    staging = "%s.__staging_%s" % (dst, time.strftime("%Y%m%d%H%M%S"))
    seq = 1
    while os.path.exists(staging):
        staging = "%s.__staging_%s_%d" % (dst, time.strftime("%Y%m%d%H%M%S"), seq)
        seq += 1

    try:
        if progress_cb:
            progress_cb(0, 1, "正在复制游戏到暂存目录…")
        copy_tree(game_dir, staging, progress_cb=progress_cb)

        fake_info = dict(info)
        fake_info["data_dir"] = os.path.join(staging, rel_data)
        if progress_cb:
            progress_cb(0, 1, "正在写回译文…")
        stats = _apply_entries(fake_info, entries_by_file)

        notes = []
        touched, created = [], []
        if font_path:
            notes.extend(apply_font(staging, engine, font_path,
                                    touched_log=touched, created_log=created))

        # ---- 换名：先移开旧目录，再就位，最后删旧 ----
        retired = None
        if dst_exists:
            retired = "%s.__old_%s" % (dst, time.strftime("%Y%m%d%H%M%S"))
            seq = 1
            while os.path.exists(retired):
                retired = "%s.__old_%s_%d" % (dst, time.strftime("%Y%m%d%H%M%S"), seq)
                seq += 1
            os.replace(dst, retired)
        try:
            os.replace(staging, dst)
        except OSError:
            # 换名失败：把旧目录放回去，保证用户至少还有原来的输出
            if retired and not os.path.exists(dst):
                os.replace(retired, dst)
            raise
        if retired:
            shutil.rmtree(retired, ignore_errors=True)
    except Exception as exc:
        # 失败：只清理暂存目录，旧输出原封不动（这是 B-01 的核心要求）
        shutil.rmtree(staging, ignore_errors=True)
        if isinstance(exc, (OverwriteNotConfirmed, AtomicWriteError)):
            raise
        raise BuildFailed("生成汉化版失败：%s: %s" % (type(exc).__name__, exc))

    return {"mode": "copy", "target_dir": dst,
            "files": stats["files"], "entries": stats["entries"],
            "notes": notes, "backup_dir": None, "rollback": None,
            "font_created": created}


def _build_inplace(session, info, game_dir, rel_data, engine, entries_by_file,
                   font_path, backup, progress_cb, confirm_overwrite):
    if not confirm_overwrite:
        raise OverwriteNotConfirmed(
            "直接覆盖原游戏需要显式确认（confirm_overwrite=True）：%s" % game_dir)

    touched = set()
    for fname in entries_by_file:
        touched.add(os.path.join(rel_data, fname).replace("\\", "/"))
    created = []
    if font_path:
        touched.update(font_touched_paths(game_dir, engine, font_path))
    touched = sorted(t for t in touched if not t.startswith(".."))

    backup_dir = None
    if backup:
        if progress_cb:
            progress_cb(0, 1, "正在备份将被修改的文件…")
        extra = {"mode": "inplace", "engine": engine}
        if font_path:
            extra["font"] = os.path.basename(font_path)
        backup_dir, _copied = backup_mod.backup_files(game_dir, touched, extra=extra)

    try:
        if progress_cb:
            progress_cb(0, 1, "正在写回译文…")
        stats = _apply_entries(info, entries_by_file)
        notes = []
        if font_path:
            before = set()
            for root, _dirs, files in os.walk(game_dir):
                for name in files:
                    before.add(os.path.relpath(os.path.join(root, name), game_dir)
                               .replace("\\", "/"))
            notes.extend(apply_font(game_dir, engine, font_path,
                                    touched_log=None, created_log=created))
            if backup_dir:
                after = set()
                for root, _dirs, files in os.walk(game_dir):
                    for name in files:
                        after.add(os.path.relpath(os.path.join(root, name), game_dir)
                                  .replace("\\", "/"))
                newly = sorted(after - before)
                if newly:
                    backup_mod.record_created(backup_dir, newly)
                    created.extend(newly)
    except Exception as exc:
        rollback = None
        if backup_dir:
            if progress_cb:
                progress_cb(0, 1, "写回失败，正在从备份还原…")
            try:
                rollback = backup_mod.restore_backup(game_dir, backup_dir,
                                                    safety=False)
            except Exception as restore_exc:
                rollback = {"error": str(restore_exc)}
        raise BuildFailed(
            "写回原游戏失败：%s: %s%s" % (
                type(exc).__name__, exc,
                "" if rollback else "（未做备份，无法自动回滚）"),
            rollback=rollback)

    # 字体兜底可能覆盖了已存在的默认字体，但这些路径在 touched 里
    # （font_touched_paths 已含），因此备份是完整的。
    return {"mode": "inplace", "target_dir": game_dir,
            "files": stats["files"], "entries": stats["entries"],
            "notes": notes, "backup_dir": backup_dir, "rollback": None,
            "font_created": created}

# -*- coding: utf-8 -*-
"""引擎识别 + 数据目录/存档目录发现 —— 全工程唯一实现。

@feature  none
@layer    core
@public   detect, detect_engine, describe, list_saves, find_save_dirs, data_dir,
          save_dir, CONVERGENCE_STATUS
@depends  core.constants
@tested   tests/unit/test_engines.py
@footprint docs/MODULES.md#coreengines

合并背景（需求 §3.3 重复实现之一）
--------------------------------
原有两个工具各有一份引擎识别，判据与返回结构都不同：

| 来源 | 入口 | MV/MZ 判据 | 兜底 | 存档发现 |
| --- | --- | --- | --- | --- |
| rpgmaker_translation_tool/tool/engines.py:33 | ``detect()`` | ``*_managers.js`` | 读 System.json | 无 |
| rpgmaker_cheating_tool/engines.py:37 | ``detect_engine()`` | ``*_core.js`` | 无 | ``SAVE_PATTERNS`` + save_dir |

本模块把 **两种判据全部保留**（任一命中即识别），并统一返回**同时服务于
"数据目录"与"存档目录"两类需求**的结构，因此本文件从第一天起就只有一个实现。

判据优先级（先强后弱）
--------------------
1. MV/MZ：``js/rmmz_managers.js`` → ``www/js/rmmz_managers.js`` → ``js/rmmz_core.js``
   → ``www/js/rmmz_core.js`` → ``rpg_managers.js`` 系列 → ``rpg_core.js`` 系列
2. MV/MZ 兜底：存在 ``data/System.json`` 或 ``www/data/System.json`` 时，读
   ``equipTypes`` / ``itemCategories`` / ``locale`` 判定 MZ，否则 MV
3. RGSS：``Data/*.rvdata2`` → vxace；``Data/*.rvdata`` → vx；``Data/*.rxdata`` → xp
4. 2000/2003：``RPG_RT.ini`` / ``RPG_RT.exe``，或任何 ``*.ldb``（只识别不修改）
"""

from __future__ import annotations

import json
import os
import re

from . import constants

#: 收敛状态：本模块**从第一天起就只有一份实现**（未经历"两份再合并"）。
#:
#: 为什么要这个常量，而不是在报告里写死字符串（M5 实测踩到）：
#: ``/api/health`` 的 ``convergence.engines`` 原先是在 ``ui/routes.py`` 里
#: **硬编码**的 ``"merged"``，而 ``features/selfcheck`` 读的是本模块的同名属性 ——
#: 属性不存在，于是自检页显示 ``engines: unknown``，与健康检查**互相矛盾**。
#: 同一个事实有两个来源，迟早会漂移；现在两边都读这一个常量。
CONVERGENCE_STATUS = "merged"

#: MV/MZ 判定用的 JS 文件名，按"越靠前越权威"排列。
MZ_JS_MARKERS = ("rmmz_managers.js", "rmmz_core.js")
MV_JS_MARKERS = ("rpg_managers.js", "rpg_core.js")

#: MV/MZ 可能的游戏根（NW.js 打包时资源在 www/ 下）。
JS_ROOT_CANDIDATES = ("", "www")

#: 数据目录候选（相对上面选中的根）。
DATA_SUBDIR = "data"

#: System.json 里只有 MZ 才有的字段。
MZ_SYSTEM_FIELDS = ("equipTypes", "itemCategories", "locale")


def _is_file(path):
    return os.path.isfile(path)


def _is_dir(path):
    return os.path.isdir(path)


def _find_first_file(root, names):
    """在 root 下按 names 顺序找文件，返回首个存在的绝对路径。"""
    for name in names:
        full = os.path.join(root, name)
        if _is_file(full):
            return full
    return None


def _detect_mvmz_js(game_dir):
    """用 JS 标记文件判定 MV/MZ。返回 (engine, js_root) 或 (None, None)。

    同时覆盖两套原有判据：``*_managers.js``（翻译工具）与 ``*_core.js``（修改工具）。
    """
    for sub in JS_ROOT_CANDIDATES:
        root = os.path.join(game_dir, sub) if sub else game_dir
        if not _is_dir(root):
            continue
        js_dir = os.path.join(root, "js")
        if not _is_dir(js_dir):
            continue
        if _find_first_file(js_dir, MZ_JS_MARKERS):
            return "mz", root
        if _find_first_file(js_dir, MV_JS_MARKERS):
            return "mv", root
    return None, None


def _find_system_json(game_dir):
    """定位 MV/MZ 的 System.json，返回 (path, data_dir) 或 (None, None)。"""
    for sub in JS_ROOT_CANDIDATES:
        root = os.path.join(game_dir, sub) if sub else game_dir
        sys_path = os.path.join(root, DATA_SUBDIR, "System.json")
        if _is_file(sys_path):
            return sys_path, os.path.join(root, DATA_SUBDIR)
    return None, None


def _engine_from_system(system_path):
    """读 System.json 兜底判定 MV / MZ（判据来自 translation_tool/tool/engines.py:22）。"""
    try:
        with open(system_path, encoding="utf-8-sig") as f:
            data = json.load(f)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    for field in MZ_SYSTEM_FIELDS:
        if field in data:
            return "mz"
    return "mv"


def _detect_rgss(game_dir):
    """用 Data 目录里的扩展名判定 RGSS 系引擎。返回 (engine, data_dir) 或 (None, None)。"""
    data_dir = os.path.join(game_dir, "Data")
    if not _is_dir(data_dir):
        return None, None
    try:
        names = os.listdir(data_dir)
    except OSError:
        return None, None
    # 注意：.rvdata2 必须先于 .rvdata 判断（前缀包含关系）。
    if any(n.endswith(".rvdata2") for n in names):
        return "vxace", data_dir
    if any(n.endswith(".rvdata") for n in names):
        return "vx", data_dir
    if any(n.endswith(".rxdata") for n in names):
        return "xp", data_dir
    return None, None


def _detect_2k3(game_dir):
    """识别 RPG Maker 2000/2003（只识别，不支持修改）。"""
    if _find_first_file(game_dir, ("RPG_RT.ini", "RPG_RT.exe")):
        return "2k3"
    try:
        names = os.listdir(game_dir)
    except OSError:
        return None
    for name in names:
        if name.lower().endswith(".ldb"):
            return "2k3"
    return None


def _blank_info(game_dir):
    return {
        "engine": None,
        "label": "未知引擎",
        "data_dir": None,
        "save_dir": None,
        "ext": None,
        "standard": None,
        "layout": None,
        "supported": False,
        "match": None,
        "game_dir": game_dir,
        "error": None,
    }


def _mvmz_info(engine, js_root):
    """组装 MV/MZ 的 info。数据与存档目录都在同一个资源根下。"""
    info = _blank_info(js_root)
    info.update(
        engine=engine,
        label=constants.engine_label(engine),
        data_dir=os.path.join(js_root, "data"),
        save_dir=os.path.join(js_root, "save"),
        ext=constants.SAVE_EXTS[engine],
        standard=False,
        layout="json",
        supported=True,
    )
    return info


def _rgss_info(engine, game_dir, data_dir):
    """组装 RGSS 系 info。存档与游戏根同级。"""
    info = _blank_info(game_dir)
    info.update(
        engine=engine,
        label=constants.engine_label(engine),
        data_dir=data_dir,
        save_dir=game_dir,
        ext=constants.SAVE_EXTS[engine],
        # VX Ace（.rvdata2）在改造版运行时下是 hash 布局；
        # XP / VX（.rxdata / .rvdata）是标准 Ruby Marshal + contents 布局。
        standard=(engine in ("xp", "vx")),
        layout="contents" if engine in ("xp", "vx") else "hash",
        supported=True,
    )
    return info


def detect_engine(game_dir):
    """识别游戏目录的引擎。

    返回 dict，键统一为::

        engine      引擎标识（'mz'/'mv'/'vxace'/'vx'/'xp'/'2k3'），未识别为 None
        label       中文显示名
        data_dir    数据目录绝对路径（未识别为 None）
        save_dir    存档目录绝对路径（未识别为 None）
        ext         存档扩展名（含点，'2k3' 为 '.lsd'）
        standard    RGSS 是否走标准 Ruby Marshal（MV/MZ 恒 False）
        layout      'json' / 'hash' / 'contents'
        supported   是否支持读写
        match       命中的判据（'js:rmmz_managers.js' / 'system.json' / ...）
        game_dir    传入目录的绝对路径
        error       未识别或不支持时的中文原因，正常为 None

    目录不存在或未识别时返回 None（与 cheat tool 的 ``detect_engine`` 语义一致）；
    识别到但不支持修改的引擎（2k3）返回 ``supported=False`` 的 info。
    """
    if not game_dir:
        return None
    game_dir = os.path.abspath(game_dir)
    if not _is_dir(game_dir):
        return None

    # ---- 1) MV / MZ：先 JS 标记，再 System.json 兜底 ----
    engine, js_root = _detect_mvmz_js(game_dir)
    if engine:
        marker = "rmmz" if engine == "mz" else "rpg"
        return _mvmz_info(engine, js_root)

    system_path, data_dir = _find_system_json(game_dir)
    if system_path:
        engine = _engine_from_system(system_path) or "mz"
        info = _mvmz_info(engine, os.path.dirname(data_dir))
        if not _is_dir(info["data_dir"]):
            info["data_dir"] = data_dir
        info["match"] = "system.json"
        return info

    # ---- 2) RGSS：VX Ace / VX / XP ----
    engine, rgss_data_dir = _detect_rgss(game_dir)
    if engine:
        return _rgss_info(engine, game_dir, rgss_data_dir)

    # ---- 3) 2000/2003：只识别 ----
    if _detect_2k3(game_dir):
        info = _blank_info(game_dir)
        info.update(
            engine="2k3",
            label=constants.engine_label("2k3"),
            data_dir=game_dir,
            save_dir=game_dir,
            ext=constants.SAVE_EXTS["2k3"],
            supported=False,
            match="lcf",
            error="暂不支持 RPG Maker 2000/2003 的 LDB 格式（仅识别）",
        )
        return info

    return None


def detect(game_dir):
    """``detect_engine()`` 的别名，返回结构永远非 None（便于 UI 直接展示错误）。

    未识别时返回 ``error`` 已填好的 info（``engine=None``、``supported=False``），
    这样调用方不需要写两套分支。
    """
    info = detect_engine(game_dir)
    if info is not None:
        return info
    out = _blank_info(os.path.abspath(game_dir) if game_dir else "")
    if not game_dir:
        out["error"] = "未提供游戏目录"
    elif not _is_dir(game_dir):
        out["error"] = "目录不存在：%s" % game_dir
    else:
        out["error"] = "未识别出支持的 RPG Maker 游戏（MV / MZ / VX Ace / VX / XP）"
    return out


def describe(info):
    """把 info 渲染成一行中文摘要，供界面显示。"""
    if not info:
        return "未识别"
    if not info.get("engine"):
        return info.get("error") or "未识别"
    text = info.get("label") or constants.engine_label(info.get("engine"))
    if not info.get("supported"):
        return "%s（仅识别，不支持修改）" % text
    if info.get("match"):
        return "%s（判据 %s）" % (text, info["match"])
    return text


# ---------------------------------------------------------------------------
# 存档发现
# ---------------------------------------------------------------------------
def list_saves(info, game_dir=None):
    """列出存档目录下的存档文件名（已排序）。

    存档目录优先取 ``info['save_dir']``；缺失时退回 ``game_dir``。
    目录不存在或无匹配命名规则时返回空列表。
    """
    if not info or not info.get("engine"):
        return []
    pattern = constants.SAVE_PATTERNS.get(info["engine"])
    if not pattern:
        return []
    save_dir = info.get("save_dir") or game_dir
    if not save_dir or not _is_dir(save_dir):
        return []
    try:
        names = os.listdir(save_dir)
    except OSError:
        return []
    rx = re.compile(pattern[0])
    return sorted(name for name in names if rx.match(name))


def find_save_dirs(info, game_dir, max_depth=2):
    """搜索所有可能存放存档的目录（应对"自动存档"等第二套存档）。

    返回 ``[(dir, [文件名...]), ...]``，目录已排序；只包含有存档的目录。
    除 ``info['save_dir']`` 外，还会在游戏根下最多下探 ``max_depth`` 层。
    """
    if not info or not info.get("engine"):
        return []
    pattern = constants.SAVE_PATTERNS.get(info["engine"])
    if not pattern:
        return []
    rx = re.compile(pattern[0])
    root = info.get("game_dir") or os.path.abspath(game_dir or "")
    if not root or not _is_dir(root):
        return []

    found = {}
    base = info.get("save_dir")
    if base and _is_dir(base):
        found[base] = []
    for dirpath, dirs, files in os.walk(root):
        depth = dirpath[len(root):].count(os.sep)
        if depth >= max_depth:
            dirs[:] = []
        hits = sorted(f for f in files if rx.match(f))
        if hits:
            found.setdefault(dirpath, [])
            found[dirpath] = sorted(set(found[dirpath]) | set(hits))
    return sorted((d, found[d]) for d in found if found[d])


def data_dir(info):
    """便捷取数据目录；无则 None。"""
    return (info or {}).get("data_dir")


def save_dir(info):
    """便捷取存档目录；无则 None。"""
    return (info or {}).get("save_dir")

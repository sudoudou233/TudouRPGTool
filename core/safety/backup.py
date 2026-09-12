# -*- coding: utf-8 -*-
"""备份、还原与备份清单 —— 所有写回操作的安全底座。

@feature  translate
@layer    core
@public   BACKUP_PREFIX, backup_files, restore_backup, list_backups,
          safety_backup, MANIFEST_NAME, write_manifest, read_manifest,
          record_created
@depends  core.paths, core.safety.atomic
@tested   tests/compat/test_build_backup.py, tests/compat/test_m2a_regressions.py
@footprint docs/MODULES.md#coresafety

背景：这个文件原先是 vendored 的 ``translation_tool/tool/build.py``（399 行，
生成汉化版 + 备份 + 字体 + 平台相关代码全挤在一起）。M2a 按职责把它拆开：

* **本文件**：备份 / 还原 / 清单。**不 import 任何 ``core.formats`` 模块**
  —— 这既让职责单一，也切断了 ``core.formats`` ↔ ``core.safety`` 的循环依赖。
* :mod:`core.safety.builder`：生成汉化版与字体应用的编排层（依赖 formats）。
* :mod:`core.safety.fontutil`：字体族名解析。

M2a 修复的缺陷（见 docs/STATE.md §5）
------------------------------------
* **B-01** 旧版目标是"先 ``shutil.rmtree(dst)`` 再拷贝"，中途失败旧输出永久丢失。
  现由 :mod:`core.safety.builder` 用"暂存目录 + 原子换名"实现（本文件提供
  :func:`safety_backup` 供换名失败时兜底）。
* **B-04** 还原只处理清单内文件，且 build 新增的文件不会被删除。
  现在清单区分 ``files``（被覆盖的原文件）与 ``created``（build 新建的文件），
  还原时前者恢复、后者删除；且**还原前会先为当前状态生成安全备份**。
* **B-07** 备份失败被静默吞掉后继续写档。现在任何拷贝失败都会抛
  :class:`core.safety.atomic.AtomicWriteError`，调用方必须处理。
* **B-26** 顶层 ``import winreg`` 已移到 :mod:`core.safety.builder` 的函数内部
  （本文件不再涉及字体安装）。
"""

from __future__ import annotations

import json
import os
import shutil
import time

from .atomic import AtomicWriteError, atomic_write_text

#: 备份目录前缀（沿用原实现的命名，保证用户习惯一致）
BACKUP_PREFIX = "汉化备份_"

#: 备份清单文件名
MANIFEST_NAME = "manifest.json"

#: 清单 schema 版本
MANIFEST_SCHEMA = 2


# ---------------------------------------------------------------------------
# 清单读写
# ---------------------------------------------------------------------------
def write_manifest(backup_dir, files, created=None, extra=None):
    """写备份清单。

    参数
    ----
    files : iterable[str]
        被**覆盖**的游戏内相对路径（还原时恢复）。
    created : iterable[str]
        build **新建**的游戏内相对路径（还原时删除）。
    extra : dict
        附加信息（如 mode / engine / font_path），便于事后追溯。
    """
    payload = {
        "schema": MANIFEST_SCHEMA,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "files": sorted(set(files or ())),
        "created": sorted(set(created or ())),
    }
    if extra:
        payload.update(extra)
    os.makedirs(backup_dir, exist_ok=True)
    target = os.path.join(backup_dir, MANIFEST_NAME)
    # 清单本身也原子写：半写的清单会让还原彻底失效
    atomic_write_text(target, json.dumps(payload, ensure_ascii=False, indent=1))
    return target


def read_manifest(backup_dir):
    """读清单；缺失或损坏时返回 ``None``（调用方走 legacy 回退）。"""
    path = os.path.join(backup_dir, MANIFEST_NAME)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            payload = json.load(f)
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    payload.setdefault("files", [])
    payload.setdefault("created", [])
    return payload


def record_created(backup_dir, rel_paths):
    """把"build 新建的文件"追加进清单（还原时会被删除）。

    为什么需要单独记录：原实现只备份**已存在**的文件，于是 build 过程中
    新产生的文件（字体等）在还原时不会被清理 —— 游戏目录回不到原状（B-04）。
    """
    payload = read_manifest(backup_dir)
    if payload is None:
        payload = {"files": [], "created": []}
    created = set(payload.get("created") or ())
    for rel in rel_paths or ():
        created.add(str(rel).replace("\\", "/"))
    payload["created"] = sorted(created)
    payload.setdefault("files", [])
    payload.setdefault("schema", MANIFEST_SCHEMA)
    payload.setdefault("created_at", time.strftime("%Y-%m-%d %H:%M:%S"))
    atomic_write_text(os.path.join(backup_dir, MANIFEST_NAME),
                      json.dumps(payload, ensure_ascii=False, indent=1))
    return payload


# ---------------------------------------------------------------------------
# 备份
# ---------------------------------------------------------------------------
def _normalize(rel):
    return str(rel).replace("\\", "/").lstrip("/")


def backup_files(game_dir, rel_files, backup_dir=None, extra=None):
    """把给定的游戏内相对路径文件复制进备份目录。

    返回 ``(backup_dir, copied_list)``。

    * 清单里**不存在**的文件会被跳过（原实现 :284-285 的行为，保持不变 ——
      新建文件由 :func:`record_created` 另行登记）。
    * 任何拷贝失败都会抛 :class:`AtomicWriteError`（**修 B-07**：原实现把
      ``OSError`` 静默吞掉，导致"没备份却照样写档"）。
    """
    game_dir = os.path.abspath(game_dir)
    if backup_dir is None:
        stamp = time.strftime("%Y%m%d_%H%M%S")
        backup_dir = os.path.join(game_dir, BACKUP_PREFIX + stamp)
        seq = 1
        while os.path.exists(backup_dir):
            backup_dir = os.path.join(game_dir, "%s%s_%d" % (BACKUP_PREFIX, stamp, seq))
            seq += 1
    os.makedirs(backup_dir, exist_ok=True)

    copied = []
    for rel in rel_files or ():
        rel = _normalize(rel)
        if not rel:
            continue
        src = os.path.join(game_dir, rel.replace("/", os.sep))
        if not os.path.isfile(src):
            continue                      # 不存在则跳过（不是错误）
        dst = os.path.join(backup_dir, rel.replace("/", os.sep))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        try:
            shutil.copy2(src, dst)
        except OSError as exc:
            raise AtomicWriteError(
                "备份失败，已中止写入：%s -> %s：%s" % (src, dst, exc))
        copied.append(rel)

    write_manifest(backup_dir, copied, extra=extra)
    return backup_dir, copied


def safety_backup(game_dir, rel_files, label="还原前"):
    """还原之前给"当前状态"再备份一次（**修 B-04**）。

    没有这一步的话，"还原错了"就不可挽回。返回备份目录或 None（无需备份时）。
    """
    rel_files = [_normalize(r) for r in (rel_files or ()) if r]
    existing = [r for r in rel_files
                if os.path.isfile(os.path.join(game_dir, r.replace("/", os.sep)))]
    if not existing:
        return None
    stamp = time.strftime("%Y%m%d_%H%M%S")
    backup_dir = os.path.join(game_dir, "%s%s_%s" % (BACKUP_PREFIX, stamp, label))
    seq = 1
    while os.path.exists(backup_dir):
        backup_dir = os.path.join(
            game_dir, "%s%s_%s_%d" % (BACKUP_PREFIX, stamp, label, seq))
        seq += 1
    backup_dir, _copied = backup_files(game_dir, existing, backup_dir=backup_dir,
                                      extra={"purpose": label})
    return backup_dir


# ---------------------------------------------------------------------------
# 还原
# ---------------------------------------------------------------------------
def restore_backup(game_dir, backup_dir, safety=True):
    """从备份目录还原游戏文件。

    返回 dict::

        {
          'restored': int,            # 恢复的文件数
          'removed': int,             # 删除的"build 新建文件"数
          'skipped': [rel, ...],     # 清单里有但备份里没有的
          'safety_backup': str|None,  # 还原前为当前状态生成的备份
          'backup_dir': str,
        }

    **修 B-04**：除了恢复 ``files``，还会删除 ``created`` 里登记的文件，
    并在还原前为当前状态生成安全备份。
    """
    game_dir = os.path.abspath(game_dir)
    backup_dir = os.path.abspath(backup_dir)
    if not os.path.isdir(backup_dir):
        raise ValueError("备份目录不存在：%s" % backup_dir)

    payload = read_manifest(backup_dir)
    if payload is None:
        # legacy 备份：早期版本没有清单，只有一堆平铺的数据文件
        files = []
        created = []
        data_dir = os.path.join(game_dir, "Data")
        for name in sorted(os.listdir(backup_dir)):
            if name.endswith((".rvdata2", ".rxdata", ".json")):
                candidate = os.path.join("Data", name).replace("\\", "/")
                files.append(candidate)
        payload = {"files": files, "created": created, "legacy": True,
                   "_data_dir": data_dir}

    files = [_normalize(r) for r in payload.get("files") or ()]
    created = [_normalize(r) for r in payload.get("created") or ()]

    safety_dir = None
    if safety:
        safety_dir = safety_backup(game_dir, files + created, label="还原前")

    restored = 0
    skipped = []
    for rel in files:
        src = os.path.join(backup_dir, rel.replace("/", os.sep))
        dst = os.path.join(game_dir, rel.replace("/", os.sep))
        if not os.path.isfile(src):
            skipped.append(rel)
            continue
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        try:
            shutil.copy2(src, dst)
        except OSError as exc:
            raise AtomicWriteError("还原失败：%s -> %s：%s" % (src, dst, exc))
        restored += 1

    removed = 0
    for rel in created:
        if rel in files:
            continue          # 既被覆盖又被标记新建：以恢复为准，不删
        dst = os.path.join(game_dir, rel.replace("/", os.sep))
        if os.path.isfile(dst):
            try:
                os.remove(dst)
                removed += 1
            except OSError:
                pass

    return {
        "restored": restored,
        "removed": removed,
        "skipped": skipped,
        "safety_backup": safety_dir,
        "backup_dir": backup_dir,
        "legacy": bool(payload.get("legacy")),
    }


def list_backups(game_dir):
    """列出游戏目录下的备份（名称/文件数/时间/是否含清单）。"""
    out = []
    if not os.path.isdir(game_dir):
        return out
    for name in sorted(os.listdir(game_dir), reverse=True):
        if not name.startswith(BACKUP_PREFIX):
            continue
        path = os.path.join(game_dir, name)
        if not os.path.isdir(path):
            continue
        payload = read_manifest(path)
        out.append({
            "dir": path,
            "name": name,
            "files": sum(len(fs) for _r, _d, fs in os.walk(path)),
            "time": time.strftime("%Y-%m-%d %H:%M:%S",
                                  time.localtime(os.path.getmtime(path))),
            "has_manifest": payload is not None,
            "restorable": (payload.get("files") if payload else None) or [],
            "created": (payload.get("created") if payload else None) or [],
        })
    return out

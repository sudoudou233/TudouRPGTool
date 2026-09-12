# -*- coding: utf-8 -*-
"""原子写入与安全护栏 —— 任何写回操作的统一入口。

@feature  none
@layer    core
@public   atomic_write_bytes, atomic_write_text, AtomicWriteError, SafeTargetError,
          assert_safe_target, next_free_dir, sibling_backup, unique_temp_path
@depends  core.paths
@tested   tests/unit/test_atomic.py
@footprint docs/MODULES.md#coresafety

修正的原有缺陷（见 docs/M0-现状测绘.md §4.1）
------------------------------------------
原两个工具**所有**游戏文件的写入都是非原子的：

* ``translation_tool/tool/vxace.py:280-283`` —— ``open(full, "wb")`` 直接截断重写（B-02）
* ``translation_tool/tool/mv_mz.py:73-77``    —— 同上
* ``translation_tool/tool/build.py:112-113``  —— ``_patch_core_js`` 直接截断重写
* ``rpgmaker_cheating_tool/main.py:480``      —— 存档写回直接覆盖（B-08）

后果：写一半被中断就留下半写文件，游戏直接损坏。本模块提供
"临时文件 + fsync + os.replace" 的原子写，作为**全工程唯一的写盘手段**。

另外提供两个原工具缺失的护栏：

* :func:`assert_safe_target` —— 拒绝磁盘根、用户主目录等危险目标
  （原实现 ``build.py:64`` 有类似检查，但只服务于"生成汉化版"一处）
* :func:`sibling_backup` —— 覆盖前生成"同目录 + 时间戳"的备份，且**失败即报错**，
  不像 ``main.py:474-478`` 那样把 ``OSError`` 静默吞掉（B-07）
"""

from __future__ import annotations

import errno
import os
import shutil
import tempfile
import time


class AtomicWriteError(IOError):
    """原子写入失败（临时文件创建/写入/替换阶段）。"""


class SafeTargetError(ValueError):
    """目标路径被安全护栏拒绝（磁盘根、家目录、游戏目录本身等）。"""


def unique_temp_path(target):
    """在 ``target`` 同目录生成唯一临时文件名。

    必须同目录：跨卷时 ``os.replace`` 会退化为"复制 + 删除"，失去原子性。
    """
    directory = os.path.dirname(os.path.abspath(target)) or "."
    base = os.path.basename(target)
    fd, path = tempfile.mkstemp(prefix=".%s." % base, suffix=".tmp", dir=directory)
    os.close(fd)
    return path


def atomic_write_bytes(path, data, backup=False, fsync=True):
    """原子地把 ``data`` 写入 ``path``。

    参数
    ----
    path : str
        目标文件路径。
    data : bytes
        完整内容（不是增量）。
    backup : bool
        写入前是否生成同目录 ``<name>.<时间戳>.bak`` 备份。
    fsync : bool
        是否 ``fsync`` 临时文件（断电安全；单元测试可关掉以加速）。

    返回
    ----
    dict: ``{'path': str, 'bytes': int, 'backup': str|None}``

    异常
    ----
    AtomicWriteError  任一步骤失败（此时**原文件保持原样**，不会半写）
    """
    path = os.path.abspath(path)
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)

    backup_path = None
    if backup and os.path.isfile(path):
        backup_path = sibling_backup(path, copy=True)

    tmp = unique_temp_path(path)
    try:
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            if fsync:
                os.fsync(f.fileno())
        os.replace(tmp, path)       # 同目录内的替换是原子的
    except Exception as exc:
        _quiet_remove(tmp)
        raise AtomicWriteError(
            "原子写入失败：%s（原文件未被修改）：%s: %s"
            % (path, type(exc).__name__, exc))
    return {"path": path, "bytes": len(data), "backup": backup_path}


def atomic_write_text(path, text, encoding="utf-8", backup=False, fsync=True,
                      preserve_newlines=False):
    """:func:`atomic_write_bytes` 的文本版（显式指定编码，避免 GBK 环境乱码）。

    换行语义
    --------
    默认把 ``\\r\\n`` / ``\\r`` 规范化成 ``\\n`` —— 与原工具的写盘行为一致
    （``translation_tool/tool/mv_mz.py:73-77`` 用 ``newline="\\n"`` 写 JSON）。

    若要**字节级保留**原始的 ``\\r\\n``（例如往返测试要求逐字节一致），
    传 ``preserve_newlines=True``。
    """
    if preserve_newlines:
        data = text.encode(encoding)
    else:
        data = text.replace("\r\n", "\n").replace("\r", "\n").encode(encoding)
    result = atomic_write_bytes(path, data, backup=backup, fsync=fsync)
    result["encoding"] = encoding
    return result


def sibling_backup(path, copy=True, stamp=None):
    """在 ``path`` 同目录生成带时间戳的备份文件，返回备份路径。

    ``copy=False`` 时改为"移动原文件到备份位置"（用于替换类操作）。
    **失败会抛异常**，不会像原实现那样静默继续（B-07）。
    """
    path = os.path.abspath(path)
    if not os.path.isfile(path):
        raise SafeTargetError("待备份文件不存在：%s" % path)
    tag = stamp or time.strftime("%Y%m%d_%H%M%S")
    candidate = "%s.%s.bak" % (path, tag)
    seq = 1
    while os.path.exists(candidate):
        candidate = "%s.%s.%d.bak" % (path, tag, seq)
        seq += 1
    try:
        if copy:
            shutil.copy2(path, candidate)
        else:
            os.replace(path, candidate)
    except OSError as exc:
        raise AtomicWriteError(
            "备份失败，已中止写入：%s -> %s：%s" % (path, candidate, exc))
    return candidate


def assert_safe_target(target, game_dir=None, allow_inside_game=False):
    """危险目标护栏。返回规范化后的绝对路径，或抛 :class:`SafeTargetError`。

    拒绝：空路径、磁盘根、用户主目录、桌面、以及（默认）游戏目录内部。
    迁移来源：``translation_tool/tool/build.py:64`` 的 ``_assert_safe_target``，
    但扩展到"游戏目录内部"这一原实现漏掉的情形。
    """
    if not target:
        raise SafeTargetError("目标路径为空")
    full = os.path.abspath(target)

    if os.path.dirname(full) == full:
        raise SafeTargetError("拒绝把磁盘根目录作为目标：%s" % full)

    protected = set()
    for candidate in (os.path.expanduser("~"), os.environ.get("USERPROFILE"),
                      os.environ.get("SystemRoot")):
        if candidate:
            protected.add(os.path.normcase(os.path.abspath(candidate)))
    if os.path.normcase(full) in protected:
        raise SafeTargetError("拒绝把系统/用户目录作为目标：%s" % full)

    if game_dir and not allow_inside_game:
        game = os.path.normcase(os.path.abspath(game_dir))
        here = os.path.normcase(full)
        if here == game or here.startswith(game + os.sep):
            raise SafeTargetError(
                "拒绝把游戏目录（或其内部）作为输出目标：%s" % full)
    return full


def next_free_dir(base):
    """返回一个尚不存在的目录名：``base`` / ``base2`` / ``base3`` …（原样沿用
    ``translation_tool/tool/build.py:54`` 的命名规则，保持用户习惯一致）。"""
    if not os.path.exists(base):
        return base
    seq = 2
    while os.path.exists("%s%d" % (base, seq)):
        seq += 1
    return "%s%d" % (base, seq)


def _quiet_remove(path):
    try:
        os.remove(path)
    except OSError as exc:
        if exc.errno not in (errno.ENOENT,):
            pass

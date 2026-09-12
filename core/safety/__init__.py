# -*- coding: utf-8 -*-
"""安全层：原子写入、备份还原、目标护栏 —— 所有写回操作的统一入口。

@feature  none
@layer    core
@public   atomic, backup, builder, fontutil
@depends  core.paths, core.formats, core.marshal.value_model
@tested   tests/unit/test_atomic.py, tests/compat/test_build_backup.py
@footprint docs/MODULES.md#coresafety

硬约束（需求 §4.2）
------------------
* 任何写回/覆盖操作前必须备份，且备份位置、命名、还原方式在 UI 上可见可点
* 未修改的内容必须字节级原样保留
* 破坏性操作需二次确认
* 处理用户游戏目录时**默认只写副本**，覆盖原文件为高级选项

本包是这些约束的唯一落点：功能模块不得自行 ``open(path, "wb")``，
必须走 :mod:`core.safety.atomic`。

M2a 拆分（原为单个 vendored ``build.py``）
----------------------------------------
* :mod:`atomic`  —— 原子写 + 备份文件 + 目标护栏（无内部依赖）
* :mod:`backup`  —— 备份 / 还原 / 清单（**不依赖 formats**，切断循环依赖）
* :mod:`builder` —— 生成汉化版与字体应用的编排层（依赖 formats）
* :mod:`fontutil`—— 字体族名解析
"""

from __future__ import annotations

import importlib

#: 子模块清单（PEP 562 懒加载用）。
#:
#: 为什么不在这里直接 import：``builder`` 依赖 ``core.formats``，而
#: ``core.formats.*`` 又需要 ``core.safety.atomic``。若 ``core.safety`` 在被
#: 导入时立刻把 ``builder`` 拉进来，就会形成
#: ``formats.__init__ → mv_mz_data → safety.__init__ → builder → formats.mv_mz_data``
#: 的环（M2a 实测复现）。改成按需加载后，``from core.safety.atomic import X``
#: 只触发 atomic 子模块，环被切断。
_SUBMODULES = ("atomic", "fontutil", "backup", "builder")


def __getattr__(name):
    """PEP 562：``core.safety.builder`` 这类属性访问时才真正 import。"""
    if name in _SUBMODULES:
        module = importlib.import_module("." + name, __name__)
        globals()[name] = module
        return module
    raise AttributeError("module %r has no attribute %r" % (__name__, name))


def __dir__():
    return sorted(set(list(globals()) + list(_SUBMODULES)))


__all__ = list(_SUBMODULES)

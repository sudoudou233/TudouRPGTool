# -*- coding: utf-8 -*-
"""安全层：原子写入、备份还原、目标护栏 —— 所有写回操作的统一入口。

@feature  none
@layer    core
@public   atomic, backup, fontutil
@depends  core.paths, core.marshal.value_model
@tested   tests/unit/test_atomic.py
@footprint docs/MODULES.md#coresafety

硬约束（需求 §4.2）
------------------
* 任何写回/覆盖操作前必须备份，且备份位置、命名、还原方式在 UI 上可见可点
* 未修改的内容必须字节级原样保留
* 破坏性操作需二次确认
* 处理用户游戏目录时**默认只写副本**，覆盖原文件为高级选项

本包是这些约束的唯一落点：功能模块不得自行 ``open(path, "wb")``，
必须走 :mod:`core.safety.atomic`。
"""

from __future__ import annotations

# 显式重导出（F-05 会核对 @public 声明的名字真实存在）。
from . import atomic, backup, fontutil  # noqa: E402,F401

__all__ = ["atomic", "backup", "fontutil"]

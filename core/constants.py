# -*- coding: utf-8 -*-
"""RPG Maker 全版本常量：引擎标识、存档命名规则、界面文案。

@feature  none
@layer    core
@public   ENGINES, ENGINE_ORDER, SAVE_PATTERNS, PARAMS, PARAM_LABELS, engine_label
@depends  (stdlib only)
@tested   tests/unit/test_config.py
@footprint docs/MODULES.md#coreconstants

本模块是"引擎相关常量"的唯一真源。历史上这些常量在两个工具里各写一份：
  - rpgmaker_cheating_tool/engines.py:6   ENGINES
  - rpgmaker_cheating_tool/engines.py:15  SAVE_PATTERNS
  - rpgmaker_cheating_tool/rpgdata.py:180 PARAMS（全仓零引用的死常量）
  - rpgmaker_cheating_tool/mvdata.py:100  PARAMS（同上，与上一份逐字相同）
本模块把它们收敛为一份，消除重复。
"""

from __future__ import annotations

#: 引擎标识 -> 中文显示名。顺序即界面呈现顺序。
ENGINES = {
    "mz": "RPG Maker MZ",
    "mv": "RPG Maker MV",
    "vxace": "RPG Maker VX Ace",
    "vx": "RPG Maker VX",
    "xp": "RPG Maker XP",
    "2k3": "RPG Maker 2000/2003",
}

#: 界面/报表里固定使用的引擎排列顺序（从新到旧）。
ENGINE_ORDER = ("mz", "mv", "vxace", "vx", "xp", "2k3")

#: 识别得到的"数据目录"里，用来识别该引擎的数据文件扩展名。
DATA_EXTS = {
    "mz": ".json",
    "mv": ".json",
    "vxace": ".rvdata2",
    "vx": ".rvdata",
    "xp": ".rxdata",
    "2k3": ".ldb",
}

#: 引擎 -> (存档文件名正则, 人类可读的通配形式)
#: 来源：rpgmaker_cheating_tool/engines.py:15-21（原样保留，含 MV/MZ 的 file*.rpgsave 命名）。
SAVE_PATTERNS = {
    "vxace": (r"^Save\d+\.rvdata2$", "Save*.rvdata2"),
    "vx": (r"^Save\d+\.rvdata$", "Save*.rvdata"),
    "xp": (r"^Save\d+\.rxdata$", "Save*.rxdata"),
    "mv": (r"^file\d+\.rpgsave$", "file*.rpgsave"),
    "mz": (r"^file\d+\.rmmzsave$", "file*.rmmzsave"),
    "2k3": (r"^Save\d+\.lsd$", "Save*.lsd"),
}

#: 存档文件扩展名（写"另存为"对话框的过滤器用）。
SAVE_EXTS = {
    "vxace": ".rvdata2",
    "vx": ".rvdata",
    "xp": ".rxdata",
    "mv": ".rpgsave",
    "mz": ".rmmzsave",
    "2k3": ".lsd",
}

#: 角色 8 项属性加成的索引顺序（RGSS 与 MV/MZ 通用）。
PARAMS = ("最大HP", "最大MP", "攻击", "防御", "魔攻", "魔防", "速度", "幸运")

PARAM_LABELS = {i: name for i, name in enumerate(PARAMS)}

#: 支持的引擎（可读写）。其余引擎只识别不修改。
SUPPORTED_ENGINES = ("mz", "mv", "vxace", "vx", "xp")

#: 只识别、不支持修改的引擎。
RECOGNIZE_ONLY_ENGINES = ("2k3",)


def engine_label(engine):
    """返回引擎的中文显示名；未知引擎返回原始标识。"""
    if not engine:
        return "未知引擎"
    return ENGINES.get(engine, str(engine))


def is_supported(engine):
    """该引擎是否支持读写。"""
    return engine in SUPPORTED_ENGINES

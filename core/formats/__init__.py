# -*- coding: utf-8 -*-
"""格式编解码层：MV/MZ 的 JSON、RGSS 的 Ruby Marshal 存档、LZString 压缩。

@feature  none
@layer    core
@public   lzstring, mv_mz_data, rgss_data, mv_save, rgss_save
@depends  core.textutil, core.marshal
@tested   tests/compat/test_formats_compat.py
@footprint docs/MODULES.md#coreformats

分工
----
* ``mv_mz_data``  MV/MZ **游戏数据**（``data/*.json``，含加密包装）提取与写回
* ``rgss_data``   VX Ace / XP **游戏数据**（``Data/*.rvdata2|rxdata``）提取与写回
* ``mv_save``     MV/MZ **存档**（``file*.rpgsave`` LZString / ``file*.rmmzsave`` zlib）
* ``rgss_save``   RGSS **存档**（``Save*.rvdata2|rvdata|rxdata``）
* ``lzstring``    MV 存档所用的 LZString 纯 Python 实现

收敛目标（需求 §3.3 第三类重复）
-------------------------------
``mv_mz_data`` 与 ``mv_save`` 目前各自实现了 JSON / 压缩 / 编码约定的处理
（``utf-8-sig``、JsonEx 元数据 ``@c/@a/@/@r``、写回风格）。M2b 抽出共享的
``core/formats/jsoncodec.py``（JSON + LZString + zlib + 加密包装），
两侧业务层保持独立。验收：一个实现，两条路径共用，两侧测试全绿。
"""

from __future__ import annotations

#: 收敛状态：'pending'（尚未抽出共享 jsoncodec） / 'merged'
CONVERGENCE_STATUS = "pending"

__all__ = ["lzstring", "mv_mz_data", "rgss_data", "mv_save", "rgss_save",
           "CONVERGENCE_STATUS"]

# 显式重导出（check_footprint 的 F-05 会核对 @public 声明的名字真实存在）。
from . import lzstring, mv_mz_data, mv_save, rgss_data, rgss_save  # noqa: E402,F401

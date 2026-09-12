# -*- coding: utf-8 -*-
"""格式编解码层：MV/MZ 的 JSON、RGSS 的 Ruby Marshal 存档、LZString 压缩。

@feature  none
@layer    core
@public   jsoncodec, lzstring, mv_mz_data, rgss_data, mv_save, rgss_save
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

收敛结果（需求 §3.3 第三类重复）—— **M2b 已完成**
------------------------------------------------
``mv_mz_data`` 与 ``mv_save`` 曾各自实现 JSON / 压缩 / 编码约定的处理。
M2b 已把**共同约定**收敛到 :mod:`core.formats.jsoncodec`：

* JSON 两种风格（游戏数据用缩进、存档用紧凑）
* ``utf-8-sig`` BOM 容忍与"坏 JSON 必须抛错"的读法
* JsonEx 元数据键 ``@c/@a/@/@r`` 的唯一真源
* 加密包装 ``{"uid","bid","data"}`` 的密钥派生与异或流加解密
* LZString / zlib 的压缩与**按内容**判别

两侧业务层只保留"提取哪些字段 / 改哪个键"的规则。
验收：包装与压缩各只有一份实现 —— 由
``tests/unit/test_jsoncodec.py::TestConvergence`` 静态断言守护（含"禁止在
mv_mz_data 里再写一遍 base64/密钥派生/压缩调用"）。
"""

from __future__ import annotations

#: 收敛状态：'pending'（尚未抽出共享 jsoncodec） / 'merged'（已收敛）
CONVERGENCE_STATUS = "merged"

__all__ = ["jsoncodec", "lzstring", "mv_mz_data", "rgss_data", "mv_save", "rgss_save",
           "CONVERGENCE_STATUS"]

# 显式重导出（check_footprint 的 F-05 会核对 @public 声明的名字真实存在）。
from . import jsoncodec, lzstring, mv_mz_data, mv_save, rgss_data, rgss_save  # noqa: E402,F401

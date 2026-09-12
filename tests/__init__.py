# -*- coding: utf-8 -*-
"""测试套件：单元 / 兼容 / 功能 / 集成 / 本地样本 五层。

@feature  none
@layer    tests
@public   (包标记)
@depends  core.*, features.*, ui.*
@tested   tests/run_all.py
@footprint docs/DEVLOG.md

分层（docs/DECISIONS.md ADR-005）
--------------------------------
* ``unit/``        纯单元测试，零外部依赖，任何机器可跑
* ``compat/``      原两个工具的既有断言（合并后的兼容性验证，防止迁移丢功能）
* ``features/``    每个功能模块的自有测试（需求 §5.1 要求）
* ``integration/`` 启动 HTTP 服务、跑完整请求链路的集成测试
* ``local/``       真实游戏样本测试（**样本不入库**，靠环境变量指定）

统一入口：``python tests/run_all.py``
"""

from __future__ import annotations

__all__ = []

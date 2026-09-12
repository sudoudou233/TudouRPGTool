# -*- coding: utf-8 -*-
"""界面层：本地 Web UI（静态资源 + HTTP 服务）。

@feature  none
@layer    ui
@public   server, routes
@depends  core.*
@tested   tests/unit/test_server.py
@footprint docs/ARCHITECTURE.md#ui

依赖方向（由 tools/check_footprint.py 静态校验）
----------------------------------------------
``ui`` 可以 import ``core`` 与 ``features``；``core`` **不得** import ``ui``
或 ``features``。选择理由见 docs/DECISIONS.md ADR-001（Web 主壳）。

页面模块放 ``ui/web/pages/<id>.js``，由前端按 ``/api/pages`` 的声明动态
``import()`` 加载 —— 新增功能等于新增文件，不需要改前端主脚本。
"""

from __future__ import annotations

LAYER = "ui"

from . import routes, server  # noqa: E402,F401

__all__ = ["LAYER", "routes", "server"]

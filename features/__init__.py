# -*- coding: utf-8 -*-
"""features 包 —— 一个子目录 = 一个可插拔功能模块。

@feature  none
@layer    features
@public   LAYER, REQUIRED_FILE
@depends  (stdlib only)
@tested   tests/unit/test_registry.py
@footprint docs/ARCHITECTURE.md#features

契约（详见 core/registry.py 与 docs/FEATURES.md#contract）
--------------------------------------------------------
每个 ``features/<name>/`` 目录必须包含：

1. ``manifest.py``，暴露模块级 ``MANIFEST`` dict：必备字段
   ``id`` / ``name`` / ``icon`` / ``version`` / ``description``；
   可选 ``order`` / ``core_deps`` / ``api_prefix`` / ``pages`` / ``health`` / ``enabled``
2. 可选的 ``register(ctx)`` 函数：**唯一**装配入口，只能通过 ``ctx`` 登记
   路由与页面，不得直接修改 app 或 server 内部
3. ``tests/features/<name>/`` 自有测试（由 tools/check_footprint.py 校验存在）

新增功能的体验：新建 ``features/<name>/`` + ``manifest.py`` + 前端页面
``ui/web/pages/<page-id>.js``，界面导航自动出现该功能入口。
"""

from __future__ import annotations

LAYER = "features"

#: 约定：功能目录必须含此文件才会被 registry 发现
REQUIRED_FILE = "manifest.py"

__all__ = ["LAYER", "REQUIRED_FILE"]

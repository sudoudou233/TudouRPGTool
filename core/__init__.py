# -*- coding: utf-8 -*-
"""core 层：与界面完全无关的纯逻辑（引擎识别、格式编解码、安全、注册表）。

@feature  none
@layer    core
@public   __version__, LAYER
@depends  (stdlib only)
@tested   tests/unit/
@footprint docs/ARCHITECTURE.md#core

本层**不得** import ``ui`` 或任何 ``features`` 模块（依赖方向单向：
``features`` -> ``core``，``ui`` -> ``core`` + ``features`` 暴露的接口）。
``tools/check_footprint.py`` 会静态校验这一约束。
"""

from __future__ import annotations

__version__ = "2.0.0-dev"

#: 分层标识，check_footprint 与运行时自检共用。
LAYER = "core"

__all__ = [
    "__version__",
    "LAYER",
    "config",
    "constants",
    "context",
    "engines",
    "jobs",
    "paths",
    "registry",
]

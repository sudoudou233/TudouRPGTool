# -*- coding: utf-8 -*-
"""功能包标记（契约见 ``docs/FEATURES.md`` §2.1）。

@feature  selfcheck
@layer    features
@public   LAYER
@depends  (none)
@tested   tests/features/selfcheck/test_manifest.py
@footprint docs/FEATURES.md#selfcheck
"""

from __future__ import annotations

#: 本包所在分层（足迹校验会核对）
LAYER = "features"

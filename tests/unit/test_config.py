# -*- coding: utf-8 -*-
"""config / paths / constants / textutil / refbridge 的测试别名入口。

@feature  none
@layer    tests
@public   (无)
@depends  tests.unit.test_misc
@tested   (本文件即测试)
@footprint docs/DEVLOG.md
@note     为什么存在：各 core 模块的 docstring 声明了细粒度的 @tested 路径
          （如 tests/unit/test_config.py）。为了让"声明的测试确实存在"
          且不复制断言，这里把同一个测试类**再导出**一次，形成稳定入口。
          run_all.py 会按实际类对象去重，不会重复执行同一批用例。
"""

from __future__ import annotations

from tests.unit.test_misc import (  # noqa: F401
    TestConfig,
    TestConstants,
    TestPaths,
    TestRefbridge,
    TestTextutil,
)

__all__ = ["TestConfig", "TestConstants", "TestPaths", "TestRefbridge",
           "TestTextutil"]

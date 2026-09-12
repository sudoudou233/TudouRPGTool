# -*- coding: utf-8 -*-
"""Ruby Marshal 编解码层 —— 当前含两份实现，M2b 收敛为一份。

@feature  none
@layer    core
@public   doc_model, value_layer
@depends  (stdlib only)
@tested   tests/compat/test_marshal_compat.py
@footprint docs/MODULES.md#coremarshal

现状（M1）
---------
本包暂时包含两份历史上的独立实现，**这是已知的临时状态**，不是最终形态：

* :mod:`core.marshal.doc_model` —— 文档模型（22 个 Node 类，``Node.raw`` +
  ``dirty`` 增量字节保真，支持多流与 XP/VX 标准模式）。来自修改工具
  ``rmarshal.py``。**M2b 的收敛主体。**
* :mod:`core.marshal.value_model` —— 值模型（13 个 ``RM*`` 类，编码感知，
  可直接从 Python 值构造并 dump）。来自翻译工具 ``tool/marshal.py``。
  **M2b 降为对象门面。**

收敛计划见 ``docs/DECISIONS.md`` 的 ADR-004 与 ``docs/ROADMAP.md``。
验收硬指标（需求 §3.3）：合并后 Ruby Marshal 只有一份实现，且两侧原有
roundtrip 断言（共 240+ 个真实文件零漂移）全部通过。

为什么 M1 不直接收敛
------------------
收敛必须先修两个 P0 缺陷（``doc_model`` 的 ``Parser._fixnum`` 重复定义导致
XP/VX 回写字节漂移；值模型的 bignum 写回崩溃），而 M1 的完成判据是
"空壳可启动 + 足迹校验通过"。带病收敛会把缺陷固化，因此按里程碑拆到 M2a/M2b。
"""

from __future__ import annotations

#: 收敛状态：'pending'（仍有两份实现） / 'merged'（已收敛为一份）
CONVERGENCE_STATUS = "merged"

# 显式重导出，使 `from core.marshal import doc_model` 与
# `core.marshal.doc_model` 两种写法都成立（check_footprint 的 F-05 会核对
# @public 里声明的名字在本模块中真实存在，因此这里必须真的 import）。
from . import doc_model, value_layer  # noqa: E402,F401

__all__ = ["doc_model", "value_layer", "CONVERGENCE_STATUS"]

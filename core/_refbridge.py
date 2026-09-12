# -*- coding: utf-8 -*-
"""参考工具桥接层 —— **M2b 收敛完成后整体删除**。

@feature  none
@layer    core
@public   ReferenceUnavailable, load_reference, reference_status
@depends  core.paths
@tested   tests/unit/test_refbridge.py
@footprint docs/MODULES.md#core_refbridge
@note     临时模块。M2b 把 marshal / formats / safety 收敛进本工程后，
          本文件与所有 import 它的代码一并删除。删除条件见 docs/ROADMAP.md。

为什么需要它
-----------
M1 的目标是"骨架可启动 + 足迹校验通过"，而不是立刻重写 700 行的 Ruby
Marshal。为避免在 M1 就产生"同一职责的两份实现"，本模块**不复制**参考
工具的代码，而是按需 import 它，并把这件事**显式化**：

* 每次使用都会在 :func:`load_reference` 的返回里带上来源路径；
* ``docs/MODULES.md`` 与 ``docs/ROADMAP.md`` 登记了所有借用的模块与删除条件；
* ``tools/check_footprint.py`` 会检查"是否还有代码在借用参考实现"并给出提示。

两个参考工具的 import 约定不同，必须分别处理：

* ``rpgmaker_translation_tool``：包内使用绝对 import（``from tool.marshal import``），
  需要把**工具目录**放进 ``sys.path``，导入名为 ``tool.xxx``。
* ``rpgmaker_cheating_tool``：平铺模块 + 平铺 import（``import rmarshal``），
  需要把**工具目录本身**放进 ``sys.path``，导入名为 ``rmarshal``。
"""

from __future__ import annotations

import importlib
import sys

from . import paths

#: 借用登记表：逻辑名 -> (参考工具 kind, 模块名, 用途)
#: M2b 收敛时逐条把 value 换成工程内实现，然后删除本模块。
REFERENCES = {
    # --- 修改工具（cheating_tool，平铺 import） ---
    "rmarshal": ("cheats", "rmarshal", "Ruby Marshal 文档模型（增量字节保真）"),
    "rpgdata": ("cheats", "rpgdata", "RGSS(VX Ace/VX/XP) 存档与数据表读写"),
    "mvdata": ("cheats", "mvdata", "MV/MZ 存档与数据表读写"),
    "lzstring": ("cheats", "lzstring", "MV 存档 LZString 编解码"),
    # 仅用于**回归对照**：core/engines.py 已是合并后的唯一实现，
    # 这里保留参考版是为了断言"新实现与两个旧实现的判定一致"。
    "engines": ("cheats", "engines", "（对照用）旧引擎识别实现"),
    # --- 翻译工具（translation_tool，包内绝对 import） ---
    "tool.marshal": ("translate", "tool.marshal", "Ruby Marshal 值模型（编码感知）"),
    "tool.mv_mz": ("translate", "tool.mv_mz", "MV/MZ 游戏数据 JSON 提取与写回"),
    "tool.vxace": ("translate", "tool.vxace", "VX Ace/XP 数据提取与写回"),
    "tool.textutil": ("translate", "tool.textutil", "控制码切分与还原"),
    "tool.translators": ("translate", "tool.translators", "四个翻译引擎适配器"),
    "tool.fontutil": ("translate", "tool.fontutil", "字体族名解析"),
    "tool.session": ("translate", "tool.session", "翻译会话与进度持久化"),
    "tool.build": ("translate", "tool.build", "生成汉化版 / 备份 / 还原 / 字体注入"),
    "tool.engines": ("translate", "tool.engines", "（对照用）旧引擎识别实现"),
}

#: 需要 ``sys.path`` 指向参考工具根目录的 kind（而非其父目录）。
_KIND_DIRECT = ("cheats", "translate")


class ReferenceUnavailable(RuntimeError):
    """参考工具目录不存在或缺少目标模块。"""


def _ensure_path(kind):
    """把参考工具目录加入 ``sys.path``（幂等），返回该目录。"""
    tool_dir = paths.reference_tool(kind)
    if not paths.reference_available(kind):
        raise ReferenceUnavailable(
            "参考工具目录不存在：%s\n"
            "若已迁移到别的机器，请设置环境变量 %s 指向两个参考工具的父目录。"
            % (tool_dir, paths.ENV_REFERENCE_ROOT))
    if tool_dir not in sys.path:
        sys.path.insert(0, tool_dir)
    return tool_dir


def load_reference(name):
    """按逻辑名加载参考实现并返回模块对象。

    参数
    ----
    name : str
        :data:`REFERENCES` 的键，例如 ``'rmarshal'`` 或 ``'tool.marshal'``。

    异常
    ----
    KeyError                未登记的名字（防止随手 import 绕过登记表）
    ReferenceUnavailable    参考目录/模块缺失
    """
    if name not in REFERENCES:
        raise KeyError(
            "未登记的参考实现 %r。新增借用必须先在 core/_refbridge.py 的 "
            "REFERENCES 里登记（便于 M2b 逐条收敛与 check_footprint 检查）。" % (name,))
    kind, module_name, _purpose = REFERENCES[name]
    _ensure_path(kind)
    try:
        return importlib.import_module(module_name)
    except Exception as exc:
        raise ReferenceUnavailable(
            "导入参考实现 %s（来自 %s）失败：%s: %s"
            % (module_name, paths.reference_tool(kind), type(exc).__name__, exc))


def reference_status():
    """返回参考实现的可用性报告，供 ``/api/health`` 与足迹校验展示。"""
    report = {"reference_root": paths.reference_root(), "tools": {}, "entries": []}
    for kind in sorted(set(v[0] for v in REFERENCES.values())):
        report["tools"][kind] = {
            "path": paths.reference_tool(kind),
            "available": paths.reference_available(kind),
        }
    for name in sorted(REFERENCES):
        kind, module_name, purpose = REFERENCES[name]
        entry = {"name": name, "kind": kind, "module": module_name,
                 "purpose": purpose, "loaded": module_name in sys.modules,
                 "available": paths.reference_available(kind)}
        report["entries"].append(entry)
    report["pending"] = len(REFERENCES)
    return report


def pending_references():
    """尚未收敛的借用清单（M2b 的待办来源）。"""
    return sorted(REFERENCES)

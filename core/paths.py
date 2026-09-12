# -*- coding: utf-8 -*-
"""路径解析：工程根、数据目录、参考工具目录 —— 全工程唯一真源。

@feature  none
@layer    core
@public   project_root, data_dir, sessions_dir, web_dir, logs_dir, reference_roots,
          reference_root, set_reference_root, ensure_dir
@depends  (stdlib only)
@tested   tests/unit/test_paths.py
@footprint docs/MODULES.md#corepaths

为什么单独成模块
--------------
原翻译工具用 ``TOOL_DIR = os.path.dirname(os.path.dirname(__file__))``
（tool/server.py:24）把路径写死在模块级，导致无法多实例、无法在测试中隔离；
``WEB_DIR`` / ``SESSIONS_DIR`` 同样是模块级常量（tool/server.py:25-26）。
本模块改为**函数式解析 + 环境变量覆盖**，所有调用方通过函数取路径，
测试可用环境变量重定向到临时目录。
"""

from __future__ import annotations

import os

#: 工程根 = 本文件所在目录的上一级（``<root>/core/paths.py`` -> ``<root>``）。
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)

#: 环境变量名：覆盖工程根（测试用）。
ENV_ROOT = "TUDOU_RPGTOOL_ROOT"

#: 环境变量名：覆盖两个参考工具的父目录。
ENV_REFERENCE_ROOT = "TUDOU_RPGTOOL_REFERENCE_ROOT"

#: 环境变量名：指定真实游戏样本目录（仅本地测试用，不入库）。
ENV_SAMPLES = "TUDOU_RPGTOOL_SAMPLES"

#: 参考工具的默认父目录（只读参照，永不修改）。
DEFAULT_REFERENCE_ROOT = r"D:\test1\rpgtool"

#: 参考工具子目录名。
REFERENCE_TOOLS = {
    "translate": "rpgmaker_translation_tool",
    "cheats": "rpgmaker_cheating_tool",
}

#: 运行时数据目录名（已被 .gitignore 忽略）。
DATA_DIRNAME = "runtime"
SESSIONS_DIRNAME = "sessions"
LOGS_DIRNAME = "logs"


def project_root():
    """返回工程根绝对路径。可用环境变量 ``TUDOU_RPGTOOL_ROOT`` 覆盖。"""
    override = os.environ.get(ENV_ROOT)
    if override:
        return os.path.abspath(override)
    return _ROOT


def core_dir():
    """``<root>/core``。"""
    return os.path.join(project_root(), "core")


def features_dir():
    """``<root>/features`` —— 功能模块的自动发现根目录。"""
    return os.path.join(project_root(), "features")


def ui_dir():
    """``<root>/ui``。"""
    return os.path.join(project_root(), "ui")


def web_dir():
    """``<root>/ui/web`` —— 静态资源根目录。"""
    return os.path.join(ui_dir(), "web")


def tests_dir():
    """``<root>/tests``。"""
    return os.path.join(project_root(), "tests")


def tools_dir():
    """``<root>/tools`` —— 开发期脚本（足迹校验等）。"""
    return os.path.join(project_root(), "tools")


def docs_dir():
    """``<root>/docs`` —— 足迹文档。"""
    return os.path.join(project_root(), "docs")


# ---------------------------------------------------------------------------
# 运行时数据（可写，已被 .gitignore 忽略）
# ---------------------------------------------------------------------------
def data_dir():
    """``<root>/runtime`` —— 会话、日志、缓存的统一根。

    可用环境变量 ``TUDOU_RPGTOOL_DATA`` 覆盖（测试隔离用）。
    """
    override = os.environ.get("TUDOU_RPGTOOL_DATA")
    if override:
        return os.path.abspath(override)
    return os.path.join(project_root(), DATA_DIRNAME)


def sessions_dir():
    """``<root>/runtime/sessions`` —— 断点续传进度。"""
    return os.path.join(data_dir(), SESSIONS_DIRNAME)


def logs_dir():
    """``<root>/runtime/logs``。"""
    return os.path.join(data_dir(), LOGS_DIRNAME)


def ensure_dir(path):
    """确保目录存在并返回它（幂等）。"""
    if not path:
        return None
    os.makedirs(path, exist_ok=True)
    return path


# ---------------------------------------------------------------------------
# 参考工具（只读）
# ---------------------------------------------------------------------------
def reference_root():
    """两个参考工具的父目录。

    默认 ``D:\\test1\\rpgtool``；可用环境变量
    ``TUDOU_RPGTOOL_REFERENCE_ROOT`` 覆盖（便于换机/回归对照）。
    """
    override = os.environ.get(ENV_REFERENCE_ROOT)
    if override:
        return os.path.abspath(override)
    return DEFAULT_REFERENCE_ROOT


def reference_roots():
    """返回 ``{'translate': <path>, 'cheats': <path>}``（不论是否存在）。"""
    root = reference_root()
    return {key: os.path.join(root, name) for key, name in REFERENCE_TOOLS.items()}


def reference_tool(kind):
    """取单个参考工具目录路径；``kind`` 为 ``'translate'`` 或 ``'cheats'``。"""
    if kind not in REFERENCE_TOOLS:
        raise KeyError("未知参考工具: %r（可选 %s）"
                       % (kind, "/".join(sorted(REFERENCE_TOOLS))))
    return os.path.join(reference_root(), REFERENCE_TOOLS[kind])


def reference_available(kind):
    """参考工具目录是否存在且可读（M2b 收敛完成后不再依赖它）。"""
    path = reference_tool(kind)
    return os.path.isdir(path)


def samples_root():
    """真实游戏样本根目录（仅本地测试）。未配置时返回 None。

    样本**不入库**：仓库内只保存路径清单与哈希，见 docs/DECISIONS.md ADR-005。
    """
    override = os.environ.get(ENV_SAMPLES)
    if override:
        return os.path.abspath(override)
    default = r"D:\gamess"
    return default if os.path.isdir(default) else None

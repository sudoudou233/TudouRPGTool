# -*- coding: utf-8 -*-
"""翻译功能模块的自我描述与注册入口。

@feature  translate
@layer    features
@public   MANIFEST, register, health
@depends  core.engines, core.formats, core.safety, core.textutil
@tested   tests/features/translate/
@footprint docs/FEATURES.md#translate

这是"新增功能只插一块"的契约样板：本文件只做三件事 —— 描述自己、
声明页面、登记路由。**不得**直接修改 app 或 server 内部。
"""

from __future__ import annotations

from .routes import TranslateService, register_routes

#: 功能自描述。必备字段：id / name / icon / version / description。
MANIFEST = {
    "id": "translate",
    "name": "文本翻译",
    "icon": "文",
    "version": "0.3.0",
    "description": "扫描游戏内全部文本，批量翻译后生成汉化版；支持 MV / MZ / VX Ace / XP 与加密 JSON 包装。",
    "order": 10,

    #: 依赖的 core 能力（供启动自检与足迹校验核对）
    "core_deps": (
        "core.engines",
        "core.textutil",
        "core.formats.mv_mz_data",
        "core.formats.rgss_data",
        "core.marshal.doc_model",
        "core.safety.backup",
        "core.safety.atomic",
        "core.safety.builder",
        "core.safety.fontutil",
    ),

    #: API 命名空间前缀（本模块登记的路由都应以此开头）
    "api_prefix": "/api/translate",

    #: 前端页面：每个页面一个 js 模块，前端动态 import 渲染。
    #: 新增功能 = 新增文件 + 在这里加一条，不需要改前端主脚本。
    "pages": (
        {
            "id": "translate",
            "title": "文本翻译",
            "icon": "文",
            "module": "translate",
            "order": 10,
        },
    ),

    #: 健康检查函数（见文件末尾 health）
    "health": None,     # 在下方赋值（避免前向引用）
    "enabled": True,
}


def register(ctx):
    """把翻译功能装配进应用。

    M3a 起这里只做两件事：**构造功能自己的服务对象**（持有会话状态）、
    **把路由登记委托给 routes 模块**。真正的业务链路在
    :mod:`features.translate.routes`，本文件保持"描述自己"的薄壳形态 ——
    这是"新增功能只插一块"的样板，后续里程碑不应把业务代码搬回来。

    本函数**只通过 ctx 暴露的接口**操作，不触碰 app / server 内部。
    """
    service = TranslateService(ctx)
    count = register_routes(ctx, service)
    ctx.page(MANIFEST["pages"][0])
    return "registered (%d routes)" % count


def health():
    """翻译功能的健康检查：core 依赖是否都能 import + 关键能力可用。"""
    import importlib
    missing = []
    for name in MANIFEST["core_deps"]:
        try:
            importlib.import_module(name)
        except Exception as exc:
            missing.append("%s (%s: %s)" % (name, type(exc).__name__, exc))
    if missing:
        return {"status": "error", "detail": "缺少 core 依赖：" + "; ".join(missing)}
    problems = []
    # 有出网能力才有"批量翻译"；没有的话功能是残的，必须报出来。
    try:
        from . import translators
        for kind in ("google", "openai", "ollama", "deepl"):
            translators.build_translator({"engine": kind, "api_key": "x"})
    except Exception as exc:
        problems.append("翻译引擎适配器不可用：%s: %s" % (type(exc).__name__, exc))
    if problems:
        return {"status": "error", "detail": "；".join(problems)}
    return {"status": "ok",
            "detail": "core 依赖齐全（%d 项）；4 个翻译引擎适配器可用"
                      % len(MANIFEST["core_deps"])}


MANIFEST["health"] = health

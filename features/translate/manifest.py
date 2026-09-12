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

#: 功能自描述。必备字段：id / name / icon / version / description。
MANIFEST = {
    "id": "translate",
    "name": "文本翻译",
    "icon": "文",
    "version": "0.1.0",
    "description": "扫描游戏内全部文本，批量翻译后生成汉化版；支持 MV / MZ / VX Ace / XP 与加密 JSON 包装。",
    "order": 10,

    #: 依赖的 core 能力（供启动自检与足迹校验核对）
    "core_deps": (
        "core.engines",
        "core.textutil",
        "core.formats.mv_mz_data",
        "core.formats.rgss_data",
        "core.marshal.value_model",
        "core.safety.backup",
        "core.safety.atomic",
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

    M1 阶段只登记路由占位与页面，真正的扫描/翻译/生成链路在 M3a 接线。
    本函数**只通过 ctx 暴露的接口**操作，不触碰 app / server 内部。
    """
    state = {"feature": "translate", "status": "skeleton",
             "detail": "M1 骨架：功能已注册，业务链路在 M3a 接线"}

    @ctx.get("/api/translate/status", name="translate_status")
    def translate_status(request=None):
        """翻译功能自身的状态（M1 为骨架占位）。"""
        return dict(state)

    @ctx.get("/api/translate/providers", name="translate_providers")
    def translate_providers(request=None):
        """列出可用的翻译引擎适配器（来自 vendored translators 模块）。"""
        from . import translators
        return {
            "providers": [
                {"id": "google", "name": "Google 翻译",
                 "need_key": False, "note": "免费接口，无需密钥"},
                {"id": "openai", "name": "OpenAI 兼容接口",
                 "need_key": True, "note": "可填 OpenAI / DeepSeek / Kimi / Qwen 等"},
                {"id": "ollama", "name": "本地 Ollama",
                 "need_key": False, "note": "默认 http://localhost:11434/v1"},
                {"id": "deepl", "name": "DeepL",
                 "need_key": True, "note": "需要 DeepL API Key"},
            ],
            "module_loaded": bool(translators),
            "skeleton": True,
        }

    ctx.page(MANIFEST["pages"][0])
    return "registered (skeleton)"


def health():
    """翻译功能的健康检查：core 依赖是否都能 import。"""
    import importlib
    missing = []
    for name in MANIFEST["core_deps"]:
        try:
            importlib.import_module(name)
        except Exception as exc:
            missing.append("%s (%s: %s)" % (name, type(exc).__name__, exc))
    if missing:
        return {"status": "error", "detail": "缺少 core 依赖：" + "; ".join(missing)}
    return {"status": "ok",
            "detail": "core 依赖齐全（%d 项）；功能链路待 M3a 接线"
                      % len(MANIFEST["core_deps"])}


MANIFEST["health"] = health

# -*- coding: utf-8 -*-
"""存档与数据修改功能模块的自我描述与注册入口。

@feature  cheats
@layer    features
@public   MANIFEST, register, health
@depends  core.engines, core.formats.mv_save, core.formats.rgss_save, core.safety
@tested   tests/features/cheats/
@footprint docs/FEATURES.md#cheats

迁移说明：原工具是 tkinter 桌面 GUI（``rpgmaker_cheating_tool/main.py``，494 行，
GUI 与业务逻辑混在一个类里）。按 docs/DECISIONS.md ADR-001，**逻辑层迁移、
界面层重写**为 Web 页面。
"""

from __future__ import annotations

MANIFEST = {
    "id": "cheats",
    "name": "存档修改",
    "icon": "改",
    "version": "0.1.0",
    "description": "读取存档并修改金币、步数、道具/武器/防具数量、角色属性与技能、开关与变量；保存前自动备份。",
    "order": 20,

    "core_deps": (
        "core.engines",
        "core.constants",
        "core.formats.mv_save",
        "core.formats.rgss_save",
        "core.formats.lzstring",
        "core.marshal.doc_model",
        "core.safety.atomic",
    ),

    "api_prefix": "/api/cheats",

    "pages": (
        {
            "id": "cheats",
            "title": "存档修改",
            "icon": "改",
            "module": "cheats",
            "order": 20,
        },
    ),

    "health": None,     # 见下方赋值
    "enabled": True,
}


def register(ctx):
    """把修改功能装配进应用（M1 骨架；业务链路在 M3b 接线）。"""
    state = {"feature": "cheats", "status": "skeleton",
             "detail": "M1 骨架：功能已注册，业务链路在 M3b 接线"}

    @ctx.get("/api/cheats/status", name="cheats_status")
    def cheats_status(request=None):
        """修改功能自身的状态（M1 为骨架占位）。"""
        return dict(state)

    @ctx.post("/api/cheats/detect", name="cheats_detect")
    def cheats_detect(request=None):
        """识别游戏目录的引擎并列出存档。

        M1 已可用：走的是 core.engines（唯一实现），因此这条链路在 M1
        就能端到端验证引擎识别与存档发现。
        """
        from core import engines
        data = getattr(request, "data", None) or {}
        game_dir = (data.get("dir") or "").strip()
        if not game_dir:
            return {"ok": False, "error": "请提供游戏目录 dir"}
        info = engines.detect(game_dir)
        if not info.get("engine"):
            return {"ok": False, "error": info.get("error") or "未能识别引擎"}
        saves = engines.list_saves(info, game_dir)
        return {
            "ok": True,
            "engine": info["engine"],
            "label": info["label"],
            "summary": engines.describe(info),
            "data_dir": info["data_dir"],
            "save_dir": info["save_dir"],
            "save_ext": info["ext"],
            "supported": info["supported"],
            "match": info["match"],
            "saves": saves,
            "save_dirs": [{"dir": d, "files": f}
                          for d, f in engines.find_save_dirs(info, game_dir)],
        }

    ctx.page(MANIFEST["pages"][0])
    return "registered (skeleton)"


def health():
    """修改功能的健康检查。"""
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
            "detail": "core 依赖齐全（%d 项）；engine 识别链路 M1 已可用"
                      % len(MANIFEST["core_deps"])}


MANIFEST["health"] = health

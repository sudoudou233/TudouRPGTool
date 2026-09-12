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

M3b：本文件改成与 ``features/translate/manifest.py`` 同一形态的**薄壳** ——
只做"构造服务 + 委托路由 + 声明页面"，业务在 :mod:`features.cheats.routes`。
"""

from __future__ import annotations

from .routes import CheatsService, register_routes

#: 功能自描述。必备字段：id / name / icon / version / description。
MANIFEST = {
    "id": "cheats",
    "name": "存档修改",
    "icon": "改",
    "version": "0.3.0",
    "description": "读取存档并修改金币、步数、道具/武器/防具数量、角色属性与技能、开关与变量；也能改游戏数据表（价格/攻击力/初始等级）；保存前自动备份。",
    "order": 20,

    "core_deps": (
        "core.engines",
        "core.constants",
        "core.formats.mv_save",
        "core.formats.rgss_save",
        "core.formats.mv_mz_data",
        "core.formats.rgss_data",
        "core.formats.lzstring",
        "core.marshal.doc_model",
        "core.marshal.value_layer",
        "core.safety.atomic",
        "core.safety.backup",
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
    """把修改功能装配进应用。

    与 translate 同一形态：构造功能自己的服务对象、把路由委托给 routes 模块。
    本函数**只通过 ctx 暴露的接口**操作，不触碰 app / server 内部。
    """
    service = CheatsService(ctx)
    count = register_routes(ctx, service)
    ctx.page(MANIFEST["pages"][0])
    return "registered (%d routes)" % count


def health():
    """修改功能的健康检查：core 依赖 + 两条读写链路真的能构造。"""
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
    # 数据字段规则表是 M3b 新增的"唯一真源"：空表 = 界面上一栏都没有
    try:
        from . import data_fields
        for engine, table in (("mv", data_fields.MV_FIELD_RULES),
                              ("vxace", data_fields.RGSS_FIELD_RULES)):
            if not table:
                problems.append("%s 的字段规则表为空" % engine)
            for fname, rules in table.items():
                for template, _label, kind in rules:
                    if kind not in data_fields.KIND_OF:
                        problems.append("%s/%s 的字段类型未知：%s"
                                        % (engine, fname, kind))
    except Exception as exc:
        problems.append("字段规则表不可用：%s: %s" % (type(exc).__name__, exc))
    if problems:
        return {"status": "error", "detail": "；".join(problems)}
    return {"status": "ok",
            "detail": "core 依赖齐全（%d 项）；MV/MZ 与 RGSS 的字段规则表各 %d 个文件"
                      % (len(MANIFEST["core_deps"]),
                         len(data_fields.MV_FIELD_RULES) + len(data_fields.RGSS_FIELD_RULES))}


MANIFEST["health"] = health

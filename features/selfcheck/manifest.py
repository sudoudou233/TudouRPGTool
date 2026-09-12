# -*- coding: utf-8 -*-
"""「环境自检」功能 —— 需求 §8-6 的**扩展性现场演示**。

@feature  selfcheck
@layer    features
@public   MANIFEST, register, health
@depends  core.paths, core.registry, core.marshal, core.formats
@tested   tests/features/selfcheck/test_manifest.py
@footprint docs/FEATURES.md#selfcheck

这个功能是干什么的
------------------
它把"运行环境现在是什么样"摊开给用户与评审者看：Python 版本、工程根目录、
已加载的功能、路由数、三类收敛状态、真实样本是否可用。
排查"为什么我这里不行"时，不用让对方开命令行敲一堆东西。

**它同时是需求 §8-6 的演示**（原文：「现场新增一个最小功能，只用契约规定的
方式即可让它出现在界面上」）。它一共只有三个文件：

    features/selfcheck/__init__.py     # 包标记
    features/selfcheck/manifest.py     # 本文件：MANIFEST + register(ctx)
    ui/web/pages/selfcheck.js          # 页面（导出 render）

而 **`app.py` / `ui/server.py` / `ui/web/index.html` / `ui/web/app.js`
一个字节都没有改动** —— 导航项、路由登记、页面加载全部自动发生。
证明这一点的方式是 `git diff --stat` 只显示这三个文件（外加测试与文档）。

刻意**不拆分 routes.py**：这个功能只有一个只读端点，拆成两个文件反而
增加了"读代码要先跳一次"的成本。契约只要求 `manifest.py` 里有
`MANIFEST` 与 `register(ctx)`，没有要求路由必须放在别的文件里 ——
`features/translate` 拆出 `routes.py` 是因为它有 17 个端点和会话状态。
"""

from __future__ import annotations

import platform
import sys

MANIFEST = {
    "id": "selfcheck",
    "name": "环境自检",
    "icon": "检",
    "version": "1.0.0",
    "description": "显示运行环境与装配结果：Python 版本、功能清单、路由数、三类收敛状态、真实样本可用性。",
    "order": 90,

    #: 依赖的 core 能力（启动自检与足迹校核用）
    "core_deps": (
        "core.paths",
        "core.registry",
        "core.constants",
        "core.engines",
        "core.marshal",
        "core.formats",
        "core.safety",
    ),

    "api_prefix": "/api/selfcheck",

    "pages": (
        {
            "id": "selfcheck",
            "title": "环境自检",
            "icon": "检",
            "module": "selfcheck",
            "order": 90,
        },
    ),

    "health": None,     # 见下方赋值
    "enabled": True,
}


def register(ctx):
    """按契约装配：登记路由 + 声明页面。**只能通过 ctx 操作。**"""
    from core import constants, paths

    from core import engines  # noqa: F401  （health 与报告都要用）

    @ctx.get("/api/selfcheck/report", name="selfcheck_report")
    def selfcheck_report(request=None):
        """一次返回全部环境信息（只读、无副作用）。"""
        from core import engines as engines_mod
        from core import formats
        from core import marshal as marshal_pkg
        from core import safety

        root = paths.project_root()
        convergence = {
            "engines": engines_mod.CONVERGENCE_STATUS,
            "formats": formats.CONVERGENCE_STATUS,
            "marshal": marshal_pkg.CONVERGENCE_STATUS,
        }
        convergence["all_merged"] = all(v == "merged"
                                        for v in convergence.values())
        report = {
            "ok": True,
            "python": {
                "version": sys.version.split()[0],
                "implementation": platform.python_implementation(),
                "executable": sys.executable,
                "platform": platform.platform(),
                "supports_3_8_syntax": sys.version_info >= (3, 8),
            },
            "paths": {
                "project_root": root,
                "data_dir": paths.data_dir(),
                "runtime_writable": _writable(paths.data_dir()),
                "reference_root": paths.reference_root(),
                "samples_root": paths.samples_root() or "",
            },
            "assembly": _assembly(ctx),
            # 三项都读各自模块的 CONVERGENCE_STATUS（**与 /api/health 同源**）：
            # 只在这里写死会让两个报告互相矛盾（M5 实测踩到）
            "convergence": convergence,
            "engines": {
                "supported": [constants.engine_label(e) + " (%s)" % e
                              for e in constants.SUPPORTED_ENGINES],
                "recognize_only": [constants.engine_label(e) + " (%s)" % e
                                   for e in constants.RECOGNIZE_ONLY_ENGINES],
            },
            "safety": {
                "modules": sorted(safety._SUBMODULES),
                "backup_prefix": getattr(__import__("core.safety.backup",
                                                    fromlist=["x"]),
                                         "BACKUP_PREFIX", ""),
            },
        }
        return report

    ctx.page(MANIFEST["pages"][0])
    return "registered (1 route)"


def _writable(path):
    """运行数据目录是否可写（写不了的话会话与日志都会失败）。"""
    import os
    try:
        os.makedirs(path, exist_ok=True)
        probe = os.path.join(path, ".selfcheck_probe")
        with open(probe, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(probe)
        return True
    except Exception:
        return False


def _assembly(ctx):
    """装配结果：功能清单、路由数、页面清单。"""
    registry_obj = getattr(getattr(ctx, "app", None), "registry", None)
    features = []
    if registry_obj is not None:
        features = [{"id": m.id, "name": m.name, "version": m.version,
                     "ok": m.ok} for m in registry_obj.all()]
    routes = ctx.router.routes()
    by_feature = {}
    for route in routes:
        key = route.feature or "(core)"
        by_feature[key] = by_feature.get(key, 0) + 1
    return {
        "features": features,
        "feature_count": len(features),
        "route_count": len(routes),
        "routes_by_feature": by_feature,
        "pages": [p.as_dict() for p in ctx.pages_sorted()],
    }


def health():
    """健康检查：core 依赖能 import + 关键能力可用。"""
    import importlib
    import os

    missing = []
    for name in MANIFEST["core_deps"]:
        try:
            importlib.import_module(name)
        except Exception as exc:
            missing.append("%s (%s: %s)" % (name, type(exc).__name__, exc))
    if missing:
        return {"status": "error", "detail": "缺少 core 依赖：" + "; ".join(missing)}

    from core import paths
    if not _writable(paths.data_dir()):
        return {"status": "error",
                "detail": "运行数据目录不可写：%s" % paths.data_dir()}
    if not os.path.isfile(os.path.join(paths.project_root(), "app.py")):
        return {"status": "error", "detail": "工程根看起来不对（缺少 app.py）"}
    return {"status": "ok",
            "detail": "core 依赖齐全（%d 项）；运行数据目录可写；共 %d 个功能"
                      % (len(MANIFEST["core_deps"]),
                         _registered_feature_count())}


def _registered_feature_count():
    from core import paths
    import os
    directory = paths.features_dir()
    if not os.path.isdir(directory):
        return 0
    return sum(1 for name in os.listdir(directory)
               if os.path.isfile(os.path.join(directory, name, "manifest.py")))


MANIFEST["health"] = health

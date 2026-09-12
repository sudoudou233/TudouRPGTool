# -*- coding: utf-8 -*-
"""界面无关但它们共用的核心路由：健康检查、功能清单、导航、任务查询。

@feature  none
@layer    ui
@public   register_core_routes
@depends  core.paths, core.registry, core.jobs, ui.server
@tested   tests/unit/test_server.py
@footprint docs/MODULES.md#uiroutes

这些路由不属任何功能模块，因此由 ui 层直接登记。功能模块自己的路由
一律通过 ``features/<name>/manifest.py`` 的 ``register(ctx)`` 登记 —— 这条
边界由 ``tools/check_footprint.py`` 静态校验（features 不得直接操作 router）。
"""

from __future__ import annotations

import platform
import sys
import time

from core import paths


def register_core_routes(ctx, app=None):
    """把核心路由登记到 ``ctx.router``。返回登记数量。"""

    @ctx.get("/api/health", name="health")
    def health(request=None):
        """整体健康检查：应用、注册表、任务队列、参考实现可用性。"""
        from core import _refbridge
        out = {
            "ok": True,
            "app": app.version_info() if app is not None else {"name": "unknown"},
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "registry": app.registry_report() if app is not None else {},
            "jobs": app.jobs.stats() if app is not None and app.jobs else {},
            "ui": app.server.health() if app is not None and app.server else {},
            "reference": _refbridge.reference_status(),
        }
        if app is not None:
            out["ok"] = bool(app.registry_report().get("ok", True))
        return out

    @ctx.get("/api/features", name="features")
    def features(request=None):
        """已加载的功能模块清单（manifest 元信息 + 加载结果 + 健康检查）。"""
        if app is None or app.registry is None:
            return {"ok": False, "error": "注册表未初始化", "features": []}
        items = []
        for module in app.registry.all():
            entry = module.nav_entry()
            # 健康检查可能失败，但不允许把接口本身拖垮
            try:
                entry["health"] = module.health()
            except Exception as exc:
                entry["health"] = {"status": "error",
                                   "detail": "%s: %s" % (type(exc).__name__, exc)}
            items.append(entry)
        return {
            "ok": True,
            "count": len(items),
            "errors": app.registry.errors,
            "features": items,
            "register_report": app.register_report,
        }

    @ctx.get("/api/nav", name="nav")
    def nav(request=None):
        """前端导航：按 order 排序的功能入口与被禁用的模块。"""
        if app is None or app.registry is None:
            return {"ok": False, "error": "注册表未初始化", "items": []}
        return {"ok": True, "items": app.registry.nav(),
                "disabled": [m.id for m in app.registry.all() if not m.enabled]}

    @ctx.get("/api/pages", name="pages")
    def pages(request=None):
        """所有功能声明的页面（前端据此动态 import 页面模块）。"""
        if app is None or app.context is None:
            return {"ok": False, "error": "上下文未初始化", "pages": []}
        return {"ok": True, "pages": [p.as_dict() for p in app.context.pages_sorted()]}

    @ctx.get("/api/routes", name="routes")
    def routes(request=None):
        """已登记的路由表（调试与足迹核对用）。"""
        if app is None or app.context is None:
            return {"ok": False, "error": "上下文未初始化", "routes": []}
        return {"ok": True, "count": len(app.context.router),
                "routes": app.context.router.describe()}

    @ctx.get("/api/job", name="job_status")
    def job_status(request):
        """查询后台任务状态（快照副本，不再返回可变对象 —— 修 B-22）。"""
        if app is None or app.jobs is None:
            return {"ok": False, "error": "任务队列未初始化"}
        job_id = request.str_arg("id")
        if not job_id:
            return {"ok": False, "error": "缺少参数 id"}
        snap = app.jobs.get(job_id)
        if snap is None:
            return {"ok": False, "error": "任务不存在或已回收：%s" % job_id,
                    "code": "job_missing"}
        return {"ok": True, "job": snap}

    @ctx.get("/api/jobs", name="job_list")
    def job_list(request):
        """最近任务列表（便于替代"任务丢失后永久轮询"的前端 —— 修 B-23）。"""
        if app is None or app.jobs is None:
            return {"ok": False, "error": "任务队列未初始化", "jobs": []}
        return {"ok": True, "jobs": app.jobs.list(
            limit=request.int_arg("limit", 50))}

    @ctx.post("/api/cancel", name="cancel_job")
    def cancel_job(request):
        """取消指定任务；未给 id 时取消全部（每任务取消 —— 修 B-22）。"""
        if app is None or app.jobs is None:
            return {"ok": False, "error": "任务队列未初始化"}
        job_id = request.str_arg("id")
        if job_id:
            return {"ok": app.jobs.cancel(job_id), "cancelled": job_id}
        count = app.jobs.cancel_all()
        return {"ok": True, "cancelled_all": count}

    @ctx.get("/api/paths", name="paths")
    def path_info(request=None):
        """展示工程路径，方便用户与后续 AI 定位。"""
        return {
            "ok": True,
            "project_root": paths.project_root(),
            "data_dir": paths.data_dir(),
            "sessions_dir": paths.sessions_dir(),
            "web_dir": paths.web_dir(),
            "reference_root": paths.reference_root(),
            "reference_tools": paths.reference_roots(),
            "samples_root": paths.samples_root(),
        }

    @ctx.get("/api/time", name="time")
    def server_time(request=None):
        """服务端时间（前端时钟校正用）。"""
        return {"ok": True, "time": time.time(),
                "iso": time.strftime("%Y-%m-%d %H:%M:%S")}

    return len(ctx.router.routes())

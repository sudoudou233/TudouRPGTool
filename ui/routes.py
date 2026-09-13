# -*- coding: utf-8 -*-
"""界面无关但它们共用的核心路由：健康检查、功能清单、导航、任务查询。

@feature  none
@layer    ui
@public   register_core_routes
@depends  core.paths, core.registry, core.jobs, core.recent, ui.server
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


def convergence_status():
    """报告需求 §3.3 三类重复实现的收敛状态。

    这是 M2b 的核心交付指标，放在 ``/api/health`` 里让"收敛是否完成"
    变成一个可观测的事实，而不是只写在文档里。

    ⚠ ``engines`` 一项必须读 ``core.engines.CONVERGENCE_STATUS``，不能在这里
    写死 ``"merged"``（M5 实测踩到）：``features/selfcheck`` 读的是那个常量，
    写死会让两个报告**互相矛盾**（一个说 merged、一个说 unknown）。
    三次状态值同源，改一处即三处一致。
    """
    from core import engines
    from core import formats
    from core import marshal
    status = {
        "engines": engines.CONVERGENCE_STATUS,
        "formats": formats.CONVERGENCE_STATUS,
        "marshal": marshal.CONVERGENCE_STATUS,
    }
    status["all_merged"] = all(v == "merged" for v in status.values())
    return status


def register_core_routes(ctx, app=None):
    """把核心路由登记到 ``ctx.router``。返回登记数量。"""

    @ctx.get("/api/health", name="health")
    def health(request=None):
        """整体健康检查：应用、注册表、任务队列、UI、路径。

        注：M2b 之前这里还有一段 ``reference``（参考实现可用性），
        那是 ``core/_refbridge.py`` 的临时脚手架 —— 桥接层已在 M2b 删除
        （收敛完成，本工程不再需要加载旧实现做对照）。
        """
        out = {
            "ok": True,
            "app": app.version_info() if app is not None else {"name": "unknown"},
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "registry": app.registry_report() if app is not None else {},
            "jobs": app.jobs.stats() if app is not None and app.jobs else {},
            "ui": app.server.health() if app is not None and app.server else {},
            "convergence": convergence_status(),
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

    # ------------------------------------------------------------ 最近打开
    #
    # 这一组是**外壳级**能力（不属于任何功能）：导航栏的「最近打开」下拉要用，
    # 而翻译与修改两个功能都会往里记。写在 core/recent.py，这里只做 HTTP 门面。
    @ctx.get("/api/recent", name="recent_list")
    def recent_list(request=None):
        """最近打开过的游戏（新→旧）。

        每项带 ``exists``（目录**现在**还在不在）—— 它是算出来的，不是存下来的，
        所以"游戏被删了/移动了"立刻能看出来，界面据此置灰该条。
        """
        store = getattr(ctx, "recent", None)
        if store is None:
            return {"ok": True, "items": [], "limit": 0,
                    "error": "最近打开记录不可用（运行目录不可写）"}
        return {"ok": True, "items": store.items(), "limit": store.limit,
                "error": store.last_error}

    @ctx.post("/api/recent/forget", name="recent_forget")
    def recent_forget(request):
        """忘掉一条（不动文件系统上的任何东西）。"""
        store = getattr(ctx, "recent", None)
        if store is None:
            return {"ok": False, "error": "最近打开记录不可用"}
        target = request.str_arg("path")
        if not target:
            return {"ok": False, "error": "请提供 path"}
        removed = store.forget(target)
        return {"ok": True, "removed": removed, "items": store.items()}

    @ctx.post("/api/recent/prune", name="recent_prune")
    def recent_prune(request=None):
        """清理**已失效**的条目（目录不存在了）。

        刻意做成显式动作而不是自动清理：用户可能只是暂时拔了移动硬盘，
        自动删掉会让人"插回来就找不到记录了"。
        """
        store = getattr(ctx, "recent", None)
        if store is None:
            return {"ok": False, "error": "最近打开记录不可用"}
        return {"ok": True, "removed": store.prune(), "items": store.items()}

    @ctx.post("/api/recent/clear", name="recent_clear")
    def recent_clear(request=None):
        store = getattr(ctx, "recent", None)
        if store is None:
            return {"ok": False, "error": "最近打开记录不可用"}
        return {"ok": True, "removed": store.clear(), "items": []}

    return len(ctx.router.routes())

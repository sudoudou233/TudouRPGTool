# -*- coding: utf-8 -*-
"""功能模块的装配契约 —— ``register(ctx)`` 收到的上下文对象。

@feature  none
@layer    core
@public   Router, Route, PageSpec, AppContext
@depends  core.paths
@tested   tests/unit/test_registry.py
@footprint docs/MODULES.md#corecontext

契约（需求 §5.1）
----------------
功能模块通过 ``manifest.py`` 里的 ``register(ctx)`` 登记自己，**不得直接修改
app 或 server 内部**。``ctx`` 只暴露三件事：

* :meth:`AppContext.route` —— 注册 HTTP 路由
* :meth:`AppContext.page` —— 声明前端页面（供导航自动出现）
* :attr:`AppContext.paths` —— 只读路径访问器

路由与页面的登记都只是"往表里加一行"，所以新增功能是"插一块"而不是"改一片"。
"""

from __future__ import annotations

import re

from . import paths


class Route(object):
    """一条 HTTP 路由。``pattern`` 支持 ``{}`` 占位段，例如 ``/api/save/{name}``。"""

    def __init__(self, method, pattern, handler, name=None, feature=None):
        self.method = method.upper()
        self.pattern = pattern
        self.handler = handler
        self.name = name or handler.__name__
        self.feature = feature
        self.regex, self.param_names = self._compile(pattern)

    @staticmethod
    def _compile(pattern):
        """把 ``/api/x/{id}`` 编译为正则，并收集参数名。"""
        names = []
        parts = []
        for seg in pattern.strip("/").split("/"):
            if seg.startswith("{") and seg.endswith("}"):
                names.append(seg[1:-1])
                parts.append(r"(?P<%s>[^/]+)" % seg[1:-1])
            else:
                parts.append(re.escape(seg))
        body = "/".join(parts)
        return re.compile(r"^/%s/?$" % body), tuple(names)

    def match(self, method, path):
        """匹配方法与路径；命中返回参数字典，否则 None。"""
        if self.method != method.upper() and self.method != "ANY":
            return None
        m = self.regex.match(path)
        if not m:
            return None
        return m.groupdict()

    def __repr__(self):
        return "<Route %s %s>" % (self.method, self.pattern)


class PageSpec(object):
    """前端页面声明。

    ``module`` 是相对 ``ui/web/pages/`` 的模块路径（不含 ``.js``），
    前端用动态 ``import()`` 按需加载，因此**新增功能等于新增文件**，
    不需要改动前端主脚本。
    """

    REQUIRED = ("id", "title", "module")

    def __init__(self, spec, feature=None):
        if not isinstance(spec, dict):
            raise TypeError("页面声明必须是 dict，收到 %r" % (type(spec),))
        missing = [k for k in self.REQUIRED if not spec.get(k)]
        if missing:
            raise ValueError("页面声明缺少字段：%s" % ", ".join(missing))
        self.id = spec["id"]
        self.title = spec["title"]
        self.module = spec["module"]
        self.icon = spec.get("icon", "")
        self.order = int(spec.get("order", 100))
        self.feature = feature or spec.get("feature")

    def as_dict(self):
        return {"id": self.id, "title": self.title, "module": self.module,
                "icon": self.icon, "order": self.order, "feature": self.feature}

    def __repr__(self):
        return "<PageSpec %s -> %s>" % (self.id, self.module)


class Router(object):
    """路由表。显式登记 + 显式匹配，替代原来的 ``if/elif`` 长链。"""

    def __init__(self):
        self._routes = []
        self._by_name = {}

    def add(self, method, pattern, handler, name=None, feature=None):
        route = Route(method, pattern, handler, name=name, feature=feature)
        for existing in self._routes:
            if existing.method == route.method and existing.pattern == route.pattern:
                raise ValueError(
                    "路由重复登记：%s %s（已由 %s 登记，现由 %s 再登记）"
                    % (route.method, route.pattern, existing.feature, feature))
        # 未显式命名时，默认名是 handler.__name__；对 lambda / 匿名函数
        # 会得到一堆同名的 "<lambda>"，从而误报"路由名重复"。
        # 因此只在**显式命名**或默认名唯一时才把名字登记进映射表。
        registered_name = route.name
        if registered_name in self._by_name:
            if name is not None:
                raise ValueError("路由名重复：%s" % registered_name)
            registered_name = "%s %s" % (route.method, route.pattern)
            route.name = registered_name
        self._routes.append(route)
        self._by_name[registered_name] = route
        return route

    def get(self, pattern, handler=None, **kw):
        """注册 GET 路由，可用作装饰器。"""
        return self._register("GET", pattern, handler, kw)

    def post(self, pattern, handler=None, **kw):
        """注册 POST 路由，可用作装饰器。"""
        return self._register("POST", pattern, handler, kw)

    def any(self, pattern, handler=None, **kw):
        """注册任意方法路由（GET/POST 皆可），可用作装饰器。"""
        return self._register("ANY", pattern, handler, kw)

    def _register(self, method, pattern, handler, kw):
        if handler is None:
            def decorator(fn):
                self.add(method, pattern, fn, **kw)
                return fn
            return decorator
        self.add(method, pattern, handler, **kw)
        return handler

    def resolve(self, method, path):
        """返回 ``(route, params)``；未命中返回 ``(None, None)``。"""
        for route in self._routes:
            params = route.match(method, path)
            if params is not None:
                return route, params
        return None, None

    def routes(self):
        return list(self._routes)

    def describe(self):
        """返回 ``[{method, pattern, name, feature}]``，供足迹校验与调试页。"""
        return [{"method": r.method, "pattern": r.pattern, "name": r.name,
                 "feature": r.feature} for r in self._routes]

    def __len__(self):
        return len(self._routes)


class AppContext(object):
    """传给 ``register(ctx)`` 的装配上下文。"""

    def __init__(self, app=None, router=None, config=None, jobs=None):
        self.app = app
        self.router = router if router is not None else Router()
        self.config = config
        self.jobs = jobs
        self.pages = {}          # page_id -> PageSpec
        self._feature = None     # 当前正在注册的功能 id

    # ------------------------------------------------------------ 只读路径
    @property
    def paths(self):
        """只读路径访问器（模块对象，调用方不得改写其常量）。"""
        return paths

    # ------------------------------------------------------------ 注册接口
    def route(self, method, pattern, handler=None, name=None):
        """登记一条 HTTP 路由。"""
        if handler is None:
            def decorator(fn):
                self.router.add(method, pattern, fn, name=name,
                                feature=self._feature)
                return fn
            return decorator
        self.router.add(method, pattern, handler, name=name,
                        feature=self._feature)
        return handler

    def get(self, pattern, handler=None, name=None):
        return self.route("GET", pattern, handler, name=name)

    def post(self, pattern, handler=None, name=None):
        return self.route("POST", pattern, handler, name=name)

    def page(self, spec):
        """声明一个前端页面。返回 :class:`PageSpec`。"""
        page = PageSpec(spec, feature=self._feature)
        if page.id in self.pages:
            raise ValueError("页面 id 重复：%s" % page.id)
        self.pages[page.id] = page
        return page

    def pages_sorted(self):
        return sorted(self.pages.values(), key=lambda p: (p.order, p.id))

    # ------------------------------------------------------------ 注册期状态
    def _enter_feature(self, feature_id):
        """由 Registry 在调用 ``register(ctx)`` 前设置，用于归属路由与页面。"""
        self._feature = feature_id

    def _leave_feature(self):
        self._feature = None

    def summary(self):
        """装配结果摘要，供 ``/api/features`` 与启动日志使用。"""
        return {
            "routes": len(self.router),
            "pages": [p.as_dict() for p in self.pages_sorted()],
        }

# -*- coding: utf-8 -*-
"""功能模块注册表 —— 扩展核心（``features/*`` 的自动发现与装配）。

@feature  none
@layer    core
@public   FootprintMeta, FeatureModule, Registry, discover, get_registry,
          reset_registry, MANIFEST_FILENAME
@depends  core.paths
@tested   tests/unit/test_registry.py
@footprint docs/MODULES.md#coreregistry

设计契约（需求 §5.1）
--------------------
每个 ``features/<name>/`` 目录**必须**自我描述并自注册：

* ``manifest.py`` 暴露模块级 ``MANIFEST``（dict）；可选暴露 ``register(ctx)``。
* manifest 必备字段：``id`` / ``name`` / ``icon`` / ``version`` / ``description``。
* ``register(ctx)`` 是唯一入口，**不得直接修改 app 或 server 内部**；
  它只能通过 ``ctx`` 提供的接口登记 API 路由与页面。

自动发现机制
-----------
用 :func:`pkgutil.iter_modules` 枚举 ``core.paths.features_dir()`` 下的子目录，
对含 ``manifest.py`` 的目录 :func:`importlib.import_module`。**明确取舍**：
不做"放个文件就靠 import 副作用生效"的隐式魔法 —— 发现过程是显式的，
且 :func:`discover` 返回加载报告，启动时打印"已加载的功能模块：translate, cheats"。

前端入口的"自动出现"：后端提供 ``/api/features`` 返回 manifest 声明的导航信息，
前端据此渲染导航。前端侧只有一处登记（``ui/web/pages/registry.js``），
符合需求 §5.1"做不到自动发现时至少只在固定一两处登记"。
"""

from __future__ import annotations

import importlib
import os
import pkgutil
import sys
import traceback

from . import paths

#: 功能模块的自描述文件名。
MANIFEST_FILENAME = "manifest.py"

#: manifest 必备字段。
REQUIRED_FIELDS = ("id", "name", "icon", "version", "description")

#: manifest 可选字段及默认值。
OPTIONAL_DEFAULTS = {
    "order": 100,
    "core_deps": (),
    "api_prefix": "",
    "pages": (),
    "enabled": True,
    "health": None,
}


class ManifestError(Exception):
    """manifest.py 缺失必备字段或格式不合法。"""


class FootprintMeta(object):
    """源文件顶部的足迹元信息（由 ``tools/check_footprint.py`` 解析）。

    解析的是模块 docstring 里的 ``@key value`` 行，例如::

        @feature  translate
        @layer    core
        @public   detect, list_saves
        @depends  core.constants
        @tested   tests/unit/test_engines.py
        @footprint docs/MODULES.md#coreengines

    这里只做数据结构承载，解析逻辑在 ``tools/check_footprint.py``
    （开发期脚本不参与运行时，避免启动开销）。
    """

    KEYS = ("feature", "layer", "public", "depends", "tested", "footprint", "note")

    def __init__(self, feature=None, layer=None, public=(), depends=(),
                 tested=None, footprint=None, note=None):
        self.feature = feature
        self.layer = layer
        self.public = tuple(public or ())
        self.depends = tuple(depends or ())
        self.tested = tested
        self.footprint = footprint
        self.note = note

    def as_dict(self):
        return {
            "feature": self.feature,
            "layer": self.layer,
            "public": list(self.public),
            "depends": list(self.depends),
            "tested": self.tested,
            "footprint": self.footprint,
            "note": self.note,
        }

    def __repr__(self):
        return "<FootprintMeta feature=%r layer=%r>" % (self.feature, self.layer)


class FeatureModule(object):
    """一个已加载的功能模块。

    属性
    ----
    manifest    原始 manifest dict
    directory   模块目录绝对路径
    module      已 import 的 ``manifest`` 模块对象
    error       加载失败时的错误文本（此时 :attr:`ok` 为 False）
    """

    def __init__(self, manifest, directory, module, error=None):
        self.manifest = manifest
        self.directory = directory
        self.module = module
        self.error = error

    # ------------------------------------------------------------ 基本字段
    @property
    def id(self):
        return self.manifest.get("id")

    @property
    def name(self):
        return self.manifest.get("name")

    @property
    def icon(self):
        return self.manifest.get("icon")

    @property
    def version(self):
        return self.manifest.get("version")

    @property
    def description(self):
        return self.manifest.get("description")

    @property
    def order(self):
        return self.manifest.get("order", OPTIONAL_DEFAULTS["order"])

    @property
    def api_prefix(self):
        return self.manifest.get("api_prefix", "")

    @property
    def pages(self):
        return tuple(self.manifest.get("pages") or ())

    @property
    def core_deps(self):
        return tuple(self.manifest.get("core_deps") or ())

    @property
    def enabled(self):
        return bool(self.manifest.get("enabled", True))

    @property
    def ok(self):
        return self.error is None

    @property
    def register_fn(self):
        """模块级 ``register`` 函数；未提供时为 None。"""
        return getattr(self.module, "register", None)

    # ------------------------------------------------------------ 输出
    def nav_entry(self):
        """给前端的导航信息（不含不可序列化对象）。"""
        return {
            "id": self.id,
            "name": self.name,
            "icon": self.icon,
            "version": self.version,
            "description": self.description,
            "order": self.order,
            "api_prefix": self.api_prefix,
            "pages": [dict(p) for p in self.pages],
            "enabled": self.enabled,
            "ok": self.ok,
            "error": self.error,
        }

    def health(self):
        """调用 manifest 声明的 ``health`` 函数（若有），返回其原始结果。"""
        fn = self.manifest.get("health")
        if not callable(fn):
            return {"feature": self.id, "status": "unknown",
                    "detail": "未声明健康检查"}
        try:
            result = fn()
        except Exception as exc:  # 健康检查本身不允许把应用拖垮
            return {"feature": self.id, "status": "error",
                    "detail": "%s: %s" % (type(exc).__name__, exc)}
        if isinstance(result, dict):
            out = dict(result)
            out.setdefault("feature", self.id)
            return out
        return {"feature": self.id, "status": "ok" if result else "error",
                "detail": str(result)}

    def __repr__(self):
        state = "ok" if self.ok else "error"
        return "<FeatureModule %s v%s %s>" % (self.id, self.version, state)


class Registry(object):
    """功能注册表：发现、保存、查询、装配。

    参数
    ----
    features_path : str
        功能目录（默认 ``<root>/features``）。
    package : str
        承载功能目录的 Python 包名（默认 ``'features'``）。
        测试需要用临时目录做夹具时，把它做成一个真实可 import 的包
        （即 ``pkg.__path__`` 指向该临时目录），否则 ``import_module``
        会解析到工程真实的 ``features`` 包而加载到错误的东西。
        默认值行为不变，因此生产代码无需关心这个参数。
    """

    def __init__(self, features_path=None, package="features"):
        self.features_path = features_path or paths.features_dir()
        self.package = package
        self._modules = {}      # id -> FeatureModule
        self._order = []        # 保持发现顺序
        self._errors = []       # 发现过程中的错误（目录级）
        self._loaded = False

    # ------------------------------------------------------------ 发现
    def discover(self, reload_modules=False):
        """扫描功能目录并加载 manifest。重复调用是幂等的。"""
        self._modules = {}
        self._order = []
        self._errors = []
        self._loaded = True

        if not os.path.isdir(self.features_path):
            self._errors.append("功能目录不存在：%s" % self.features_path)
            return self

        for pkg_name in self._candidate_dirs():
            directory = os.path.join(self.features_path, pkg_name)
            manifest_path = os.path.join(directory, MANIFEST_FILENAME)
            if not os.path.isfile(manifest_path):
                self._errors.append(
                    "%s 缺少 %s，未注册" % (pkg_name, MANIFEST_FILENAME))
                continue
            if not os.path.isfile(os.path.join(directory, "__init__.py")):
                self._errors.append(
                    "%s 有 %s 但缺少 __init__.py，无法作为包 import"
                    % (pkg_name, MANIFEST_FILENAME))
                continue
            self._load_one(pkg_name, directory, reload_modules)
        return self

    def _candidate_dirs(self):
        """列出功能目录下所有子目录名（**不依赖 pkgutil 的包判定**）。

        明确取舍：不用 ``pkgutil.iter_modules`` 的 ``ispkg`` 过滤，因为它
        会静默跳过缺 ``__init__.py`` 的目录 —— 那正是最需要报错的情形
        （手工新建功能目录却忘了包文件）。这里改为直接列目录，逐个判定并
        给出可读的错误信息，符合"不做隐式魔法"的取舍。
        """
        try:
            names = os.listdir(self.features_path)
        except OSError as exc:
            self._errors.append("无法列出功能目录：%s" % exc)
            return []
        out = []
        for name in sorted(names):
            if name.startswith(".") or name == "__pycache__":
                continue
            if os.path.isdir(os.path.join(self.features_path, name)):
                out.append(name)
        return out

    def _load_one(self, pkg_name, directory, reload_modules):
        full_name = "%s.%s.%s" % (self.package, pkg_name, MANIFEST_FILENAME[:-3])
        try:
            self._ensure_importable()
            if reload_modules and full_name in sys.modules:
                module = importlib.reload(sys.modules[full_name])
            else:
                module = importlib.import_module(full_name)
        except Exception as exc:
            self._errors.append(
                "加载 %s 失败：%s: %s" % (pkg_name, type(exc).__name__, exc))
            self._errors.append(traceback.format_exc(limit=3).rstrip())
            return

        manifest = getattr(module, "MANIFEST", None)
        if not isinstance(manifest, dict):
            self._errors.append("%s 未定义 MANIFEST dict" % pkg_name)
            return

        missing = [f for f in REQUIRED_FIELDS if not manifest.get(f)]
        if missing:
            self._errors.append(
                "%s 的 MANIFEST 缺少字段：%s" % (pkg_name, ", ".join(missing)))
            return

        for key, value in OPTIONAL_DEFAULTS.items():
            manifest.setdefault(key, value)

        fid = manifest["id"]
        if fid in self._modules:
            self._errors.append(
                "功能 id 重复：%r（%s 与 %s）"
                % (fid, self._modules[fid].directory, directory))
            return

        self._modules[fid] = FeatureModule(manifest, directory, module)
        self._order.append(fid)

    def _ensure_importable(self):
        """保证承载功能目录的包的父目录在 ``sys.path`` 上。

        默认情形：``features`` 包位于工程根，因此把工程根加进 ``sys.path``。
        测试情形：调用方已把临时目录做成名为 ``self.package`` 的包，
        此时该包的 ``__path__`` 已经指向临时目录，无需再改 ``sys.path``。
        """
        existing = sys.modules.get(self.package)
        if existing is not None and getattr(existing, "__path__", None):
            return
        root = paths.project_root()
        if root not in sys.path:
            sys.path.insert(0, root)

    # ------------------------------------------------------------ 查询
    @property
    def loaded(self):
        return self._loaded

    @property
    def errors(self):
        return list(self._errors)

    def ids(self):
        return list(self._order)

    def all(self):
        """按 ``order`` 再按发现顺序返回所有模块。"""
        return sorted((self._modules[i] for i in self._order),
                      key=lambda m: (m.order, self._order.index(m.id)))

    def enabled(self):
        return [m for m in self.all() if m.enabled]

    def get(self, feature_id):
        return self._modules.get(feature_id)

    def __contains__(self, feature_id):
        return feature_id in self._modules

    def __len__(self):
        return len(self._modules)

    # ------------------------------------------------------------ 装配
    def register_all(self, ctx):
        """对每个已启用模块调用其 ``register(ctx)``。

        返回 ``{feature_id: 注册结果或错误文本}``。单个模块注册失败不会
        阻断其它模块（但会记录在返回值和 :attr:`register_errors` 里）。
        """
        report = {}
        for module in self.enabled():
            fn = module.register_fn
            if fn is None:
                report[module.id] = "skipped: 未提供 register(ctx)"
                continue
            try:
                setter = getattr(ctx, "_enter_feature", None)
                if callable(setter):
                    setter(module.id)
                result = fn(ctx)
                report[module.id] = "ok" if result is None else result
            except Exception as exc:
                detail = "%s: %s" % (type(exc).__name__, exc)
                report[module.id] = "error: " + detail
                self._errors.append("register(%s) 失败：%s" % (module.id, detail))
                self._errors.append(traceback.format_exc(limit=3).rstrip())
            finally:
                leaver = getattr(ctx, "_leave_feature", None)
                if callable(leaver):
                    leaver()
        return report

    # ------------------------------------------------------------ 输出
    def nav(self):
        """前端导航数据。"""
        return [m.nav_entry() for m in self.enabled()]

    def health(self):
        """整体健康检查：自身 + 每个功能模块。"""
        return {
            "ok": not self._errors and all(m.ok for m in self.all()),
            "features": [m.health() for m in self.enabled()],
            "errors": self.errors,
        }

    def describe(self):
        """一行中文摘要，供启动日志打印。"""
        if not self.enabled():
            return "未加载任何功能模块"
        return "已加载的功能模块：" + "、".join(
            "%s(%s)" % (m.name, m.id) for m in self.enabled())


# ---------------------------------------------------------------------------
# 进程级默认注册表（显式初始化，不做 import 副作用）
# ---------------------------------------------------------------------------
_REGISTRY = None


def get_registry(features_path=None, reload_modules=False):
    """取进程级注册表；首次调用时发现。"""
    global _REGISTRY
    if _REGISTRY is None or features_path is not None:
        _REGISTRY = Registry(features_path).discover(reload_modules=reload_modules)
    return _REGISTRY


def discover(features_path=None, reload_modules=False):
    """便捷入口：发现并返回注册表。"""
    return get_registry(features_path, reload_modules=reload_modules)


def reset_registry():
    """清空进程级注册表（测试隔离用）。"""
    global _REGISTRY
    _REGISTRY = None

# -*- coding: utf-8 -*-
"""注册表与模块契约的单元测试（需求 §5.1 扩展点的可验证性）。

@feature  none
@layer    tests
@public   TestManifestDiscovery, TestManifestValidation, TestRegisterContract,
          TestRealFeatures, TestRouter, TestContext
@depends  core.registry, core.context
@tested   (本文件即测试)
@footprint docs/MODULES.md#coreregistry
"""

from __future__ import annotations

import os
import sys
import tempfile
import textwrap
import types
import unittest

_ROOT = os.path.dirname(os.path.abspath(__file__))
while not os.path.isfile(os.path.join(_ROOT, "app.py")):
    parent = os.path.dirname(_ROOT)
    if parent == _ROOT:
        raise RuntimeError("无法定位工程根（未找到 app.py）")
    _ROOT = parent
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core import registry as registry_mod  # noqa: E402
from core.context import AppContext, PageSpec, Router  # noqa: E402


def write_feature(features_dir, name, manifest_body, extra_files=None):
    """在 features_dir 下造一个功能目录。"""
    directory = os.path.join(features_dir, name)
    os.makedirs(directory, exist_ok=True)
    with open(os.path.join(directory, "__init__.py"), "w", encoding="utf-8") as f:
        f.write("")
    with open(os.path.join(directory, "manifest.py"), "w", encoding="utf-8") as f:
        f.write(textwrap.dedent(manifest_body))
    for filename, content in (extra_files or {}).items():
        with open(os.path.join(directory, filename), "w", encoding="utf-8") as f:
            f.write(content)
    return directory


def install_temp_package(name, path):
    """把 ``path`` 注册为一个真实可 import 的包并返回包对象。

    为什么必须这样做：``core.registry`` 用 ``importlib.import_module``
    加载 ``<package>.<feature>.manifest``。若只把临时目录传给 Registry，
    import 会解析到工程真实的 ``features`` 包，加载到错误的东西
    （这正是首轮测试暴露出的 14 个错误的根因）。注册一个 ``__path__``
    指向临时目录的同名包即可让测试用上真正的 import 语义。
    """
    package = types.ModuleType(name)
    package.__path__ = [path]
    package.__package__ = name
    sys.modules[name] = package
    return package


def make_registry(features_dir, package="tmpfeatures"):
    """构造一个使用临时包的 Registry（自动清理 sys.modules）。"""
    install_temp_package(package, features_dir)
    return registry_mod.Registry(features_dir, package=package)


GOOD_MANIFEST = '''
    MANIFEST = {
        "id": "demo",
        "name": "示例功能",
        "icon": "示",
        "version": "1.0.0",
        "description": "用于测试",
    }

    def register(ctx):
        @ctx.get("/api/demo/ping", name="demo_ping")
        def ping(request=None):
            return {"pong": True}
        ctx.page({"id": "demo", "title": "示例", "module": "demo"})
        return "ok"
'''


class FeatureDirTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="feat_")
        self.addCleanup(self.tmp.cleanup)
        self.features_dir = os.path.join(self.tmp.name, "features")
        os.makedirs(self.features_dir, exist_ok=True)
        self.package = "tmpfeatures"
        self.addCleanup(lambda: sys.modules.pop(self.package, None))
        # 清掉上一用例可能残留的子模块缓存，避免串味
        for key in [k for k in sys.modules if k.startswith(self.package + ".")]:
            sys.modules.pop(key, None)

    def registry(self, features_dir=None):
        return make_registry(features_dir or self.features_dir, self.package)


class TestManifestDiscovery(FeatureDirTestCase):
    def test_discovers_feature(self):
        write_feature(self.features_dir, "demo", GOOD_MANIFEST)
        reg = self.registry().discover()
        self.assertEqual(reg.ids(), ["demo"])
        module = reg.get("demo")
        self.assertIsNotNone(module)
        self.assertEqual(module.name, "示例功能")
        self.assertTrue(module.ok)

    def test_empty_dir(self):
        reg = self.registry().discover()
        self.assertEqual(reg.ids(), [])
        self.assertEqual(reg.errors, [])

    def test_missing_features_dir_reports_error(self):
        reg = self.registry(os.path.join(self.tmp.name, "nope")).discover()
        self.assertEqual(reg.ids(), [])
        self.assertTrue(reg.errors)

    def test_dir_without_manifest_is_reported_not_silently_ignored(self):
        """明确取舍：不做隐式魔法，缺 manifest 必须报错而不是静默跳过。"""
        os.makedirs(os.path.join(self.features_dir, "broken"), exist_ok=True)
        reg = self.registry().discover()
        self.assertEqual(reg.ids(), [])
        self.assertTrue(any("manifest.py" in e for e in reg.errors))

    def test_discovers_multiple_sorted_by_order(self):
        write_feature(self.features_dir, "a", '''
            MANIFEST = {"id": "a", "name": "A", "icon": "A", "version": "1",
                        "description": "d", "order": 30}
        ''')
        write_feature(self.features_dir, "b", '''
            MANIFEST = {"id": "b", "name": "B", "icon": "B", "version": "1",
                        "description": "d", "order": 10}
        ''')
        reg = self.registry().discover()
        self.assertEqual([m.id for m in reg.all()], ["b", "a"])

    def test_disabled_feature_excluded_from_enabled(self):
        write_feature(self.features_dir, "off", '''
            MANIFEST = {"id": "off", "name": "Off", "icon": "-", "version": "1",
                        "description": "d", "enabled": False}
        ''')
        reg = self.registry().discover()
        self.assertEqual(len(reg), 1)
        self.assertEqual(reg.enabled(), [])
        self.assertEqual(reg.nav(), [])

    def test_discover_is_idempotent(self):
        write_feature(self.features_dir, "demo", GOOD_MANIFEST)
        reg = self.registry()
        reg.discover()
        reg.discover()
        self.assertEqual(reg.ids(), ["demo"])


class TestManifestValidation(FeatureDirTestCase):
    def test_missing_required_field_reported(self):
        write_feature(self.features_dir, "bad", '''
            MANIFEST = {"id": "bad", "name": "B"}
        ''')
        reg = self.registry().discover()
        self.assertEqual(reg.ids(), [])
        joined = " ".join(reg.errors)
        for field in ("icon", "version", "description"):
            self.assertIn(field, joined)

    def test_no_manifest_dict(self):
        write_feature(self.features_dir, "bad", "X = 1\n")
        reg = self.registry().discover()
        self.assertTrue(any("MANIFEST" in e for e in reg.errors))

    def test_import_error_is_captured_not_raised(self):
        write_feature(self.features_dir, "bad", "raise RuntimeError('boom')\n")
        reg = self.registry().discover()
        self.assertEqual(reg.ids(), [])
        self.assertTrue(any("boom" in e for e in reg.errors))

    def test_duplicate_id_reported(self):
        write_feature(self.features_dir, "one", '''
            MANIFEST = {"id": "same", "name": "1", "icon": "1", "version": "1",
                        "description": "d"}
        ''')
        write_feature(self.features_dir, "two", '''
            MANIFEST = {"id": "same", "name": "2", "icon": "2", "version": "1",
                        "description": "d"}
        ''')
        reg = self.registry().discover()
        self.assertEqual(len(reg), 1)
        self.assertTrue(any("重复" in e for e in reg.errors))

    def test_optional_defaults_applied(self):
        write_feature(self.features_dir, "demo", GOOD_MANIFEST)
        reg = self.registry().discover()
        module = reg.get("demo")
        self.assertEqual(module.order, 100)
        self.assertEqual(module.api_prefix, "")
        self.assertEqual(module.pages, ())
        self.assertEqual(module.core_deps, ())
        self.assertTrue(module.enabled)


class TestRegisterContract(FeatureDirTestCase):
    def test_register_registers_routes_and_pages(self):
        write_feature(self.features_dir, "demo", GOOD_MANIFEST)
        reg = self.registry().discover()
        ctx = AppContext()
        report = reg.register_all(ctx)
        self.assertEqual(report["demo"], "ok")
        self.assertEqual(len(ctx.router), 1)
        self.assertIn("demo", ctx.pages)
        route, params = ctx.router.resolve("GET", "/api/demo/ping")
        self.assertIsNotNone(route)
        self.assertEqual(route.feature, "demo", "路由必须归属到登记它的功能")

    def test_feature_without_register_is_skipped_not_failed(self):
        write_feature(self.features_dir, "noreg", '''
            MANIFEST = {"id": "noreg", "name": "N", "icon": "N", "version": "1",
                        "description": "d"}
        ''')
        reg = self.registry().discover()
        report = reg.register_all(AppContext())
        self.assertIn("skipped", report["noreg"])

    def test_register_exception_does_not_break_others(self):
        write_feature(self.features_dir, "boom", '''
            MANIFEST = {"id": "boom", "name": "B", "icon": "B", "version": "1",
                        "description": "d", "order": 1}
            def register(ctx):
                raise RuntimeError("注册失败")
        ''')
        write_feature(self.features_dir, "good", GOOD_MANIFEST)
        reg = self.registry().discover()
        ctx = AppContext()
        report = reg.register_all(ctx)
        self.assertIn("error", report["boom"])
        self.assertEqual(report["demo"], "ok")
        self.assertEqual(len(ctx.router), 1, "一个功能注册失败不应阻断其它功能")
        self.assertTrue(any("boom" in e for e in reg.errors))

    def test_health_unknown_when_not_declared(self):
        write_feature(self.features_dir, "demo", GOOD_MANIFEST)
        reg = self.registry().discover()
        self.assertEqual(reg.get("demo").health()["status"], "unknown")

    def test_health_ok(self):
        write_feature(self.features_dir, "healthy", '''
            MANIFEST = {"id": "healthy", "name": "H", "icon": "H", "version": "1",
                        "description": "d"}
            def health():
                return {"status": "ok", "detail": "齐全"}
            MANIFEST["health"] = health
        ''')
        reg = self.registry().discover()
        result = reg.get("healthy").health()
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["feature"], "healthy")

    def test_health_exception_is_contained(self):
        write_feature(self.features_dir, "sick", '''
            MANIFEST = {"id": "sick", "name": "S", "icon": "S", "version": "1",
                        "description": "d"}
            def health():
                raise ValueError("检查炸了")
            MANIFEST["health"] = health
        ''')
        reg = self.registry().discover()
        result = reg.get("sick").health()
        self.assertEqual(result["status"], "error")
        self.assertIn("检查炸了", result["detail"])

    def test_nav_entry_is_json_serializable(self):
        import json
        write_feature(self.features_dir, "demo", GOOD_MANIFEST)
        reg = self.registry().discover()
        entry = reg.nav()[0]
        json.dumps(entry)      # 不得抛异常（health 是函数对象，必须已剔除）
        self.assertEqual(entry["id"], "demo")
        self.assertIsInstance(entry["pages"], list)


class TestRealFeatures(unittest.TestCase):
    """对本工程真实的两个功能模块做体检。"""

    def setUp(self):
        self.reg = registry_mod.Registry().discover()

    def test_both_features_present(self):
        self.assertIn("translate", self.reg)
        self.assertIn("cheats", self.reg)

    def test_no_load_errors(self):
        self.assertEqual(self.reg.errors, [],
                         "真实功能模块不得有加载错误：%s" % self.reg.errors)

    def test_each_feature_healthy(self):
        for module in self.reg.all():
            with self.subTest(feature=module.id):
                health = module.health()
                self.assertEqual(health["status"], "ok", health.get("detail"))

    def test_each_feature_declares_page(self):
        for module in self.reg.all():
            with self.subTest(feature=module.id):
                self.assertTrue(module.pages, "功能必须声明至少一个页面")

    def test_each_feature_declares_api_prefix(self):
        for module in self.reg.all():
            with self.subTest(feature=module.id):
                self.assertTrue(module.api_prefix.startswith("/api/"),
                                "api_prefix 必须以 /api/ 开头")

    def test_register_all_succeeds(self):
        ctx = AppContext()
        report = self.reg.register_all(ctx)
        for feature_id, result in report.items():
            with self.subTest(feature=feature_id):
                self.assertNotIn("error", str(result), result)

    def test_feature_routes_use_declared_prefix(self):
        """功能登记的路由必须落在自己声明的 api_prefix 下（防越界）。"""
        ctx = AppContext()
        self.reg.register_all(ctx)
        for module in self.reg.all():
            prefix = module.api_prefix.rstrip("/")
            own = [r for r in ctx.router.routes() if r.feature == module.id]
            for route in own:
                with self.subTest(feature=module.id, route=route.pattern):
                    self.assertTrue(
                        route.pattern.startswith(prefix),
                        "路由 %s 不在声明的前缀 %s 下" % (route.pattern, prefix))

    def test_describe_mentions_both(self):
        text = self.reg.describe()
        self.assertIn("文本翻译", text)
        self.assertIn("存档修改", text)


class TestRouter(unittest.TestCase):
    def test_static_and_param_routes(self):
        router = Router()
        router.get("/api/a", lambda r: 1, name="a")
        router.get("/api/b/{id}", lambda r: 2, name="b")
        self.assertIsNotNone(router.resolve("GET", "/api/a")[0])
        route, params = router.resolve("GET", "/api/b/xyz")
        self.assertIsNotNone(route)
        self.assertEqual(params, {"id": "xyz"})

    def test_method_mismatch(self):
        router = Router()
        router.post("/api/only-post", lambda r: 1, name="p")
        self.assertIsNone(router.resolve("GET", "/api/only-post")[0])

    def test_any_method(self):
        router = Router()
        router.any("/api/any", lambda r: 1, name="any")
        self.assertIsNotNone(router.resolve("GET", "/api/any")[0])
        self.assertIsNotNone(router.resolve("POST", "/api/any")[0])

    def test_duplicate_pattern_rejected(self):
        router = Router()
        router.get("/api/x", lambda r: 1, name="one")
        with self.assertRaises(ValueError):
            router.get("/api/x", lambda r: 2, name="two")

    def test_trailing_slash_tolerated(self):
        router = Router()
        router.get("/api/x", lambda r: 1, name="x")
        self.assertIsNotNone(router.resolve("GET", "/api/x/")[0])

    def test_describe_shape(self):
        router = Router()
        router.get("/api/x", lambda r: 1, name="x")
        described = router.describe()
        self.assertEqual(described[0]["pattern"], "/api/x")
        self.assertEqual(described[0]["method"], "GET")


class TestPageSpec(unittest.TestCase):
    def test_required_fields(self):
        with self.assertRaises(ValueError):
            PageSpec({"id": "x", "title": "t"})
        with self.assertRaises(TypeError):
            PageSpec("not-a-dict")

    def test_defaults(self):
        page = PageSpec({"id": "x", "title": "T", "module": "m"})
        self.assertEqual(page.order, 100)
        self.assertEqual(page.icon, "")

    def test_context_rejects_duplicate_page_id(self):
        ctx = AppContext()
        ctx.page({"id": "d", "title": "1", "module": "m"})
        with self.assertRaises(ValueError):
            ctx.page({"id": "d", "title": "2", "module": "m"})

    def test_context_route_attribution(self):
        ctx = AppContext()
        ctx._enter_feature("f1")
        ctx.get("/api/f1/x", lambda r: 1)
        ctx._leave_feature()
        ctx.get("/api/core/x", lambda r: 1)
        routes = {r.pattern: r.feature for r in ctx.router.routes()}
        self.assertEqual(routes["/api/f1/x"], "f1")
        self.assertIsNone(routes["/api/core/x"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

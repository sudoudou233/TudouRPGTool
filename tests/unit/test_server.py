# -*- coding: utf-8 -*-
"""HTTP 服务层与核心路由的单元测试（含安全护栏）。

@feature  none
@layer    tests
@public   TestSafeConvert, TestRouterDispatch, TestHttpServer, TestSecurity,
          TestCoreRoutes
@depends  ui.server, ui.routes, app
@tested   (本文件即测试)
@footprint docs/MODULES.md#uiserver
"""

from __future__ import annotations

import json
import os
import sys
import unittest
import urllib.error
import urllib.request

_ROOT = os.path.dirname(os.path.abspath(__file__))
while not os.path.isfile(os.path.join(_ROOT, "app.py")):
    parent = os.path.dirname(_ROOT)
    if parent == _ROOT:
        raise RuntimeError("无法定位工程根（未找到 app.py）")
    _ROOT = parent
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.context import Router  # noqa: E402
from ui import server as ui_server  # noqa: E402


def http(url, method="GET", body=None, headers=None, timeout=10):
    """极简 HTTP 客户端（只用标准库，避免重蹈 requests 依赖的覆辙）。"""
    data = None
    hdrs = dict(headers or {})
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        hdrs["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            ctype = response.headers.get("Content-Type", "")
            payload = json.loads(raw.decode("utf-8")) if "json" in ctype else raw
            return response.status, payload
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        ctype = exc.headers.get("Content-Type", "")
        payload = json.loads(raw.decode("utf-8")) if "json" in ctype else raw
        return exc.code, payload


class TestSafeConvert(unittest.TestCase):
    """修 B-14：原实现 ``int(params.get("page", 1))`` 遇空串抛异常并断连。"""

    def test_safe_int(self):
        cases = [(None, 0), ("", 0), ("5", 5), ("abc", 0), ("3.7", 3),
                 ("-2", -2), (7, 7), ([], 0), ("  9 ", 9)]
        for value, expected in cases:
            with self.subTest(value=value):
                self.assertEqual(ui_server.safe_int(value, 0), expected)

    def test_safe_int_default(self):
        self.assertEqual(ui_server.safe_int("", 42), 42)

    def test_safe_bool(self):
        for value in ("1", "true", "YES", "on", True):
            self.assertTrue(ui_server.safe_bool(value), value)
        for value in ("0", "false", "no", "off", False, ""):
            self.assertFalse(ui_server.safe_bool(value), value)

    def test_safe_bool_default_on_garbage(self):
        self.assertTrue(ui_server.safe_bool("maybe", True))
        self.assertFalse(ui_server.safe_bool("maybe", False))


class TestRouterDispatch(unittest.TestCase):
    def make(self, routes=()):
        router = Router()
        for method, pattern, handler in routes:
            router.add(method, pattern, handler, feature="test")
        return ui_server.JsonApiServer(router=router, web_dir=None)

    def test_dict_becomes_ok_json(self):
        server = self.make([("GET", "/api/x", lambda r: {"value": 1})])
        request = ui_server.Request("GET", "/api/x", {}, {}, {})
        response = server.handle(request)
        self.assertEqual(response.status, 200)
        self.assertEqual(response.body, {"value": 1})

    def test_handler_exception_becomes_500(self):
        def boom(_request):
            raise ValueError("炸了")

        server = self.make([("GET", "/api/boom", boom)])
        request = ui_server.Request("GET", "/api/boom", {}, {}, {})
        response = server.handle(request)
        self.assertEqual(response.status, 500)
        self.assertEqual(response.body["ok"], False)
        self.assertIn("炸了", response.body["error"])

    def test_unknown_api_route_404(self):
        server = self.make()
        request = ui_server.Request("GET", "/api/nope", {}, {}, {})
        response = server.handle(request)
        self.assertEqual(response.status, 404)
        self.assertEqual(response.body["code"], "not_found")

    def test_request_arg_prefers_body_over_query(self):
        request = ui_server.Request("POST", "/api/x", {"dir": "from-query"},
                                   {"dir": "from-body"}, {})
        self.assertEqual(request.arg("dir"), "from-body")

    def test_request_int_and_bool_args(self):
        request = ui_server.Request("GET", "/api/x", {"n": "", "b": "yes"}, {}, {})
        self.assertEqual(request.int_arg("n", 7), 7)
        self.assertTrue(request.bool_arg("b"))


class TestHttpServer(unittest.TestCase):
    """真实启动 HTTP 服务并走完整 socket 链路。"""

    @classmethod
    def setUpClass(cls):
        router = Router()
        router.get("/api/ping", lambda r: {"pong": True}, name="ping")
        router.post("/api/echo", lambda r: {"got": r.data}, name="echo")
        router.get("/api/kaboom", lambda r: (_ for _ in ()).throw(RuntimeError("x")),
                   name="kaboom")
        cls.server = ui_server.JsonApiServer(router=router)
        cls.url = cls.server.start(port=0)

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()

    def test_health_endpoint_absent_here(self):
        """本测试用的 router 没有 /api/health，应得到 404 而不是崩溃。"""
        status, payload = http(self.url + "api/health")
        self.assertEqual(status, 404)

    def test_get_route(self):
        status, payload = http(self.url + "api/ping")
        self.assertEqual(status, 200)
        self.assertTrue(payload["pong"])

    def test_post_body_roundtrip(self):
        status, payload = http(self.url + "api/echo", "POST", {"a": 1, "中文": "值"})
        self.assertEqual(status, 200)
        self.assertEqual(payload["got"], {"a": 1, "中文": "值"})

    def test_invalid_json_does_not_crash(self):
        """修 B-14：畸形 body 不得让服务断连。"""
        request = urllib.request.Request(
            self.url + "api/echo", data=b"{not json",
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
        # 新行为：声明 JSON 却解析失败时保留原文并标记，不伪造成表单键值
        self.assertEqual(payload["got"].get("_parse_error"), "invalid json")
        self.assertEqual(payload["got"].get("_raw"), "{not json")

    def test_query_params_reachable_on_get(self):
        """修原实现的 GET/POST 语义不对称：GET 也必须能读到 query。"""
        router = Router()
        router.get("/api/q", lambda r: {"dir": r.str_arg("dir")}, name="q")
        server = ui_server.JsonApiServer(router=router)
        url = server.start(port=0)
        self.addCleanup(server.stop)
        status, payload = http(url + "api/q?dir=hello%20world")
        self.assertEqual(status, 200)
        self.assertEqual(payload["dir"], "hello world")

    def test_empty_query_value_does_not_500(self):
        router = Router()
        router.get("/api/p", lambda r: {"page": r.int_arg("page", 1)}, name="p")
        server = ui_server.JsonApiServer(router=router)
        url = server.start(port=0)
        self.addCleanup(server.stop)
        status, payload = http(url + "api/p?page=")
        self.assertEqual(status, 200)
        self.assertEqual(payload["page"], 1)

    def test_handler_exception_returns_500_over_http(self):
        status, payload = http(self.url + "api/kaboom")
        self.assertEqual(status, 500)
        self.assertFalse(payload["ok"])


class TestSecurity(unittest.TestCase):
    """修 B-20：原实现无 Host/Origin 校验，任何本地网页都能驱动工具。"""

    @classmethod
    def setUpClass(cls):
        router = Router()
        router.get("/api/x", lambda r: {"ok": True}, name="x")
        cls.server = ui_api = ui_server.JsonApiServer(router=router)
        cls.url = ui_api.start(port=0)

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()

    def test_allows_localhost_host(self):
        status, _ = http(self.url + "api/x", headers={"Host": "127.0.0.1:1"})
        self.assertEqual(status, 200)

    def test_rejects_foreign_host(self):
        status, payload = http(self.url + "api/x",
                               headers={"Host": "evil.example.com"})
        self.assertEqual(status, 403)
        self.assertEqual(payload["code"], "bad_host")

    def test_rejects_foreign_origin(self):
        status, payload = http(self.url + "api/x",
                               headers={"Origin": "http://evil.example.com"})
        self.assertEqual(status, 403)
        self.assertEqual(payload["code"], "bad_origin")

    def test_allows_local_origin(self):
        status, _ = http(self.url + "api/x",
                         headers={"Origin": "http://127.0.0.1:8765"})
        self.assertEqual(status, 200)

    def test_path_traversal_blocked(self):
        for path in ("api/../app.py", "..%2fapp.py", "api/%2e%2e/app.py"):
            with self.subTest(path=path):
                status, _ = http(self.url + path)
                self.assertIn(status, (400, 403, 404))

    def test_static_serves_web_dir(self):
        import tempfile
        tmp = tempfile.TemporaryDirectory(prefix="web_")
        self.addCleanup(tmp.cleanup)
        with open(os.path.join(tmp.name, "index.html"), "w", encoding="utf-8") as f:
            f.write("<html>ok</html>")
        server = ui_server.JsonApiServer(router=Router(), web_dir=tmp.name)
        url = server.start(port=0)
        self.addCleanup(server.stop)
        status, payload = http(url)
        self.assertEqual(status, 200)
        self.assertIn(b"ok", payload)


class TestCoreRoutes(unittest.TestCase):
    """用真实 App 装配后验证核心路由与功能路由都可用。"""

    @classmethod
    def setUpClass(cls):
        import app as app_mod
        cls.app = app_mod.build_app()
        cls.url = cls.app.start(port=0)
        cls.ok, cls.report = cls.app.check()

    @classmethod
    def tearDownClass(cls):
        cls.app.stop()

    def test_selfcheck_passed(self):
        self.assertTrue(self.ok, self.report["problems"])

    def test_health(self):
        status, payload = http(self.url + "api/health")
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        # 功能数量是目录驱动的（§8-6）；断言"≥ 已知的三个"而不是写死，
        # 这样新增功能不必回头改这条测试
        self.assertGreaterEqual(payload["registry"]["count"], 3)

    def test_features_lists_every_discovered_feature_with_health(self):
        status, payload = http(self.url + "api/features")
        self.assertEqual(status, 200)
        ids = sorted(f["id"] for f in payload["features"])
        self.assertEqual(ids, sorted(self.app.registry.ids()),
                         "/api/features 与注册表不一致")
        for feature in payload["features"]:
            with self.subTest(feature=feature["id"]):
                self.assertEqual(feature["health"]["status"], "ok",
                                 feature["health"].get("detail"))

    def test_nav_is_sorted_by_declared_order(self):
        status, payload = http(self.url + "api/nav")
        orders = [(i["order"], i["id"]) for i in payload["items"]]
        self.assertEqual(orders, sorted(orders),
                         "导航没有按 order 排序：%s" % orders)
        ids = [i["id"] for i in payload["items"]]
        for required in ("translate", "cheats", "selfcheck"):
            with self.subTest(feature=required):
                self.assertIn(required, ids)

    def test_pages_lists_every_page(self):
        status, payload = http(self.url + "api/pages")
        modules = {p["module"] for p in payload["pages"]}
        for required in ("translate", "cheats", "selfcheck"):
            with self.subTest(page=required):
                self.assertIn(required, modules)

    def test_routes_include_feature_routes(self):
        status, payload = http(self.url + "api/routes")
        patterns = {r["pattern"] for r in payload["routes"]}
        self.assertIn("/api/health", patterns)
        # M3a：翻译功能已接线，这里改断言一个真实的业务端点
        # （骨架端点 /api/translate/status 已由 /api/translate/state 取代）
        self.assertIn("/api/translate/state", patterns)
        self.assertIn("/api/cheats/detect", patterns)
        # M3b：修改功能同样接线
        self.assertIn("/api/cheats/saves", patterns)
        # §8-6：新增功能的路由也自动出现
        self.assertIn("/api/selfcheck/report", patterns)

    def test_selfcheck_report_over_http(self):
        """§8-6 的演示功能端到端过一次 HTTP。"""
        status, payload = http(self.url + "api/selfcheck/report")
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertGreaterEqual(payload["assembly"]["feature_count"], 3)
        self.assertEqual(payload["convergence"]["marshal"], "merged")

    def test_translate_state_over_http(self):
        """端到端过一次 HTTP：路由 → 处理器 → JSON 序列化。

        单元测试直接调 handler 拿不到"响应能不能被序列化成 JSON"这一层，
        而 M3a 返回的都是复杂嵌套 dict（含 None / 浮点 / 中文），值得钉一下。
        """
        status, payload = http(self.url + "api/translate/state")
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["session"]["loaded"])
        self.assertIsNone(payload["session"]["game_dir"])

    def test_translate_open_missing_dir_over_http(self):
        status, payload = http(self.url + "api/translate/open", "POST", {})
        self.assertEqual(status, 200)
        self.assertFalse(payload["ok"])
        self.assertIn("dir", payload["error"])

    def test_translate_providers_over_http(self):
        status, payload = http(self.url + "api/translate/providers")
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(len(payload["providers"]), 4)

    def test_cheats_status_over_http(self):
        status, payload = http(self.url + "api/cheats/status")
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["game"]["opened"])
        self.assertTrue(payload["actor_attrs"])
        self.assertNotEqual(payload.get("status"), "skeleton")

    def test_cheats_saves_without_game_over_http(self):
        status, payload = http(self.url + "api/cheats/saves")
        self.assertEqual(status, 200)
        self.assertFalse(payload["ok"])
        self.assertIn("游戏目录", payload["error"])

    def test_job_missing_code(self):
        status, payload = http(self.url + "api/job?id=nope")
        self.assertEqual(payload["code"], "job_missing")

    def test_cheats_detect_without_dir(self):
        status, payload = http(self.url + "api/cheats/detect", "POST", {})
        self.assertFalse(payload["ok"])

    def test_cheats_detect_unknown_dir(self):
        status, payload = http(self.url + "api/cheats/detect", "POST",
                               {"dir": os.path.join(_ROOT, "core")})
        self.assertFalse(payload["ok"])
        self.assertIn("未识别", payload["error"])

    def test_cheats_detect_on_reference_tool_is_not_a_game(self):
        status, payload = http(self.url + "api/cheats/detect", "POST",
                               {"dir": _ROOT})
        self.assertFalse(payload["ok"])

    def test_index_html_served(self):
        with urllib.request.urlopen(self.url, timeout=10) as response:
            body = response.read().decode("utf-8")
        self.assertIn("RPG Maker 全能工具", body)
        self.assertIn('id="nav"', body)
        self.assertIn('id="view"', body)


if __name__ == "__main__":
    unittest.main(verbosity=2)

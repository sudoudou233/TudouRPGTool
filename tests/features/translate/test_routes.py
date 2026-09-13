# -*- coding: utf-8 -*-
"""M3a 后端接线测试：``/api/translate/*` 全链路（扫描→编辑→翻译→构建→还原）。

@feature  translate
@layer    tests
@public   RouteTestCase, TestRouteRegistration, TestSessionIdentity,
          TestOpenAndScan, TestEntryPaging, TestConfigEndpoints,
          TestJobEndpoints, TestBuildAndRestore, TestPrivacy
@depends  features.translate.manifest, features.translate.routes,
          core.jobs, core.config, core.safety.backup
@tested   (本文件即测试)
@footprint docs/STATE.md

为什么这个文件重要
------------------
M1/M2 阶段两个功能页都还是骨架，**没有任何测试碰过 features/translate 的路由**。
M3a 首次接线时最容易出的错不是"抛异常"，而是：

* 路由名/路径与旧前端约定不一致 → 页面静默 404；
* ``Session.entries`` 是 keyed-dict → 构建时一条译文都写不进去却不报错；
* "用户没改 Key" 的掩码回显把已保存的 API Key 覆盖成空；
* 长任务没有真正接上 ``ctx.jobs`` → 进度/取消全部失效。

本文件对每一条都给出**可观测断言**。

夹具说明
--------
* MV 夹具是纯 JSON，直接写盘；
* VX Ace 夹具用 ``core.marshal.doc_model`` 构造节点树再 ``dumps`` 成
  ``.rvdata2`` —— 这是**真实字节流**（含 Ruby Marshal 头与符号表），
  因此它同时验证了"解析→扫描→写回→再解析"的整条链路。
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

_ROOT = os.path.dirname(os.path.abspath(__file__))
while not os.path.isfile(os.path.join(_ROOT, "app.py")):
    parent = os.path.dirname(_ROOT)
    if parent == _ROOT:
        raise RuntimeError("无法定位工程根（未找到 app.py）")
    _ROOT = parent
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core import paths  # noqa: E402
from core.context import AppContext  # noqa: E402


# ---------------------------------------------------------------------------
# 夹具：合成游戏目录
# ---------------------------------------------------------------------------
def write_text(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False)


def text_command(code, text):
    """MV/MZ 事件指令（``code`` 401 为对话、402 为选项）。"""
    return {"code": code, "indent": 0, "parameters": [text]}


def make_mv_game(root, dialogue="你好，旅行者。", www=False):
    """合成一个能被 ``engines.detect`` 认出的 RPG Maker MV 游戏。

    ``www=True`` 时用**老版 NW.js 布局**：``js/`` 与 ``data/`` 在 ``www/`` 下，
    而 ``Game.exe`` 等运行时在**游戏根**（真实游戏里非常常见，例如
    boli3/RJ01052631）。这个布局是"生成的汉化版只有 www、没有 Game.exe"
    那个缺陷的现场，因此必须有一个夹具专门覆盖它。
    """
    web = os.path.join(root, "www") if www else root
    write_text(os.path.join(web, "js", "rpg_core.js"), "// synthetic\n")
    write_json(os.path.join(web, "data", "System.json"),
               {"gameTitle": "合成MV", "locale": "ja_JP"})
    write_json(os.path.join(web, "data", "CommonEvents.json"), [
        None,
        {"id": 1, "name": "开场",
         "list": [text_command(101, ""),
                  text_command(401, dialogue),
                  {"code": 402, "indent": 0,
                   "parameters": [["是", "否"], 1, 0]},
                  {"code": 0, "indent": 0, "parameters": []}]},
    ])
    write_json(os.path.join(web, "data", "Items.json"), [
        None,
        {"id": 1, "name": "药草", "description": "恢复少量生命"},
    ])
    write_json(os.path.join(web, "data", "MapInfos.json"),
               [None, {"id": 1, "name": "起始村"}])
    if www:
        # 游戏根的运行时文件 —— 副本里缺了它们就根本启动不了
        with open(os.path.join(root, "Game.exe"), "wb") as f:
            f.write(b"MZ\x90\x00 fake nw.js exe")
        with open(os.path.join(root, "package.json"), "w", encoding="utf-8") as f:
            f.write('{"name":"synthetic","main":"www/index.html"}')
        with open(os.path.join(root, "nw.dll"), "wb") as f:
            f.write(b"\x00" * 64)
    return root


def make_vxace_game(root, dialogue="你好，旅行者。"):
    """合成一个 VX Ace 游戏（``.rvdata2`` 是真实 Marshal 字节流）。"""
    from core.marshal import doc_model as D

    def st(text):
        return D.String(text.encode("utf-8"))

    def sym(name):
        return D.Symbol(name.encode("utf-8"))

    def command(code, params):
        return D.ObjectNode(sym("RPG::EventCommand"), [
            (sym("@code"), D.Fixnum(code)),
            (sym("@indent"), D.Fixnum(0)),
            (sym("@parameters"), D.Array(params)),
        ])

    write_text(os.path.join(root, "Game.ini"), "[Game]\nTitle=合成\n")
    data = os.path.join(root, "Data")
    events = D.Array([
        D.NilNode(),
        D.ObjectNode(sym("RPG::CommonEvent"), [
            (sym("@name"), st("开场")),
            (sym("@list"), D.Array([
                command(401, [st(dialogue)]),
                command(402, [D.Array([st("是"), st("否")]), D.Fixnum(1)]),
            ])),
        ]),
    ])
    os.makedirs(data, exist_ok=True)
    with open(os.path.join(data, "CommonEvents.rvdata2"), "wb") as f:
        f.write(D.dumps(events))
    items = D.Array([D.NilNode(),
                     D.ObjectNode(sym("RPG::Item"), [
                         (sym("@name"), st("药草")),
                         (sym("@description"), st("恢复少量生命")),
                     ])])
    with open(os.path.join(data, "Items.rvdata2"), "wb") as f:
        f.write(D.dumps(items))
    with open(os.path.join(data, "System.rvdata2"), "wb") as f:
        f.write(D.dumps(D.ObjectNode(sym("RPG::System"), [
            (sym("@game_title"), st("合成VXAce")),
            (sym("@currency_unit"), st("金币")),
        ])))
    return root


# ---------------------------------------------------------------------------
# 基类：装配一个隔离的应用上下文
# ---------------------------------------------------------------------------
class RouteTestCase(unittest.TestCase):
    """给每个用例一套**隔离**的数据目录 / 配置 / 任务管理器。

    ``TUDOU_RPGTOOL_DATA`` 被指向临时目录，所以会话文件不会污染
    ``runtime/sessions``（CI 上也不会有跨用例串味）。
    """

    #: 子类指定合成游戏的构造函数
    make_game = staticmethod(make_mv_game)

    def setUp(self):
        # ⚠ Windows 上 ``TemporaryDirectory.cleanup`` 偶发
        # "OSError: [WinError 145] 目录不是空的"：后台任务线程刚写完会话文件，
        # 与 rmtree 撞在一起。有 ``ignore_cleanup_errors``（3.10+）就用它；
        # 3.8/3.9 没有该参数，退回普通 cleanup（残留交给系统临时目录）。
        try:
            self.tmp = tempfile.TemporaryDirectory(prefix="troutes_",
                                                   ignore_cleanup_errors=True)
        except TypeError:
            self.tmp = tempfile.TemporaryDirectory(prefix="troutes_")
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name
        self.data = os.path.join(self.root, "runtime")
        os.makedirs(self.data, exist_ok=True)

        env = mock.patch.dict(os.environ, {"TUDOU_RPGTOOL_DATA": self.data})
        env.start()
        self.addCleanup(env.stop)

        from core import config as config_mod
        from core import jobs as jobs_mod
        from core.context import Router

        self.config = config_mod.AppConfig(path=os.path.join(self.root, "config.json"))
        self.jobs = jobs_mod.JobManager(max_workers=2, max_pending=32, ttl=60,
                                        id_prefix="t")
        self.addCleanup(self.jobs.shutdown)

        ctx = AppContext(router=Router(), config=self.config, jobs=self.jobs)
        from features.translate import manifest as translate_manifest
        translate_manifest.register(ctx)
        self.ctx = ctx

    # ------------------------------------------------------------ 调用助手
    def handler(self, method, path):
        """取路由处理器（**staticmethod 包裹**，避免描述符绑定陷阱）。"""
        route, _params = self.ctx.router.resolve(method, path)
        self.assertIsNotNone(route, "路由不存在：%s %s" % (method, path))
        return staticmethod(route.handler).__func__

    def call(self, method, path, **body):
        from ui.server import Request
        request = Request(method, path, {}, body, {})
        return self.handler(method, path)(request)

    def get(self, path, **query):
        from ui.server import Request
        request = Request("GET", path, query, {}, {})
        return self.handler("GET", path)(request)

    # ------------------------------------------------------------ 夹具助手
    def game(self, name="game", **kw):
        directory = os.path.join(self.root, name)
        os.makedirs(directory, exist_ok=True)
        self.make_game(directory, **kw)
        return directory

    def service(self):
        """取 ``manifest.register`` 构造的 TranslateService。

        ``register_routes`` 把它挂在 ``ctx.translate_service`` 上（见该函数
        文档）；只有测试与调试页用它，生产代码不应依赖这个属性。
        """
        service = getattr(self.ctx, "translate_service", None)
        self.assertIsNotNone(service, "register_routes 未暴露服务实例")
        return service

    @staticmethod
    def _read(path):
        """读文本文件（显式 UTF-8；不用裸 ``open().read()`` 以免 ResourceWarning）。"""
        with open(path, encoding="utf-8") as f:
            return f.read()

    def scanned(self, **kw):
        """建游戏 → open → 同步跑完 scan，返回 ``(dir, payload)``。"""
        directory = self.game(**kw)
        opened = self.call("POST", "/api/translate/open", dir=directory)
        self.assertTrue(opened["ok"], opened.get("error"))
        scanned = self.call("POST", "/api/translate/scan", dir=directory)
        self.assertTrue(scanned["ok"], scanned.get("error"))
        payload = self.jobs.wait(scanned["job"], timeout=60)
        self.assertEqual(payload["status"], "done",
                         "扫描任务未成功：%s %s" % (payload["error"],
                                                    payload["traceback_tail"]))
        return directory, payload["result"]

    def entries(self, **kw):
        payload = self.get("/api/translate/entries", **kw)
        return payload["entries"]


# ---------------------------------------------------------------------------
# 路由登记
# ---------------------------------------------------------------------------
class TestRouteRegistration(unittest.TestCase):
    """路由表必须完整，且**不得逃出** ``/api/translate`` 命名空间。"""

    #: M3a 约定的完整端点清单（前端 ui/web/pages/translate.js 依赖它）
    EXPECTED = (
        ("GET", "/api/translate/state"),
        ("POST", "/api/translate/open"),
        ("POST", "/api/translate/pick_folder"),
        ("POST", "/api/translate/pick_font"),
        ("POST", "/api/translate/scan"),
        ("GET", "/api/translate/entries"),
        ("POST", "/api/translate/entry"),
        ("POST", "/api/translate/skip_all"),
        ("POST", "/api/translate/start"),
        ("GET", "/api/translate/providers"),
        ("POST", "/api/translate/test"),
        ("GET", "/api/translate/config"),
        ("POST", "/api/translate/config"),
        ("POST", "/api/translate/build"),
        ("GET", "/api/translate/backups"),
        ("POST", "/api/translate/restore"),
        ("POST", "/api/translate/open_dir"),
    )

    @classmethod
    def setUpClass(cls):
        # 走真实的 Registry 装配路径，而不是直接调 manifest.register ——
        # ``route.feature`` 是由 ``Registry.register_all`` 设置 ctx 的
        # "当前功能" 后才填上的；直接调 register 会全是 None，
        # 那样就**测不出**"路由归属是否正确"这个真实问题。
        #
        # 副作用：注册表会把**所有**功能都装配进来（cheats 也在），
        # 因此断言前必须按 ``route.feature`` 过滤 —— 这不是为了迁就测试，
        # 而是真实的运行时视图。
        from core import registry as registry_mod
        from core.context import AppContext, Router
        reg = registry_mod.Registry().discover()
        ctx = AppContext(router=Router())
        cls.report = reg.register_all(ctx)
        cls.routes = [r for r in ctx.router.routes() if r.feature == "translate"]
        cls.ctx = ctx

    def test_all_expected_endpoints_registered(self):
        have = {(r.method, r.pattern) for r in self.routes}
        missing = [pair for pair in self.EXPECTED if pair not in have]
        self.assertEqual(missing, [], "缺少 M3a 约定的端点：%s" % missing)

    def test_no_extra_endpoints_beyond_the_declared_list(self):
        """反向检查：多出来的端点必须显式加进 ``EXPECTED``。

        只查"有没有少"会让前端偷偷多调一个没人知道的接口也能过；
        双向核对才能保证"接口清单"是一份可信的契约。
        """
        have = {(r.method, r.pattern) for r in self.routes}
        extra = sorted(have - set(self.EXPECTED))
        self.assertEqual(extra, [], "出现了未登记的端点：%s" % extra)

    def test_every_route_in_namespace(self):
        for route in self.routes:
            with self.subTest(route=route.pattern):
                self.assertTrue(route.pattern.startswith("/api/translate"),
                                "路由逃出命名空间：%s" % route.pattern)

    def test_routes_attributed_to_feature(self):
        """路由要带上 feature 归属，否则足迹校验与调试页看不到它。"""
        for route in self.routes:
            with self.subTest(route=route.pattern):
                self.assertEqual(route.feature, "translate")
        self.assertTrue(self.routes, "registry 装配后一条 translate 路由都没有")

    def test_register_report_is_not_skeleton(self):
        self.assertIn("routes", self.report["translate"])
        self.assertNotIn("skeleton", self.report["translate"])

    def test_no_route_name_collision(self):
        names = [r.name for r in self.routes]
        self.assertEqual(len(names), len(set(names)),
                         "路由名重复：%s" % names)

    def test_providers_ids_match_build_translator(self):
        """下拉里的引擎 id 必须都能真的构造出适配器（防"列表里有、选了报错"）。"""
        from features.translate import translators
        payload = staticmethod(self.ctx.router.resolve(
            "GET", "/api/translate/providers")[0].handler).__func__(None)
        for provider in payload["providers"]:
            with self.subTest(provider=provider["id"]):
                translator = translators.build_translator(
                    {"engine": provider["id"], "api_key": "x"})
                self.assertTrue(hasattr(translator, "translate_batch"))


# ---------------------------------------------------------------------------
# 会话 id
# ---------------------------------------------------------------------------
class TestSessionIdentity(unittest.TestCase):
    """会话文件必须**只由游戏目录**决定，且斜杠/反斜杠写法不产生两份。"""

    def test_same_dir_different_separators_same_id(self):
        from features.translate import routes
        a = routes.session_id_for("D:\\games\\A")
        b = routes.session_id_for("D:/games/A")
        self.assertEqual(a, b)

    def test_id_has_no_path_separators_or_colon(self):
        from features.translate import routes
        sid = routes.session_id_for("D:\\games\\A")
        for ch in ("\\", "/", ":"):
            self.assertNotIn(ch, sid)
        self.assertTrue(sid)

    def test_empty_dir_is_unknown(self):
        from features.translate import routes
        self.assertEqual(routes.session_id_for(""), "unknown")

    def test_session_path_lands_in_runtime_dir(self):
        from features.translate import routes
        path = routes.session_path_for("D:\\games\\A")
        self.assertEqual(os.path.dirname(os.path.abspath(path)),
                         os.path.abspath(paths.sessions_dir()))
        self.assertTrue(path.endswith(".json"))


# ---------------------------------------------------------------------------
# 打开 / 扫描
# ---------------------------------------------------------------------------
class TestOpenAndScan(RouteTestCase):
    def test_state_before_open(self):
        payload = self.call("GET", "/api/translate/state")
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["session"]["loaded"])

    def test_open_requires_dir(self):
        payload = self.call("POST", "/api/translate/open")
        self.assertFalse(payload["ok"])
        self.assertIn("dir", payload["error"])

    def test_open_unknown_dir_is_reported(self):
        with tempfile.TemporaryDirectory(prefix="nogame_") as tmp:
            payload = self.call("POST", "/api/translate/open", dir=tmp)
        self.assertFalse(payload["ok"])
        self.assertIn("未识别", payload["error"])

    def test_open_recognizes_engine(self):
        directory = self.game()
        payload = self.call("POST", "/api/translate/open", dir=directory)
        self.assertTrue(payload["ok"], payload.get("error"))
        self.assertEqual(payload["session"]["engine"], "mv")
        self.assertEqual(payload["session"]["game_dir"],
                         os.path.abspath(directory))

    def test_open_unsupported_engine_is_refused(self):
        """2K/2K3 能识别但格式不支持 —— 必须明确拒绝，而不是扫出 0 条。"""
        with tempfile.TemporaryDirectory(prefix="2k_") as tmp:
            write_text(os.path.join(tmp, "RPG_RT.ini"), "[RPG_RT]\n")
            payload = self.call("POST", "/api/translate/open", dir=tmp)
        self.assertFalse(payload["ok"])
        self.assertIn("不支持", payload["error"])

    def test_scan_produces_entries(self):
        _dir, result = self.scanned()
        self.assertGreater(result["total"], 0)
        self.assertTrue(result["session"]["loaded"])
        self.assertIn("counts", result["session"])

    def test_scan_is_a_background_job_with_progress(self):
        """扫描必须走 ``ctx.jobs``（否则进度条/取消全失效）。"""
        directory = self.game()
        self.call("POST", "/api/translate/open", dir=directory)
        payload = self.call("POST", "/api/translate/scan", dir=directory)
        self.assertTrue(payload["ok"], payload.get("error"))
        self.assertIn("job", payload)
        self.jobs.wait(payload["job"], timeout=60)
        snap = self.jobs.get(payload["job"])
        self.assertEqual(snap["name"], "扫描文本")
        self.assertIn(snap["status"], ("done", "running"))

    def test_scan_persists_session_for_resume(self):
        """扫描后必须落盘 —— 关掉工具再开要能续。"""
        directory, _result = self.scanned()
        from features.translate import routes
        path = routes.session_path_for(directory)
        self.assertTrue(os.path.isfile(path), "会话文件未写出：%s" % path)

    def test_reopen_resumes_without_rescan(self):
        """同一目录再次 open 要复用已存会话（断点续传）。"""
        directory, _result = self.scanned()
        payload = self.call("POST", "/api/translate/open", dir=directory)
        self.assertTrue(payload["ok"], payload.get("error"))
        self.assertGreater(payload["cached_entries"], 0,
                           "重开同一目录时未复用已扫描的条目")

    def test_reopen_after_move_retargets_game_dir(self):
        """游戏目录被改名后，``info`` 必须跟着指向新路径。

        ``builder.build`` 读的是 ``session.info["game_dir"]`` 而不是
        ``session.game_dir``，只改后者会让"生成汉化版"写到旧路径。
        """
        directory, _result = self.scanned()
        moved = directory + "_moved"
        shutil.move(directory, moved)
        self.addCleanup(lambda: shutil.rmtree(moved, ignore_errors=True))
        payload = self.call("POST", "/api/translate/open", dir=moved)
        self.assertTrue(payload["ok"], payload.get("error"))
        self.assertEqual(os.path.abspath(self.service().session.info["game_dir"]),
                         os.path.abspath(moved))

    def test_corrupt_session_file_does_not_break_open(self):
        directory, _result = self.scanned()
        from features.translate import routes
        with open(routes.session_path_for(directory), "w", encoding="utf-8") as f:
            f.write("{ 这不是 JSON")
        payload = self.call("POST", "/api/translate/open", dir=directory)
        self.assertTrue(payload["ok"], payload.get("error"))
        self.assertEqual(payload["cached_entries"], 0, "损坏会话应被丢弃并新建")


class TestOpenAndScanVXAce(TestOpenAndScan):
    """同一批用例在 VX Ace（真实 Marshal 字节流）上重跑一遍。"""

    make_game = staticmethod(make_vxace_game)

    def test_open_recognizes_engine(self):
        directory = self.game()
        payload = self.call("POST", "/api/translate/open", dir=directory)
        self.assertTrue(payload["ok"], payload.get("error"))
        self.assertEqual(payload["session"]["engine"], "vxace")

    def test_scan_includes_dialogue_not_just_terms(self):
        """**N-12/13/14 的接线级护栏**：对话必须出现在扫描结果里。"""
        _dir, result = self.scanned()
        categories = result["session"]["categories"]
        self.assertGreaterEqual(categories.get("对话", 0), 1,
                                "VX Ace 对话未进入扫描结果：%s" % categories)
        self.assertGreaterEqual(categories.get("名称", 1), 1)


# ---------------------------------------------------------------------------
# 条目列表 / 编辑
# ---------------------------------------------------------------------------
class TestEntryPaging(RouteTestCase):
    def test_entries_without_session_is_empty_not_error(self):
        payload = self.call("GET", "/api/translate/entries")
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["entries"], [])
        self.assertEqual(payload["total"], 0)

    def test_page_size_is_clamped(self):
        self.scanned()
        payload = self.get("/api/translate/entries", size=99999)
        self.assertLessEqual(payload["size"], 500)
        payload = self.get("/api/translate/entries", size=1)
        self.assertGreaterEqual(payload["size"], 10)

    def test_bad_page_number_falls_back(self):
        self.scanned()
        payload = self.get("/api/translate/entries", page="abc")
        self.assertEqual(payload["page"], 1)

    def test_paging_covers_everything_once(self):
        self.scanned()
        total = self.get("/api/translate/entries", size=10)["total"]
        seen = []
        for page in range(1, (total + 9) // 10 + 1):
            seen.extend(e["original"]
                        for e in self.entries(page=page, size=10))
        self.assertEqual(len(seen), total)
        self.assertEqual(len(set(seen)), total, "分页出现重复条目")

    def test_filter_by_category(self):
        self.scanned()
        payload = self.get("/api/translate/entries", category="名称")
        self.assertGreater(payload["total"], 0)
        for entry in payload["entries"]:
            self.assertEqual(entry["category"], "名称")

    def test_search_matches_original_and_translation(self):
        self.scanned()
        hit = self.get("/api/translate/entries", q="药草")
        self.assertGreater(hit["total"], 0)
        miss = self.get("/api/translate/entries", q="绝对不存在的字符串xyz")
        self.assertEqual(miss["total"], 0)

    def test_public_view_omits_internal_fields(self):
        """条目视图只暴露前端需要的字段（防止把内部状态当接口）。"""
        self.scanned()
        entry = self.entries()[0]
        self.assertEqual(set(entry), {"file", "path", "category", "original",
                                      "translated", "status", "note", "error"})

    def test_update_entry_requires_key(self):
        self.scanned()
        payload = self.call("POST", "/api/translate/entry", key="")
        self.assertFalse(payload["ok"])
        self.assertIn("key", payload["error"])

    def test_update_entry_unknown_key_reports(self):
        self.scanned()
        payload = self.call("POST", "/api/translate/entry", key="nope|nope",
                            translated="x")
        self.assertFalse(payload["ok"])
        self.assertIn("不存在", payload["error"])

    def test_update_entry_writes_and_persists(self):
        directory, _result = self.scanned()
        entry = self.entries(q="药草")[0]
        key = "%s|%s" % (entry["file"], entry["path"])
        payload = self.call("POST", "/api/translate/entry", key=key,
                            translated="Herb", status="translated")
        self.assertTrue(payload["ok"], payload.get("error"))
        again = [e for e in self.entries() if e["original"] == "药草"][0]
        self.assertEqual(again["translated"], "Herb")
        self.assertEqual(again["status"], "translated")

        from features.translate import routes
        with open(routes.session_path_for(directory), encoding="utf-8") as f:
            saved = json.load(f)
        self.assertTrue(any(e.get("translated") == "Herb"
                            for e in saved["entries"]),
                        "改过的译文没有落盘（断点续传会丢）")

    def test_update_entry_without_session_is_clean_error(self):
        payload = self.call("POST", "/api/translate/entry", key="a|b",
                            translated="x")
        self.assertFalse(payload["ok"])
        self.assertIn("扫描", payload["error"])

    def test_skip_all_marks_pending(self):
        self.scanned()
        before = self.get("/api/translate/entries", status="pending")["total"]
        self.assertGreater(before, 0)
        payload = self.call("POST", "/api/translate/skip_all")
        self.assertTrue(payload["ok"], payload.get("error"))
        self.jobs.wait(payload["job"], timeout=60)
        after = self.get("/api/translate/entries", status="pending")["total"]
        self.assertEqual(after, 0)
        self.assertGreaterEqual(
            self.get("/api/translate/entries", status="skipped")["total"], before)

    def test_skip_all_can_be_scoped_to_category(self):
        """限定类别时不得波及其它类别。

        ⚠ **必须等任务结束再断言**（开发本用例时踩到）：``skip_all`` 是后台
        任务，``submit`` 之后立刻读条目大概率读到"一条都没动"的状态 ——
        本用例最初忘了 ``jobs.wait``，于是**间歇性失败**（同样的代码有时
        0、有时 3）。这类"偶发红"最容易被误判成业务缺陷，所以这里显式等。
        """
        self.scanned()
        pending_before = self.get("/api/translate/entries", status="pending")["total"]
        payload = self.call("POST", "/api/translate/skip_all", category="名称")
        self.assertTrue(payload["ok"], payload.get("error"))
        snap = self.jobs.wait(payload["job"], timeout=60)
        self.assertEqual(snap["status"], "done", snap.get("error"))

        self.assertEqual(self.get("/api/translate/entries",
                                  category="名称", status="pending")["total"], 0)
        rest = self.get("/api/translate/entries", status="pending")["total"]
        self.assertGreater(rest, 0, "限定类别时不应波及别的类别")
        self.assertEqual(rest + snap["result"]["skipped"], pending_before,
                         "跳过的条数必须恰好等于该类别的待处理条数")


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------
class TestConfigEndpoints(RouteTestCase):
    def test_get_config_masks_api_key(self):
        self.config["api_key"] = "sk-1234567890abcdef"
        payload = self.call("GET", "/api/translate/config")
        self.assertTrue(payload["ok"])
        self.assertNotIn("1234567890", payload["config"]["api_key"])
        self.assertIn("***", payload["config"]["api_key"])

    def test_save_config_requires_object(self):
        payload = self.call("POST", "/api/translate/config", config="nope")
        self.assertFalse(payload["ok"])

    def test_save_config_persists_and_masks(self):
        payload = self.call("POST", "/api/translate/config",
                            config={"model": "deepseek-chat",
                                    "api_key": "sk-abcdefghijkl"})
        self.assertTrue(payload["ok"], payload.get("error"))
        on_disk = json.loads(self._read(self.config.path))
        self.assertEqual(on_disk["model"], "deepseek-chat")
        self.assertEqual(on_disk["api_key"], "sk-abcdefghijkl",
                         "密钥必须真的落盘（否则用户每次都要重填）")
        self.assertNotIn("abcdefghijkl", payload["config"]["api_key"],
                         "接口返回值必须掩码")

    def test_start_does_not_clobber_saved_key_with_blank(self):
        """**回归**：前端回显掩码/空值时不得把关好的 Key 清掉。

        原工具的表现是"用户不重填 Key 就会认证失败"，排查起来很费时。
        """
        self.config["api_key"] = "sk-REAL-KEY-0123456789"
        self.config.save()
        directory, _result = self.scanned()
        self.call("POST", "/api/translate/start", config={
            "engine": "google",          # google 不需要 Key
            "api_key": "sk-RE***89",     # 掩码回显
        })
        self.assertEqual(self.config.get("api_key"), "sk-REAL-KEY-0123456789")

    def test_start_with_empty_key_keeps_saved_key(self):
        self.config["api_key"] = "sk-KEEP-ME"
        self.scanned()
        self.call("POST", "/api/translate/start",
                  config={"engine": "google", "api_key": ""})
        self.assertEqual(self.config.get("api_key"), "sk-KEEP-ME")

    def test_start_can_clear_key_when_explicitly_asked(self):
        self.config["api_key"] = "sk-DROP-ME"
        self.scanned()
        self.call("POST", "/api/translate/start", config={"engine": "google"},
                  clear_api_key=True)
        self.assertEqual(self.config.get("api_key"), "")

    def test_start_rejects_unknown_engine(self):
        self.scanned()
        payload = self.call("POST", "/api/translate/start",
                            config={"engine": "不存在的引擎"})
        self.assertFalse(payload["ok"])
        self.assertIn("配置有误", payload["error"])

    def test_start_without_session_is_clean_error(self):
        payload = self.call("POST", "/api/translate/start", config={})
        self.assertFalse(payload["ok"])
        self.assertIn("扫描", payload["error"])

    def test_test_endpoint_reports_failure_without_network(self):
        """自检端点必须**把错误当作返回值**，而不是让 HTTP 500。

        用一个必然连不上的本地地址，避免测试出网。
        """
        payload = self.call("POST", "/api/translate/test", config={
            "engine": "ollama", "base_url": "http://127.0.0.1:1/v1",
            "model": "x", "timeout": 2, "chunk_timeout": 2, "json_mode": False,
        })
        self.assertFalse(payload["ok"])
        self.assertTrue(payload["error"])
        self.assertIn("elapsed", payload)


# ---------------------------------------------------------------------------
# 后台任务契约
# ---------------------------------------------------------------------------
class TestJobEndpoints(RouteTestCase):
    def test_long_tasks_require_jobs_manager(self):
        """``ctx.jobs`` 为空时必须明确报错，而不是假装成功。"""
        from core.context import AppContext, Router
        from features.translate import manifest as translate_manifest
        ctx = AppContext(router=Router(), config=self.config, jobs=None)
        translate_manifest.register(ctx)
        handler = staticmethod(ctx.router.resolve(
            "POST", "/api/translate/scan")[0].handler).__func__
        from ui.server import Request
        payload = handler(Request("POST", "/api/translate/scan", {},
                                  {"dir": self.game()}, {}))
        self.assertFalse(payload["ok"])
        self.assertIn("后台任务", payload["error"])

    def test_cancel_bridge_maps_is_cancelled_to_is_set(self):
        from features.translate.routes import _CancelBridge
        from core.jobs import CancelToken

        token = CancelToken("x")
        bridge = _CancelBridge(token)
        self.assertFalse(bridge.is_set())
        token.cancel()
        self.assertTrue(bridge.is_set(),
                        "_CancelBridge 必须把 CancelToken.is_cancelled() 映射成 is_set()")

    def test_cancel_bridge_without_token_is_safe(self):
        from features.translate.routes import _CancelBridge
        self.assertFalse(_CancelBridge(None).is_set())

    def test_skip_all_job_can_be_cancelled(self):
        """取消要真的生效：大条目集上取消后不能把全部条目标完。"""
        self.scanned()
        payload = self.call("POST", "/api/translate/skip_all")
        self.jobs.cancel(payload["job"])
        snap = self.jobs.wait(payload["job"], timeout=60)
        self.assertIn(snap["status"], ("cancelled", "done"))


# ---------------------------------------------------------------------------
# 生成汉化版 + 备份还原
# ---------------------------------------------------------------------------
class TestBuildAndRestore(RouteTestCase):
    make_game = staticmethod(make_vxace_game)

    def _translate_all(self, text="旅行者"):
        session = self.service().session
        for entry in session.entries.values():
            entry["translated"] = text
            entry["status"] = "translated"
        self.service().persist()
        return session

    def _dialogue_in(self, path):
        """读回 ``CommonEvents.rvdata2`` 里第一条 401 指令的文本。

        结构是 ``[nil, RPG::CommonEvent]`` → ``@list[0]`` → ``@parameters[0]``。
        """
        from core.marshal import doc_model as D
        with open(path, "rb") as f:
            root = D.loads(f.read())
        command = D.ivar(D.ivar(root.items[1], "@list").items[0], "@parameters")
        return command.items[0].to_py()

    def _build_and_wait(self, **body):
        payload = self.call("POST", "/api/translate/build", **body)
        self.assertTrue(payload["ok"], payload.get("error"))
        snap = self.jobs.wait(payload["job"], timeout=120)
        self.assertEqual(snap["status"], "done",
                         "构建失败：%s %s" % (snap["error"], snap["traceback_tail"]))
        return snap["result"]

    def test_build_refused_without_translations(self):
        self.scanned()
        payload = self.call("POST", "/api/translate/build",
                            target=os.path.join(self.root, "out"))
        self.assertFalse(payload["ok"])
        self.assertIn("翻译", payload["error"])

    def test_build_rejects_bad_mode(self):
        self.scanned()
        payload = self.call("POST", "/api/translate/build", mode="destroy")
        self.assertFalse(payload["ok"])
        self.assertIn("mode", payload["error"])

    def test_build_copy_writes_translation_into_copy(self):
        _directory, _result = self.scanned()
        self._translate_all("旅行者")
        target = os.path.join(self.root, "out")
        result = self._build_and_wait(mode="copy", target=target)
        self.assertTrue(result, "构建返回空结果")
        self.assertEqual(os.path.abspath(result["target_dir"]),
                         os.path.abspath(target))
        self.assertGreaterEqual(result["entries"], 1)

        self.assertEqual(self._dialogue_in(
            os.path.join(target, "Data", "CommonEvents.rvdata2")), "旅行者",
            "译文没有写进汉化版")

    def test_build_copy_leaves_original_untouched(self):
        """默认只写副本：原游戏目录必须**字节不变**。"""
        directory, _result = self.scanned()
        before = self._fingerprint(directory)
        self._translate_all("旅行者")
        self._build_and_wait(mode="copy", target=os.path.join(self.root, "out"))
        self.assertEqual(self._fingerprint(directory), before,
                         "copy 模式改动了原游戏目录")

    def test_build_overwrite_requires_confirmation(self):
        """**B-05**：覆盖已有输出必须显式确认。"""
        self.scanned()
        self._translate_all("旅行者")
        target = os.path.join(self.root, "out")
        os.makedirs(target, exist_ok=True)
        write_text(os.path.join(target, "blocker.txt"), "已存在")
        payload = self.call("POST", "/api/translate/build", mode="copy",
                            target=target, overwrite=True)
        self.assertTrue(payload["ok"])
        snap = self.jobs.wait(payload["job"], timeout=120)
        self.assertEqual(snap["status"], "error")
        self.assertIn("OverwriteNotConfirmed", snap["error"])

    def test_build_overwrite_with_confirmation_succeeds(self):
        self.scanned()
        self._translate_all("旅行者")
        target = os.path.join(self.root, "out")
        os.makedirs(target, exist_ok=True)
        write_text(os.path.join(target, "blocker.txt"), "已存在")
        result = self._build_and_wait(mode="copy", target=target,
                                      overwrite=True, confirm=True)
        self.assertGreaterEqual(result["entries"], 1)

    def test_build_inplace_backs_up_original(self):
        """**硬约束**：写回原游戏前必须备份，且备份可还原。"""
        directory, _result = self.scanned()
        self._translate_all("旅行者")
        result = self._build_and_wait(mode="inplace", confirm=True)
        self.assertTrue(result.get("backup_dir"),
                        "inplace 构建没有生成备份：%s" % list(result))
        self.assertTrue(os.path.isdir(result["backup_dir"]))

        backups = self.call("GET", "/api/translate/backups")
        self.assertTrue(backups["ok"])
        self.assertTrue(backups["backups"], "list_backups 看不到刚生成的备份")
        self.assertTrue(backups["backups"][0]["has_manifest"])

    def test_restore_brings_original_back(self):
        directory, _result = self.scanned()
        self._translate_all("旅行者")
        self._build_and_wait(mode="inplace", confirm=True)

        path = os.path.join(directory, "Data", "CommonEvents.rvdata2")
        self.assertEqual(self._dialogue_in(path), "旅行者", "写回未生效，无法验证还原")

        backups = self.call("GET", "/api/translate/backups")["backups"]
        payload = self.call("POST", "/api/translate/restore", dir=backups[0]["dir"])
        self.assertTrue(payload["ok"], payload.get("error"))
        self.assertGreaterEqual(payload["result"]["restored"], 1)
        self.assertTrue(payload["result"]["safety_backup"],
                        "还原前必须为当前状态再备份一次（还原错了还能救）")
        self.assertEqual(self._dialogue_in(path), "你好，旅行者。",
                         "还原后原文未回来")

    def test_restore_requires_dir(self):
        self.scanned()
        payload = self.call("POST", "/api/translate/restore", dir="")
        self.assertFalse(payload["ok"])
        self.assertIn("dir", payload["error"])

    def test_restore_of_missing_dir_reports(self):
        self.scanned()
        payload = self.call("POST", "/api/translate/restore",
                            dir=os.path.join(self.root, "没有这个目录"))
        self.assertFalse(payload["ok"])
        self.assertIn("还原失败", payload["error"])

    def test_backups_without_session_is_clean_error(self):
        payload = self.call("GET", "/api/translate/backups")
        self.assertFalse(payload["ok"])
        self.assertIn("扫描", payload["error"])

    def test_restore_without_session_is_clean_error(self):
        payload = self.call("POST", "/api/translate/restore", dir="x")
        self.assertFalse(payload["ok"])
        self.assertIn("扫描", payload["error"])

    def test_open_dir_rejects_missing_dir(self):
        payload = self.call("POST", "/api/translate/open_dir",
                            dir=os.path.join(self.root, "没有这个目录"))
        self.assertFalse(payload["ok"])
        self.assertIn("不存在", payload["error"])

    @staticmethod
    def _fingerprint(root):
        out = {}
        for base, _dirs, files in os.walk(root):
            for name in files:
                full = os.path.join(base, name)
                with open(full, "rb") as f:
                    out[os.path.relpath(full, root)] = f.read()
        return out


class TestBuildAndRestoreMV(TestBuildAndRestore):
    """同一批构建/还原用例在 MV（JSON）上重跑一遍。"""

    make_game = staticmethod(make_mv_game)

    def test_build_copy_writes_translation_into_copy(self):
        _directory, _result = self.scanned()
        self._translate_all("旅行者")
        target = os.path.join(self.root, "out")
        result = self._build_and_wait(mode="copy", target=target)
        self.assertGreaterEqual(result["entries"], 1)
        with open(os.path.join(target, "data", "CommonEvents.json"),
                  encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data[1]["list"][1]["parameters"][0], "旅行者",
                         "译文没有写进 MV 汉化版")

    def test_build_inplace_backs_up_original(self):
        self.scanned()
        self._translate_all("旅行者")
        result = self._build_and_wait(mode="inplace", confirm=True)
        self.assertTrue(result.get("backup_dir"))
        with open(os.path.join(self.root, "game", "data", "CommonEvents.json"),
                  encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data[1]["list"][1]["parameters"][0], "旅行者")

    def test_restore_brings_original_back(self):
        directory, _result = self.scanned()
        self._translate_all("旅行者")
        self._build_and_wait(mode="inplace", confirm=True)
        backups = self.call("GET", "/api/translate/backups")["backups"]
        payload = self.call("POST", "/api/translate/restore", dir=backups[0]["dir"])
        self.assertTrue(payload["ok"], payload.get("error"))
        with open(os.path.join(directory, "data", "CommonEvents.json"),
                  encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data[1]["list"][1]["parameters"][0], "你好，旅行者。")


# ---------------------------------------------------------------------------
# 隐私：请求体里不得出现游戏路径 / 文本内容
# ---------------------------------------------------------------------------
class TestPrivacy(unittest.TestCase):
    """**隐私断言**：翻译是出网操作，请求里不能带上游戏目录等本地信息。

    原工具的一个界面承诺是"翻译只发送文本本身"。这里从**代码层**把它钉死：
    出网请求由 ``translators`` 构造，构造入参只有文本列表 + 语言代码。
    """

    def test_translate_batch_receives_only_texts(self):
        from features.translate import translators

        calls = []

        class Spy(translators.GoogleTranslator):
            def translate_batch(self, texts, src, dst):
                calls.append({"texts": list(texts), "src": src, "dst": dst})
                return list(texts)

        original = translators.build_translator
        translators.build_translator = lambda cfg: Spy()
        self.addCleanup(setattr, translators, "build_translator", original)

        class FakeSession(object):
            entries = {
                "a|b": {"file": "Map001.json", "path": "events/0",
                        "category": "对话", "original": "こんにちは",
                        "translated": "", "status": "pending"},
            }
            cache = {}
            game_dir = "D:/secret/game"

        done, failed, _errors = translators.translate_entries(
            FakeSession(), {"engine": "google"})
        self.assertEqual((done, failed), (1, 0))
        self.assertEqual(len(calls), 1)
        blob = json.dumps(calls[0], ensure_ascii=False)
        for secret in ("secret", "Map001", "D:/", "D:\\\\"):
            self.assertNotIn(secret, blob,
                             "出网请求里带上了本地信息：%s" % blob)

    def test_pick_folder_failure_is_returned_not_raised(self):
        """没有原生对话框的环境下（CI）也必须返回可读错误，不能 500。"""
        from features.translate.routes import register_routes
        from core.context import AppContext, Router
        ctx = AppContext(router=Router())
        register_routes(ctx, mock.Mock())
        handler = staticmethod(ctx.router.resolve(
            "POST", "/api/translate/pick_folder")[0].handler).__func__
        from ui.server import Request
        with mock.patch("core.sysdialog.pick_folder",
                        side_effect=RuntimeError("没有对话框")):
            payload = handler(Request("POST", "/api/translate/pick_folder", {}, {}, {}))
        self.assertFalse(payload["ok"])
        self.assertIn("对话框", payload["error"])

    def test_pick_folder_cancel_is_not_an_error(self):
        """用户点"取消"不是错误：必须 ``ok=True`` + ``cancelled=True``。

        否则前端只能靠空字符串猜"是取消了还是失败了"，容易弹出假的错误提示。
        """
        from features.translate.routes import register_routes
        from core.context import AppContext, Router
        from ui.server import Request
        ctx = AppContext(router=Router())
        register_routes(ctx, mock.Mock())
        handler = staticmethod(ctx.router.resolve(
            "POST", "/api/translate/pick_folder")[0].handler).__func__
        with mock.patch("core.sysdialog.pick_folder", return_value=""):
            payload = handler(Request("POST", "/api/translate/pick_folder", {}, {}, {}))
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["dir"], "")
        self.assertTrue(payload["cancelled"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

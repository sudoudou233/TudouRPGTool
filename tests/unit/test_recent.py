# -*- coding: utf-8 -*-
"""``core/recent.py``（最近打开的游戏）与它的四个 HTTP 门面。

@feature  none
@layer    tests
@public   TestRecentStore, TestRecentRobustness, TestNoteGame,
          TestRecentRoutes
@depends  core.recent, core.context, ui.routes
@tested   (本文件即测试)
@footprint docs/MODULES.md#corerecent

重点不在"能不能存下来"，而在**存不下来时会怎样**
------------------------------------------------
"最近打开列表"是个纯锦上添花的东西，它坏掉的正确表现是**功能消失**，
而不是**把主流程拖垮**。所以下面有一整类用例专门喂坏数据：

* 文件根本不存在 / 内容是垃圾 / 结构不对 / 里面混了重复项与残缺项
  → 一律退化成空列表 + ``last_error``，**绝不抛**；
* 盘写不进去 → 内存里的列表照样更新（本次会话可用），只是下次打开没了，
  并且 ``last_error`` 里说清原因。

另外单独钉住一条**排序判据**：顺序来自**列表位置**而不是时间戳。
同一秒内连开两个游戏完全可能（自动扫描），按时间戳排会出现"顺序随机"。
"""

from __future__ import annotations

import json
import os
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

from core import recent as recent_mod          # noqa: E402


class RecentCase(unittest.TestCase):
    def setUp(self):
        try:
            self.tmp = tempfile.TemporaryDirectory(prefix="recent_",
                                                   ignore_cleanup_errors=True)
        except TypeError:                       # Python 3.8 / 3.9
            self.tmp = tempfile.TemporaryDirectory(prefix="recent_")
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name
        self.file = os.path.join(self.root, "recent.json")

    def store(self, **kw):
        return recent_mod.RecentGames(path=self.file, **kw)

    def game(self, name):
        """造一个**真的存在**的游戏目录。"""
        path = os.path.join(self.root, name)
        os.makedirs(path, exist_ok=True)
        return path

    def read_file(self):
        with open(self.file, "r", encoding="utf-8") as f:
            return json.load(f)


# ---------------------------------------------------------------------------
# 基本行为
# ---------------------------------------------------------------------------
class TestRecentStore(RecentCase):

    def test_starts_empty_when_file_missing(self):
        store = self.store()
        self.assertEqual(store.items(), [])
        self.assertIsNone(store.last_error)
        self.assertFalse(os.path.exists(self.file),
                         "只是读一下不该把文件造出来")

    def test_record_writes_and_lists_newest_first(self):
        a, b = self.game("a"), self.game("b")
        store = self.store()
        store.record(a, kind="cheats", engine="mv")
        store.record(b, kind="translate", engine="vxace")
        items = store.items()
        self.assertEqual([i["path"] for i in items], [os.path.abspath(b),
                                                      os.path.abspath(a)])
        self.assertEqual(items[0]["kind"], "translate")
        self.assertEqual(items[0]["engine"], "vxace")

    def test_recording_the_same_game_moves_it_not_duplicates(self):
        a, b = self.game("a"), self.game("b")
        store = self.store()
        store.record(a)
        store.record(b)
        store.record(a)
        items = store.items()
        self.assertEqual(len(items), 1 + 1)
        self.assertEqual(items[0]["path"], os.path.abspath(a))
        self.assertEqual(len({i["path"] for i in items}), len(items),
                         "出现了重复项")

    @unittest.skipUnless(os.name == "nt", "大小写只在 Windows 上等价")
    def test_dedupe_is_case_insensitive_on_windows(self):
        a = self.game("CaseTest")
        store = self.store()
        store.record(a)
        store.record(a.upper())
        self.assertEqual(len(store.items()), 1,
                         "D:\\x 与 d:\\X 在 Windows 上是同一个目录")

    def test_limit_keeps_the_newest(self):
        paths = [self.game("g%d" % i) for i in range(4)]
        store = self.store(limit=2)
        for path in paths:
            store.record(path)
        items = store.items()
        self.assertEqual(len(items), 2)
        self.assertEqual([i["path"] for i in items],
                         [os.path.abspath(paths[3]), os.path.abspath(paths[2])])

    def test_limit_is_at_least_one(self):
        store = self.store(limit=0)
        self.assertEqual(store.limit, 1)

    def test_label_defaults_to_folder_name(self):
        path = self.game("我的游戏")
        store = self.store()
        store.record(path)
        self.assertEqual(store.items()[0]["label"], "我的游戏")

    def test_explicit_label_wins(self):
        store = self.store()
        store.record(self.game("g"), label="药水冒险")
        self.assertEqual(store.items()[0]["label"], "药水冒险")

    def test_blank_label_falls_back_to_folder_name(self):
        store = self.store()
        store.record(self.game("g"), label="   ")
        self.assertEqual(store.items()[0]["label"], "g")

    def test_when_is_recorded(self):
        store = self.store()
        store.record(self.game("g"))
        self.assertRegex(store.items()[0]["when"], r"^\d{4}-\d\d-\d\d \d\d:")

    def test_record_ignores_blank_path(self):
        store = self.store()
        self.assertEqual(store.record("   "), [])
        self.assertEqual(store.count(), 0)

    def test_exists_is_computed_not_stored(self):
        alive = self.game("alive")
        dead = os.path.join(self.root, "dead")
        store = self.store()
        store.record(alive)
        store.record(dead)
        rows = {i["path"]: i["exists"] for i in store.items()}
        self.assertTrue(rows[os.path.abspath(alive)])
        self.assertFalse(rows[os.path.abspath(dead)])

    def test_missing_dir_stays_in_the_list(self):
        """**目录失效不等于该被删掉** —— 可能只是暂时移走了。"""
        dead = os.path.join(self.root, "moved")
        store = self.store()
        store.record(dead)
        self.assertEqual(len(store.items()), 1)
        self.assertFalse(store.items()[0]["exists"])

    def test_forget(self):
        a, b = self.game("a"), self.game("b")
        store = self.store()
        store.record(a)
        store.record(b)
        self.assertTrue(store.forget(a))
        self.assertEqual([i["path"] for i in store.items()],
                         [os.path.abspath(b)])

    def test_forget_unknown_returns_false(self):
        store = self.store()
        store.record(self.game("a"))
        self.assertFalse(store.forget(self.game("zzz")))

    def test_prune_removes_only_missing(self):
        alive = self.game("alive")
        dead = os.path.join(self.root, "dead")
        store = self.store()
        store.record(dead)
        store.record(alive)
        self.assertEqual(store.prune(), 1)
        self.assertEqual([i["path"] for i in store.items()],
                         [os.path.abspath(alive)])

    def test_prune_with_nothing_to_do(self):
        store = self.store()
        store.record(self.game("a"))
        self.assertEqual(store.prune(), 0)

    def test_clear(self):
        store = self.store()
        store.record(self.game("a"))
        store.record(self.game("b"))
        self.assertEqual(store.clear(), 2)
        self.assertEqual(store.items(), [])
        self.assertEqual(self.read_file()["items"], [])

    def test_clear_on_empty_returns_zero(self):
        self.assertEqual(self.store().clear(), 0)

    def test_order_is_list_position_not_timestamp(self):
        """同一秒内连开多个游戏，顺序也必须是"最后打开的在最前"。"""
        a, b, c = self.game("a"), self.game("b"), self.game("c")
        store = self.store()
        for path in (a, b, c):
            store.record(path)
        self.assertEqual([i["path"] for i in store.items()],
                         [os.path.abspath(c), os.path.abspath(b),
                          os.path.abspath(a)])

    def test_survives_reload(self):
        a, b = self.game("a"), self.game("b")
        store = self.store()
        store.record(a, kind="cheats")
        store.record(b, kind="translate")
        again = self.store()
        self.assertEqual([i["path"] for i in again.items()],
                         [os.path.abspath(b), os.path.abspath(a)])
        self.assertEqual(again.items()[1]["kind"], "cheats")

    def test_file_shape(self):
        store = self.store()
        store.record(self.game("a"))
        payload = self.read_file()
        self.assertEqual(payload["schema"], recent_mod.SCHEMA)
        self.assertIn("saved", payload)
        self.assertEqual(len(payload["items"]), 1)

    def test_default_path_sits_under_runtime(self):
        from core import paths
        store = recent_mod.RecentGames()
        self.assertEqual(store.path,
                         os.path.join(paths.data_dir(), recent_mod.FILENAME))

    def test_max_items_alias(self):
        self.assertEqual(recent_mod.MAX_ITEMS, recent_mod.DEFAULT_LIMIT)


# ---------------------------------------------------------------------------
# 坏数据：必须优雅降级，绝不能抛
# ---------------------------------------------------------------------------
class TestRecentRobustness(RecentCase):

    def write_raw(self, text):
        with open(self.file, "w", encoding="utf-8") as f:
            f.write(text)

    def test_corrupt_json_degrades_to_empty(self):
        self.write_raw("{ this is not json")
        store = self.store()
        self.assertEqual(store.items(), [])
        self.assertIn("读取最近打开记录失败", store.last_error)

    def test_top_level_not_an_object(self):
        self.write_raw("[1, 2, 3]")
        store = self.store()
        self.assertEqual(store.items(), [])
        self.assertIn("格式不对", store.last_error)

    def test_items_not_a_list(self):
        self.write_raw(json.dumps({"items": {"a": 1}}))
        store = self.store()
        self.assertEqual(store.items(), [])
        self.assertIn("没有 items 列表", store.last_error)

    def test_entries_without_path_are_skipped(self):
        self.write_raw(json.dumps({"items": [
            {"kind": "cheats"}, {"path": ""}, "not a dict",
            {"path": "D:\\ok"},
        ]}))
        store = self.store()
        self.assertEqual([i["path"] for i in store.items()], ["D:\\ok"])

    def test_duplicate_entries_in_file_are_collapsed(self):
        self.write_raw(json.dumps({"items": [
            {"path": "D:\\same"}, {"path": "D:\\same"},
        ]}))
        self.assertEqual(len(self.store().items()), 1)

    def test_non_string_fields_become_empty(self):
        self.write_raw(json.dumps({"items": [
            {"path": "D:\\g", "kind": 5, "label": None, "engine": ["mv"]},
        ]}))
        row = self.store().items()[0]
        self.assertEqual(row["kind"], "")
        self.assertEqual(row["engine"], "")
        self.assertEqual(row["label"], "g")     # 退回目录名

    def test_recovered_store_can_be_written_again(self):
        """坏文件不该让这个文件永久废掉 —— 下一次 record 要能修好它。"""
        self.write_raw("garbage")
        store = self.store()
        store.record(self.game("g"))
        self.assertIsNone(store.last_error)
        self.assertEqual(len(self.read_file()["items"]), 1)

    def test_unwritable_target_does_not_raise(self):
        """盘写不进去：内存里照样更新，只是记下原因。"""
        store = self.store()
        with mock.patch.object(recent_mod.atomic, "atomic_write_text",
                               side_effect=OSError("拒绝访问")):
            store.record(self.game("a"), kind="cheats")
        self.assertEqual(len(store.items()), 1,
                         "写盘失败不该把内存里的记录也丢掉")
        self.assertIn("写入最近打开记录失败", store.last_error)
        self.assertFalse(os.path.exists(self.file))

    def test_last_error_clears_after_a_successful_write(self):
        store = self.store()
        with mock.patch.object(recent_mod.atomic, "atomic_write_text",
                               side_effect=OSError("拒绝访问")):
            store.record(self.game("a"))
        self.assertIsNotNone(store.last_error)
        store.record(self.game("b"))
        self.assertIsNone(store.last_error)

    def test_write_goes_through_the_atomic_helper(self):
        """硬约束 §4.2：不得直接 open(path,'wb')，一律走 atomic。"""
        store = self.store()
        with mock.patch.object(recent_mod.atomic, "atomic_write_text",
                               wraps=recent_mod.atomic.atomic_write_text) as spy:
            store.record(self.game("a"))
        self.assertEqual(spy.call_count, 1)

    def test_directory_in_place_of_file_degrades(self):
        os.makedirs(self.file)                  # 同名目录，open 会失败
        store = self.store()
        self.assertEqual(store.items(), [])
        self.assertIsNotNone(store.last_error)


# ---------------------------------------------------------------------------
# 功能侧的便捷入口
# ---------------------------------------------------------------------------
class TestNoteGame(RecentCase):

    def test_note_game_writes_through_the_context(self):
        from core.context import AppContext, Router
        ctx = AppContext(router=Router(), recent=self.store())
        path = self.game("g")
        recent_mod.note_game(ctx, path, kind="cheats", engine="mv")
        self.assertEqual([i["path"] for i in ctx.recent.items()],
                         [os.path.abspath(path)])

    def test_none_context_is_a_no_op(self):
        self.assertEqual(recent_mod.note_game(None, "D:\\x"), [])

    def test_context_without_recent_is_a_no_op(self):
        class Bare(object):
            pass
        self.assertEqual(recent_mod.note_game(Bare(), "D:\\x"), [])

    def test_a_broken_store_never_propagates(self):
        """记录失败绝不能让"打开游戏"这件事本身失败。"""
        class Boom(object):
            def record(self, *a, **kw):
                raise RuntimeError("炸了")
        self.assertEqual(recent_mod.note_game(Boom(), "D:\\x"), [])

    def test_blank_path_is_a_no_op(self):
        from core.context import AppContext, Router
        ctx = AppContext(router=Router(), recent=self.store())
        self.assertEqual(recent_mod.note_game(ctx, ""), [])

    def test_lazy_context_creates_a_store(self):
        """测试里直接 AppContext(router=...) 时也要能拿到可用的 store。"""
        from core.context import AppContext, Router
        data = os.path.join(self.root, "runtime")
        os.makedirs(data, exist_ok=True)
        with mock.patch.dict(os.environ, {"TUDOU_RPGTOOL_DATA": data}):
            ctx = AppContext(router=Router())
            store = ctx.recent
        self.assertIsNotNone(store)
        self.assertEqual(store.items(), [])
        # 同一个实例（不是每次访问都新建，否则记一条丢一条）
        self.assertIs(ctx.recent, store)


# ---------------------------------------------------------------------------
# HTTP 门面（直接调处理器，不起服务）
# ---------------------------------------------------------------------------
class TestRecentRoutes(RecentCase):
    """``ui/routes.py`` 里的四个端点。"""

    def setUp(self):
        super(TestRecentRoutes, self).setUp()
        from core.context import AppContext, Router
        from ui import routes as ui_routes
        self.ctx = AppContext(router=Router(), recent=self.store())
        ui_routes.register_core_routes(self.ctx)

    def handler(self, method, route_path):
        route, _ = self.ctx.router.resolve(method, route_path)
        self.assertIsNotNone(route, "路由不存在：%s %s" % (method, route_path))
        return staticmethod(route.handler).__func__

    def get(self, route_path, **query):
        from ui.server import Request
        return self.handler("GET", route_path)(
            Request("GET", route_path, query, {}, {}))

    def post(self, route_path, **body):
        from ui.server import Request
        return self.handler("POST", route_path)(
            Request("POST", route_path, {}, body, {}))

    def test_all_four_endpoints_exist(self):
        for method, path in (("GET", "/api/recent"),
                             ("POST", "/api/recent/forget"),
                             ("POST", "/api/recent/prune"),
                             ("POST", "/api/recent/clear")):
            with self.subTest(endpoint=path):
                self.handler(method, path)

    def test_list_is_empty_at_first(self):
        res = self.get("/api/recent")
        self.assertTrue(res["ok"])
        self.assertEqual(res["items"], [])
        self.assertIsNone(res["error"])

    def test_list_reports_limit(self):
        self.assertEqual(self.get("/api/recent")["limit"],
                         recent_mod.DEFAULT_LIMIT)

    def test_list_exposes_last_error(self):
        """坏文件的原因要能传到界面上（否则用户只看到"列表是空的"）。

        ⚠ 必须在**构造 store 之前**把文件弄坏：``last_error`` 是加载时算出来的，
        构造之后再改磁盘是看不到的（这一条第一次就写错了）。
        """
        with open(self.file, "w", encoding="utf-8") as f:
            f.write("garbage")
        from core.context import AppContext, Router
        from ui import routes as ui_routes
        ctx = AppContext(router=Router(), recent=self.store())
        ui_routes.register_core_routes(ctx)
        route, _ = ctx.router.resolve("GET", "/api/recent")
        res = staticmethod(route.handler).__func__(None)
        self.assertTrue(res["ok"])
        self.assertEqual(res["items"], [])
        self.assertIn("读取最近打开记录失败", res["error"])

    def test_forget(self):
        path = self.game("a")
        self.ctx.recent.record(path)
        res = self.post("/api/recent/forget", path=path)
        self.assertTrue(res["ok"])
        self.assertTrue(res["removed"])
        self.assertEqual(res["items"], [])

    def test_forget_requires_path(self):
        res = self.post("/api/recent/forget")
        self.assertFalse(res["ok"])
        self.assertIn("path", res["error"])

    def test_forget_unknown_path_is_not_an_error(self):
        res = self.post("/api/recent/forget", path="D:\\nope")
        self.assertTrue(res["ok"])
        self.assertFalse(res["removed"])

    def test_prune(self):
        alive = self.game("alive")
        self.ctx.recent.record(alive)
        self.ctx.recent.record(os.path.join(self.root, "dead"))
        res = self.post("/api/recent/prune")
        self.assertTrue(res["ok"])
        self.assertEqual(res["removed"], 1)
        self.assertEqual([i["path"] for i in res["items"]],
                         [os.path.abspath(alive)])

    def test_clear(self):
        self.ctx.recent.record(self.game("a"))
        res = self.post("/api/recent/clear")
        self.assertTrue(res["ok"])
        self.assertEqual(res["removed"], 1)
        self.assertEqual(res["items"], [])

    def test_missing_store_degrades(self):
        """store 不可用时接口照常回，只是说明原因（不 500）。"""
        from core.context import AppContext, Router
        from ui import routes as ui_routes
        ctx = AppContext(router=Router())
        ui_routes.register_core_routes(ctx)
        ctx._recent = None
        ctx._recent_ready = True
        route, _ = ctx.router.resolve("GET", "/api/recent")
        res = staticmethod(route.handler).__func__(None)
        self.assertTrue(res["ok"])
        self.assertEqual(res["items"], [])
        self.assertIn("不可用", res["error"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

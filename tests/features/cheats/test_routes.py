# -*- coding: utf-8 -*-
"""M3b 后端接线测试：``/api/cheats/*`` 读档 → 改档 → 写回 → 还原 全链路。

@feature  cheats
@layer    tests
@public   CheatsTestCase, TestRouteRegistration, TestOpenAndSaves,
          TestReadEndpoints, TestWriteEndpoints, TestSaveAndRestore,
          TestDataTableEdit
@depends  features.cheats.manifest, features.cheats.routes,
          core.formats.mv_save, core.formats.rgss_save, core.safety.backup
@tested   (本文件即测试)
@footprint docs/STATE.md

为什么这个文件重要
------------------
M1/M2 阶段 ``features/cheats`` 只有两个只读端点（``/status``、``/detect``），
**写回路径一次都没被端到端验证过**。而"改存档"是这个功能里最容易毁掉玩家
数据的操作，所以每条断言都落在**可观测后果**上：

* 改完之后**重新解析文件**必须看到新值（不是"接口返回 ok"就算过）；
* 写回原存档前**一定**生成备份，且备份能还原回原字节；
* 没带 ``confirm=true`` 时**拒绝写**，且文件字节不变；
* ``copy`` 语义的错误（例如把 0 当"没改"）必须被抓住 ——
  ``translated=0`` 表示"把数量改成 0"，不是"没有译文"。
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

from core.context import AppContext  # noqa: E402


# ---------------------------------------------------------------------------
# 夹具：合成游戏（MV 与 VX Ace）
# ---------------------------------------------------------------------------
def write_text(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False)


MV_SAVE_DATA = {
    "system": {"_switches": {"@a": [True, False]}},
    "switches": {"_data": {"@a": [True, False, True]}},
    "variables": {"_data": {"@a": [0, 10, 20]}},
    "party": {
        "_gold": 1000,
        "_steps": 500,
        "_items": {"@c": 1, "1": 3},
        "_weapons": {"1": 1},
        "_armors": {},
        "_actors": {"@a": [1, 2]},
    },
    "actors": {"_data": {"@a": [
        None,
        {"_actorId": 1, "_classId": 1, "_level": 5, "_exp": {"1": 100},
         "_hp": 200, "_mp": 50, "_tp": 0, "_paramPlus": {"@a": [0] * 8},
         "_skills": {"@a": [1, 2]}},
        {"_actorId": 2, "_classId": 2, "_level": 3, "_exp": {"2": 50},
         "_hp": 100, "_mp": 30, "_tp": 0, "_paramPlus": {"@a": [0] * 8},
         "_skills": {"@a": []}},
    ]}},
}


def make_mv_game(root, gold=1000, item_count=3, www=False):
    """合成一个含存档的 MV 游戏。

    ``www=True`` 时用**老版布局**（``www/js`` + ``www/data`` + ``www/save``，
    真实游戏里很常见，例如 boli3/RJ01052631）；默认是新版布局
    （``js`` / ``data`` / ``save`` 都在游戏根）。

    两种布局的存档目录不同，而 ``core.engines`` 是按 **js 根**推导
    ``save_dir`` 的 —— 因此夹具必须跟着布局走，否则会出现
    "``/saves`` 递归搜索能找到、``/detect`` 却返回空"这种自相矛盾的现象
    （M3b 实测踩到）。
    """
    from core.formats import mv_save

    js_root = os.path.join(root, "www") if www else root
    write_text(os.path.join(js_root, "js", "rpg_core.js"), "// synthetic\n")
    for fname, payload in (
            ("System.json", {"gameTitle": "合成MV", "currencyUnit": "金币",
                             "optDisplayTp": True, "optExtraExp": False,
                             "optSideView": True}),
            ("Items.json", [None, {"id": 1, "name": "药草", "price": 50,
                                   "consumable": True, "occasion": 0,
                                   "itypeId": 1},
                            {"id": 2, "name": "解毒草", "price": 20,
                             "consumable": True, "occasion": 0, "itypeId": 1}]),
            ("Weapons.json", [None, {"id": 1, "name": "短剑", "price": 100,
                                     "params": [0, 10, 0, 0, 0, 0]}]), 
            ("Armors.json", [None, {"id": 1, "name": "布甲", "price": 80,
                                    "etypeId": 1, "params": [8, 0]}]),
            ("Actors.json", [None, {"id": 1, "name": "勇者", "initialLevel": 1,
                                    "maxLevel": 99, "classId": 1},
                             {"id": 2, "name": "法师", "initialLevel": 1,
                              "maxLevel": 99, "classId": 2}]),
            ("Classes.json", [None, {"id": 1, "name": "战士",
                                     "params": [[10, 20], [5, 10], [3, 4],
                                                [2, 3]]}]),
            ("Skills.json", [None, {"id": 1, "name": "斩击", "mpCost": 0,
                                    "tpCost": 0, "scope": 1, "occasion": 0}]),
            ("Enemies.json", [None, {"id": 1, "name": "史莱姆",
                                     "params": [50, 0, 8, 4], "exp": 10,
                                     "gold": 5}]),
            ("States.json", [None, {"id": 1, "name": "中毒", "priority": 50,
                                    "restriction": 0}]),
    ):
        write_json(os.path.join(js_root, "data", fname), payload)

    data = json.loads(json.dumps(MV_SAVE_DATA))
    data["party"]["_gold"] = gold
    data["party"]["_items"]["1"] = item_count
    save_dir = os.path.join(js_root, "save")
    os.makedirs(save_dir, exist_ok=True)
    with open(os.path.join(save_dir, "file0.rpgsave"), "wb") as f:
        f.write(mv_save.SaveFileMV._dump(data, "mv"))
    return root


def make_vxace_game(root, gold=1000, item_count=3):
    """合成一个含存档的 VX Ace 游戏（``.rvdata2`` 是真实 Marshal 字节流）。"""
    from core.marshal import doc_model as D

    def sym(name):
        return D.Symbol(name.encode("utf-8"))

    def st(text):
        return D.String(text.encode("utf-8"))

    def obj(class_name, ivars):
        return D.ObjectNode(sym(class_name), [
            (sym(k if k.startswith("@") else "@" + k), v) for k, v in ivars.items()])

    def table(rows):
        return D.Array([D.NilNode()] + rows)

    write_text(os.path.join(root, "Game.ini"), "[Game]\nTitle=合成\n")
    data = os.path.join(root, "Data")
    os.makedirs(data, exist_ok=True)

    def dump(fname, node):
        with open(os.path.join(data, fname), "wb") as f:
            f.write(D.dumps(node))

    dump("Items.rvdata2", table([
        obj("RPG::Item", {"id": D.Fixnum(1), "name": st("药草"),
                          "price": D.Fixnum(50), "consumable": D.BoolNode(True),
                          "occasion": D.Fixnum(0)}),
        obj("RPG::Item", {"id": D.Fixnum(2), "name": st("解毒草"),
                          "price": D.Fixnum(20), "consumable": D.BoolNode(True),
                          "occasion": D.Fixnum(0)}),
    ]))
    dump("Weapons.rvdata2", table([
        obj("RPG::Weapon", {"id": D.Fixnum(1), "name": st("短剑"),
                            "price": D.Fixnum(100),
                            "params": D.Array([D.Fixnum(0), D.Fixnum(10),
                                               D.Fixnum(0), D.Fixnum(0),
                                               D.Fixnum(0), D.Fixnum(0)])}),
    ]))
    dump("Armors.rvdata2", table([
        obj("RPG::Armor", {"id": D.Fixnum(1), "name": st("布甲"),
                           "price": D.Fixnum(80),
                           "params": D.Array([D.Fixnum(8), D.Fixnum(0),
                                              D.Fixnum(0)])}),
    ]))
    dump("Actors.rvdata2", table([
        obj("RPG::Actor", {"id": D.Fixnum(1), "name": st("勇者"),
                           "class_id": D.Fixnum(1), "initial_level": D.Fixnum(1),
                           "final_level": D.Fixnum(99)}),
    ]))
    dump("Classes.rvdata2", table([
        obj("RPG::Class", {"id": D.Fixnum(1), "name": st("战士"),
                           "params": D.Array([D.Array([D.Fixnum(10), D.Fixnum(20)]),
                                              D.Array([D.Fixnum(5), D.Fixnum(10)]),
                                              D.Array([D.Fixnum(3), D.Fixnum(4)]),
                                              D.Array([D.Fixnum(2), D.Fixnum(3)])])}),
    ]))
    dump("Skills.rvdata2", table([
        obj("RPG::Skill", {"id": D.Fixnum(1), "name": st("斩击"),
                           "mp_cost": D.Fixnum(0), "tp_cost": D.Fixnum(0),
                           "scope": D.Fixnum(1), "occasion": D.Fixnum(0)}),
    ]))
    dump("Enemies.rvdata2", table([
        obj("RPG::Enemy", {"id": D.Fixnum(1), "name": st("史莱姆"),
                           "params": D.Array([D.Fixnum(50), D.Fixnum(0),
                                              D.Fixnum(8), D.Fixnum(4)]),
                           "exp": D.Fixnum(10), "gold": D.Fixnum(5)}),
    ]))
    dump("States.rvdata2", table([
        obj("RPG::State", {"id": D.Fixnum(1), "name": st("中毒"),
                           "priority": D.Fixnum(50), "restriction": D.Fixnum(0)}),
    ]))

    # 存档：改造版布局 —— 顶层 Hash（键为符号名），单流
    party = obj("Game_Party", {
        "gold": D.Fixnum(gold), "steps": D.Fixnum(500),
        "items": D.Hash([(D.Fixnum(1), D.Fixnum(item_count))]),
        "weapons": D.Hash([(D.Fixnum(1), D.Fixnum(1))]),
        "armors": D.Hash([]),
        "actors": D.Array([D.Fixnum(1)]),
    })
    save = D.Hash([
        (sym("system"), obj("Game_System", {})),
        (sym("switches"), obj("Game_Switches", {
            "data": D.Array([D.BoolNode(False), D.BoolNode(True),
                             D.BoolNode(False)])})),
        (sym("variables"), obj("Game_Variables", {
            "data": D.Array([D.Fixnum(0), D.Fixnum(10), D.Fixnum(20)])})),
        (sym("actors"), D.Array([
            D.NilNode(),
            obj("Game_Actor", {"id": D.Fixnum(1), "name": st("勇者"),
                               "class_id": D.Fixnum(1), "level": D.Fixnum(5),
                               "exp": D.Hash([(D.Fixnum(1), D.Fixnum(100))]),
                               "hp": D.Fixnum(200), "mp": D.Fixnum(50),
                               "tp": D.Fixnum(0),
                               "param_plus": D.Array([D.Fixnum(0)] * 8),
                               "skills": D.Array([D.Fixnum(1), D.Fixnum(2)])}),
        ])),
        (sym("party"), party),
    ])
    with open(os.path.join(root, "Save01.rvdata2"), "wb") as f:
        f.write(D.dumps(save))
    return root


# ---------------------------------------------------------------------------
# 基类
# ---------------------------------------------------------------------------
class CheatsTestCase(unittest.TestCase):
    """给每个用例一套隔离的应用上下文。"""

    make_game = staticmethod(make_mv_game)

    def setUp(self):
        try:
            self.tmp = tempfile.TemporaryDirectory(prefix="cheats_",
                                                   ignore_cleanup_errors=True)
        except TypeError:                     # Python 3.8 / 3.9
            self.tmp = tempfile.TemporaryDirectory(prefix="cheats_")
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name
        data = os.path.join(self.root, "runtime")
        os.makedirs(data, exist_ok=True)
        env = mock.patch.dict(os.environ, {"TUDOU_RPGTOOL_DATA": data})
        env.start()
        self.addCleanup(env.stop)

        from core import config as config_mod
        from core.context import Router

        self.config = config_mod.AppConfig(path=os.path.join(self.root, "config.json"))
        ctx = AppContext(router=Router(), config=self.config)
        from features.cheats import manifest as cheats_manifest
        cheats_manifest.register(ctx)
        self.ctx = ctx

    # ------------------------------------------------------------ 调用助手
    #
    # ⚠ 助手方法的第一个位置参数**不能**叫 ``path``：调用方会写
    # ``self.call("POST", "/api/cheats/load", path=存档路径)``，而那个
    # ``path=`` 会撞上助手的形参名 → ``TypeError: got multiple values for
    # argument 'path'``。这里统一用 ``route_path``（M3b 实测踩到）。
    def handler(self, method, route_path):
        route, _params = self.ctx.router.resolve(method, route_path)
        self.assertIsNotNone(route, "路由不存在：%s %s" % (method, route_path))
        return staticmethod(route.handler).__func__

    def call(self, method, route_path, **body):
        from ui.server import Request
        return self.handler(method, route_path)(
            Request(method, route_path, {}, body, {}))

    def get(self, route_path, **query):
        from ui.server import Request
        return self.handler("GET", route_path)(Request("GET", route_path, query, {}, {}))

    def service(self):
        service = getattr(self.ctx, "cheats_service", None)
        self.assertIsNotNone(service, "register_routes 未暴露服务实例")
        return service

    # ------------------------------------------------------------ 夹具助手
    def game(self, name="game", **kw):
        directory = os.path.join(self.root, name)
        os.makedirs(directory, exist_ok=True)
        self.make_game(directory, **kw)
        return directory

    def opened(self, **kw):
        """建游戏 → open → 打开第一个存档，返回 ``(dir, save_path)``。"""
        directory = self.game(**kw)
        res = self.call("POST", "/api/cheats/open", dir=directory)
        self.assertTrue(res["ok"], res.get("error"))
        saves = self.get("/api/cheats/saves")
        self.assertTrue(saves["ok"], saves.get("error"))
        self.assertTrue(saves["saves"], "没有发现存档")
        path = saves["saves"][0]["path"]
        loaded = self.call("POST", "/api/cheats/load", path=path)
        self.assertTrue(loaded["ok"], loaded.get("error"))
        return directory, path

    @staticmethod
    def fingerprint(root, skip_prefixes=("汉化备份",)):
        out = {}
        for base, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if not d.startswith(skip_prefixes)]
            for name in files:
                full = os.path.join(base, name)
                with open(full, "rb") as f:
                    out[os.path.relpath(full, root)] = f.read()
        return out


# ---------------------------------------------------------------------------
# 路由登记
# ---------------------------------------------------------------------------
class TestRouteRegistration(unittest.TestCase):
    """端点清单**双向**核对（与 translate 同一做法）。"""

    EXPECTED = (
        ("GET", "/api/cheats/status"),
        ("POST", "/api/cheats/detect"),
        ("POST", "/api/cheats/open"),
        ("POST", "/api/cheats/pick_folder"),
        ("GET", "/api/cheats/saves"),
        ("POST", "/api/cheats/load"),
        ("GET", "/api/cheats/party"),
        ("GET", "/api/cheats/actors"),
        ("GET", "/api/cheats/vars"),
        ("POST", "/api/cheats/party"),
        ("POST", "/api/cheats/actor"),
        ("POST", "/api/cheats/var"),
        ("POST", "/api/cheats/save"),
        ("GET", "/api/cheats/data"),
        ("POST", "/api/cheats/data"),
        ("GET", "/api/cheats/backups"),
        ("POST", "/api/cheats/restore"),
        ("POST", "/api/cheats/open_dir"),
    )

    @classmethod
    def setUpClass(cls):
        from core import registry as registry_mod
        from core.context import Router
        reg = registry_mod.Registry().discover()
        ctx = AppContext(router=Router())
        cls.report = reg.register_all(ctx)
        cls.routes = [r for r in ctx.router.routes() if r.feature == "cheats"]
        cls.ctx = ctx

    def test_all_expected_endpoints_registered(self):
        have = {(r.method, r.pattern) for r in self.routes}
        missing = [pair for pair in self.EXPECTED if pair not in have]
        self.assertEqual(missing, [], "缺少 M3b 约定的端点：%s" % missing)

    def test_no_extra_endpoints(self):
        have = {(r.method, r.pattern) for r in self.routes}
        extra = sorted(have - set(self.EXPECTED))
        self.assertEqual(extra, [], "出现了未登记的端点：%s" % extra)

    def test_every_route_in_namespace_and_owned(self):
        for route in self.routes:
            with self.subTest(route=route.pattern):
                self.assertTrue(route.pattern.startswith("/api/cheats"),
                                "路由逃出命名空间：%s" % route.pattern)
                self.assertEqual(route.feature, "cheats")

    def test_register_report_is_not_skeleton(self):
        self.assertIn("routes", self.report["cheats"])
        self.assertNotIn("skeleton", self.report["cheats"])

    def test_status_lists_actor_attrs_and_kinds(self):
        payload = staticmethod(self.ctx.router.resolve(
            "GET", "/api/cheats/status")[0].handler).__func__(None)
        self.assertTrue(payload["ok"])
        keys = {a["key"] for a in payload["actor_attrs"]}
        for required in ("level", "exp", "hp", "mp", "param_plus_0"):
            with self.subTest(attr=required):
                self.assertIn(required, keys)
        self.assertEqual(set(payload["item_kinds"]), {"items", "weapons", "armors"})
        self.assertTrue(payload["backup_policy"])


# ---------------------------------------------------------------------------
# 打开游戏 / 存档发现
# ---------------------------------------------------------------------------
class TestOpenAndSaves(CheatsTestCase):
    def test_open_requires_dir(self):
        payload = self.call("POST", "/api/cheats/open")
        self.assertFalse(payload["ok"])
        self.assertIn("dir", payload["error"])

    def test_open_unknown_engine(self):
        with tempfile.TemporaryDirectory(prefix="nogame_") as tmp:
            payload = self.call("POST", "/api/cheats/open", dir=tmp)
        self.assertFalse(payload["ok"])
        self.assertIn("未识别", payload["error"])

    def test_open_reports_engine_and_save_count(self):
        directory = self.game()
        payload = self.call("POST", "/api/cheats/open", dir=directory)
        self.assertTrue(payload["ok"], payload.get("error"))
        self.assertEqual(payload["game"]["engine"], "mv")
        self.assertEqual(payload["saves"], 1)

    def test_saves_requires_game(self):
        payload = self.get("/api/cheats/saves")
        self.assertFalse(payload["ok"])
        self.assertIn("游戏目录", payload["error"])

    def test_saves_lists_name_size_time(self):
        self.game()
        self.call("POST", "/api/cheats/open",
                  dir=os.path.join(self.root, "game"))
        payload = self.get("/api/cheats/saves")
        self.assertTrue(payload["ok"], payload.get("error"))
        self.assertEqual(len(payload["saves"]), 1,
                         "同一个存档被列了多遍（两个来源没去重）：%s"
                         % [s["path"] for s in payload["saves"]])
        entry = payload["saves"][0]
        for key in ("name", "path", "dir", "size", "time"):
            with self.subTest(key=key):
                self.assertIn(key, entry)
        self.assertGreater(entry["size"], 0)
        self.assertTrue(entry["time"])

    def test_saves_and_save_dirs_are_deduplicated(self):
        """存档列表与目录列表都不得出现重复项（两个来源要合并且去重）。"""
        self.game()
        self.call("POST", "/api/cheats/open", dir=os.path.join(self.root, "game"))
        payload = self.get("/api/cheats/saves")
        paths = [s["path"] for s in payload["saves"]]
        dirs = payload["save_dirs"]
        self.assertEqual(len(paths), len(set(paths)), "存档路径重复：%s" % paths)
        self.assertEqual(len(dirs), len(set(dirs)), "存档目录重复：%s" % dirs)

    def test_load_requires_path(self):
        self.call("POST", "/api/cheats/open", dir=self.game())
        payload = self.call("POST", "/api/cheats/load")
        self.assertFalse(payload["ok"])
        self.assertIn("path", payload["error"])

    def test_load_rejects_path_outside_game(self):
        """**越权防线**：不许读游戏目录之外的任意文件。"""
        self.call("POST", "/api/cheats/open", dir=self.game())
        outside = os.path.join(self.root, "outside.rpgsave")
        write_text(outside, "not a save")
        payload = self.call("POST", "/api/cheats/load", path=outside)
        self.assertFalse(payload["ok"])
        self.assertIn("存档目录", payload["error"])

    def test_load_missing_file(self):
        directory = self.game()
        self.call("POST", "/api/cheats/open", dir=directory)
        payload = self.call("POST", "/api/cheats/load",
                            path=os.path.join(directory, "save", "nope.rpgsave"))
        self.assertFalse(payload["ok"])

    def test_load_returns_party_and_actors(self):
        _dir, _path = self.opened()
        party = self.get("/api/cheats/party")
        self.assertTrue(party["ok"], party.get("error"))
        self.assertEqual(party["party"]["gold"], 1000)
        self.assertEqual(party["party"]["steps"], 500)
        actors = self.get("/api/cheats/actors")
        self.assertTrue(actors["ok"], actors.get("error"))
        self.assertTrue(actors["attrs"])

    def test_detect_endpoint_still_works(self):
        """M1 的只读端点必须保持可用（不被 M3b 顺手删掉）。"""
        directory = self.game()
        payload = self.call("POST", "/api/cheats/detect", dir=directory)
        self.assertTrue(payload["ok"], payload.get("error"))
        self.assertEqual(payload["engine"], "mv")
        self.assertEqual(payload["saves"], ["file0.rpgsave"])
        for key in ("data_dir", "save_dir", "save_ext", "supported", "match",
                    "save_dirs", "summary"):
            with self.subTest(key=key):
                self.assertIn(key, payload)

    def test_old_www_layout_save_dir_is_accepted(self):
        """**回归**：老版 MV 布局（``www/save/file*.rpgsave``）必须能改档。

        M3b 实测踩到：``open_save`` 的"合法目录"只取
        ``engines.find_save_dirs`` 的结果，而**空目录不算**；同时
        ``list_saves`` 只看 ``info['save_dir']``。两者标准不一致会让
        "列表里有、点开却被拒"或"目录里有存档却列不出来"。
        真实游戏（如 boli3/RJ01052631）就是这种布局，所以单列一条断言。
        """
        directory = os.path.join(self.root, "wwwgame")
        os.makedirs(directory, exist_ok=True)
        make_mv_game(directory, www=True)
        opened = self.call("POST", "/api/cheats/open", dir=directory)
        self.assertTrue(opened["ok"], opened.get("error"))
        saves = self.get("/api/cheats/saves")
        self.assertTrue(saves["saves"], "老布局下的存档没有被列出来")
        self.assertIn("www", saves["saves"][0]["dir"])
        self.assertTrue(any("www" in d for d in saves["save_dirs"]),
                        "save_dirs 里应包含 www/save：%s" % saves["save_dirs"])
        loaded = self.call("POST", "/api/cheats/load", path=saves["saves"][0]["path"])
        self.assertTrue(loaded["ok"], loaded.get("error"))
        self.assertEqual(loaded["party"]["gold"], 1000)

    def test_save_dirs_includes_empty_standard_dir(self):
        """标准存档目录即使**还没有存档**也要算合法（否则往里存会被拒）。"""
        directory = self.game()
        self.call("POST", "/api/cheats/open", dir=directory)
        service = self.service()
        standard = os.path.abspath(service.info["save_dir"])
        self.assertIn(standard, service.save_dirs())


class TestOpenAndSavesVXAce(TestOpenAndSaves):
    """同一批用例在 VX Ace（真实 Marshal 字节流）上重跑一遍。"""

    make_game = staticmethod(make_vxace_game)

    def test_open_reports_engine_and_save_count(self):
        directory = self.game()
        payload = self.call("POST", "/api/cheats/open", dir=directory)
        self.assertTrue(payload["ok"], payload.get("error"))
        self.assertEqual(payload["game"]["engine"], "vxace")
        self.assertEqual(payload["saves"], 1)

    def test_detect_endpoint_still_works(self):
        directory = self.game()
        payload = self.call("POST", "/api/cheats/detect", dir=directory)
        self.assertTrue(payload["ok"], payload.get("error"))
        self.assertEqual(payload["engine"], "vxace")
        self.assertEqual(payload["saves"], ["Save01.rvdata2"])


# ---------------------------------------------------------------------------
# 读取端点
# ---------------------------------------------------------------------------
class TestReadEndpoints(CheatsTestCase):
    def test_party_needs_save(self):
        self.call("POST", "/api/cheats/open", dir=self.game())
        payload = self.get("/api/cheats/party")
        self.assertFalse(payload["ok"])
        self.assertIn("存档", payload["error"])

    def test_party_items_carry_names(self):
        """**可读性等价**：原工具的列表显示道具名而不是 id。"""
        self.opened()
        party = self.get("/api/cheats/party")["party"]
        items = {row["id"]: row for row in party["items"]["items"]}
        self.assertIn(1, items)
        self.assertEqual(items[1]["name"], "药草")
        self.assertEqual(items[1]["count"], 3)

    def test_party_names_fall_back_to_id(self):
        """名字表里没有的 id 必须回退成 ``#id``，而不是空白。"""
        self.opened()
        self.call("POST", "/api/cheats/party", items=[{"id": 9999, "count": 4}])
        party = self.get("/api/cheats/party")["party"]
        items = {row["id"]: row for row in party["items"]["items"]}
        self.assertEqual(items[9999]["name"], "#9999")

    def test_party_has_party_members_with_names(self):
        self.opened()
        party = self.get("/api/cheats/party")["party"]
        self.assertEqual([p["id"] for p in party["party"]], [1, 2])
        self.assertEqual(party["party"][0]["name"], "勇者")

    def test_vars_default_page(self):
        self.opened()
        payload = self.get("/api/cheats/vars")
        self.assertTrue(payload["ok"], payload.get("error"))
        view = payload["view"]
        self.assertEqual(view["key"], "switches")
        self.assertEqual(view["offset"], 0)
        self.assertGreater(view["total"], 0)
        self.assertTrue(view["items"])

    def test_vars_paging(self):
        self.opened()
        view = self.get("/api/cheats/vars", key="variables", offset=1, limit=2)["view"]
        self.assertEqual(view["offset"], 1)
        self.assertEqual(len(view["items"]), 2)
        self.assertEqual(view["items"][0]["index"], 1)
        self.assertEqual(view["items"][0]["value"], 10)

    def test_vars_rejects_bad_key(self):
        self.opened()
        payload = self.get("/api/cheats/vars", key="nope")
        self.assertFalse(payload["ok"])
        self.assertIn("switches", payload["error"])

    def test_vars_limit_is_clamped(self):
        self.opened()
        view = self.get("/api/cheats/vars", limit=99999)["view"]
        self.assertLessEqual(view["limit"], 500)


class TestReadEndpointsVXAce(TestReadEndpoints):
    make_game = staticmethod(make_vxace_game)

    def test_party_items_carry_names(self):
        self.opened()
        party = self.get("/api/cheats/party")["party"]
        items = {row["id"]: row for row in party["items"]["items"]}
        self.assertIn(1, items)
        self.assertEqual(items[1]["name"], "药草")

    def test_party_has_party_members_with_names(self):
        self.opened()
        party = self.get("/api/cheats/party")["party"]
        self.assertEqual([p["id"] for p in party["party"]], [1])
        self.assertEqual(party["party"][0]["name"], "勇者")


# ---------------------------------------------------------------------------
# 写端点（改内存）
# ---------------------------------------------------------------------------
class TestWriteEndpoints(CheatsTestCase):
    def test_set_gold_and_steps(self):
        self.opened()
        payload = self.call("POST", "/api/cheats/party", gold=888888, steps=12345)
        self.assertTrue(payload["ok"], payload.get("error"))
        self.assertEqual(payload["party"]["gold"], 888888)
        self.assertEqual(payload["party"]["steps"], 12345)
        self.assertTrue(payload["changed"])

    def test_set_item_quantity(self):
        self.opened()
        self.call("POST", "/api/cheats/party", items=[{"id": 1, "count": 99}])
        party = self.get("/api/cheats/party")["party"]
        self.assertEqual({r["id"]: r["count"] for r in party["items"]["items"]}[1], 99)

    def test_set_item_zero_removes_it(self):
        self.opened()
        self.call("POST", "/api/cheats/party", items=[{"id": 1, "count": 0}])
        party = self.get("/api/cheats/party")["party"]
        self.assertNotIn(1, {r["id"] for r in party["items"]["items"]})

    def test_add_item_that_did_not_exist(self):
        self.opened()
        self.call("POST", "/api/cheats/party", items=[{"id": 9999, "count": 7}])
        party = self.get("/api/cheats/party")["party"]
        self.assertEqual({r["id"]: r["count"] for r in party["items"]["items"]}[9999], 7)

    def test_weapons_and_armors_are_separate_buckets(self):
        self.opened()
        self.call("POST", "/api/cheats/party",
                  weapons=[{"id": 1, "count": 5}], armors=[{"id": 1, "count": 2}])
        party = self.get("/api/cheats/party")["party"]
        self.assertEqual({r["id"]: r["count"] for r in party["items"]["weapons"]}[1], 5)
        self.assertEqual({r["id"]: r["count"] for r in party["items"]["armors"]}[1], 2)

    def test_bad_number_is_rejected(self):
        self.opened()
        payload = self.call("POST", "/api/cheats/party", gold="abc")
        self.assertFalse(payload["ok"])
        self.assertIn("参数不合法", payload["error"])

    def test_set_actor_attr(self):
        self.opened()
        payload = self.call("POST", "/api/cheats/actor", actor_id=1,
                            attrs={"level": 88, "hp": 7777, "param_plus_0": 300})
        self.assertTrue(payload["ok"], payload.get("error"))
        actors = {a["index"]: a for a in payload["actors"] if a}
        self.assertEqual(actors[1]["level"], 88)
        self.assertEqual(actors[1]["hp"], 7777)
        self.assertEqual(actors[1]["param_plus"][0], 300)

    def test_set_actor_skills(self):
        self.opened()
        payload = self.call("POST", "/api/cheats/actor", actor_id=1,
                            attrs={}, skills=[5, 6, 7])
        self.assertTrue(payload["ok"], payload.get("error"))
        actors = {a["index"]: a for a in payload["actors"] if a}
        self.assertEqual(actors[1]["skills"], [5, 6, 7])

    def test_actor_rejects_unknown_attr(self):
        """拼错的属性名必须报错，而不是静默什么都不改。"""
        self.opened()
        payload = self.call("POST", "/api/cheats/actor", actor_id=1,
                            attrs={"levle": 10})
        self.assertFalse(payload["ok"])
        self.assertIn("不支持", payload["error"])

    def test_actor_rejects_bad_id(self):
        self.opened()
        payload = self.call("POST", "/api/cheats/actor", actor_id="x", attrs={})
        self.assertFalse(payload["ok"])
        self.assertIn("actor_id", payload["error"])

    def test_actor_rejects_non_object_attrs(self):
        self.opened()
        payload = self.call("POST", "/api/cheats/actor", actor_id=1, attrs=[1, 2])
        self.assertFalse(payload["ok"])
        self.assertIn("attrs", payload["error"])

    def test_set_switch(self):
        self.opened()
        payload = self.call("POST", "/api/cheats/var", key="switches",
                            index=2, value=True)
        self.assertTrue(payload["ok"], payload.get("error"))
        view = self.get("/api/cheats/vars", key="switches")["view"]
        values = {row["index"]: row["value"] for row in view["items"]}
        self.assertEqual(values[2], 1)

    def test_set_variable(self):
        self.opened()
        self.call("POST", "/api/cheats/var", key="variables", index=5, value=555)
        view = self.get("/api/cheats/vars", key="variables", offset=0, limit=10)["view"]
        values = {row["index"]: row["value"] for row in view["items"]}
        self.assertEqual(values[5], 555)

    def test_var_rejects_bad_index(self):
        self.opened()
        payload = self.call("POST", "/api/cheats/var", key="switches",
                            index="x", value=1)
        self.assertFalse(payload["ok"])
        self.assertIn("index", payload["error"])

    def test_writes_before_load_are_refused(self):
        self.call("POST", "/api/cheats/open", dir=self.game())
        for path in ("/api/cheats/party", "/api/cheats/actor", "/api/cheats/var"):
            with self.subTest(path=path):
                payload = self.call("POST", path, actor_id=1, key="switches",
                                    index=0, value=1, gold=1)
                self.assertFalse(payload["ok"])
                self.assertIn("存档", payload["error"])


class TestWriteEndpointsVXAce(TestWriteEndpoints):
    make_game = staticmethod(make_vxace_game)

    def test_set_actor_attr(self):
        """VX Ace 的角色数组只有 1 个有效角色（下标 1）。"""
        self.opened()
        payload = self.call("POST", "/api/cheats/actor", actor_id=1,
                            attrs={"level": 88, "hp": 7777, "param_plus_0": 300})
        self.assertTrue(payload["ok"], payload.get("error"))
        actors = {a["index"]: a for a in payload["actors"] if a}
        self.assertEqual(actors[1]["level"], 88)

    def test_actor_rejects_unknown_attr(self):
        self.opened()
        payload = self.call("POST", "/api/cheats/actor", actor_id=1,
                            attrs={"levle": 10})
        self.assertFalse(payload["ok"])

    def test_set_switch(self):
        self.opened()
        payload = self.call("POST", "/api/cheats/var", key="switches",
                            index=2, value=True)
        self.assertTrue(payload["ok"], payload.get("error"))

    def test_set_variable(self):
        self.opened()
        payload = self.call("POST", "/api/cheats/var", key="variables",
                            index=5, value=555)
        self.assertTrue(payload["ok"], payload.get("error"))


# ---------------------------------------------------------------------------
# 保存与还原（最需要小心的一段）
# ---------------------------------------------------------------------------
class TestSaveAndRestore(CheatsTestCase):
    def _assert_persisted(self, path, gold):
        """重新解析文件，确认改动真的落盘（不是只看接口返回 ok）。"""
        from core.formats import mv_save
        again = mv_save.SaveFileMV(path, engine="mv")
        self.assertEqual(again.read_party()["gold"], gold,
                         "改动没有落盘（重新解析看到的还是旧值）")

    def test_save_requires_confirm(self):
        """**硬约束 §4.2**：覆盖原存档必须显式确认。"""
        _dir, path = self.opened()
        before = open(path, "rb").read()
        payload = self.call("POST", "/api/cheats/party", gold=77777)
        self.assertTrue(payload["ok"])
        saved = self.call("POST", "/api/cheats/save")
        self.assertFalse(saved["ok"])
        self.assertTrue(saved["need_confirm"])
        self.assertIn("确认", saved["error"])
        with open(path, "rb") as f:
            self.assertEqual(f.read(), before, "未确认时文件必须字节不变")

    def test_save_with_confirm_writes_and_backs_up(self):
        _dir, path = self.opened()
        self.call("POST", "/api/cheats/party", gold=77777)
        saved = self.call("POST", "/api/cheats/save", confirm=True)
        self.assertTrue(saved["ok"], saved.get("error"))
        self.assertTrue(saved["backup_dir"], "写回前必须备份")
        self.assertTrue(os.path.isdir(saved["backup_dir"]))
        self._assert_persisted(path, 77777)

        backups = self.get("/api/cheats/backups")
        self.assertTrue(backups["ok"])
        self.assertTrue(backups["backups"], "备份列表里应该能看到刚才的备份")
        self.assertTrue(backups["backups"][0]["has_manifest"])

    def test_backup_can_restore_original(self):
        _dir, path = self.opened()
        original = open(path, "rb").read()
        self.call("POST", "/api/cheats/party", gold=77777)
        saved = self.call("POST", "/api/cheats/save", confirm=True)
        self.assertTrue(saved["ok"], saved.get("error"))
        self.assertNotEqual(open(path, "rb").read(), original, "改动应已写入")

        restored = self.call("POST", "/api/cheats/restore",
                             dir=saved["backup_dir"], confirm=True)
        self.assertTrue(restored["ok"], restored.get("error"))
        self.assertGreaterEqual(restored["result"]["restored"], 1)
        with open(path, "rb") as f:
            self.assertEqual(f.read(), original, "还原后必须与原字节完全一致")
        self.assertEqual(self.get("/api/cheats/party")["party"]["gold"], 1000,
                         "还原后内存里的对象也应刷新")

    def test_restore_requires_confirm(self):
        _dir, path = self.opened()
        self.call("POST", "/api/cheats/party", gold=77777)
        saved = self.call("POST", "/api/cheats/save", confirm=True)
        payload = self.call("POST", "/api/cheats/restore", dir=saved["backup_dir"])
        self.assertFalse(payload["ok"])
        self.assertTrue(payload["need_confirm"])

    def test_restore_requires_dir(self):
        self.opened()
        payload = self.call("POST", "/api/cheats/restore", confirm=True)
        self.assertFalse(payload["ok"])
        self.assertIn("dir", payload["error"])

    def test_save_reopens_and_refreshes_view(self):
        """保存后重新读取，界面拿到的必须是新值（不是缓存）。"""
        self.opened()
        self.call("POST", "/api/cheats/party", gold=424242)
        self.call("POST", "/api/cheats/save", confirm=True)
        self.assertEqual(self.get("/api/cheats/party")["party"]["gold"], 424242)

    def test_zero_and_false_are_written(self):
        """**M3b 修掉的坑**：把值改成 0 / False 不能被当成"没有译文"而丢弃。"""
        _dir, path = self.opened()
        self.call("POST", "/api/cheats/party", gold=0, steps=0)
        self.call("POST", "/api/cheats/party", items=[{"id": 1, "count": 0}])
        saved = self.call("POST", "/api/cheats/save", confirm=True)
        self.assertTrue(saved["ok"], saved.get("error"))
        self._assert_persisted(path, 0)
        self.assertEqual(self.get("/api/cheats/party")["party"]["steps"], 0)


class TestSaveAndRestoreVXAce(TestSaveAndRestore):
    make_game = staticmethod(make_vxace_game)

    def _assert_persisted(self, path, gold):
        from core.formats import rgss_save
        again = rgss_save.SaveFile(path, layout="hash")
        self.assertEqual(again.read_party()["gold"], gold,
                         "改动没有落盘（重新解析看到的还是旧值）")

    def test_save_with_confirm_writes_and_backs_up(self):
        _dir, path = self.opened()
        self.call("POST", "/api/cheats/party", gold=77777)
        saved = self.call("POST", "/api/cheats/save", confirm=True)
        self.assertTrue(saved["ok"], saved.get("error"))
        self.assertTrue(saved["backup_dir"])
        self._assert_persisted(path, 77777)

    def test_zero_and_false_are_written(self):
        _dir, path = self.opened()
        self.call("POST", "/api/cheats/party", gold=0)
        self.call("POST", "/api/cheats/var", key="switches", index=1, value=False)
        saved = self.call("POST", "/api/cheats/save", confirm=True)
        self.assertTrue(saved["ok"], saved.get("error"))
        self._assert_persisted(path, 0)


# ---------------------------------------------------------------------------
# 游戏数据表编辑
# ---------------------------------------------------------------------------
class TestDataTableEdit(CheatsTestCase):
    #: 用于"改价格 / 还原"的 (文件名, 路径)。子类按引擎改写 ——
    #: 两个引擎的路径约定不同（``1/price`` vs ``1/@price``），
    #: 硬编码在方法里会让子类继承到的用例测错对象。
    PRICE_FILE = "Items.json"
    PRICE_PATH = "1/price"

    def _open(self):
        directory = self.game()
        payload = self.call("POST", "/api/cheats/open", dir=directory)
        self.assertTrue(payload["ok"], payload.get("error"))
        return directory

    def test_data_requires_game(self):
        payload = self.get("/api/cheats/data")
        self.assertFalse(payload["ok"])
        self.assertIn("游戏目录", payload["error"])

    def test_data_lists_editable_fields(self):
        self._open()
        payload = self.get("/api/cheats/data")
        self.assertTrue(payload["ok"], payload.get("error"))
        fields = payload["fields"]
        self.assertTrue(fields)
        for key in ("file", "path", "label", "kind", "value", "name"):
            with self.subTest(key=key):
                self.assertIn(key, fields[0])
        paths = {f["path"] for f in fields}
        self.assertIn("1/price", paths, "道具价格应在可编辑字段里")
        self.assertIn("1/name", paths, "道具名应可读出来（用于标注）")
        self.assertIn("gameTitle", paths, "System.json 的字段应被列出")

    def test_data_lists_numeric_kinds(self):
        self._open()
        fields = self.get("/api/cheats/data")["fields"]
        kinds = {f["kind"] for f in fields}
        self.assertIn("int", kinds)
        self.assertTrue(kinds <= {"int", "bool", "text"}, kinds)

    def test_data_can_filter_by_file(self):
        self._open()
        payload = self.get("/api/cheats/data", file="Items.json")
        self.assertTrue(payload["ok"], payload.get("error"))
        self.assertTrue(payload["fields"])
        self.assertEqual({f["file"] for f in payload["fields"]}, {"Items.json"})

    def test_data_edit_stale_original_is_rejected(self):
        self._open()
        payload = self.call("POST", "/api/cheats/data", confirm=True,
                            edits=[{"file": self.PRICE_FILE, "path": self.PRICE_PATH,
                                    "value": 999, "original": 12345, "kind": "int"}])
        self.assertFalse(payload["ok"])
        stale = {s["path"]: s for s in payload["stale"]}
        self.assertIn(self.PRICE_PATH, stale)
        self.assertEqual(stale[self.PRICE_PATH]["actual"], 50)

    def test_data_edit_requires_confirm(self):
        self._open()
        payload = self.call("POST", "/api/cheats/data",
                            edits=[{"file": "Items.json", "path": "1/price",
                                    "value": 999, "original": 50}])
        self.assertFalse(payload["ok"])
        self.assertTrue(payload["need_confirm"])

    def test_data_edit_requires_edits(self):
        self._open()
        payload = self.call("POST", "/api/cheats/data", confirm=True)
        self.assertFalse(payload["ok"])
        self.assertIn("edits", payload["error"])

    def test_data_edit_writes_and_backs_up(self):
        """写回必须真的落盘、必须备份、回读字段里能看到新值。

        两个引擎共用本用例（子类只改 ``PRICE_FILE`` / ``PRICE_PATH``）——
        "改价格"这件事在 MV 与 RGSS 上的**可观测后果**是一样的。
        """
        directory = self._open()
        payload = self.call("POST", "/api/cheats/data", confirm=True,
                            edits=[{"file": self.PRICE_FILE, "path": self.PRICE_PATH,
                                    "value": 999, "original": 50, "kind": "int"}])
        self.assertTrue(payload["ok"], payload.get("error"))
        self.assertTrue(payload["backup_dir"], "写回数据表前必须备份")
        self.assertGreaterEqual(payload["stats"]["entries"], 1)
        self.assertEqual(payload["stats"].get("skipped", 0), 0,
                         "有改动被跳过了：%s" % payload["stats"])
        # 回读的字段列表里必须能看到新值（按 (文件, 路径) 定位 ——
        # `1/price` 在 Items 与 Weapons 里都有，只按 path 会串）
        target = [f["value"] for f in payload["fields"]
                  if f["file"] == self.PRICE_FILE and f["path"] == self.PRICE_PATH]
        self.assertEqual(target, [999], "重新读取数据表没有看到新价格")
        _ = directory

    def test_data_edit_stale_original_is_rejected(self):
        """**陈旧性校验（B-13 同类防线）**：界面看到的值过期时必须拒绝。

        ⚠ 两个引擎的路径不同（``1/price`` vs ``1/@price``），所以断言按
        ``PRICE_PATH`` 取，而不是硬编码 —— 否则子类继承到的用例会测错对象。
        """
        self._open()
        payload = self.call("POST", "/api/cheats/data", confirm=True,
                            edits=[{"file": self.PRICE_FILE, "path": self.PRICE_PATH,
                                    "value": 999, "original": 12345,
                                    "kind": "int"}])
        self.assertFalse(payload["ok"])
        self.assertIn("不一致", payload["error"])
        self.assertTrue(payload["stale"])
        stale = {s["path"]: s for s in payload["stale"]}
        self.assertIn(self.PRICE_PATH, stale)
        self.assertEqual(stale[self.PRICE_PATH]["actual"], 50)

    def test_data_edit_stale_check_reads_original_field(self):
        """回归：陈旧性校验必须认 **original** 这个字段名。

        M3b 实测踩到：路由与界面用 ``original``，而写回层用 ``expect``，
        校验只看 ``expect`` → **所有改动都被当成"没有原值"而放行**，
        校验形同不存在。
        """
        self._open()
        payload = self.call("POST", "/api/cheats/data", confirm=True,
                            edits=[{"file": self.PRICE_FILE, "path": self.PRICE_PATH,
                                    "value": 1, "original": 2, "kind": "int"}])
        self.assertFalse(payload["ok"], "带过期 original 的改动必须被拒绝")
        self.assertTrue(payload["stale"])

    def test_data_edit_keeps_unrelated_fields(self):
        """未修改的字段必须原样保留（"未修改内容字节级保留"的推广）。"""
        self._open()
        before = {f["path"]: f["value"] for f in self.get("/api/cheats/data")["fields"]
                  if f["file"] == self.PRICE_FILE}
        self.call("POST", "/api/cheats/data", confirm=True,
                  edits=[{"file": self.PRICE_FILE, "path": self.PRICE_PATH,
                          "value": 999, "original": 50, "kind": "int"}])
        after = {f["path"]: f["value"] for f in self.get("/api/cheats/data")["fields"]
                 if f["file"] == self.PRICE_FILE}
        for path, value in before.items():
            if path == self.PRICE_PATH:
                continue
            with self.subTest(path=path):
                self.assertEqual(after.get(path), value,
                                 "未修改的字段被改动了：%s" % path)

    def test_data_edit_offers_restore(self):
        _dir, _path = self.opened()
        payload = self.call("POST", "/api/cheats/data", confirm=True,
                            edits=[{"file": self.PRICE_FILE, "path": self.PRICE_PATH,
                                    "value": 999, "original": 50, "kind": "int"}])
        backups = self.get("/api/cheats/backups")["backups"]
        self.assertTrue(backups)
        restored = self.call("POST", "/api/cheats/restore",
                             dir=payload["backup_dir"], confirm=True)
        self.assertTrue(restored["ok"], restored.get("error"))
        target = [f["value"] for f in self.get("/api/cheats/data")["fields"]
                  if f["file"] == self.PRICE_FILE and f["path"] == self.PRICE_PATH]
        self.assertEqual(target, [50], "还原后价格应回到 50")

    @staticmethod
    def _data_sub():
        return "data"


class TestDataTableEditVXAce(TestDataTableEdit):
    make_game = staticmethod(make_vxace_game)
    #: RGSS 的路径带 ``@`` 前缀，与 MV 的 ``1/price`` 不同 ——
    #: 子类必须改写，否则继承来的用例会在**错误的路径**上做断言
    PRICE_FILE = "Items.rvdata2"
    PRICE_PATH = "1/@price"

    @staticmethod
    def _data_sub():
        return "Data"

    def test_data_lists_editable_fields(self):
        self._open()
        payload = self.get("/api/cheats/data")
        self.assertTrue(payload["ok"], payload.get("error"))
        paths = {f["path"] for f in payload["fields"]}
        self.assertIn("1/@price", paths, "VX Ace 的道具价格应在可编辑字段里")
        self.assertIn("1/@name", paths, "VX Ace 的道具名应可读出来")

    def test_data_lists_numeric_kinds(self):
        self._open()
        fields = self.get("/api/cheats/data")["fields"]
        kinds = {f["kind"] for f in fields}
        self.assertIn("int", kinds)
        self.assertIn("bool", kinds, "consumable 是布尔字段")

    def test_data_can_filter_by_file(self):
        self._open()
        payload = self.get("/api/cheats/data", file="Items.rvdata2")
        self.assertTrue(payload["ok"], payload.get("error"))
        self.assertTrue(payload["fields"])
        self.assertEqual({f["file"] for f in payload["fields"]},
                         {"Items.rvdata2"})

    def test_data_edit_writes_fixnum_not_string(self):
        """VX Ace 侧必须写回**数字节点**而不是字符串（类型不能漂移）。

        这一条是 VX Ace **独有**的：MV/MZ 走 JSON，类型天然由 Python 值决定；
        而 RGSS 要构造 Marshal 节点，写错类型游戏会读崩（显示异常或脚本报错）。
        """
        from core.marshal import doc_model as D
        directory = self._open()
        payload = self.call("POST", "/api/cheats/data", confirm=True,
                            edits=[{"file": "Items.rvdata2", "path": "1/@price",
                                    "value": 999, "original": 50, "kind": "int"}])
        self.assertTrue(payload["ok"], payload.get("error"))
        with open(os.path.join(directory, "Data", "Items.rvdata2"), "rb") as f:
            tree = D.loads(f.read())
        price = D.ivar(tree.items[1], "@price")
        self.assertIsInstance(price, D.Fixnum,
                              "价格被写成了 %s —— 类型漂移（游戏会读崩）"
                              % type(price).__name__)
        self.assertEqual(price.value, 999)

    def test_data_edit_writes_boolean_node(self):
        """布尔字段必须仍是 BoolNode，不能变成 Fixnum。"""
        from core.marshal import doc_model as D
        directory = self._open()
        payload = self.call("POST", "/api/cheats/data", confirm=True,
                            edits=[{"file": "Items.rvdata2",
                                    "path": "1/@consumable",
                                    "value": False, "original": True,
                                    "kind": "bool"}])
        self.assertTrue(payload["ok"], payload.get("error"))
        with open(os.path.join(directory, "Data", "Items.rvdata2"), "rb") as f:
            tree = D.loads(f.read())
        node = D.ivar(tree.items[1], "@consumable")
        self.assertIsInstance(node, D.BoolNode,
                              "布尔字段被写成了 %s" % type(node).__name__)
        self.assertFalse(node.value)


if __name__ == "__main__":
    unittest.main(verbosity=2)

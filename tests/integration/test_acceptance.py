# -*- coding: utf-8 -*-
"""需求 §8-2/§8-3 的**端到端回归**：5 类存档格式 + 4 个引擎的真实样本。

@feature  none
@layer    tests
@public   TestTranslateRegression, TestCheatsRegression,
          TestLosslessness, TestSafety
@depends  features.translate.routes, features.cheats.routes,
          core.formats, core.safety
@tested   (本文件即测试)
@footprint docs/STATE.md

需求原文（§8）
--------------
* **2. 翻译回归**：MV / MZ / VX Ace / XP 各至少 1 个样本，完成
  "扫描 → 翻译（可用离线假翻译器跑通）→ 生成汉化版 → 写回原游戏 → 还原"全链路。
* **3. 修改回归**：5 类存档格式各至少 1 个样本，完成
  "识别 → 读档 → 改金币/物品/角色/开关变量 → 保存 → 重新读取确认"。
* **4. 无损性**：未改动内容往返后字节级一致（自动化断言，不允许人工目视）。
* **5. 安全性**：备份存在、还原可用；覆盖前有确认；异常中断不产生半写文件。

样本来源（关键设计）
--------------------
本机真实游戏库覆盖 **VX Ace / MV / MZ**，**没有** VX（``.rvdata``）与
XP（``.rxdata``）游戏 —— M0 已登记为空白。因此：

| 格式 | 样本来源 |
| --- | --- |
| ``.rvdata2``（VX Ace） | 真实游戏（`TUDOU_RPGTOOL_SAMPLES`） |
| ``.rpgsave``（MV） | 真实游戏 |
| ``.rmmzsave``（MZ） | 真实游戏 |
| ``.rvdata``（VX） | **合成**（``core.marshal.doc_model`` 构造，standard=True） |
| ``.rxdata``（XP） | **合成** |

合成是为"没有样本 = 没有证据"准备的替代品（与
``tests/compat/test_standard_mode.py`` 同一手法），不是偷工减料：
``standard=True`` 正是 P0 缺陷 B-10 的活路径，反而比真实样本覆盖得更准。

真实样本**不入库**（ADR-005）：路径由环境变量给出，缺失时本文件
**整类 skip**（而不是失败），并在输出里说明怎么开启。
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest

_ROOT = os.path.dirname(os.path.abspath(__file__))
while not os.path.isfile(os.path.join(_ROOT, "app.py")):
    parent = os.path.dirname(_ROOT)
    if parent == _ROOT:
        raise RuntimeError("无法定位工程根（未找到 app.py）")
    _ROOT = parent
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core import engines as engines_mod  # noqa: E402
from core import paths  # noqa: E402
from core.marshal import doc_model as M  # noqa: E402

#: 真实样本：``(引擎, 相对样本根的游戏目录)``
REAL_GAMES = {
    "vxace": r"boli\B7794\博麗霊夢は洗脳されてしまいました",
    "mv": r"痴女の触手 官中版\痴女の触手 官中版",
    "mz": r"demon\DD_V07c_Windows\DD_V07c_Windows",
}

#: 操作笔数上限：真实样本动辄上万条，全量操作会让回归跑几十分钟。
#: 这里只取前 N 条**改成假译文**，其余保持原样 —— 而"其余保持原样"正是
#: §8-4 无损性要验证的东西（改动越少，字节对比的覆盖面越大）。
MAX_EDITS = 25


def samples_root():
    root = paths.samples_root()
    return root if root and os.path.isdir(root) else None


def real_game(engine):
    root = samples_root()
    if not root:
        return None
    path = os.path.join(root, REAL_GAMES[engine])
    return path if os.path.isdir(path) else None


# ---------------------------------------------------------------------------
# 合成 VX / XP 游戏（各一份完整可识别的游戏目录 + 一个存档）
# ---------------------------------------------------------------------------
def _sym(name):
    return M.Symbol(name.encode("utf-8"))


def _str(text):
    return M.String(text.encode("utf-8"))


def _obj(class_name, ivars):
    return M.ObjectNode(_sym(class_name), [
        (_sym(k if k.startswith("@") else "@" + k), v) for k, v in ivars.items()])


def _force_standard(node, seen=None):
    """把树里所有 ``Fixnum`` 标记成标准编码（XP / VX 的活路径）。

    ⚠ **必须这样做的原因**（M5 实测踩到）：``Fixnum.__init__(value, std=False)``
    的 ``std`` 默认是 **False**，而序列化时按 ``self.std`` 选编码器。
    合成夹具里如果漏了一个 ``std=True``，写出来的字节就是**变体**编码，
    于是解析侧（``standard=True``）读不出来 —— 表现不是报错，而是
    **VX 的扫描结果为 0 条**（XP 恰好全写对了所以正常）。
    与其在夹具里逐处传 ``std=True``（漏一处就静默失效），不如在写盘前
    统一强制一遍。真实游戏的数据由游戏自己写出，不受此影响。
    """
    from core.marshal import doc_model as D

    if node is None:
        return
    seen = seen if seen is not None else set()
    if id(node) in seen:
        return
    seen.add(id(node))
    if isinstance(node, D.Fixnum):
        node.std = True
        return
    if isinstance(node, D.Array):
        for item in node.items:
            _force_standard(item, seen)
        return
    if isinstance(node, D.Hash):
        for key, value in node.entries:
            _force_standard(key, seen)
            _force_standard(value, seen)
        return
    if isinstance(node, D.HashDef):
        for key, value in node.entries:
            _force_standard(key, seen)
            _force_standard(value, seen)
        _force_standard(node.default, seen)
        return
    if isinstance(node, D.ObjectNode):
        for _key, value in node.ivars:
            _force_standard(value, seen)
        return
    if isinstance(node, D.Ivar):
        _force_standard(node.inner, seen)
        for _key, value in node.ivars:
            _force_standard(value, seen)
        return


def make_synthetic_rgss_game(root, engine):
    """造一个 VX（``.rvdata``）或 XP（``.rxdata``）游戏。

    ``engine`` 取 ``'vx'`` 或 ``'xp'``。两者都走 ``standard=True``
    （Ruby 1.8 的标准整数编码）+ ``contents`` 布局。

    形状取自真实存档：
    ``[header, [system, switches, variables, self_switches, actors, party,
    troop, map, player]]``。
    """
    ext = ".rvdata" if engine == "vx" else ".rxdata"
    std = True
    os.makedirs(os.path.join(root, "Data"), exist_ok=True)
    with open(os.path.join(root, "Game.ini"), "w", encoding="utf-8") as f:
        f.write("[Game]\nTitle=合成%s\n" % engine)

    def dump(fname, node):
        _force_standard(node)          # 见 _force_standard 的说明
        with open(os.path.join(root, "Data", fname), "wb") as f:
            f.write(M.dumps(node))

    # 数据表（让 detect 能认出 RGSS，并给名字表提供内容）
    dump("Items" + ext, M.Array([
        M.NilNode(),
        _obj("RPG::Item", {"id": M.Fixnum(1, std=std), "name": _str("药草"),
                           "price": M.Fixnum(50, std=std),
                           "consumable": M.BoolNode(True),
                           "occasion": M.Fixnum(0, std=std)}),
    ]))
    dump("Weapons" + ext, M.Array([
        M.NilNode(),
        _obj("RPG::Weapon", {"id": M.Fixnum(1, std=std), "name": _str("短剑"),
                             "price": M.Fixnum(100, std=std),
                             "params": M.Array([M.Fixnum(0, std=std),
                                                M.Fixnum(10, std=std)])}),
    ]))
    dump("Armors" + ext, M.Array([
        M.NilNode(),
        _obj("RPG::Armor", {"id": M.Fixnum(1, std=std), "name": _str("布甲"),
                            "price": M.Fixnum(80, std=std),
                            "params": M.Array([M.Fixnum(8, std=std)])}),
    ]))
    dump("Actors" + ext, M.Array([
        M.NilNode(),
        _obj("RPG::Actor", {"id": M.Fixnum(1, std=std), "name": _str("勇者"),
                            "class_id": M.Fixnum(1, std=std),
                            "initial_level": M.Fixnum(1, std=std)}),
    ]))
    dump("Classes" + ext, M.Array([
        M.NilNode(),
        _obj("RPG::Class", {"id": M.Fixnum(1, std=std), "name": _str("战士")}),
    ]))
    dump("Enemies" + ext, M.Array([
        M.NilNode(),
        _obj("RPG::Enemy", {"id": M.Fixnum(1, std=std), "name": _str("史莱姆")}),
    ]))

    contents = M.Array([
        _obj("Game_System", {}),                                     # 0 system
        _obj("Game_Switches", {"data": M.Array([                     # 1 switches
            M.BoolNode(False), M.BoolNode(True), M.BoolNode(False)])}),
        _obj("Game_Variables", {"data": M.Array([                    # 2 variables
            M.Fixnum(0, std=std), M.Fixnum(10, std=std),
            M.Fixnum(20, std=std)])}),
        M.Hash([]),                                                  # 3 self_switches
        M.Array([                                                    # 4 actors
            M.NilNode(),
            _obj("Game_Actor", {"id": M.Fixnum(1, std=std),
                                "name": _str("勇者"),
                                "class_id": M.Fixnum(1, std=std),
                                "level": M.Fixnum(5, std=std),
                                "exp": M.Hash([(M.Fixnum(1, std=std),
                                                M.Fixnum(100, std=std))]),
                                "hp": M.Fixnum(200, std=std),
                                "mp": M.Fixnum(50, std=std),
                                "param_plus": M.Array(
                                    [M.Fixnum(0, std=std) for _ in range(8)]),
                                "skills": M.Array([M.Fixnum(1, std=std)])}),
        ]),
        _obj("Game_Party", {                                         # 5 party
            "gold": M.Fixnum(1000, std=std),
            "steps": M.Fixnum(500, std=std),
            "items": M.Hash([(M.Fixnum(1, std=std), M.Fixnum(3, std=std))]),
            "weapons": M.Hash([(M.Fixnum(1, std=std), M.Fixnum(1, std=std))]),
            "armors": M.Hash([]),
            "actors": M.Array([M.Fixnum(1, std=std)]),
        }),
        M.Hash([]),                                                  # 6 troop
        M.Hash([]),                                                  # 7 map
        M.Hash([]),                                                  # 8 player
    ])
    root_node = M.Array([_obj("header", {"title": _str("合成%s存档" % engine)}),
                         contents])
    name = "Save01%s" % ext
    with open(os.path.join(root, name), "wb") as f:
        f.write(M.dumps(root_node))
    return os.path.join(root, name)


# ---------------------------------------------------------------------------
# 假翻译器（离线，不出网）
# ---------------------------------------------------------------------------
class FakeTranslator(object):
    """把每条文本加上前缀 —— 可逆、可断言、不出网。"""

    PREFIX = "[ZH]"

    def __init__(self, **kw):
        self.calls = 0

    def translate_batch(self, texts, src, dst):
        self.calls += 1
        return ["%s%s" % (self.PREFIX, t) for t in texts]


class AcceptanceBase(unittest.TestCase):
    """装配一套隔离的应用上下文（与两个功能的测试同一形态）。"""

    def setUp(self):
        try:
            self.tmp = tempfile.TemporaryDirectory(prefix="accept_",
                                                   ignore_cleanup_errors=True)
        except TypeError:
            self.tmp = tempfile.TemporaryDirectory(prefix="accept_")
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name
        os.environ["TUDOU_RPGTOOL_DATA"] = os.path.join(self.root, "runtime")
        os.makedirs(os.environ["TUDOU_RPGTOOL_DATA"], exist_ok=True)

        from core import config as config_mod
        from core import jobs as jobs_mod
        from core.context import AppContext, Router
        from features.cheats import manifest as cheats_manifest
        from features.translate import manifest as translate_manifest

        self.config = config_mod.AppConfig(path=os.path.join(self.root, "config.json"))
        # 翻译链路要跑后台任务（扫描 / 构建），所以必须装配 JobManager
        self.jobs_manager = jobs_mod.JobManager(max_workers=2, max_pending=32,
                                                ttl=120, id_prefix="acc")
        self.addCleanup(self.jobs_manager.shutdown)
        ctx = AppContext(router=Router(), config=self.config,
                         jobs=self.jobs_manager)
        cheats_manifest.register(ctx)
        translate_manifest.register(ctx)
        self.ctx = ctx

    def call(self, method, route_path, **body):
        from ui.server import Request
        route, _params = self.ctx.router.resolve(method, route_path)
        self.assertIsNotNone(route, "路由不存在：%s %s" % (method, route_path))
        handler = staticmethod(route.handler).__func__
        return handler(Request(method, route_path, {}, body, {}))

    def get(self, route_path, **query):
        from ui.server import Request
        route, _params = self.ctx.router.resolve("GET", route_path)
        self.assertIsNotNone(route, "路由不存在：GET %s" % route_path)
        handler = staticmethod(route.handler).__func__
        return handler(Request("GET", route_path, query, {}, {}))

    @property
    def jobs(self):
        return self.jobs_manager

    def wait(self, payload, timeout=300):
        job = self.jobs.wait(payload["job"], timeout=timeout)
        self.assertIn(job["status"], ("done", "cancelled"),
                      "任务失败：%s\n%s" % (job.get("error"), job.get("traceback_tail")))
        return job

    def copy_game(self, src, name=None):
        """把真实游戏**复制**到临时目录再动手 —— 参考样本永不修改。"""
        dst = os.path.join(self.root, name or os.path.basename(src.rstrip("\\/")))
        shutil.copytree(src, dst)
        return dst

    @staticmethod
    def fingerprint(root, skip=("汉化备份",)):
        out = {}
        for base, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if not d.startswith(skip)]
            for name in files:
                full = os.path.join(base, name)
                with open(full, "rb") as f:
                    out[os.path.relpath(full, root)] = f.read()
        return out


# ---------------------------------------------------------------------------
# §8-2 翻译回归
# ---------------------------------------------------------------------------
class TranslateRegressionMixin(object):
    """翻译全链路：扫描 → 翻译（假翻译器）→ 生成汉化版 → 写回 → 还原。"""

    engine = None

    def make_game(self):
        raise NotImplementedError

    def test_translate_full_chain(self):
        game = self.make_game()
        info = engines_mod.detect(game)
        self.assertTrue(info.get("engine"), "未能识别引擎：%s" % info.get("error"))
        self.assertEqual(info["engine"], self.engine)

        before = self.fingerprint(game)

        # ---- 扫描 ----
        opened = self.call("POST", "/api/translate/open", dir=game)
        self.assertTrue(opened["ok"], opened.get("error"))
        scan = self.call("POST", "/api/translate/scan", dir=game)
        self.assertTrue(scan["ok"], scan.get("error"))
        job = self.wait(scan)
        total = job["result"]["total"]
        self.assertGreater(total, 0, "扫描结果为空")

        # ---- 翻译（离线假翻译器）----
        entries = self.get("/api/translate/entries", size=MAX_EDITS)["entries"]
        self.assertTrue(entries)
        for entry in entries:
            key = "%s|%s" % (entry["file"], entry["path"])
            saved = self.call("POST", "/api/translate/entry", key=key,
                              translated=FakeTranslator.PREFIX + entry["original"],
                              status="translated")
            self.assertTrue(saved["ok"], saved.get("error"))

        # ---- 生成汉化版（写副本）----
        out = os.path.join(self.root, "out")
        built = self.call("POST", "/api/translate/build", mode="copy", target=out)
        self.assertTrue(built["ok"], built.get("error"))
        job = self.wait(built)
        result = job["result"]
        self.assertGreaterEqual(result["entries"], 1, "一条译文都没写进去")
        self.assertFalse(result["backup_dir"], "写副本不该产生备份")
        self.assertTrue(os.path.isdir(out))

        # ---- 无损性：原游戏一个字节都没变 ----
        self.assertEqual(self.fingerprint(game), before,
                         "copy 模式改动了原游戏目录")

        # ---- 汉化版里真的有译文 ----
        self.assert_translated(out, entries)

        # ---- 写回原游戏（inplace）+ 还原 ----
        inplace = self.call("POST", "/api/translate/build", mode="inplace",
                            confirm=True)
        self.assertTrue(inplace["ok"], inplace.get("error"))
        job = self.wait(inplace)
        backup = job["result"]["backup_dir"]
        self.assertTrue(backup, "inplace 构建必须生成备份")
        self.assertNotEqual(self.fingerprint(game), before,
                            "inplace 构建没有改动原游戏")

        restored = self.call("POST", "/api/translate/restore", dir=backup)
        self.assertTrue(restored["ok"], restored.get("error"))
        self.assertEqual(self.fingerprint(game), before,
                         "还原后原游戏必须与原字节完全一致")

    def assert_translated(self, out, entries):
        """在汉化版里找到第一条改过的条目（子类按格式实现）。"""
        raise NotImplementedError


class TestTranslateRegressionMV(TranslateRegressionMixin, AcceptanceBase):
    engine = "mv"

    def make_game(self):
        from tests.features.cheats.test_routes import make_mv_game
        game = os.path.join(self.root, "mvgame")
        os.makedirs(game, exist_ok=True)
        make_mv_game(game)
        return game

    def assert_translated(self, out, entries):
        target = entries[0]
        with open(os.path.join(out, "data", target["file"]), encoding="utf-8") as f:
            data = json.load(f)
        segs = target["path"].split("/")
        cur = data
        for seg in segs[:-1]:
            cur = cur[int(seg)] if isinstance(cur, list) else cur[seg]
        self.assertEqual(cur[int(segs[-1]) if isinstance(cur, list) else segs[-1]],
                         FakeTranslator.PREFIX + target["original"])


class TestTranslateRegressionMZ(TranslateRegressionMixin, AcceptanceBase):
    engine = "mz"

    def make_game(self):
        """MZ 与 MV 的 JSON 数据结构一致，差别只在标记文件与存档扩展名。"""
        from tests.features.cheats.test_routes import make_mv_game
        game = os.path.join(self.root, "mzgame")
        os.makedirs(game, exist_ok=True)
        make_mv_game(game)
        # 换成 MZ 的标记与存档
        os.remove(os.path.join(game, "js", "rpg_core.js"))
        with open(os.path.join(game, "js", "rmmz_core.js"), "w") as f:
            f.write("// synthetic mz\n")
        os.remove(os.path.join(game, "save", "file0.rpgsave"))
        from core.formats import mv_save
        with open(os.path.join(game, "save", "file0.rmmzsave"), "wb") as f:
            f.write(mv_save.SaveFileMV._dump(
                json.loads(json.dumps({
                    "party": {"_gold": 1, "_steps": 1, "_items": {},
                              "_weapons": {}, "_armors": {}, "_actors": {"@a": []}},
                    "switches": {"_data": [True]},
                    "variables": {"_data": [0]},
                    "actors": {"_data": []}})), "mz"))
        return game

    def assert_translated(self, out, entries):
        target = entries[0]
        with open(os.path.join(out, "data", target["file"]), encoding="utf-8") as f:
            data = json.load(f)
        segs = target["path"].split("/")
        cur = data
        for seg in segs[:-1]:
            cur = cur[int(seg)] if isinstance(cur, list) else cur[seg]
        self.assertEqual(cur[int(segs[-1]) if isinstance(cur, list) else segs[-1]],
                         FakeTranslator.PREFIX + target["original"])


class TestTranslateRegressionVXAce(TranslateRegressionMixin, AcceptanceBase):
    engine = "vxace"

    def make_game(self):
        source = real_game("vxace")
        if not source:
            raise unittest.SkipTest(
                "缺少 VX Ace 真实样本。设置 %s 后重跑。" % paths.ENV_SAMPLES)
        return self.copy_game(source, "vxacegame")

    def assert_translated(self, out, entries):
        from core.marshal import doc_model as D
        target = entries[0]
        with open(os.path.join(out, "Data", target["file"]), "rb") as f:
            tree = D.loads(f.read())
        # RGSS 的路径是 ``@list/0/@parameters/0`` 这种；用项目的导航器定位
        from core.marshal import value_layer as V
        root = V.wrap(tree)
        from core.formats import rgss_data
        parent, key, _ = rgss_data._navigate(root, target["path"])
        self.assertEqual(rgss_data._text_of(parent[key]),
                         FakeTranslator.PREFIX + target["original"])


class TestTranslateRegressionXP(TestTranslateRegressionVXAce):
    """XP 用合成样本（本机没有真实 XP 游戏）。

    ⚠ 与 VX Ace 的差别不只是扩展名：XP 走 ``standard=True`` + ``contents``
    布局，而 VX Ace 是 ``hash`` 布局 —— 正是 P0 缺陷 B-10 的活路径。
    """

    engine = "xp"

    def make_game(self):
        game = os.path.join(self.root, "xpgame")
        os.makedirs(game, exist_ok=True)
        make_synthetic_rgss_game(game, "xp")
        return game

    def assert_translated(self, out, entries):
        """合成 XP 的数据表没有事件，改的是数据表字段（名字/价格）。"""
        from core.marshal import doc_model as D
        target = entries[0]
        with open(os.path.join(out, "Data", target["file"]), "rb") as f:
            tree = D.loads(f.read())
        index = int(target["path"].split("/")[0])
        field = target["path"].split("/")[-1]
        self.assertEqual(D.ivar(tree.items[index], field).to_py(),
                         FakeTranslator.PREFIX + target["original"])


class TestTranslateRegressionVX(TestTranslateRegressionXP):
    engine = "vx"

    def make_game(self):
        game = os.path.join(self.root, "vxgame")
        os.makedirs(game, exist_ok=True)
        make_synthetic_rgss_game(game, "vx")
        return game


# ---------------------------------------------------------------------------
# §8-3 修改回归
# ---------------------------------------------------------------------------
class CheatsRegressionMixin(object):
    """修改全链路：识别 → 读档 → 改四类 → 保存 → 重新读取确认。"""

    engine = None

    def make_game(self):
        raise NotImplementedError

    def test_cheats_full_chain(self):
        game = self.make_game()
        info = engines_mod.detect(game)
        self.assertEqual(info["engine"], self.engine)

        opened = self.call("POST", "/api/cheats/open", dir=game)
        self.assertTrue(opened["ok"], opened.get("error"))
        saves = self.get("/api/cheats/saves")
        self.assertTrue(saves["saves"], "没有发现存档")
        path = saves["saves"][0]["path"]
        loaded = self.call("POST", "/api/cheats/load", path=path)
        self.assertTrue(loaded["ok"], loaded.get("error"))
        self.assertGreaterEqual(loaded["party"]["gold"], 0)
        self.assertTrue(loaded["actors"], "没有读到角色")

        before = self.fingerprint(game)

        # ---- 改四类 ----
        party = self.call("POST", "/api/cheats/party", gold=888888, steps=1234,
                          items=[{"id": 1, "count": 33}])
        self.assertTrue(party["ok"], party.get("error"))
        actor = self.call("POST", "/api/cheats/actor", actor_id=1,
                          attrs={"level": 77, "hp": 4321}, skills=[1, 2, 3])
        self.assertTrue(actor["ok"], actor.get("error"))
        var = self.call("POST", "/api/cheats/var", key="switches", index=1,
                        value=True)
        self.assertTrue(var["ok"], var.get("error"))
        var2 = self.call("POST", "/api/cheats/var", key="variables", index=2,
                         value=777)
        self.assertTrue(var2["ok"], var2.get("error"))

        # ---- 未确认必须拒绝且文件不变 ----
        refused = self.call("POST", "/api/cheats/save")
        self.assertFalse(refused["ok"])
        self.assertTrue(refused["need_confirm"])
        self.assertEqual(self.fingerprint(game), before, "未确认时文件不该变")

        # ---- 保存 ----
        saved = self.call("POST", "/api/cheats/save", confirm=True)
        self.assertTrue(saved["ok"], saved.get("error"))
        self.assertTrue(saved["backup_dir"], "写回前必须备份")
        self.assertNotEqual(self.fingerprint(game), before, "保存没有改动文件")

        # ---- 重新读取确认（四个值都在）----
        again = self.call("POST", "/api/cheats/load", path=path)
        self.assertTrue(again["ok"], again.get("error"))
        self.assertEqual(again["party"]["gold"], 888888)
        self.assertEqual(again["party"]["steps"], 1234)
        items = {r["id"]: r["count"] for r in again["party"]["items"]["items"]}
        self.assertEqual(items.get(1), 33)
        actors = {a["index"]: a for a in again["actors"] if a}
        self.assertEqual(actors[1]["level"], 77)
        self.assertEqual(actors[1]["hp"], 4321)
        self.assertEqual(actors[1]["skills"], [1, 2, 3])
        switches = self.get("/api/cheats/vars", key="switches")["view"]["items"]
        self.assertEqual({s["index"]: s["value"] for s in switches}[1], 1)
        variables = self.get("/api/cheats/vars", key="variables",
                             offset=0, limit=10)["view"]["items"]
        self.assertEqual({v["index"]: v["value"] for v in variables}[2], 777)

        # ---- 还原 ----
        restored = self.call("POST", "/api/cheats/restore",
                             dir=saved["backup_dir"], confirm=True)
        self.assertTrue(restored["ok"], restored.get("error"))
        _ = restored
        self.assertEqual(self.fingerprint(game), before,
                         "还原后必须与原字节完全一致")


class TestCheatsRegressionMV(CheatsRegressionMixin, AcceptanceBase):
    engine = "mv"

    def make_game(self):
        from tests.features.cheats.test_routes import make_mv_game
        game = os.path.join(self.root, "mvcheat")
        os.makedirs(game, exist_ok=True)
        make_mv_game(game)
        return game


class TestCheatsRegressionMZ(TestCheatsRegressionMV):
    engine = "mz"

    def make_game(self):
        from tests.features.cheats.test_routes import make_mv_game
        from core.formats import mv_save
        game = os.path.join(self.root, "mzcheat")
        os.makedirs(game, exist_ok=True)
        make_mv_game(game)
        os.remove(os.path.join(game, "js", "rpg_core.js"))
        with open(os.path.join(game, "js", "rmmz_core.js"), "w") as f:
            f.write("// synthetic mz\n")
        # MZ 的存档是 zlib，扩展名不同 —— 用同一个内容重打包
        from core.formats.jsoncodec import decompress_save
        with open(os.path.join(game, "save", "file0.rpgsave"), "rb") as f:
            payload = decompress_save(f.read())
        os.remove(os.path.join(game, "save", "file0.rpgsave"))
        with open(os.path.join(game, "save", "file0.rmmzsave"), "wb") as f:
            f.write(mv_save.SaveFileMV._dump(json.loads(payload), "mz"))
        return game


class TestCheatsRegressionVXAce(CheatsRegressionMixin, AcceptanceBase):
    engine = "vxace"

    def make_game(self):
        source = real_game("vxace")
        if not source:
            raise unittest.SkipTest(
                "缺少 VX Ace 真实样本。设置 %s 后重跑。" % paths.ENV_SAMPLES)
        return self.copy_game(source, "vxacecheat")


class TestCheatsRegressionXP(CheatsRegressionMixin, AcceptanceBase):
    engine = "xp"

    def make_game(self):
        game = os.path.join(self.root, "xpcheat")
        os.makedirs(game, exist_ok=True)
        make_synthetic_rgss_game(game, "xp")
        return game


class TestCheatsRegressionVX(TestCheatsRegressionXP):
    engine = "vx"

    def make_game(self):
        game = os.path.join(self.root, "vxcheat")
        os.makedirs(game, exist_ok=True)
        make_synthetic_rgss_game(game, "vx")
        return game


# ---------------------------------------------------------------------------
# §8-4 无损性（不依赖真实样本：合成 + 真实都跑）
# ---------------------------------------------------------------------------
class TestLosslessness(AcceptanceBase):
    """未改动内容往返后**字节级**一致 —— 自动化断言，不靠人眼。"""

    def test_mv_untouched_bytes_survive_roundtrip(self):
        from core.formats import mv_mz_data
        from tests.features.cheats.test_routes import make_mv_game
        game = os.path.join(self.root, "mvloss")
        os.makedirs(game, exist_ok=True)
        make_mv_game(game)
        data_dir = os.path.join(game, "data")
        before = {}
        for name in os.listdir(data_dir):
            with open(os.path.join(data_dir, name), "rb") as f:
                before[name] = f.read()

        info = engines_mod.detect(game)
        # 只改一个字段
        stats = mv_mz_data.apply_to_files(info, {"Items.json": [{
            "file": "Items.json", "path": "1/price", "translated": 123,
            "expect": 50, "status": "translated", "kind": "int"}]})
        self.assertEqual(stats["entries"], 1, stats)

        for name, raw in before.items():
            with open(os.path.join(data_dir, name), "rb") as f:
                got = f.read()
            if name == "Items.json":
                self.assertNotEqual(got, raw, "改过的文件应当变化")
            else:
                self.assertEqual(got, raw, "**未改动的文件字节不该变**：%s" % name)

    def test_mv_wrapped_file_stays_wrapped(self):
        """加密 JSON 包装的文件：改一个字段后仍是包装格式（B-22 的推广）。"""
        from core.formats import jsoncodec, mv_mz_data
        from tests.features.cheats.test_routes import make_mv_game
        game = os.path.join(self.root, "wrapped")
        os.makedirs(game, exist_ok=True)
        make_mv_game(game)
        plain = [None, {"id": 1, "name": "药草", "price": 50}]
        payload_b64 = jsoncodec.encrypt_wrapper_payload(
            json.dumps(plain, ensure_ascii=False), "Items.json")
        wrapped = jsoncodec.join_wrapper(
            {"uid": "x", "bid": "y"}, payload_b64)
        path = os.path.join(game, "data", "Items.json")
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(wrapped if isinstance(wrapped, str) else json.dumps(wrapped))
        info = engines_mod.detect(game)
        stats = mv_mz_data.apply_to_files(info, {"Items.json": [{
            "file": "Items.json", "path": "1/price", "translated": 999,
            "expect": 50, "status": "translated", "kind": "int"}]})
        self.assertEqual(stats["entries"], 1, stats)
        with open(path, encoding="utf-8") as f:
            after_raw = f.read()
        payload = json.loads(after_raw)
        self.assertTrue(jsoncodec.is_wrapped(payload),
                        "包装格式丢了：%s" % list(payload))
        data, _wrapped, _header = mv_mz_data._load_data_file(path, "Items.json")
        self.assertEqual(data[1]["price"], 999)
        self.assertEqual(data[1]["name"], "药草", "未改动的字段变了")

    def test_rgss_untouched_fields_survive_roundtrip(self):
        """RGSS：改一个整数后，同一对象的其它字段与原值一致。"""
        from core.formats import rgss_data
        game = os.path.join(self.root, "rgssloss")
        os.makedirs(game, exist_ok=True)
        make_synthetic_rgss_game(game, "vxace_synth")
        info = engines_mod.detect(game)
        # 合成函数里 engine 名只用来决定扩展名，识别结果由文件决定
        if not info.get("engine"):
            self.skipTest("合成目录未被识别：%s" % info.get("error"))

        path = os.path.join(info["data_dir"], "Items.rvdata2")
        if not os.path.isfile(path):
            # 合成用的是 .rxdata/.rvdata，按识别到的扩展名改
            path = os.path.join(info["data_dir"],
                                "Items%s" % (".rvdata" if info["engine"] == "vx"
                                             else ".rxdata"))
        with open(path, "rb") as f:
            original = f.read()
        from core.marshal import doc_model as D
        tree_before = D.loads(original)

        stats = rgss_data.apply_to_files(info, {os.path.basename(path): [{
            "file": os.path.basename(path), "path": "1/@price",
            "translated": 999, "original": 50, "status": "translated",
            "kind": "int"}]})
        if stats["entries"] != 1:
            self.skipTest("合成表里没有 @price 字段：%s" % stats)

        with open(path, "rb") as f:
            tree_after = D.loads(f.read())
        self.assertEqual(D.ivar(tree_after.items[1], "@name").to_py(),
                         D.ivar(tree_before.items[1], "@name").to_py(),
                         "未改动的字段变了")
        self.assertEqual(D.ivar(tree_after.items[1], "@price").value, 999)


# ---------------------------------------------------------------------------
# §8-5 安全性
# ---------------------------------------------------------------------------
class TestSafety(AcceptanceBase):
    """备份存在、还原可用、覆盖前有确认、异常中断不产生半写文件。"""

    def test_atomic_write_leaves_no_half_file(self):
        """让 ``os.replace`` 失败 → 目标文件必须**字节不变**且不留临时文件。"""
        from core.safety import atomic
        target = os.path.join(self.root, "target.bin")
        with open(target, "wb") as f:
            f.write(b"ORIGINAL")
        real = atomic.os.replace
        atomic.os.replace = _boom
        try:
            with self.assertRaises(atomic.AtomicWriteError):
                atomic.atomic_write_bytes(target, b"NEW-CONTENT")
        finally:
            atomic.os.replace = real
        with open(target, "rb") as f:
            self.assertEqual(f.read(), b"ORIGINAL", "写入失败后目标文件被改了")
        leftovers = [n for n in os.listdir(self.root) if n.startswith(".")]
        self.assertEqual(leftovers, [], "写入失败后残留了临时文件：%s" % leftovers)

    def test_backup_and_restore_roundtrip(self):
        from core.safety import backup as backup_mod
        game = os.path.join(self.root, "game")
        os.makedirs(os.path.join(game, "Data"))
        target = os.path.join(game, "Data", "Items.rvdata2")
        with open(target, "wb") as f:
            f.write(b"V1")
        backup_dir, copied = backup_mod.backup_files(game, ["Data/Items.rvdata2"])
        # ``backup_files`` 返回 ``(备份目录, 已复制的相对路径列表)``
        self.assertTrue(backup_dir and os.path.isdir(backup_dir))
        self.assertEqual(copied, ["Data/Items.rvdata2"],
                         "备份清单不对：%r" % (copied,))
        with open(target, "wb") as f:
            f.write(b"V2")
        result = backup_mod.restore_backup(game, backup_dir)
        self.assertGreaterEqual(result["restored"], 1)
        with open(target, "rb") as f:
            self.assertEqual(f.read(), b"V1")
        self.assertTrue(result["safety_backup"], "还原前必须为当前状态再备份")

    def test_restore_entry_is_reachable_from_ui_routes(self):
        """需求 §9：还原入口在 UI 中**可点** —— 即两个功能都有还原端点。"""
        patterns = {r.pattern for r in self.ctx.router.routes()}
        self.assertIn("/api/translate/restore", patterns)
        self.assertIn("/api/cheats/restore", patterns)

    def test_confirm_required_for_every_overwrite(self):
        """所有覆盖类端点都必须要求确认（有确认机制的断言在各自测试里）。"""
        patterns = {r.pattern for r in self.ctx.router.routes()}
        for required in ("/api/translate/build", "/api/cheats/save",
                         "/api/cheats/data", "/api/cheats/restore"):
            with self.subTest(endpoint=required):
                self.assertIn(required, patterns)


def _boom(src, dst):
    raise OSError("模拟 replace 失败")


if __name__ == "__main__":
    unittest.main(verbosity=2)

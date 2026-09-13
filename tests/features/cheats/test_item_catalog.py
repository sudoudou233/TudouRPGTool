# -*- coding: utf-8 -*-
"""道具列表必须给出**整份数据表**（与参考工具一致）—— 用户报告回归。

@feature  cheats
@layer    tests
@public   TestItemCatalog
@depends  features.cheats.routes, core.formats.mv_save
@tested   (本文件即测试)
@footprint docs/STATE.md

用户报告
--------
「修改工具里面读取出来的道具内容没有 `D:\\test1\\rpgtool\\rpgmaker_cheating_tool`
全啊，只读出了人物身上自带有的道具」

对照参考工具 ``main.py:294-305`` 的 ``_refresh_inv``：

```python
counts = self.sf.read_party(0).get(kind, {})
table  = self.gd.items if kind == 'items' else (...)
for oid in sorted(table):                 # ← 遍历**整张数据表**
    name = table[oid]
    tree.insert('', 'end', values=(oid, name, counts.get(oid, 0)))   # ← 没有就显示 0
```

也就是说参考工具**列出数据表里的每一件**，没持有的显示 0 —— 这样用户才能
**添加自己还没有的道具**（改档的主要用途之一）。

我们之前只列 ``party['_items']`` 里已有的键，于是"未持有的一律看不见" ——
功能比参考工具窄。用户那个游戏：数据表 35 件，身上只有 2 件，界面上就只有 2 行。

修法：`CheatsService.catalog()` 返回整张表 + 持有数（``owned`` 标记是否持有），
``party_view()`` 同时给出 ``items``（仅持有）与 ``catalog``（整表）。
界面默认显示 catalog，并加"搜索"与"只看已持有"两个筛子
（35 件还好，几百件时没有筛子没法用）。
"""

from __future__ import annotations

import json
import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.abspath(__file__))
while not os.path.isfile(os.path.join(_ROOT, "app.py")):
    parent = os.path.dirname(_ROOT)
    if parent == _ROOT:
        raise RuntimeError("无法定位工程根（未找到 app.py）")
    _ROOT = parent
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from tests.features.cheats.test_routes import (  # noqa: E402
    CheatsTestCase, make_mv_game, make_vxace_game)


#: 数据表里的"空槽位"（有 id、没名字）。
#:
#: ⚠ **这是 N-30 的夹具**。原先的夹具只写了有名字的条目，于是
#: ``test_missing_name_placeholder_is_hidden_when_unowned`` 那条断言
#: **循环体一次都没进过** —— 名字和文档都写对了，实际什么都没验，
#: 所以"空槽位没被跳过"这个缺陷一路活到用户手里（用户报的是
#: "tot 的武器防具图标读取不对"，实际是列表里超过一半是空白占位行）。
PLACEHOLDER_IDS = (30, 31)

#: 夹具里"有名字但没图标"的那条（真实游戏里普遍存在，例如用户那个游戏的
#: ``啊啊啊啊``）—— 用来验证"有名字就一定要列出来"。
NAMED_NO_ICON_ID = 40


def _patch_items_json(directory, www=False):
    """MV：给 ``Items.json`` 补空槽位。

    ⚠ MV 侧的空槽位必须是 ``"name": ""`` 而不是**缺 name 字段**：
    ``GameDataMV._load_names`` 只在 ``isinstance(name, str)`` 时入库，
    缺字段的条目**根本到不了 catalog**（这条路走不通，也就复现不了缺陷）。
    真实游戏里两种都有，而能触发缺陷的是前者。
    """
    js_root = os.path.join(directory, "www") if www else directory
    path = os.path.join(js_root, "data", "Items.json")
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    have = {ent.get("id") for ent in payload if isinstance(ent, dict)}
    for oid in PLACEHOLDER_IDS:
        if oid not in have:
            payload.append({"id": oid, "name": "", "price": 0,
                            "consumable": True, "occasion": 0, "iconIndex": 0})
    if NAMED_NO_ICON_ID not in have:
        payload.append({"id": NAMED_NO_ICON_ID, "name": "啊啊啊啊", "price": 0,
                        "consumable": True, "occasion": 0, "iconIndex": 0})
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, ensure_ascii=False)
    return directory


def _patch_items_rvdata2(directory):
    """VX Ace：重写 ``Items.rvdata2`` 补空槽位。

    ⚠ 这里才是 N-30 **真正暴露**的地方：``GameData._load_icon_table`` 是
    **无条件** ``store[oid] = _strval(...)``，``@name`` 为 nil 时存进去的是
    空串 —— 于是空槽位真的进得了 catalog。用户那个 TOT 正是 VX Ace，
    200 个武器槽位里 122 个是空的。
    """
    from core.marshal import doc_model as D

    def sym(name):
        return D.Symbol(name.encode("utf-8"))

    def st(text):
        return D.String(text.encode("utf-8"))

    rows = [D.NilNode()]

    def item(oid, name=None, icon=None):
        ivars = [(sym("@id"), D.Fixnum(oid))]
        if name is not None:
            ivars.append((sym("@name"), st(name)))
        if icon is not None:
            ivars.append((sym("@icon_index"), D.Fixnum(icon)))
        ivars.append((sym("@price"), D.Fixnum(10)))
        rows.append(D.ObjectNode(sym("RPG::Item"), ivars))

    item(1, "药草", 1)
    item(2, "解毒草", 2)
    for oid in PLACEHOLDER_IDS:
        item(oid)                       # 只有 @id —— 真正的空槽位
    item(NAMED_NO_ICON_ID, "啊啊啊啊", 0)
    with open(os.path.join(directory, "Data", "Items.rvdata2"), "wb") as f:
        f.write(D.dumps(D.Array(rows)))
    return directory


class TestItemCatalog(CheatsTestCase):
    """整表展示 + 持有标记 + 未持有可添加。"""

    def setUp(self):
        super(TestItemCatalog, self).setUp()
        # 夹具：数据表里 2 件道具 / 1 把武器 / 1 件防具，身上只有道具 1；
        # 另外**故意**加了空槽位与"有名字但没图标"的条目 —— 没有这些，
        # 占位断言就是空转的（见 PLACEHOLDER_IDS 的说明）。
        self.directory = self.game()
        self.inject_placeholders(self.directory)
        self.opened_here()

    @staticmethod
    def inject_placeholders(directory):
        return _patch_items_json(directory)

    def opened_here(self):
        res = self.call("POST", "/api/cheats/open", dir=self.directory)
        self.assertTrue(res["ok"], res.get("error"))
        saves = self.get("/api/cheats/saves")
        self.assertTrue(saves["saves"], "夹具没有存档")
        self.save_path = saves["saves"][0]["path"]
        loaded = self.call("POST", "/api/cheats/load", path=self.save_path)
        self.assertTrue(loaded["ok"], loaded.get("error"))

    def test_catalog_lists_every_database_entry(self):
        """**核心断言**：整张数据表都要出现，未持有的 count 为 0。"""
        party = self.get("/api/cheats/party")["party"]
        catalog = party["catalog"]["items"]
        names = [r["name"] for r in catalog]
        self.assertIn("药草", names, "数据表里的道具没列出来：%s" % names)
        self.assertIn("解毒草", names, "未持有的道具也必须列出（参考工具行为）")

    def test_unowned_entries_have_zero_count(self):
        party = self.get("/api/cheats/party")["party"]
        rows = {r["id"]: r for r in party["catalog"]["items"]}
        # 夹具里 1 号持有 3 个，2 号没有
        self.assertEqual(rows[1]["count"], 3)
        self.assertTrue(rows[1]["owned"])
        self.assertEqual(rows[2]["count"], 0)
        self.assertFalse(rows[2]["owned"], "2 号没持有，owned 应当是 False")

    def test_all_three_buckets_have_catalogs(self):
        party = self.get("/api/cheats/party")["party"]
        for kind in ("items", "weapons", "armors"):
            with self.subTest(kind=kind):
                self.assertIn(kind, party["catalog"], "缺少 %s 的整表" % kind)
                self.assertTrue(party["catalog"][kind],
                                "%s 的整表是空的" % kind)

    def test_owned_only_view_is_a_subset(self):
        """``items``（仅持有）必须是 catalog 的子集，保留给快速核对。"""
        party = self.get("/api/cheats/party")["party"]
        owned_ids = {r["id"] for r in party["items"]["items"]}
        catalog_ids = {r["id"] for r in party["catalog"]["items"]}
        self.assertTrue(owned_ids <= catalog_ids)
        self.assertLess(len(owned_ids), len(catalog_ids),
                        "夹具里应当有'未持有'的条目，否则这条断言没有意义")

    def test_unowned_entry_can_be_granted(self):
        """**用户要的能力**：给一件还没有的道具，保存后真的进背包。"""
        payload = self.call("POST", "/api/cheats/party",
                            items=[{"id": 2, "count": 7}])
        self.assertTrue(payload["ok"], payload.get("error"))
        rows = {r["id"]: r for r in payload["party"]["catalog"]["items"]}
        self.assertEqual(rows[2]["count"], 7)
        self.assertTrue(rows[2]["owned"])

        saved = self.call("POST", "/api/cheats/save", confirm=True)
        self.assertTrue(saved["ok"], saved.get("error"))
        again = self.get("/api/cheats/party")["party"]
        rows = {r["id"]: r for r in again["catalog"]["items"]}
        self.assertEqual(rows[2]["count"], 7, "新加的道具没有落盘")

    def test_setting_to_zero_keeps_the_row_visible(self):
        """把数量改成 0 之后，条目仍要留在表里（只是变成"未持有"）。"""
        payload = self.call("POST", "/api/cheats/party",
                            items=[{"id": 1, "count": 0}])
        self.assertTrue(payload["ok"], payload.get("error"))
        rows = {r["id"]: r for r in payload["party"]["catalog"]["items"]}
        self.assertIn(1, rows, "数量归零后条目不该从整表里消失")
        self.assertEqual(rows[1]["count"], 0)
        self.assertFalse(rows[1]["owned"])
        # 但"仅持有"视图里应当没有了
        owned = {r["id"] for r in payload["party"]["items"]["items"]}
        self.assertNotIn(1, owned)

    def test_rows_are_sorted_by_id(self):
        party = self.get("/api/cheats/party")["party"]
        for kind in ("items", "weapons", "armors"):
            ids = [r["id"] for r in party["catalog"][kind]]
            with self.subTest(kind=kind):
                self.assertEqual(ids, sorted(ids))

    def test_catalog_carries_id_name_count_owned(self):
        party = self.get("/api/cheats/party")["party"]
        row = party["catalog"]["items"][0]
        for key in ("id", "name", "count", "owned"):
            with self.subTest(key=key):
                self.assertIn(key, row)
        self.assertIsInstance(row["owned"], bool)

    def test_missing_name_placeholder_is_hidden_when_unowned(self):
        """数据表里的"空槽位"（有 id 没名字、也没图标）不该列出来。

        列出来只会让用户以为能加一件叫 ``#35`` 的道具。真实游戏里这不是
        小数目：``ToT 1.16.2.2 CN1.0`` 的 200 个武器槽位里有 **122 个是空的**
        —— 界面上超过一半是 ``#61``/``#62``… 配空白虚线框，用户报的就是
        "图标读取的不是很对"（N-30）。

        ⚠ 这条断言**以前是空转的**：夹具里没有空槽位，循环体一次都没进过，
        所以缺陷存在时它照样绿。现在先断言"夹具里真的有"，再断言"真的被跳过"。
        """
        party = self.get("/api/cheats/party")["party"]
        catalog = party["catalog"]["items"]
        listed = {r["id"] for r in catalog}
        # 1) 夹具必须真的包含病灶，否则这条测试没有意义
        for oid in PLACEHOLDER_IDS:
            with self.subTest(placeholder=oid):
                self.assertNotIn(oid, listed,
                                 "空槽位 #%d 被列出来了" % oid)
        # 2) 反向确认夹具确实有这些 id（防止"夹具改了、断言跟着变空转"）
        store = self.service().gamedata.items
        for oid in PLACEHOLDER_IDS:
            with self.subTest(fixture=oid):
                self.assertIn(oid, store,
                              "夹具里没有 id=%d 的空槽位，这条测试退化成空转了"
                              % oid)
        # 3) 一条占位行都不该剩下
        for row in catalog:
            with self.subTest(row=row):
                if row["name"].startswith("#") and not row["count"] \
                        and not row.get("icon"):
                    self.fail("未命名、无图标、未持有的空槽位被列出来了：%s" % row)

    def test_named_entry_without_icon_is_still_listed(self):
        """有名字就该列出来，哪怕它没有图标（真实游戏里很常见）。"""
        rows = {r["id"]: r for r in
                self.get("/api/cheats/party")["party"]["catalog"]["items"]}
        self.assertIn(40, rows, "有名字但没图标的条目被当成空槽位跳过了")
        self.assertEqual(rows[40]["name"], "啊啊啊啊")
        self.assertEqual(rows[40]["icon"], 0)

    def test_entry_with_icon_but_no_name_is_kept(self):
        """没名字**但有图标**的条目要保留 —— 图标本身就是辨认线索。

        这是"跳过空槽位"的边界：判据必须是"没名字 **且** 没图标 **且** 没持有"，
        只看名字会把这类条目误杀。
        """
        directory = os.path.join(self.root, "icononly")
        os.makedirs(directory, exist_ok=True)
        make_mv_game(directory)
        js_root = directory
        path = os.path.join(js_root, "data", "Items.json")
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        payload.append({"id": 50, "iconIndex": 7})       # 只有图标，没有名字
        payload.append({"id": 51})                       # 真正的空槽位
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(payload, f, ensure_ascii=False)
        self.directory = directory
        self.opened_here()
        rows = {r["id"]: r for r in
                self.get("/api/cheats/party")["party"]["catalog"]["items"]}
        self.assertIn(50, rows, "有图标（没名字）的条目被误当成空槽位跳过了")
        self.assertEqual(rows[50]["icon"], 7)
        self.assertNotIn(51, rows, "真正的空槽位没被跳过")

    def test_hidden_slot_count_is_reported(self):
        """跳过多少**必须说出来** —— 不许静默隐藏（用户会以为工具漏读了）。"""
        stats = self.get("/api/cheats/party")["party"]["catalog_stats"]["items"]
        self.assertEqual(stats["hidden"], len(PLACEHOLDER_IDS))
        self.assertGreater(stats["rows"], 0)
        self.assertEqual(stats["has_icon"],
                         sum(1 for r in self.get("/api/cheats/party")
                             ["party"]["catalog"]["items"] if r.get("icon")))

    def test_owned_placeholder_is_still_listed(self):
        """空槽位一旦**被持有**就必须列出来（背包里的东西不能看不见）。"""
        oid = PLACEHOLDER_IDS[0]
        res = self.call("POST", "/api/cheats/party",
                        items=[{"id": oid, "count": 4}])
        self.assertTrue(res["ok"], res.get("error"))
        rows = {r["id"]: r for r in res["party"]["catalog"]["items"]}
        self.assertIn(oid, rows, "持有中的空槽位被跳过了")
        self.assertEqual(rows[oid]["count"], 4)
        self.assertEqual(res["party"]["catalog_stats"]["items"]["hidden"],
                         len(PLACEHOLDER_IDS) - 1)

    def test_inventory_entry_missing_from_database_is_shown(self):
        """存档里有、数据表里没有的 id（MOD/换过数据表）也要能看见。"""
        self.call("POST", "/api/cheats/party", items=[{"id": 9999, "count": 2}])
        party = self.get("/api/cheats/party")["party"]
        rows = {r["id"]: r for r in party["catalog"]["items"]}
        self.assertIn(9999, rows, "背包里的'孤儿'条目在界面上看不见")
        self.assertEqual(rows[9999]["count"], 2)
        self.assertTrue(rows[9999].get("orphan"))


class TestItemCatalogVXAce(TestItemCatalog):
    """同一批断言在 VX Ace（Marshal 路径）上重跑一遍。

    ⚠ 这一份才是 N-30 的**主战场**：RGSS 侧的 ``GameData`` 无条件把每个条目
    入库（``@name`` 为 nil 时存空串），所以空槽位真的会进 catalog；
    MV 侧缺 name 字段的条目在加载阶段就被丢掉了。
    """

    make_game = staticmethod(make_vxace_game)

    @staticmethod
    def inject_placeholders(directory):
        return _patch_items_rvdata2(directory)

    def test_unowned_entries_have_zero_count(self):
        party = self.get("/api/cheats/party")["party"]
        rows = {r["id"]: r for r in party["catalog"]["items"]}
        self.assertIn(1, rows)
        self.assertTrue(rows[1]["owned"])
        # VX Ace 夹具里 2 号（解毒草）没持有
        self.assertIn(2, rows)
        self.assertEqual(rows[2]["count"], 0)
        self.assertFalse(rows[2]["owned"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

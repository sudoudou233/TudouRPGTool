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


class TestItemCatalog(CheatsTestCase):
    """整表展示 + 持有标记 + 未持有可添加。"""

    def setUp(self):
        super(TestItemCatalog, self).setUp()
        # 夹具：数据表里 3 件道具 / 1 把武器 / 1 件防具，身上只有道具 1
        self.directory, self.save_path = self.opened()

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
        """数据表末尾的"占位条目"（有 id 没名字）不该列出来。

        列出来只会让用户以为能加一件叫 ``#35`` 的道具。真实游戏里很常见：
        用户那个游戏的 Items.json 第 35 条就只有 id。
        """
        party = self.get("/api/cheats/party")["party"]
        for row in party["catalog"]["items"]:
            with self.subTest(row=row):
                if row["name"].startswith("#") and not row["count"]:
                    self.fail("未命名且未持有的占位条目被列出来了：%s" % row)

    def test_inventory_entry_missing_from_database_is_shown(self):
        """存档里有、数据表里没有的 id（MOD/换过数据表）也要能看见。"""
        self.call("POST", "/api/cheats/party", items=[{"id": 9999, "count": 2}])
        party = self.get("/api/cheats/party")["party"]
        rows = {r["id"]: r for r in party["catalog"]["items"]}
        self.assertIn(9999, rows, "背包里的'孤儿'条目在界面上看不见")
        self.assertEqual(rows[9999]["count"], 2)
        self.assertTrue(rows[9999].get("orphan"))


class TestItemCatalogVXAce(TestItemCatalog):
    """同一批断言在 VX Ace（Marshal 路径）上重跑一遍。"""

    make_game = staticmethod(make_vxace_game)

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

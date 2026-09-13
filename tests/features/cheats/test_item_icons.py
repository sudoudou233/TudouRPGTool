# -*- coding: utf-8 -*-
"""道具列表里的**游戏内图标**（用户报告的新功能）。

@feature  cheats
@layer    tests
@public   TestIconLookup, TestIconInfoRoute, TestIconSheetRoute,
          TestIconCacheInvalidation
@depends  features.cheats, core.iconutil, tests.features.cheats.test_routes
@tested   (本文件即测试)
@footprint docs/FEATURES.md#cheats

用户的原话
----------
> 有些物品基本是文本乱码、编号数字、或者干脆没名字，如果在前方加入一个
> 小图标，那么找到相对应的物体会更简单

所以这里要证明的**不是**"接口返回了 icon 字段"，而是三件具体的事：

1. ``iconIndex`` 真的从数据表读出来了（MV 读 ``iconIndex``，RGSS 读 ``@icon_index``）；
2. 后端算出的切片参数与图集实际尺寸一致（``cell`` / ``columns`` / ``rows``）；
3. 返回的图集字节是**解密后的真 PNG**，且**换游戏之后立刻换成新游戏的图集**。

第 3 条是本工程反复踩到的那一类缺陷（"接口说成功、画面还是旧的"），
所以专门有一个类守着它。
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

from core import iconutil                                          # noqa: E402
from tests.features.cheats.test_routes import (                    # noqa: E402
    CheatsTestCase, make_mv_game, make_vxace_game)
from tests.unit.test_iconutil import encrypt_png, make_png         # noqa: E402

#: 夹具用的 key（16 字节十六进制）
KEY = "0f1e2d3c4b5a69788796a5b4c3d2e1f0"
#: 图集几何：16 列 × 2 行 = 32 格，故意做成"非正方形"，让行/列都不为零
COLUMNS = 16
ROWS = 2

#: 各表的图标索引 —— 刻意选"行列都不是 0"的值，写错坐标就会露馅
ICON_ITEMS = {1: 20, 2: 0}      # 20 -> 第 1 行(0基) 第 4 列；0 -> 显式无图标
ICON_WEAPONS = {1: 5}           # 5  -> 第 0 行 第 5 列
ICON_ARMORS = {1: 17}           # 17 -> 第 1 行 第 1 列


def _patch_json(path, mutate):
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    mutate(payload)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, ensure_ascii=False)


def make_mv_icon_game(root, www=False, encrypted=True, with_sheet=True,
                      key=KEY, width=512, height=64):
    """MV 游戏 + 带 ``iconIndex`` 的数据表 + （可加密的）图标图集。"""
    root = make_mv_game(root, www=www)
    js_root = os.path.join(root, "www") if www else root

    for fname, mapping in (("Items.json", ICON_ITEMS),
                           ("Weapons.json", ICON_WEAPONS),
                           ("Armors.json", ICON_ARMORS)):
        def add_icons(payload, mapping=mapping):
            for ent in payload:
                if isinstance(ent, dict) and ent.get("id") in mapping:
                    ent["iconIndex"] = mapping[ent["id"]]
        _patch_json(os.path.join(js_root, "data", fname), add_icons)

    def add_key(payload):
        payload["encryptionKey"] = key
        payload["hasEncryptedImages"] = True
    _patch_json(os.path.join(js_root, "data", "System.json"), add_key)

    if with_sheet:
        png = make_png(width, height)
        name = "IconSet.rpgmvp" if encrypted else "IconSet.png"
        payload = encrypt_png(png, key) if encrypted else png
        path = os.path.join(js_root, "img", "system", name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(payload)
    return root


def make_vxace_icon_game(root, width=384, height=48, icons=(3, 9)):
    """VX Ace 游戏 + 带 ``@icon_index`` 的道具表 + 明文图集（24px/16 列）。"""
    from core.marshal import doc_model as D

    root = make_vxace_game(root)

    def sym(name):
        return D.Symbol(name.encode("utf-8"))

    def st(text):
        return D.String(text.encode("utf-8"))

    data = os.path.join(root, "Data")
    rows = [D.NilNode()]
    for oid, icon in enumerate(icons, start=1):
        rows.append(D.ObjectNode(sym("RPG::Item"), [
            (sym("@id"), D.Fixnum(oid)),
            (sym("@name"), st("道具%d" % oid)),
            (sym("@icon_index"), D.Fixnum(icon)),
            (sym("@price"), D.Fixnum(10)),
        ]))
    with open(os.path.join(data, "Items.rvdata2"), "wb") as f:
        f.write(D.dumps(D.Array(rows)))

    path = os.path.join(root, "Graphics", "System", "IconSet.png")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(make_png(width, height))
    # 只留 VX Ace 认得的扩展名，避免 make_vxace_game 的旧 Items 干扰
    return root


class IconCase(CheatsTestCase):
    def mv_game(self, **kw):
        directory = os.path.join(self.root, "mv")
        os.makedirs(directory, exist_ok=True)
        make_mv_icon_game(directory, **kw)
        return directory

    def opened_icons(self, directory):
        res = self.call("POST", "/api/cheats/open", dir=directory)
        self.assertTrue(res["ok"], res.get("error"))
        saves = self.get("/api/cheats/saves")
        self.assertTrue(saves["saves"], "夹具没有存档：%s" % saves.get("error"))
        loaded = self.call("POST", "/api/cheats/load",
                           path=saves["saves"][0]["path"])
        self.assertTrue(loaded["ok"], loaded.get("error"))
        return saves["saves"][0]["path"]


# ---------------------------------------------------------------------------
# iconIndex 读取
# ---------------------------------------------------------------------------
class TestIconLookup(IconCase):

    def test_catalog_rows_carry_the_icon_index(self):
        self.opened_icons(self.mv_game())
        rows = {r["id"]: r for r in
                self.get("/api/cheats/party")["party"]["catalog"]["items"]}
        self.assertEqual(rows[1]["icon"], 20)
        self.assertEqual(rows[2]["icon"], 0)

    def test_weapons_and_armors_too(self):
        self.opened_icons(self.mv_game())
        catalog = self.get("/api/cheats/party")["party"]["catalog"]
        self.assertEqual(catalog["weapons"][0]["icon"], 5)
        self.assertEqual(catalog["armors"][0]["icon"], 17)

    def test_zero_and_missing_are_different(self):
        """``0`` 是"这件没图标"，``None`` 是"这个表不提供图标信息"。

        界面两者都不画图，但语义不同 —— 合并了就没法区分
        "作者没给图标"和"后端读不到图标表"。
        """
        self.opened_icons(self.mv_game())
        service = self.service()
        self.assertEqual(service.icon_of("items", 1), 20)
        self.assertEqual(service.icon_of("items", 2), 0)       # 显式 0
        self.assertIsNone(service.icon_of("items", 99))        # 表里没有
        self.assertIsNone(service.icon_of("actors", 1))        # 表本身不支持

    def test_items_bucket_also_has_icons(self):
        """``items``（当前持有）这条兼容路径也要带图标。"""
        self.opened_icons(self.mv_game())
        held = self.get("/api/cheats/party")["party"]["items"]["items"]
        self.assertTrue(held)
        self.assertEqual(held[0]["icon"], 20)

    def test_rgss_reads_icon_index_ivar(self):
        """VX Ace 的字段名是 ``@icon_index``（MV 是 ``iconIndex``）。"""
        directory = os.path.join(self.root, "vx")
        os.makedirs(directory, exist_ok=True)
        make_vxace_icon_game(directory)
        self.opened_icons(directory)
        rows = {r["id"]: r for r in
                self.get("/api/cheats/party")["party"]["catalog"]["items"]}
        self.assertEqual(rows[1]["icon"], 3)
        self.assertEqual(rows[2]["icon"], 9)

    def test_orphan_rows_have_no_icon(self):
        """存档里有、数据表里没有的 id（MOD 换过表）不给图标信息。"""
        directory = self.mv_game()
        self.opened_icons(directory)
        res = self.call("POST", "/api/cheats/party",
                        items=[{"id": 777, "count": 1}])
        self.assertTrue(res["ok"], res.get("error"))
        rows = {r["id"]: r for r in res["party"]["catalog"]["items"]}
        self.assertIn(777, rows)
        self.assertTrue(rows[777].get("orphan"))
        self.assertIsNone(rows[777]["icon"])


# ---------------------------------------------------------------------------
# icon_info
# ---------------------------------------------------------------------------
class TestIconInfoRoute(IconCase):

    def test_before_opening_a_game(self):
        icons = self.get("/api/cheats/icon_info")["icons"]
        self.assertFalse(icons["available"])
        self.assertEqual(icons["reason"], "还没有打开游戏")

    def test_reports_geometry_matching_the_real_sheet(self):
        self.opened_icons(self.mv_game())
        icons = self.get("/api/cheats/icon_info")["icons"]
        self.assertTrue(icons["available"], icons["reason"])
        self.assertEqual(icons["cell"], 32)
        self.assertEqual(icons["columns"], COLUMNS)
        self.assertEqual(icons["rows"], ROWS)
        self.assertEqual(icons["count"], COLUMNS * ROWS)
        self.assertEqual((icons["width"], icons["height"]), (512, 64))
        self.assertTrue(icons["encrypted"])

    def test_plain_sheet_is_not_marked_encrypted(self):
        self.opened_icons(self.mv_game(encrypted=False))
        icons = self.get("/api/cheats/icon_info")["icons"]
        self.assertTrue(icons["available"], icons["reason"])
        self.assertFalse(icons["encrypted"])

    def test_missing_sheet_is_explained_not_crashed(self):
        """没有图集时：接口照常返回，只是说明原因（界面据此置灰开关）。"""
        self.opened_icons(self.mv_game(with_sheet=False))
        icons = self.get("/api/cheats/icon_info")["icons"]
        self.assertFalse(icons["available"])
        self.assertIn("找不到图标图集", icons["reason"])
        # 道具列表本身**不受影响**；而 icon 索引照样给 —— 它来自数据表，
        # 与"有没有图集可切"是两件事。界面靠 available 决定画不画，
        # 不要在这里把 icon 抹成 None（那会让"表里有图标"这条信息丢失）。
        rows = self.get("/api/cheats/party")["party"]["catalog"]["items"]
        self.assertTrue(rows)
        self.assertEqual(rows[0]["icon"], 20)

    def test_rgss_cell_is_24(self):
        directory = os.path.join(self.root, "vx")
        os.makedirs(directory, exist_ok=True)
        make_vxace_icon_game(directory)
        self.opened_icons(directory)
        icons = self.get("/api/cheats/icon_info")["icons"]
        self.assertTrue(icons["available"], icons["reason"])
        self.assertEqual(icons["cell"], 24)
        self.assertEqual(icons["columns"], COLUMNS)
        self.assertEqual(icons["count"], COLUMNS * 2)

    def test_info_dict_is_json_safe(self):
        self.opened_icons(self.mv_game())
        json.dumps(self.get("/api/cheats/icon_info"))


# ---------------------------------------------------------------------------
# icon_set
# ---------------------------------------------------------------------------
class TestIconSheetRoute(IconCase):

    def test_returns_decrypted_png_bytes(self):
        """**核心断言**：拿到的必须是解密后的真 PNG，与源图逐字节相同。"""
        directory = self.mv_game()
        self.opened_icons(directory)
        res = self.get("/api/cheats/icon_set")
        self.assertEqual(res.content_type, "image/png")
        self.assertTrue(res.body.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertEqual(iconutil.png_size(res.body), (512, 64))
        # 与磁盘上那份"如果没加密会长什么样"一致
        self.assertEqual(res.body, make_png(512, 64))

    def test_plain_sheet_is_passed_through_unchanged(self):
        self.opened_icons(self.mv_game(encrypted=False))
        res = self.get("/api/cheats/icon_set")
        self.assertEqual(res.body, make_png(512, 64))

    def test_unavailable_returns_json_reason_not_a_broken_image(self):
        self.opened_icons(self.mv_game(with_sheet=False))
        res = self.get("/api/cheats/icon_set")
        self.assertIsInstance(res, dict)
        self.assertFalse(res["ok"])
        self.assertIn("找不到图标图集", res["error"])

    def test_endpoint_takes_no_path_argument(self):
        """**不引入路径穿越面**：图集位置只由当前会话推出，参数一律无效。"""
        directory = self.mv_game()
        self.opened_icons(directory)
        evil = os.path.join(self.root, "outside.png")
        with open(evil, "wb") as f:
            f.write(make_png(8, 8))
        res = self.get("/api/cheats/icon_set", path=evil)
        self.assertEqual(res.body, make_png(512, 64),
                         "端点居然接受了外部路径参数")

    def test_before_opening_a_game_is_a_json_error(self):
        res = self.get("/api/cheats/icon_set")
        self.assertIsInstance(res, dict)
        self.assertFalse(res["ok"])


# ---------------------------------------------------------------------------
# 缓存失效（本工程反复踩到的那一类）
# ---------------------------------------------------------------------------
class TestIconCacheInvalidation(IconCase):
    """换游戏后图集必须立刻换掉。

    这条如果坏了，界面会**静默地**用上一个游戏的图集去裁新游戏的
    ``iconIndex`` —— 画出来是"另一件道具的图标"，看起来还挺正常，
    只有用户自己发现"图标对不上"才可能报出来。
    """

    def test_switching_from_mv_to_vxace_switches_the_sheet(self):
        mv = self.mv_game(width=512, height=64)
        self.opened_icons(mv)
        first = self.get("/api/cheats/icon_set")
        self.assertEqual(iconutil.png_size(first.body), (512, 64))
        self.assertEqual(self.get("/api/cheats/icon_info")["icons"]["cell"], 32)

        vx_root = os.path.join(self.root, "vx")
        os.makedirs(vx_root, exist_ok=True)
        make_vxace_icon_game(vx_root, width=384, height=48)
        self.opened_icons(vx_root)

        icons = self.get("/api/cheats/icon_info")["icons"]
        self.assertEqual(icons["cell"], 24, "换游戏后 cell 还是旧值 -> 缓存没失效")
        self.assertEqual((icons["width"], icons["height"]), (384, 48))
        second = self.get("/api/cheats/icon_set")
        self.assertEqual(iconutil.png_size(second.body), (384, 48),
                         "换游戏后图集字节还是上一个游戏的")

    def test_reopening_the_same_game_refreshes_after_sheet_edit(self):
        """同一个目录里把图集换掉后再 open，也应当重新读。"""
        directory = self.mv_game(width=512, height=64)
        self.opened_icons(directory)
        self.assertEqual(self.get("/api/cheats/icon_info")["icons"]["rows"], ROWS)

        path = os.path.join(directory, "img", "system", "IconSet.rpgmvp")
        with open(path, "wb") as f:
            f.write(encrypt_png(make_png(512, 160), KEY))
        self.opened_icons(directory)
        icons = self.get("/api/cheats/icon_info")["icons"]
        self.assertEqual(icons["rows"], 5, "重新打开同一目录没有重读图集")


if __name__ == "__main__":
    unittest.main(verbosity=2)

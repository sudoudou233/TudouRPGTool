# -*- coding: utf-8 -*-
"""修改页面的**静态契约**测试（与 translate 页同一做法）。

@feature  cheats
@layer    tests
@public   TestPageContract, TestEndpointsExist, TestHygiene,
          TestDestructiveFlows
@depends  features.cheats.manifest, features.cheats.routes, ui.routes
@tested   (本文件即测试)
@footprint docs/UI_SPEC.md

为什么能只做静态检查
--------------------
本工程零第三方依赖，**没有前端测试框架**。但"改存档"这个界面最容易出的问题
恰好是静态可查的：

* 调了后端不存在的端点 → 点了没反应；
* **写回原存档漏了二次确认** → 直接违反硬约束 §4.2（而这是会毁玩家数据的）；
* 把"改内存"和"写盘"混在一起 → 用户改错了没法整体放弃；
* 写回后不展示备份路径 → 「备份在哪」说不清，还原无从下手。

后端路由表用真实的 Registry 装配取得，不维护第二份清单。
"""

from __future__ import annotations

import os
import re
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

PAGE = os.path.join(_ROOT, "ui", "web", "pages", "cheats.js")
DOM = os.path.join(_ROOT, "ui", "web", "dom.js")

#: 页面**故意**不使用的端点（写清理由，避免以后被当成遗漏）
#:
#: ``/api/cheats/detect`` 是 M1 就有的"无状态问一次"端点（返回引擎判据与
#: 数据/存档目录），页面走的是 ``/open``（它顺带记住上下文并加载名字表）。
#: 本测试的"可执行探针"用它证明路由链路活着 —— 界面不必再提供入口，
#: 否则会出现两个做同一件事的按钮。
NOT_YET_USED = {
    "/api/cheats/detect": "无状态识别端点；页面用 /open。/api/health 的探针会调它",
}


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


class TestPageContract(unittest.TestCase):
    """页面模块必须满足 `docs/UI_SPEC.md` §4 的契约。"""

    @classmethod
    def setUpClass(cls):
        cls.source = read(PAGE)

    def test_file_exists(self):
        self.assertTrue(os.path.isfile(PAGE))

    def test_exports_render(self):
        self.assertRegex(self.source, r"export\s+async\s+function\s+render\s*\(",
                         "页面必须导出 async render(host)")

    def test_imports_only_from_dom_js(self):
        imports = re.findall(r"from\s+'([^']+)'", self.source)
        self.assertEqual(imports, ["/dom.js"],
                         "页面只能 import /dom.js，实际：%s" % imports)

    def test_imported_symbols_all_exist_in_dom_js(self):
        """import 的每个符号都必须在 dom.js 里真的导出。

        少了会变成 ``undefined``，浏览器只在点到那一行时才报
        "xxx is not a function"。
        """
        block = re.search(r"import\s*\{([^}]*)\}\s*from\s*'/dom\.js'", self.source)
        self.assertIsNotNone(block, "未找到对 /dom.js 的具名 import")
        names = [n.strip() for n in block.group(1).split(",") if n.strip()]
        dom = read(DOM)
        exported = set(re.findall(r"export\s+(?:async\s+)?function\s+(\w+)", dom))
        exported |= set(re.findall(r"export\s+const\s+(\w+)", dom))
        self.assertEqual([n for n in names if n not in exported], [],
                         "dom.js 未导出这些符号：%s" % names)

    def test_no_inline_colour_values(self):
        offenders = []
        for pattern in (r"#[0-9a-fA-F]{3,8}\b", r"\brgba?\s*\(", r"\bhsla?\s*\("):
            offenders.extend(re.findall(pattern, self.source))
        self.assertEqual(offenders, [], "页面出现硬编码颜色：%s" % offenders)

    def test_documented_in_ui_spec(self):
        spec = read(os.path.join(_ROOT, "docs", "UI_SPEC.md"))
        self.assertIn("pages/cheats.js", spec)


class TestEndpointsExist(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = read(PAGE)
        cls.called = {p.rstrip("/") for p in
                      re.findall(r"['\"`](/api/[A-Za-z0-9_/\-]*)", cls.source)
                      if p.startswith("/api/")}

        from core import registry as registry_mod
        from core.context import AppContext, Router
        from ui import routes as ui_routes
        reg = registry_mod.Registry().discover()
        ctx = AppContext(router=Router())
        ui_routes.register_core_routes(ctx)
        reg.register_all(ctx)
        cls.patterns = {r.pattern for r in ctx.router.routes()}

    def test_page_calls_the_whole_flow(self):
        for required in ("/api/cheats/open", "/api/cheats/saves",
                         "/api/cheats/load", "/api/cheats/party",
                         "/api/cheats/actors", "/api/cheats/vars",
                         "/api/cheats/save", "/api/cheats/data",
                         "/api/cheats/backups", "/api/cheats/restore"):
            with self.subTest(endpoint=required):
                self.assertIn(required, self.called,
                              "页面没有调用 %s —— 功能链路不完整" % required)

    def test_every_called_endpoint_exists(self):
        missing = sorted(p for p in self.called if p not in self.patterns)
        self.assertEqual(missing, [],
                         "页面调用了后端不存在的端点：%s" % missing)

    def test_every_feature_endpoint_is_used(self):
        """反向：后端提供的修改端点都应该有界面入口（死接口要报出来）。"""
        feature = {p for p in self.patterns if p.startswith("/api/cheats/")}
        unused = sorted(feature - self.called - set(NOT_YET_USED))
        self.assertEqual(unused, [],
                         "以下修改端点没有任何界面入口（死接口）：%s" % unused)
        for pattern in NOT_YET_USED:
            with self.subTest(excused=pattern):
                self.assertIn(pattern, feature,
                              "NOT_YET_USED 里的端点已不存在，请从豁免表删掉")

    def test_no_self_written_polling(self):
        self.assertNotIn("setInterval(", self.source,
                         "自己写轮询会绕过 dom.js 的超时与任务丢失容忍（B-23）")


class TestHygiene(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = read(PAGE)

    def test_no_console_log_leftovers(self):
        self.assertEqual(re.findall(r"console\.(?:log|debug)\(", self.source), [],
                         "页面里残留了调试输出")

    def test_no_todo_markers(self):
        self.assertEqual(re.findall(r"\b(?:TODO|FIXME|XXX)\b", self.source), [],
                         "页面里残留了未完成标记")

    def test_no_duplicate_top_level_function_names(self):
        names = re.findall(r"(?m)^(?:async\s+)?function\s+(\w+)", self.source)
        self.assertEqual(len(names), len(set(names)),
                         "存在同名函数（后者会覆盖前者）：%s" % names)

    def test_no_skeleton_leftovers(self):
        """M1 骨架的措辞不能留在页面上（用户会以为功能没做）。"""
        for phrase in ("后续里程碑将在此接入", "M3b：读档"):
            with self.subTest(phrase=phrase):
                self.assertNotIn(phrase, self.source)


class TestDestructiveFlows(unittest.TestCase):
    """硬约束的可静态检查部分 —— 改存档这件事上最要紧的一组。"""

    @classmethod
    def setUpClass(cls):
        cls.source = read(PAGE)

    @classmethod
    def enclosing_function(cls, marker):
        """取包含 ``marker`` 的那个函数体的源码。

        为什么要按函数取而不是按"前面 N 个字符"取：破坏性操作分布在几个
        函数里（``saveCurrent`` / ``writeData`` / ``restoreBackup``），
        用固定窗口会漏（代码一长就取不到 ``confirmDialog``，或者把**别的**
        函数的确认对话框当成本函数的）。按函数边界切就没有这个问题。
        """
        idx = cls.source.find(marker)
        assert idx > 0, "找不到标记：%s" % marker
        # 往前找最近的函数定义行
        starts = [m.start() for m in
                  re.finditer(r"(?m)^(?:async\s+)?function\s+\w+", cls.source)]
        begin = max([s for s in starts if s < idx] or [0])
        ends = [s for s in starts if s > idx]
        end = min(ends) if ends else len(cls.source)
        return cls.source[begin:end]

    def test_save_requires_confirm_dialog(self):
        """写回原存档前必须二次确认，并把确认结果传给后端 ``confirm``。"""
        body = self.enclosing_function("'/api/cheats/save'")
        self.assertIn("confirmDialog(", body,
                      "保存存档前没有二次确认（违反硬约束 §4.2）")
        self.assertIn("confirm: true", body,
                      "二次确认的结果没有传给后端 confirm 参数")

    def test_restore_requires_confirm_dialog(self):
        body = self.enclosing_function("'/api/cheats/restore'")
        self.assertIn("confirmDialog(", body, "还原前没有二次确认")
        self.assertIn("confirm: true", body)

    def test_data_write_requires_confirm_dialog(self):
        """改游戏数据表同样要先确认，并列出会改哪些文件。

        ⚠ 标记要带上 ``postJSON``：``/api/cheats/data`` 在页面里出现两次
        （GET 读字段、POST 写回），只按路径找会定位到**读**那一处，
        于是断言在错误的函数里找 ``confirmDialog``。
        """
        body = self.enclosing_function("postJSON('/api/cheats/data'")
        self.assertIn("confirmDialog(", body, "写回数据表前没有二次确认")
        self.assertIn("confirm: true", body)

    def test_edits_are_collected_before_writing(self):
        """**"先改内存、再统一保存"**：页面必须区分"应用"与"保存"两种操作。

        原工具每改一项就立刻写盘；M3b 改成两段式（备份只做一次，
        也能整体放弃）。这条断言守住这个交互形态不被改回去。
        """
        self.assertIn("collectDataEdits", self.source)
        self.assertIn("放弃改动", self.source)
        self.assertIn("未保存的改动", self.source)

    def test_backup_path_is_shown_after_save(self):
        self.assertIn("backup_dir", self.source)
        self.assertIn("备份", self.source)
        self.assertIn("ch-backups", self.source)

    def test_lists_every_save_dir_warning(self):
        """原工具有"发现多套存档要提醒"的行为，迁移时不能丢。"""
        body = self.enclosing_function("'/api/cheats/saves'")
        self.assertIn("s.dir", body, "没有按存档目录分组")
        self.assertIn("warn-text", body,
                      "发现多个存档目录时没有提醒用户（原行为，迁移对照表 B-31）")


if __name__ == "__main__":
    unittest.main(verbosity=2)

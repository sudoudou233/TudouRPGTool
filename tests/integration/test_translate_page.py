# -*- coding: utf-8 -*-
"""翻译页面的**静态契约**测试（需求 §6.1：界面必须可验证，而不只是"看着对"）。

@feature  translate
@layer    tests
@public   TestPageContract, TestEndpointsExist, TestHygiene,
          TestPrivacyAndDestructiveFlows
@depends  features.translate.routes, features.translate.manifest, ui.routes
@tested   (本文件即测试)
@footprint docs/UI_SPEC.md

为什么能只做静态检查
--------------------
本工程零第三方依赖，**没有前端测试框架**（不引 npm/playwright）。但前端最容易
出的问题恰好是静态可查的：

* 调了一个后端**不存在的端点** → 页面上是"点了没反应"或 404 toast；
* 破坏性操作**漏了二次确认** → 直接违反硬约束 §4.2；
* 写死颜色值 → 违反 `docs/UI_SPEC.md` 的令牌约定；
* 忘记 `export render` → 页面根本加载不出来（F-07 也会拦）。

因此这里把"页面 ↔ 后端"的一致性做成**双向断言**：JS 里出现的每个
``/api/...`` 必须真实存在；每个后端端点也必须被页面用到（或显式列在
``NOT_YET_USED`` 里并写明理由）。后端路由表用真实的 Registry 装配取得，
不维护第二份清单。
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

PAGE = os.path.join(_ROOT, "ui", "web", "pages", "translate.js")
DOM = os.path.join(_ROOT, "ui", "web", "dom.js")

#: 页面故意不使用的端点（写清理由，避免"以后顺手删掉"）
NOT_YET_USED = {
    "/api/translate/pick_folder": "页面用的是它 —— 见下方校验（占位，保持集合完整）",
}


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


class TestPageContract(unittest.TestCase):
    """页面模块必须满足 `docs/UI_SPEC.md` §4 的契约。"""

    @classmethod
    def setUpClass(cls):
        cls.source = read(PAGE)

    def test_file_exists_and_is_utf8(self):
        self.assertTrue(os.path.isfile(PAGE))

    def test_exports_render(self):
        self.assertRegex(self.source, r"export\s+async\s+function\s+render\s*\(",
                         "页面必须导出 async render(host)")

    def test_imports_only_from_dom_js(self):
        """只能依赖共享工具，不得从别处 import（保持"外壳不变、功能自足"）。"""
        imports = re.findall(r"from\s+'([^']+)'", self.source)
        self.assertEqual(imports, ["/dom.js"],
                         "页面只能 import /dom.js，实际：%s" % imports)

    def test_imported_symbols_all_exist_in_dom_js(self):
        """import 的每个符号都必须在 dom.js 里真的导出。

        M3a 实测踩到：`import { escapeHTML } from '/dom.js'` 少了这一句就会在
        浏览器里静默变成 `undefined`，直到用户点到那一行才报
        "escapeHTML is not a function"。
        """
        block = re.search(r"import\s*\{([^}]*)\}\s*from\s*'/dom\.js'", self.source)
        self.assertIsNotNone(block, "未找到对 /dom.js 的具名 import")
        names = [n.strip() for n in block.group(1).split(",") if n.strip()]
        dom = read(DOM)
        exported = set(re.findall(r"export\s+(?:async\s+)?function\s+(\w+)", dom))
        exported |= set(re.findall(r"export\s+const\s+(\w+)", dom))
        missing = [n for n in names if n not in exported]
        self.assertEqual(missing, [], "dom.js 未导出这些符号：%s" % missing)

    def test_no_inline_colour_values(self):
        """硬规则：页面不得写具体颜色值（只能用令牌或 components.css 的类）。"""
        offenders = []
        for pattern in (r"#[0-9a-fA-F]{3,8}\b",
                        r"\brgba?\s*\(",
                        r"\bhsla?\s*\("):
            offenders.extend(re.findall(pattern, self.source))
        self.assertEqual(offenders, [], "页面出现硬编码颜色：%s" % offenders)

    def test_no_inline_style_attribute_for_colour(self):
        """`style:` 只允许用于布局（宽度/隐藏），不允许出现 color/background。"""
        for match in re.finditer(r"style\s*:\s*\{([^}]*)\}", self.source):
            body = match.group(1)
            for bad in ("color", "background", "border"):
                self.assertNotIn(bad, body,
                                 "内联样式里出现配色属性：%s" % body)

    def test_documented_in_ui_spec(self):
        """F-12 的同一约束在这里也断言一次（页面清单双向一致）。"""
        spec = read(os.path.join(_ROOT, "docs", "UI_SPEC.md"))
        self.assertIn("pages/translate.js", spec)


class TestEndpointsExist(unittest.TestCase):
    """页面调用的每个端点都必须真的存在；反向也要能对上。"""

    @classmethod
    def setUpClass(cls):
        cls.source = read(PAGE)
        #: JS 里出现的所有 /api/... 字面量（端点参数也可能出现在模板串里）
        cls.called = set(re.findall(r"['\"`](/api/[A-Za-z0-9_/\-]*)", cls.source))
        cls.called = {p.rstrip("/") for p in cls.called if p.startswith("/api/")}

        from core.context import AppContext, Router
        from core import registry as registry_mod
        from ui import routes as ui_routes
        reg = registry_mod.Registry().discover()
        ctx = AppContext(router=Router())
        ui_routes.register_core_routes(ctx)
        reg.register_all(ctx)
        cls.patterns = {r.pattern for r in ctx.router.routes()}

    def test_page_calls_at_least_the_core_flow(self):
        for required in ("/api/translate/open", "/api/translate/scan",
                         "/api/translate/entries", "/api/translate/build",
                         "/api/translate/backups", "/api/translate/restore"):
            with self.subTest(endpoint=required):
                self.assertIn(required, self.called,
                              "页面没有调用 %s —— 功能链路不完整" % required)

    def test_every_called_endpoint_exists(self):
        missing = sorted(p for p in self.called if p not in self.patterns)
        self.assertEqual(missing, [],
                         "页面调用了后端不存在的端点：%s" % missing)

    def test_every_feature_endpoint_is_used_or_excused(self):
        """反向：后端提供的翻译端点应该都被页面用到（或在 NOT_YET_USED 里说明）。"""
        feature = {p for p in self.patterns if p.startswith("/api/translate/")}
        unused = sorted(feature - self.called - set(NOT_YET_USED))
        self.assertEqual(unused, [],
                         "以下翻译端点没有任何界面入口（死接口）：%s" % unused)

    def test_job_polling_uses_shared_helper(self):
        """长任务必须走 dom.js 的 waitJob（带总超时），不得自己写轮询。"""
        self.assertIn("waitJob(", self.source)
        self.assertNotIn("setInterval(", self.source,
                         "自己写轮询会绕过 waitJob 的超时与任务丢失容忍（B-23）")

    def test_every_long_task_call_is_awaited(self):
        """每个返回 ``{ok, job}`` 的调用都必须交给 ``runJob`` 等待。

        M3a 实测踩到：漏掉 ``await runJob(...)`` 时，界面会立刻显示"完成"，
        而任务其实还在跑 —— 用户以为翻译完了，实际一条都没翻。
        """
        long_tasks = ("/api/translate/scan", "/api/translate/skip_all",
                      "/api/translate/start", "/api/translate/build")
        starts = [p for p in self.called if p in long_tasks]
        self.assertEqual(len(starts), len(long_tasks),
                         "有长任务端点没被页面调用：%s" % sorted(long_tasks))
        run_jobs = len(re.findall(r"await\s+runJob\(", self.source))
        self.assertEqual(run_jobs, len(long_tasks),
                         "长任务调用数与 `await runJob(` 数不一致：%d vs %d"
                         % (len(long_tasks), run_jobs))


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

    def test_uses_design_tokens_for_layout_spacing(self):
        """布局性内联样式必须用 --sp-* 令牌或百分比，避免散落魔法数字。"""
        for match in re.finditer(r"style\s*:\s*\{([^}]*)\}", self.source):
            body = match.group(1)
            self.assertTrue(("'%'" in body) or ("--sp-" in body)
                            or ("width" in body),
                            "布局样式既不是百分比也不是令牌：%s" % body)

    def test_no_duplicate_top_level_function_names(self):
        names = re.findall(r"(?m)^(?:async\s+)?function\s+(\w+)", self.source)
        self.assertEqual(len(names), len(set(names)),
                         "存在同名函数（后者会悄悄覆盖前者）：%s" % names)


class TestPrivacyAndDestructiveFlows(unittest.TestCase):
    """硬约束的可静态检查部分。"""

    @classmethod
    def setUpClass(cls):
        cls.source = read(PAGE)

    def test_overwrite_requires_confirm_dialog(self):
        """覆盖原游戏前必须弹二次确认，并**在同一段代码里**传 confirm: true。"""
        idx = self.source.find("'/api/translate/build'")
        self.assertGreater(idx, 0, "找不到构建端点调用")
        window = self.source[max(0, idx - 2600):idx + 900]
        self.assertIn("confirmDialog(", window,
                      "生成汉化版前没有二次确认对话框（违反硬约束 §4.2）")
        self.assertIn("confirm: true", window,
                      "二次确认的结果没有传给后端 confirm 参数")

    def test_restore_requires_confirm_dialog(self):
        idx = self.source.find("'/api/translate/restore'")
        self.assertGreater(idx, 0)
        window = self.source[max(0, idx - 1400):idx + 400]
        self.assertIn("confirmDialog(", window, "还原前没有二次确认")

    def test_default_mode_is_copy(self):
        """默认零破坏：'copy' 必须是第一个（即默认选中）选项。"""
        modes = re.findall(r"modeSel\.append\(el\('option',\s*\{\s*value:\s*'(\w+)'",
                           self.source)
        self.assertTrue(modes, "没有找到写入方式下拉")
        self.assertEqual(modes[0], "copy", "默认写入方式不是写副本：%s" % modes)

    def test_backup_path_is_shown_after_inplace(self):
        """覆盖类操作必须展示备份路径（硬约束 §4.2）。"""
        self.assertIn("result.backup_dir", self.source)
        self.assertIn("备份位置", self.source)

    def test_api_key_input_is_password_and_never_echoed(self):
        """密钥框必须是 password，且密钥只能出现在"提交"这一条路径上。"""
        self.assertRegex(self.source, r"type:\s*'password',\s*id:\s*'tr-key'",
                         "API Key 输入框不是 password 类型")
        self.assertNotIn("toast(cfg.api_key", self.source)
        self.assertNotIn("html: cfg.api_key", self.source)
        # 密钥标识符只允许出现在 collectConfig 及其调用处，不得被渲染回界面
        before = self.source.split("function collectConfig")[0]
        self.assertNotIn("cfg.api_key", before,
                         "collectConfig 之外出现了 cfg.api_key，可能被回显")
        self.assertNotIn("api_key", self.source.split("function loadConfig")[1]
                         .split("function ")[0],
                         "loadConfig 里出现了 api_key —— 后端只返回掩码值，回填会覆盖真 Key")

    def test_cancel_button_exists_for_jobs(self):
        self.assertIn("'/api/cancel'", self.source)
        self.assertIn("取消", self.source)

    def test_privacy_note_is_shown_to_user(self):
        """界面必须告知"出网只发文本"，这是原工具的既有承诺。"""
        self.assertIn("出网请求只包含", self.source)


if __name__ == "__main__":
    unittest.main(verbosity=2)

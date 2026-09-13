# -*- coding: utf-8 -*-
"""UI 统一性契约（需求 §8-8）：全部页面共用同一套令牌与组件，无孤立样式。

@feature  none
@layer    tests
@public   TestSharedComponents, TestNoIsolatedStyles, TestResponsiveness,
          TestInteractionParadigm
@depends  ui/web/{components,tokens}.css, ui/web/pages/*.js
@tested   (本文件即测试)
@footprint docs/UI_SPEC.md

需求 §8-8 原文
--------------
「**UI**：全部页面共用同一套令牌与组件，无孤立样式；常见窗口尺寸下无布局错乱。」

前两句可以**机械地**验证，而且这正是"孤立样式"最容易溜进来的地方：
某个页面顺手写了个 ``class: 'my-special-box'``，样式没定义 → 悄悄不生效或
继承到奇怪的值；或者顺手写了个 ``#3b82f6`` → 换主题时漏改。

后一句（布局不错乱）没法在无浏览器的 CI 里量像素，但它的**成因**是可查的：
固定像素宽度、缺少 ``flex-wrap``、模态框没有 ``max-width``。
因此本文件断言这些成因，并在 ``docs/UI_SPEC.md`` §7 保留人工走查清单。

为什么用"扫描源码"而不是跑浏览器
--------------------------------
本工程零第三方依赖（不引 npm / playwright），而且页面是**无构建**的原生
ES 模块 —— 源码里的 ``class:`` 与 ``el(...)`` 就是最终 DOM 的构造过程，
扫描它得到的结论与运行时一致。
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

WEB = os.path.join(_ROOT, "ui", "web")
PAGES = os.path.join(WEB, "pages")

#: 允许的"非组件库"类名：纯布局辅助或由 dom.js 动态加的状态类
ALLOWED_EXTRA = {
    "toast",        # #toast .toast（由 dom.js 的 toast() 生成）
    "modal-mask",   # 由 dom.js 的 modal() 生成（components.css 里已定义）
}


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def page_files():
    return sorted(os.path.join(PAGES, n) for n in os.listdir(PAGES)
                  if n.endswith(".js"))


def classes_used(source):
    """收集页面源码里出现的所有 CSS 类名。"""
    used = set()
    for match in re.finditer(r"class:\s*'([^']*)'", source):
        used.update(match.group(1).split())
    for match in re.finditer(r"class:\s*`([^`]*)`", source):
        # 模板串里的类名（可能含插值），只取静态片段
        for token in re.split(r"\$\{[^}]*\}", match.group(1)):
            used.update(token.split())
    for match in re.finditer(r'class="([^"]+)"', source):
        used.update(match.group(1).split())
    return {c for c in used if c and not c.startswith("$")}


def classes_defined():
    """``components.css`` 与 ``tokens.css`` 里定义的类名。"""
    defined = set()
    for name in ("components.css", "tokens.css"):
        css = read(os.path.join(WEB, name))
        defined.update(re.findall(r"\.([a-zA-Z][\w-]*)", css))
    return defined


class TestSharedComponents(unittest.TestCase):
    """页面只能使用共享组件库里的类。"""

    def test_every_class_used_is_defined(self):
        defined = classes_defined() | ALLOWED_EXTRA
        offenders = {}
        for path in page_files():
            used = classes_used(read(path))
            unknown = sorted(c for c in used if c not in defined)
            if unknown:
                offenders[os.path.basename(path)] = unknown
        self.assertEqual(offenders, {},
                         "以下页面用了组件库里没有的类（孤立样式）：%s" % offenders)

    def test_no_page_defines_its_own_style_block(self):
        """页面不得自带样式（否则就是"孤立样式"）。"""
        for path in page_files():
            source = read(path)
            with self.subTest(page=os.path.basename(path)):
                self.assertNotIn("<style", source)
                self.assertNotIn("insertRule", source)
                self.assertNotIn("createElement('style')", source.replace('"', "'"))

    def test_components_css_is_the_only_component_source(self):
        """页面样式只能来自 components.css（tokens.css 只放变量）。"""
        tokens = read(os.path.join(WEB, "tokens.css"))
        # tokens.css 里不应该有类选择器（只应有 :root 变量与少量基础规则）
        class_rules = re.findall(r"(?m)^\s*\.([a-zA-Z][\w-]*)\s*\{", tokens)
        self.assertEqual(class_rules, [],
                         "tokens.css 里出现了类选择器（应只放令牌）：%s" % class_rules)


class TestNoIsolatedStyles(unittest.TestCase):
    """没有硬编码颜色、没有魔法数值。"""

    def test_no_hardcoded_colours_in_pages(self):
        offenders = {}
        for path in page_files():
            source = read(path)
            hits = []
            for pattern in (r"#[0-9a-fA-F]{3,8}\b", r"\brgba?\s*\(",
                            r"\bhsla?\s*\("):
                hits.extend(re.findall(pattern, source))
            if hits:
                offenders[os.path.basename(path)] = hits
        self.assertEqual(offenders, {}, "页面里有硬编码颜色：%s" % offenders)

    def test_no_hardcoded_colours_outside_tokens(self):
        """除 tokens.css 外，任何样式文件都不得硬编码颜色。"""
        for name in ("components.css",):
            source = read(os.path.join(WEB, name))
            hits = re.findall(r"#[0-9a-fA-F]{3,8}\b", source)
            self.assertEqual(hits, [],
                             "%s 里出现硬编码色值（应使用令牌）：%s" % (name, hits))

    def test_inline_styles_do_not_carry_colour(self):
        for path in page_files():
            source = read(path)
            for match in re.finditer(r"style\s*:\s*\{([^}]*)\}", source):
                body = match.group(1)
                with self.subTest(page=os.path.basename(path), body=body.strip()):
                    for bad in ("color", "background", "border"):
                        self.assertNotIn(bad, body,
                                         "内联样式里出现配色属性：%s" % body)

    def test_every_token_used_is_defined(self):
        """页面/组件里引用的 ``var(--x)`` 必须在 tokens.css 里定义。"""
        tokens = read(os.path.join(WEB, "tokens.css"))
        defined = set(re.findall(r"(--[\w-]+)\s*:", tokens))
        # 允许的浏览器内建/继承变量白名单
        allowed = {"--x", "--y"}
        for name in ("components.css", "index.html"):
            source = read(os.path.join(WEB, name))
            used = set(re.findall(r"var\((--[\w-]+)", source))
            unknown = sorted(used - defined - allowed)
            with self.subTest(file=name):
                self.assertEqual(unknown, [],
                                 "%s 引用了未定义的令牌：%s" % (name, unknown))


class TestResponsiveness(unittest.TestCase):
    """常见窗口尺寸下无布局错乱的**成因**检查。

    像素级验证需要浏览器（本工程不引），但"会不会错乱"主要由这几条决定：
    固定像素宽度、栅格是否自适应、模态框是否有上限、表格是否可滚。
    """

    @classmethod
    def setUpClass(cls):
        cls.css = read(os.path.join(WEB, "components.css"))
        cls.tokens = read(os.path.join(WEB, "tokens.css"))

    def test_content_has_max_width(self):
        self.assertIn("--content-max", self.tokens)
        self.assertIn("max-width: var(--content-max)", self.css)

    def test_grid_is_auto_fit(self):
        """栅格必须自适应（固定列数在窄窗口会溢出）。"""
        self.assertIn("auto-fit", self.css)
        self.assertIn("minmax(", self.css)

    def test_rows_wrap(self):
        self.assertIn("flex-wrap: wrap", self.css,
                      ".row 不换行的话窄窗口会横向溢出")

    def test_tables_scroll(self):
        self.assertIn(".table-wrap", self.css)
        self.assertIn("overflow: auto", self.css)
        self.assertIn("max-height", self.css)

    def test_modal_has_viewport_cap(self):
        self.assertIn("max-width: min(", self.css,
                      "模态框没有视口上限，小窗口会溢出")

    #: 有意写死尺寸的小控件（图标/徽标/数字输入框/开关），不算"容器"。
    #:
    #: 判据不是"哪个文件"而是"它会不会随内容变宽"：这些都只有几十像素、
    #: 内部不装可变长文本，所以窄窗口下不会溢出。新增的 `.switch`
    #: （"显示图标"小开关，34x18）属于同一类，故一并豁免。
    FIXED_SIZE_OK = (".step", "input[type=number]", "input[type=text]",
                     ".progress", ".btn", ".tag", ".chip", ".modal",
                     ".switch", ".icon-cell")

    def test_no_fixed_pixel_width_on_containers(self):
        """除小控件与输入框外，不应对**容器**写死宽度。"""
        offenders = []
        for match in re.finditer(r"(?m)^([.#][\w-]+[^{]*)\{([^}]*)\}", self.css):
            selector, body = match.group(1), match.group(2)
            if "width" not in body or "%" in body or "max-width" in body:
                continue
            if "min-width" in body:
                continue
            if any(ok in selector for ok in self.FIXED_SIZE_OK):
                continue
            for line in body.splitlines():
                if re.search(r"\bwidth:\s*\d+px", line):
                    offenders.append("%s { %s }" % (selector.strip(),
                                                    line.strip()))
        self.assertEqual(offenders, [],
                         "容器写死了像素宽度（窄窗口会溢出）：%s" % offenders)


class TestInteractionParadigm(unittest.TestCase):
    """交互范式（docs/UI_SPEC.md §5）在全站一致。"""

    def test_every_page_wraps_content_in_cards(self):
        for path in page_files():
            source = read(path)
            with self.subTest(page=os.path.basename(path)):
                self.assertIn("class: 'card'", source,
                              "页面没有用 .card 分组内容")

    def test_every_page_starts_with_a_card_sub(self):
        """每个页面的首张卡片都要有 .card-sub 说明（用户不知道这是什么功能）。"""
        for path in page_files():
            source = read(path)
            with self.subTest(page=os.path.basename(path)):
                self.assertIn("card-sub", source)

    def test_long_tasks_use_the_shared_job_ui(self):
        """有长任务的页面必须用 dom.js 的 waitJob（带总超时）。"""
        with_jobs = []
        for path in page_files():
            source = read(path)
            if "/api/job" in source or "waitJob(" in source:
                with_jobs.append(os.path.basename(path))
                with self.subTest(page=os.path.basename(path)):
                    self.assertIn("waitJob(", source)
                    self.assertNotIn("setInterval(", source)
        self.assertTrue(with_jobs, "没有任何页面使用任务轮询？")

    def test_destructive_actions_use_danger_button(self):
        """破坏性操作的按钮要用 .btn.danger（视觉标记，§5-4）。"""
        marks = 0
        for path in page_files():
            source = read(path)
            for match in re.finditer(r"class:\s*'btn[^']*danger[^']*'", source):
                marks += 1
        self.assertGreaterEqual(marks, 3,
                                "破坏性按钮的 .btn.danger 标记太少（现 %d 处）"
                                % marks)

    def test_error_messages_are_chinese(self):
        """面向用户的错误必须是中文句子（§5-6）。"""
        for path in page_files():
            source = read(path)
            with self.subTest(page=os.path.basename(path)):
                # 每个 toast(..., 'error') 的第一个参数里应当有中文字符
                for match in re.finditer(r"toast\(\s*'([^']*)'\s*,\s*'error'",
                                         source):
                    self.assertRegex(match.group(1), r"[\u4e00-\u9fff]",
                                     "错误提示不是中文：%s" % match.group(1))


if __name__ == "__main__":
    unittest.main(verbosity=2)

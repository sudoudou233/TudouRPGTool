# -*- coding: utf-8 -*-
"""前端**真的能跑起来**的断言（需求 §8-1 / §8-8）。

@feature  none
@layer    tests
@public   TestWebSyntax, TestWebProbe, TestNoCommentTruncation
@depends  ui/web/*.js, tools/web_probe.mjs, app.py
@tested   (本文件即测试)
@footprint docs/UI_SPEC.md

为什么要有这个文件（**一次真实的白屏事故**）
--------------------------------------------
用户双击 `启动.bat` 后，浏览器里**永远停在「加载中…」，没有任何可交互内容**。

根因：`ui/web/app.js` 的块注释里出现了「星号紧跟斜杠」这个两字符序列 ——
来源是一句通配路径 `features/*` 与 `/manifest.py` 被写在了一起：

    *   1. 启动时 GET /api/nav 取导航 —— 后端由 features/*/manifest.py 自动发现

其中的星号 + 斜杠**在块注释内部提前闭合了注释**，后面的中文散文就变成了
代码 → `app.js` 解析失败 → 一行都不执行 → 导航、功能表、页面全都不渲染。

**为什么 800+ 测试都没抓到**：它们全是**文本断言**——
"文件里有 `export render`"、"调用了某个端点"、"类名都在 components.css 里"。
没有任何一条**真的解析或执行**过这些 js。文本对 ≠ 语法对。

本文件补上这一层，两道防线：

1. **静态语法**：对 `ui/web/**/*.js` 逐个跑 ``node --check``（纯语法，不执行）。
   成本极低，能抓住一切解析错误 —— 包括本文件 §TestNoCommentTruncation
   描述的那一类。
2. **真实执行**：`tools/web_probe.mjs` 在 Node 里用最小 DOM shim 真实加载并
   执行 `index.html` + `app.js`，打真实接口，逐个切换三个功能页，
   报告"页面是否从加载中变成了有内容的卡片"。

**Node 是可选的**：本工程的主体约束是"零第三方依赖（Python 标准库）"，
Node 只用于这层前端冒烟，不是运行必需 —— 没装 Node 时本文件整类 skip，
而不是失败。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
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
PROBE = os.path.join(_ROOT, "tools", "web_probe.mjs")

#: 前端 js 文件（页面 + 外壳）
def web_js_files():
    out = []
    for base, dirs, files in os.walk(WEB):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for name in sorted(files):
            if name.endswith(".js"):
                out.append(os.path.join(base, name))
    return sorted(out)


def node_exe():
    """找一个可用的 Node；没有返回 None（本文件整类 skip）。"""
    return shutil.which("node") or shutil.which("node.exe")


def _parse_position(text):
    """``'-128px -32px'`` -> ``(-128, -32)``（供图标 sprite 坐标断言用）。"""
    parts = str(text).split()
    if len(parts) != 2:
        raise AssertionError("backgroundPosition 形状不对：%r" % text)
    return tuple(int(p[:-2] if p.endswith("px") else p) for p in parts)


def comment_truncations(source):
    """返回"块注释里出现通配路径拼接"的位置（行号, 命中片段）。

    判据：块注释内部出现了「星号 + 斜杠 + 词」—— 也就是 ``*/x`` 形态。
    它会**在注释内部提前闭合注释**，后面的散文就变成代码。

    为什么不用 ``node --check`` 覆盖这一条：``--check`` 只告诉你"某行有语法
    错误"，不告诉你"是注释被提前闭合了"。分开断言，失败信息才能直接指出
    该改哪儿（实测：白屏那次 ``--check`` 报的是第 12 行"Unexpected identifier"，
    看起来像中文的问题，其实是注释在第 12 行被截断了）。
    """
    hits = []
    for match in _WILDCARD_SLASH_RE.finditer(source):
        if _inside_block_comment(source, match.start()):
            hits.append((source[:match.start()].count("\n") + 1, match.group(0)))
    return hits


def _inside_block_comment(source, pos):
    """``source[pos]`` 是否位于块注释内部（用 :func:`_scan` 的同一套词法）。

    只扫到 ``pos`` 之前，因此不受后面内容影响。
    """
    prefix = source[:pos]
    i, n = 0, len(prefix)
    in_block = False
    prev_significant = ""
    while i < n:
        ch = prefix[i]
        nxt = prefix[i + 1] if i + 1 < n else ""
        if in_block:
            if ch == "*" and nxt == "/":
                in_block = False
                i += 2
                continue
            i += 1
            continue
        if ch in ("'", '"', "`"):
            quote = ch
            i += 1
            while i < n:
                if prefix[i] == "\\":
                    i += 2
                    continue
                if prefix[i] == quote:
                    i += 1
                    break
                i += 1
            prev_significant = quote
            continue
        if ch == "/" and nxt == "/":
            while i < n and prefix[i] != "\n":
                i += 1
            continue
        if ch == "/" and nxt == "*":
            in_block = True
            i += 2
            continue
        if not ch.isspace():
            prev_significant = ch
        i += 1
    return in_block


#: 会提前闭合块注释的写法：星号 + 斜杠 + 紧跟一个单词字符
_WILDCARD_SLASH_RE = re.compile(r"\*/[A-Za-z_]")


def _scan(source):
    """极简 JS 词法扫描：返回 ``(块注释起止计数, 提前闭合位置列表)``。

    为什么要自己扫而不是数 ``source.count("/*")``：字符串、模板串、正则字面量
    里都可能出现 ``/*``。实测踩到 —— ``replace(/&/g, '&amp;')`` 这类代码里
    的斜杠与星号会被朴素计数误判成注释，于是"计数不匹配"报了一个**假**错误。
    朴素计数一旦误报，就会被后人当成噪音关掉，防线随之失效。

    这个扫描器只关心四件事：单引号串、双引号串、模板串、正则字面量，
    以及块注释的起止。足够覆盖本项目的前端代码风格。
    """
    i, n = 0, len(source)
    line = 1
    opens = closes = 0
    truncations = []
    in_block = False
    prev_significant = ""      # 上一个"有意义的字符"，用于判断 / 是除号还是正则
    while i < n:
        ch = source[i]
        nxt = source[i + 1] if i + 1 < n else ""
        if ch == "\n":
            line += 1
        if in_block:
            if ch == "*" and nxt == "/":
                in_block = False
                closes += 1
                i += 2
                continue
            i += 1
            continue
        # 不在块注释里
        if ch in ("'", '"', "`"):
            quote = ch
            i += 1
            while i < n:
                if source[i] == "\\":
                    i += 2
                    continue
                if source[i] == quote:
                    i += 1
                    break
                if source[i] == "\n":
                    line += 1
                i += 1
            prev_significant = quote
            continue
        if ch == "/" and nxt == "/":
            while i < n and source[i] != "\n":
                i += 1
            continue
        if ch == "/" and nxt == "*":
            in_block = True
            opens += 1
            i += 2
            continue
        if ch == "/" and prev_significant in ("", "(", ",", "=", ":", "[", "!", "&", "|", "?", "{", "}", ";", "\n"):
            # 正则字面量（粗略）：跳到未转义的 /
            i += 1
            while i < n:
                if source[i] == "\\":
                    i += 2
                    continue
                if source[i] == "/":
                    i += 1
                    break
                if source[i] == "\n":
                    break
                i += 1
            prev_significant = "/"
            continue
        if not ch.isspace():
            prev_significant = ch
        i += 1
    return (opens, closes), truncations


class TestNoCommentTruncation(unittest.TestCase):
    """**白屏事故的直接回归**：块注释里不得出现能提前闭合它的序列。"""

    def test_no_wildcard_path_inside_comments(self):
        offenders = {}
        for path in web_js_files():
            with open(path, encoding="utf-8") as f:
                source = f.read()
            hits = comment_truncations(source)
            if hits:
                offenders[os.path.relpath(path, _ROOT)] = hits
        self.assertEqual(offenders, {},
                         "以下文件的块注释里有「星号+斜杠+词」—— 会在注释内部提前"
                         "闭合注释，后面的散文变成代码，整个模块解析失败：%s"
                         % offenders)

    def test_comment_count_is_balanced(self):
        """``/*`` 与 ``*/`` 必须成对（用词法扫描计数，不是朴素字符串计数）。"""
        for path in web_js_files():
            with open(path, encoding="utf-8") as f:
                source = f.read()
            (opens, closes), _hits = _scan(source)
            with self.subTest(file=os.path.relpath(path, _ROOT)):
                self.assertEqual(opens, closes,
                                 "块注释起止数量不匹配：%d 个 /*，%d 个 */"
                                 % (opens, closes))


class TestWebSyntax(unittest.TestCase):
    """每个前端 js 都必须能被 JS 引擎**解析**（这是之前完全缺失的一层）。"""

    @classmethod
    def setUpClass(cls):
        cls.node = node_exe()
        if not cls.node:
            raise unittest.SkipTest(
                "未找到 node —— 前端语法检查跳过（本工程不要求 Node）")

    def test_every_web_js_parses(self):
        failures = {}
        for path in web_js_files():
            result = subprocess.run([self.node, "--check", path],
                                    capture_output=True, text=True,
                                    encoding="utf-8", errors="replace", timeout=120)
            if result.returncode != 0:
                failures[os.path.relpath(path, _ROOT)] = (
                    result.stderr or result.stdout).strip()[:400]
        self.assertEqual(failures, {},
                         "以下前端文件无法解析（页面会白屏）：\n%s"
                         % json.dumps(failures, ensure_ascii=False, indent=2))


class TestWebProbe(unittest.TestCase):
    """真实执行：起一次服务，在 Node 里跑前端，确认页面**变成可交互**。"""

    @classmethod
    def setUpClass(cls):
        cls.node = node_exe()
        if not cls.node:
            raise unittest.SkipTest("未找到 node —— 前端冒烟跳过")
        if not os.path.isfile(PROBE):
            raise unittest.SkipTest("缺少 tools/web_probe.mjs")

        import app as app_module
        cls.application = app_module.App(port=0, bind="127.0.0.1")
        cls.application.build()
        cls.base = cls.application.start(open_browser=False).rstrip("/")

        result = subprocess.run(
            [cls.node, "--experimental-vm-modules", PROBE, cls.base, "ui/web", "--json"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            cwd=_ROOT, timeout=300)
        cls.raw = result.stdout or ""
        cls.stderr = result.stderr or ""
        cls.report = None
        for line in cls.raw.splitlines():
            line = line.strip()
            if line.startswith("{") and line.endswith("}"):
                try:
                    cls.report = json.loads(line)
                except ValueError:
                    continue

    @classmethod
    def tearDownClass(cls):
        cls.application.stop()

    def _report(self):
        if self.report is None:
            self.fail("探针没有输出可解析的报告。\nstdout:\n%s\nstderr:\n%s"
                      % (self.raw[-2000:], self.stderr[-2000:]))
        return self.report

    def test_shell_boots_without_fatal_error(self):
        """**白屏事故的核心断言**：外壳必须启动成功。"""
        report = self._report()
        self.assertIsNone(report["fatal"],
                          "前端启动即失败（用户会看到永远「加载中…」）：%s\n%s"
                          % (report["fatal"], self.stderr[-800:]))

    def test_version_and_health_chips_are_filled(self):
        """顶栏必须从「加载中…」变成真实版本号。"""
        report = self._report()
        self.assertNotIn("加载中", report["appVersion"])
        self.assertTrue(report["appVersion"].strip(),
                        "app-version 仍是空的 —— 健康检查没跑到")

    def test_nav_has_all_three_features(self):
        """导航必须渲染出三个功能（用户靠它进入各功能）。"""
        report = self._report()
        self.assertEqual(len(report["nav"]), 3,
                         "导航项数量不对：%s" % report["nav"])
        joined = "".join(report["nav"])
        for name in ("文本翻译", "存档修改", "环境自检"):
            with self.subTest(feature=name):
                self.assertIn(name, joined)

    def test_feature_table_is_rendered(self):
        report = self._report()
        self.assertEqual(report["featureRows"], 3,
                         "功能状态表仍是「加载中…」或行数不对：%s"
                         % report["featureRows"])

    def test_default_page_renders_cards(self):
        """默认打开的第一个功能页必须渲染出卡片（不是空白）。"""
        report = self._report()
        self.assertGreaterEqual(report["viewCards"], 3,
                                "默认页没有渲染出卡片：%s" % report["viewCards"])
        self.assertNotIn("页面加载失败", report["viewText"])

    def test_every_page_renders_without_failure(self):
        """逐个切换三个功能页，都必须渲染出带内容的卡片。"""
        report = self._report()
        for page in ("translate", "cheats", "selfcheck"):
            with self.subTest(page=page):
                info = report["pages"].get(page)
                self.assertIsNotNone(info, "探针没有报告页面 %s" % page)
                self.assertFalse(info.get("failed"),
                                 "页面 %s 报「页面加载失败」：%s" % (page, info))
                self.assertGreaterEqual(info.get("cards", 0), 3,
                                        "页面 %s 的卡片太少：%s" % (page, info))
                self.assertGreater(info.get("chars", 0), 100,
                                   "页面 %s 几乎没有文案：%s" % (page, info))

    def test_no_page_level_errors(self):
        """页面代码不得打出 error 级日志（资源加载失败、未处理异常等）。"""
        report = self._report()
        errors = [p for p in report.get("problems", []) if p.startswith("error:")]
        self.assertEqual(errors, [], "页面报错：%s" % errors)

    def test_pages_actually_talk_to_the_api(self):
        """页面要真的打接口（否则"渲染出卡片"可能只是静态骨架）。"""
        report = self._report()
        self.assertGreaterEqual(report["calls"], 6,
                                "页面只发了 %d 次请求，看起来没在取数据"
                                % report["calls"])


class TestWebProbeIconFlow(unittest.TestCase):
    """**真的驱动界面**：填目录 → 点「读取游戏数据」→ 点「载入」→ 数图标格。

    为什么必须有这一层
    ------------------
    `/api/cheats/icon_info` 存在、`iconIndex` 读出来了，都**证明不了**
    界面上真的画出了图标 —— 坐标算错、开关没接线、图集没解密，
    每一条都能让"接口全绿但用户看不见图标"。

    所以这里用合成游戏（自带加密图集，不依赖用户游戏库）真的点一遍界面，
    并断言**每个图标的 CSS 坐标**。夹具的 icon 索引刻意选成"行列都不为 0"：

        item  1 -> icon 20 -> 第 1 行第 4 列 -> -128px -32px
        item  2 -> icon  0 -> 虚线空位（引擎里 0 就是"不显示图标"）
        weapon1 -> icon  5 -> 第 0 行第 5 列 -> -160px  0px
        armor 1 -> icon 17 -> 第 1 行第 1 列 ->  -32px -32px

    行列写反、忘记乘 cell、把 0 当成有效索引，都会立刻红灯。
    """

    @classmethod
    def setUpClass(cls):
        cls.node = node_exe()
        if not cls.node:
            raise unittest.SkipTest("未找到 node —— 前端冒烟跳过")
        if not os.path.isfile(PROBE):
            raise unittest.SkipTest("缺少 tools/web_probe.mjs")

        import tempfile
        from tests.features.cheats.test_item_icons import make_mv_icon_game

        try:
            cls.tmp = tempfile.TemporaryDirectory(prefix="probe_icon_",
                                                  ignore_cleanup_errors=True)
        except TypeError:                       # Python 3.8 / 3.9
            cls.tmp = tempfile.TemporaryDirectory(prefix="probe_icon_")
        cls.game_dir = os.path.join(cls.tmp.name, "game")
        os.makedirs(cls.game_dir, exist_ok=True)
        make_mv_icon_game(cls.game_dir)

        import app as app_module
        cls.application = app_module.App(port=0, bind="127.0.0.1")
        cls.application.build()
        cls.base = cls.application.start(open_browser=False).rstrip("/")

        result = subprocess.run(
            [cls.node, "--experimental-vm-modules", PROBE, cls.base, "ui/web",
             "--json", "--game", cls.game_dir],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            cwd=_ROOT, timeout=300)
        cls.raw = result.stdout or ""
        cls.stderr = result.stderr or ""
        cls.report = None
        for line in cls.raw.splitlines():
            line = line.strip()
            if line.startswith("{") and line.endswith("}"):
                try:
                    cls.report = json.loads(line)
                except ValueError:
                    continue

    @classmethod
    def tearDownClass(cls):
        cls.application.stop()
        cls.tmp.cleanup()

    def _flow(self):
        if self.report is None:
            self.fail("探针没有输出可解析的报告。\nstdout:\n%s\nstderr:\n%s"
                      % (self.raw[-2000:], self.stderr[-2000:]))
        flow = self.report.get("iconFlow")
        self.assertIsNotNone(flow, "探针没有报告图标流程（--game 没生效？）")
        self.assertIsNone(flow.get("error"), "驱动界面时出错：%s" % flow.get("error"))
        self.assertTrue(flow.get("ok"),
                        "图标流程没走通：%s" % json.dumps(flow, ensure_ascii=False))
        return flow

    def test_toggle_is_present_enabled_and_on(self):
        """开关必须在、可用、默认打开（用户要的就是"看到图标"）。"""
        flow = self._flow()
        self.assertTrue(flow["togglePresent"], "页面上没有图标开关")
        self.assertFalse(flow["toggleDisabled"], "开关被置灰了：%s" % flow.get("hint"))
        self.assertTrue(flow["toggleChecked"], "开关默认没打开")

    def test_hint_explains_where_the_sheet_came_from(self):
        """提示里要写清"多少格、每格多少像素、有没有解密"。"""
        hint = self._flow().get("hint", "")
        self.assertIn("32", hint)
        self.assertIn("解密", hint)

    def test_every_data_row_gets_an_icon_cell(self):
        flow = self._flow()
        self.assertEqual(flow["cells"], 4, "图标格数量不对：%s" % flow)
        self.assertTrue(flow["cellsMatchRows"],
                        "图标格与表格数据行没有一一对应：%s" % flow)

    def test_zero_icon_index_renders_a_blank_not_a_wrong_icon(self):
        """``iconIndex == 0`` 必须画成虚线空位，不能去裁第 0 格。"""
        flow = self._flow()
        self.assertEqual(flow["blankCells"], 1, "空位数不对：%s" % flow)
        self.assertIn("没有图标", flow["blankTitles"][0])
        self.assertEqual(flow["realCells"], 3)

    def test_sprite_coordinates_are_exact(self):
        """**坐标断言**：行列 × cell 必须分毫不差。

        按**数值**比较而不是字符串：真实浏览器把 ``style.backgroundPosition``
        读回来时会规范化（``0`` -> ``0px``），钉死字符串只会测出"浏览器怎么
        格式化"，测不出坐标算得对不对。
        """
        flow = self._flow()
        positions = sorted(_parse_position(s["pos"]) for s in flow["sample"])
        self.assertEqual(positions, [(-160, 0), (-128, -32), (-32, -32)],
                         "sprite 坐标算错了（行/列写反或没乘 cell）：%s"
                         % json.dumps(flow["sample"], ensure_ascii=False))

    def test_cells_use_native_pixel_size(self):
        """按原始像素显示（像素画不缩放才不糊）。"""
        for sample in self._flow()["sample"]:
            self.assertEqual(sample["size"], "32pxx32px")
            self.assertIn("/api/cheats/icon_set", sample["url"])

    def test_toggling_only_swaps_a_class(self):
        """关掉图标只是切 class —— 不能重建表格（会抖掉用户没提交的输入）。"""
        flow = self._flow()
        self.assertEqual(flow["hiddenClassWhenOff"], "hide-icons")
        self.assertEqual(flow["cellsAfterToggle"], flow["cells"],
                         "开关一关，图标格就被删了（应该是只藏不删）")
        self.assertEqual(flow["classWhenOn"], "")


if __name__ == "__main__":
    unittest.main(verbosity=2)

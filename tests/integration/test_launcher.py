# -*- coding: utf-8 -*-
"""交付入口测试：``启动.bat`` + ``run.py``（需求 §8-1）。

@feature  none
@layer    tests
@public   TestLauncherFiles, TestRunPy, TestEntryMatchesDocs
@depends  run.py, app.py
@tested   (本文件即测试)
@footprint docs/STATE.md

需求 §8-1：**干净 Python 环境（无第三方包）+ 双击启动脚本 → 界面正常打开，无报错。**

自动化能覆盖的部分
------------------
"双击"这个动作本身没法在 CI 里做，但它的**失败模式**都能静态或半动态地覆盖，
而且这些正是真正会出错的地方：

* 批处理里出现非 ASCII 字符 → ``cmd.exe`` 会吃掉每行第一个字节（本项目实测），
  于是 ``echo.`` 变成 ``cho.``、变量名被截断 —— 界面根本起不来；
* 批处理里的行尾写成 LF → 老版本 ``cmd.exe`` 解析异常；
* ``run.py`` 引用了不存在的 ``app.py``/参数拼错 → 自检通过但启动失败；
* README 里教用户敲的命令与真实 CLI 不一致 → 用户照着做会失败。

因此这里断言：**批处理是纯 ASCII + CRLF**、**run.py 自检退出码为 0**、
**README 里的每条命令都能真的跑通**（用 ``--help`` 与实际解析器核对）。
"""

from __future__ import annotations

import os
import re
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

LAUNCHER = os.path.join(_ROOT, "启动.bat")
RUNPY = os.path.join(_ROOT, "run.py")
README = os.path.join(_ROOT, "README.md")


class TestLauncherFiles(unittest.TestCase):
    def test_files_exist(self):
        self.assertTrue(os.path.isfile(LAUNCHER), "缺少双击启动脚本")
        self.assertTrue(os.path.isfile(RUNPY), "缺少 run.py")

    def test_bat_is_ascii_only(self):
        """**关键约束**：批处理必须是纯 ASCII。

        实测：含中文的 UTF-8 批处理在 ``chcp 65001`` 下仍会**丢掉每行的
        第一个字节**（``echo.`` → ``cho.``），脚本直接失效。
        因此所有中文提示都必须放在 run.py 里。
        """
        with open(LAUNCHER, "rb") as f:
            raw = f.read()
        offenders = [(i, b) for i, b in enumerate(raw) if b > 0x7F]
        self.assertEqual(offenders[:5], [],
                         "批处理里出现了非 ASCII 字节（cmd.exe 会吃字符）：%s"
                         % offenders[:5])

    def test_bat_has_crlf_line_endings(self):
        """Windows 批处理必须是 CRLF 行尾。"""
        with open(LAUNCHER, "rb") as f:
            raw = f.read()
        lone_lf = len(re.findall(rb"(?<!\r)\n", raw))
        self.assertEqual(lone_lf, 0, "批处理里有 %d 个单独的 LF 行尾" % lone_lf)

    def test_bat_delegates_to_run_py(self):
        text = open(LAUNCHER, encoding="ascii").read()
        self.assertIn("run.py", text, "批处理没有把工作交给 run.py")
        self.assertIn('cd /d "%~dp0"', text,
                      "批处理没有切到脚本目录（双击时工作目录可能是桌面）")
        self.assertIn("pause", text,
                      "失败时没有 pause，双击的黑窗口会一闪而过")

    def test_bat_mentions_python_requirement(self):
        text = open(LAUNCHER, encoding="ascii").read()
        self.assertIn("python.org", text,
                      "找不到 Python 时应告诉用户去哪装")

    def test_bat_prefers_path_python_over_py_launcher(self):
        """**回归**：优先用 PATH 上的 ``python``，而不是 ``py -3``。

        M5 实测踩到：本机 ``py -3`` 指向 Python **3.14.5**（最新安装），
        而 ``python`` 指向 3.10.9 —— 也就是文档里所有命令
        （``python app.py`` / ``python tests/run_all.py``）与全部测试
        实际使用的那一个。批处理原先优先 ``py -3``，于是**双击启动跑的解释器
        与开发/验证时用的不是同一个**：用户环境的问题无法复现，
        开发环境的问题也不会在这条路径上暴露。
        """
        text = open(LAUNCHER, encoding="ascii").read()
        lines = [ln for ln in text.splitlines()
                 if "where " in ln and "run.py" in ln]
        self.assertEqual(len(lines), 2, "批处理里应当有两条解释器探测：%s" % lines)
        self.assertIn("where python", lines[0],
                      "第一条应当是 PATH 上的 python：%s" % lines[0])
        self.assertTrue(lines[1].strip().startswith("where py"),
                        "第二条才是 py 启动器：%s" % lines[1])

    def test_bat_is_ascii_only_and_crlf(self):
        """把两条硬约束合成一条，避免以后只改了一处就以为全对。"""
        raw = open(LAUNCHER, "rb").read()
        self.assertEqual([b for b in raw if b > 0x7F], [], "批处理里有非 ASCII 字节")
        self.assertEqual(len(re.findall(rb"(?<!\r)\n", raw)), 0, "批处理里有单独的 LF")


class TestRunPy(unittest.TestCase):
    def test_imports_without_side_effects(self):
        """导入 run.py 不得启动服务或起线程（与 app.py 同一约束）。"""
        probe = subprocess.run(
            [sys.executable, "-c",
             "import sys; sys.path.insert(0, sys.argv[1]);\n"
             "import run\n"
             "import threading\n"
             "alive = [t.name for t in threading.enumerate()\n"
             "         if t is not threading.main_thread()]\n"
             "print('THREADS=' + ','.join(sorted(alive)))\n",
             _ROOT],
            capture_output=True, text=True, encoding="utf-8", cwd=_ROOT, timeout=120)
        self.assertEqual(probe.returncode, 0, probe.stderr)
        line = [ln for ln in probe.stdout.splitlines() if ln.startswith("THREADS=")][0]
        self.assertEqual(line.split("=", 1)[1], "",
                         "导入 run.py 不应启动线程")

    def test_check_exits_zero(self):
        """``python run.py --check`` 必须退出码 0（§8-1 的可自动化判据）。"""
        completed = subprocess.run(
            [sys.executable, RUNPY, "--check"],
            capture_output=True, text=True, encoding="utf-8", cwd=_ROOT, timeout=300)
        self.assertEqual(completed.returncode, 0,
                         "自检失败：\n%s\n%s" % (completed.stdout[-2000:],
                                                 completed.stderr[-2000:]))
        self.assertIn("自检结果：通过", completed.stdout)
        self.assertIn("已加载的功能模块", completed.stdout)

    def test_check_reports_features_and_routes(self):
        completed = subprocess.run(
            [sys.executable, RUNPY, "--check"],
            capture_output=True, text=True, encoding="utf-8", cwd=_ROOT, timeout=300)
        for expected in ("文本翻译(translate)", "存档修改(cheats)", "已登记路由"):
            with self.subTest(expected=expected):
                self.assertIn(expected, completed.stdout)

    def test_find_python_returns_something_usable(self):
        import run
        exe, args = run.find_python()
        self.assertTrue(exe, "找不到任何可用的 Python")
        ok, version = run.check_python(exe, args)
        self.assertTrue(ok, "find_python 返回的解释器不可用：%s %s" % (version, exe))

    def test_check_python_rejects_old_version(self):
        import run
        # 用一个必然不存在的解释器模拟"不可用"
        ok, detail = run.check_python(os.path.join(_ROOT, "no-such-python.exe"))
        self.assertFalse(ok)
        self.assertTrue(detail)

    def test_missing_app_py_is_reported(self):
        """``app.py`` 不在旁边时要给出可读提示，而不是栈回溯。"""
        import tempfile
        import run
        with tempfile.TemporaryDirectory(prefix="norun_") as tmp:
            original = run.ROOT
            run.ROOT = tmp
            try:
                code = run.main(["--check"])
            finally:
                run.ROOT = original
        self.assertEqual(code, 2)


class TestEntryMatchesDocs(unittest.TestCase):
    """README / AGENTS 里教的命令必须与真实 CLI 一致。"""

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, _ROOT)
        import app as app_module
        cls.parser = app_module.build_parser()

    def test_readme_exists(self):
        self.assertTrue(os.path.isfile(README), "缺少 README.md（需求 §9 交付物）")

    def test_readme_documents_the_real_flags(self):
        """README 里 ``python app.py`` / ``启动.bat`` 后面的参数必须真实存在。

        ⚠ 只检查**这两个入口**的示例：README 里还有 ``tests/run_all.py --suite``
        这类别的入口，把全文的 ``--xxx`` 一起收进来会误报（实测踩到）。
        做法：按 ``python app.py`` / ``启动.bat`` 切开，取同一行里跟的参数。
        """
        text = open(README, encoding="utf-8").read()
        known = set()
        for action in self.parser._actions:
            known.update(action.option_strings)
        checked = 0
        for line in text.splitlines():
            if "python app.py" not in line and "启动.bat" not in line:
                continue
            for token in re.findall(r"(?<![\w-])--[a-z][a-z0-9-]+", line):
                checked += 1
                self.assertIn(token, known,
                              "README 这一行提到了 CLI 不认识的参数：%s（%s）"
                              % (token, line.strip()))
        self.assertGreater(checked, 0, "README 里没有找到任何 app.py 的参数示例")

    def test_readme_tells_how_to_start(self):
        text = open(README, encoding="utf-8").read()
        self.assertIn("启动.bat", text, "README 没有告诉用户怎么启动")
        self.assertIn("python app.py", text)

    def test_readme_documents_backup_and_restore(self):
        """§9「不可逆操作」：必须向用户说明备份与还原在哪。"""
        text = open(README, encoding="utf-8").read()
        for keyword in ("备份", "还原", "汉化备份"):
            with self.subTest(keyword=keyword):
                self.assertIn(keyword, text)

    def test_readme_documents_supported_engines(self):
        text = open(README, encoding="utf-8").read()
        for engine in ("MV", "MZ", "VX Ace", "XP", "2000/2003"):
            with self.subTest(engine=engine):
                self.assertIn(engine, text)


def github_slug(heading):
    """按 GitHub 的规则把标题转成锚点。

    规则（实测归纳）：转小写 → 去掉**字母数字与 -_ 之外**的标点（中文标题里的
    `、`/`（）`/`：` 都会被丢掉）→ 空格转连字符。
    CJK 属于字母，会保留，所以 `## 一、怎么启动` 的锚点是 `#一怎么启动`。
    """
    out = []
    for ch in heading.strip().lower():
        if ch.isalnum() or ch in "-_":
            out.append(ch)
        elif ch == " ":
            out.append("-")
    return "".join(out)


class TestReadmeIsPublishable(unittest.TestCase):
    """README 要能直接发到 GitHub —— 死链与坏锚点是发布后才发现的那种问题。"""

    @classmethod
    def setUpClass(cls):
        with open(README, encoding="utf-8") as f:
            cls.text = f.read()
        cls.links = re.findall(r"\[[^\]]*\]\(([^)]+)\)", cls.text)
        #: 去重后的相对链接（GitHub 上的仓库内跳转）
        cls.relative = sorted({t for t in cls.links
                               if not t.startswith(("http://", "https://", "#"))})
        cls.anchors = sorted({t[1:] for t in cls.links if t.startswith("#")})
        #: 标题里可能带行内代码/加粗，锚点按纯文本算
        cls.headings = []
        for line in cls.text.splitlines():
            if line.startswith("#"):
                title = line.lstrip("#").strip()
                title = re.sub(r"[`*]", "", title)
                cls.headings.append(title)

    def test_every_relative_link_resolves(self):
        """仓库内链接指向的文件必须真的存在（否则 GitHub 上是死链）。"""
        missing = [t for t in self.relative
                   if not os.path.exists(os.path.join(_ROOT, t.split("#")[0]))]
        self.assertEqual(missing, [], "README 里的这些链接指向了不存在的文件：%s"
                         % missing)
        self.assertGreaterEqual(len(self.relative), 8,
                                "相对链接太少，检查逻辑可能失效了：%s" % self.relative)

    def test_every_anchor_matches_a_heading(self):
        """目录里的每个锚点都要对得上一个真实标题。"""
        slugs = {github_slug(h) for h in self.headings}
        bad = [a for a in self.anchors if a not in slugs]
        self.assertEqual(bad, [], "README 目录里的锚点找不到对应标题：%s\n"
                         "现有标题锚点：%s" % (bad, sorted(slugs)))
        self.assertGreaterEqual(len(self.anchors), 8, "目录锚点太少，检查逻辑可能失效")

    def test_states_the_license(self):
        """没有许可证的仓库默认"保留所有权利" —— 发布前必须有。"""
        self.assertIn("MIT", self.text)
        self.assertTrue(os.path.isfile(os.path.join(_ROOT, "LICENSE")),
                        "README 说了 MIT，但仓库里没有 LICENSE 文件")

    def test_has_a_disclaimer(self):
        """涉及改存档与汉化，必须写清责任边界。"""
        self.assertIn("免责声明", self.text)
        self.assertIn("无任何关联", self.text)

    def test_has_english_intro(self):
        """外国访客要能一眼看懂这是什么。"""
        self.assertIn("**English**", self.text)


if __name__ == "__main__":
    unittest.main(verbosity=2)

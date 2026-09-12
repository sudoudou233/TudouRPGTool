# -*- coding: utf-8 -*-
"""``core.sysdialog``：原生对话框的纯逻辑与降级行为。

@feature  none
@layer    tests
@public   TestShellCandidates, TestBuildScript, TestPickFallback,
          TestDialogUnavailable
@depends  core.sysdialog
@tested   (本文件即测试)
@footprint docs/MODULES.md#coresysdialog

为什么需要这个文件
------------------
这段代码是 M0 台账 **B-27** 的修复点（原实现把 PowerShell 的绝对路径写死在
``tool/server.py`` 里，换台机器/换 PowerShell 版本就弹不出对话框）。

真正的"弹窗"无法在 CI 里断言，但**导致 B-27 的那部分逻辑是纯的**：
候选路径怎么找、脚本怎么拼、失败怎么降级。本文件把这些钉死，
并验证"两者都不可用时抛 ``DialogUnavailable``"这条降级契约 ——
调用方（``features/translate/routes.py``）靠它返回可读错误而不是 500。
"""

from __future__ import annotations

import os
import sys
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

from core import sysdialog  # noqa: E402


class TestShellCandidates(unittest.TestCase):
    """**B-27**：不得写死 PowerShell 绝对路径。"""

    def test_which_result_comes_first(self):
        with mock.patch.object(sysdialog.shutil, "which",
                               side_effect=lambda name: (
                                   r"X:\custom\%s.exe" % name
                                   if name == "powershell" else None)):
            candidates = sysdialog.shell_candidates()
        self.assertEqual(candidates[0], r"X:\custom\powershell.exe")

    def test_falls_back_to_pwsh_from_path(self):
        with mock.patch.object(sysdialog.shutil, "which",
                               side_effect=lambda name: (
                                   r"X:\custom\pwsh.exe" if name == "pwsh" else None)):
            candidates = sysdialog.shell_candidates()
        self.assertEqual(candidates[0], r"X:\custom\pwsh.exe")

    @unittest.skipUnless(sys.platform == "win32", "仅在 Windows 上有常见安装位置")
    def test_windows_has_fallback_locations(self):
        with mock.patch.object(sysdialog.shutil, "which", return_value=None):
            candidates = sysdialog.shell_candidates()
        self.assertTrue(candidates, "Windows 上至少应给出常见安装位置")
        self.assertTrue(all(os.path.isabs(p) for p in candidates),
                        "候选必须是绝对路径：%s" % candidates)
        self.assertTrue(any("powershell.exe" in p.lower() for p in candidates),
                        "应包含 Windows PowerShell 的常见位置：%s" % candidates)

    def test_no_candidates_when_nothing_found(self):
        with mock.patch.object(sysdialog.shutil, "which", return_value=None):
            candidates = sysdialog.shell_candidates()
        # 非 Windows：没有 PATH 命中就没有候选（调用方据此抛 DialogUnavailable）
        if sys.platform != "win32":
            self.assertEqual(candidates, [])

    def test_existing_shell_skips_nonexistent_paths(self):
        with mock.patch.object(sysdialog, "shell_candidates",
                               return_value=[r"Z:\nope\pwsh.exe"]):
            self.assertIsNone(sysdialog._existing_shell())

    def test_existing_shell_returns_real_file(self):
        with mock.patch.object(sysdialog, "shell_candidates",
                               return_value=[sys.executable]):
            self.assertEqual(sysdialog._existing_shell(), sys.executable)


class TestBuildScript(unittest.TestCase):
    """脚本拼装是纯函数，可以直接断言（这是把逻辑放进 core 的收益之一）。"""

    def test_folder_script_uses_folder_browser(self):
        script = sysdialog.build_script("folder")
        self.assertIn("FolderBrowserDialog", script)
        self.assertIn("SelectedPath", script)
        self.assertNotIn("OpenFileDialog", script)

    def test_font_script_filters_font_extensions(self):
        script = sysdialog.build_script("font")
        self.assertIn("OpenFileDialog", script)
        for ext in ("*.ttf", "*.otf", "*.ttc"):
            with self.subTest(ext=ext):
                self.assertIn(ext, script)

    def test_title_is_embedded(self):
        self.assertIn("我的游戏", sysdialog.build_script("folder", "我的游戏"))

    def test_single_quotes_in_title_are_escaped(self):
        """标题带单引号不能破坏脚本（顺带挡住注入）。"""
        script = sysdialog.build_script("folder", "it's a game'; Remove-Item C:\\")
        self.assertIn("it''s a game''", script)
        # 转义后不应再出现"落单"的引号对（计数必须是偶数）
        self.assertEqual(script.count("'") % 2, 0,
                         "脚本里的单引号数量为奇数，说明转义不完整：%s" % script)

    def test_unknown_kind_raises(self):
        with self.assertRaises(ValueError):
            sysdialog.build_script("printer")

    def test_no_hardcoded_absolute_shell_path_in_script(self):
        for kind in ("folder", "font"):
            with self.subTest(kind=kind):
                self.assertNotIn("System32", sysdialog.build_script(kind))


class TestPickFallback(unittest.TestCase):
    """降级顺序：tkinter → PowerShell → 抛错。"""

    def test_tkinter_is_preferred(self):
        with mock.patch.object(sysdialog, "_tk_available", return_value=True), \
                mock.patch.object(sysdialog, "_with_tk",
                                  return_value=r"C:\games\A") as tk, \
                mock.patch.object(sysdialog, "_with_powershell") as ps:
            self.assertEqual(sysdialog.pick_folder(), r"C:\games\A")
        tk.assert_called_once()
        ps.assert_not_called()

    def test_falls_back_to_powershell_when_tk_fails(self):
        with mock.patch.object(sysdialog, "_tk_available", return_value=True), \
                mock.patch.object(sysdialog, "_with_tk",
                                  side_effect=RuntimeError("no display")), \
                mock.patch.object(sysdialog, "_with_powershell",
                                  return_value=r"C:\games\B"):
            result = sysdialog.pick_folder(r"C:\games")
        self.assertEqual(result, r"C:\games\B")

    def test_exception_mentions_both_attempts(self):
        with mock.patch.object(sysdialog, "_tk_available", return_value=True), \
                mock.patch.object(sysdialog, "_with_tk",
                                  side_effect=RuntimeError("no display")), \
                mock.patch.object(sysdialog.sys, "platform", "win32"), \
                mock.patch.object(sysdialog, "_with_powershell",
                                  side_effect=RuntimeError("blocked")):
            with self.assertRaises(sysdialog.DialogUnavailable) as caught:
                sysdialog.pick_folder()
        message = str(caught.exception)
        self.assertIn("tkinter", message)
        self.assertIn("powershell", message)
        self.assertIn("手动输入", message)

    def test_unavailable_on_non_windows_without_tk(self):
        with mock.patch.object(sysdialog, "_tk_available", return_value=False), \
                mock.patch.object(sysdialog.sys, "platform", "linux"):
            with self.assertRaises(sysdialog.DialogUnavailable):
                sysdialog.pick_font()

    def test_pick_font_passes_kind(self):
        with mock.patch.object(sysdialog, "pick",
                               return_value=r"C:\f\a.ttf") as pick:
            self.assertEqual(sysdialog.pick_font("init", "标题"), r"C:\f\a.ttf")
        pick.assert_called_once_with("font", "init", "标题")

    def test_powershell_result_is_stripped(self):
        """PowerShell 输出常带换行/空白 —— 必须 strip 掉再返回。"""
        completed = mock.Mock(stdout="  C:\\games\\C \r\n", returncode=0)
        with mock.patch.object(sysdialog, "_existing_shell",
                               return_value=r"C:\ps.exe"), \
                mock.patch.object(sysdialog.subprocess, "run",
                                  return_value=completed):
            self.assertEqual(sysdialog._with_powershell("folder"),
                             r"C:\games\C")

    def test_powershell_uses_sta_and_no_profile(self):
        """``-STA`` 是 WinForms 对话框的必要条件；``-NoProfile`` 避免用户配置干扰。"""
        completed = mock.Mock(stdout="", returncode=0)
        with mock.patch.object(sysdialog, "_existing_shell",
                               return_value=r"C:\ps.exe"), \
                mock.patch.object(sysdialog.subprocess, "run",
                                  return_value=completed) as run:
            sysdialog._with_powershell("folder")
        argv = run.call_args[0][0]
        self.assertIn("-STA", argv)
        self.assertIn("-NoProfile", argv)


class TestDialogUnavailable(unittest.TestCase):
    def test_available_is_boolean(self):
        self.assertIsInstance(sysdialog.available(), bool)

    def test_available_true_when_tk_present(self):
        with mock.patch.object(sysdialog, "_tk_available", return_value=True):
            self.assertTrue(sysdialog.available())

    def test_available_true_on_windows(self):
        with mock.patch.object(sysdialog, "_tk_available", return_value=False), \
                mock.patch.object(sysdialog.sys, "platform", "win32"):
            self.assertTrue(sysdialog.available())

    def test_available_false_otherwise(self):
        with mock.patch.object(sysdialog, "_tk_available", return_value=False), \
                mock.patch.object(sysdialog.sys, "platform", "linux"):
            self.assertFalse(sysdialog.available())


if __name__ == "__main__":
    unittest.main(verbosity=2)

# -*- coding: utf-8 -*-
"""原生系统对话框（选文件夹 / 选字体文件）—— UI 无关的唯一实现。

@feature  none
@layer    core
@public   pick_folder, pick_font, available, DialogUnavailable,
          shell_candidates, build_script
@depends  core.constants
@tested   tests/unit/test_sysdialog.py
@footprint docs/MODULES.md#coresysdialog

迁移来源与位置调整
------------------
原翻译工具把这段逻辑**内联在** ``tool/server.py:65-87``，并硬编码了
PowerShell 的绝对路径 ``C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe``
（M0 台账 **B-27**）。

M3a 首次把它抽成 ``ui/native_pick.py``，但足迹校验的 **F-09** 立刻报错：
``features/translate/routes.py`` 反向 import 了 ``ui`` —— 分层规定
``features → core``、``ui → core + features``，反向依赖是硬约束违规。
把它放进 ``core`` 是正确的位置：**"弹一个系统对话框"是与业务和界面都无关的
系统能力**（和剪贴板、文件选择同级别），不是应用逻辑，也不是 HTTP 关注点。
``ui/routes.py`` 里的两个端点只是这层能力的 HTTP 门面。

为什么优先 tkinter
------------------
* tkinter 随官方 Python 分发（Windows 默认包含），跨平台，比 PowerShell 可靠；
* PowerShell 回退仅在 Windows 上使用，且**用 ``shutil.which`` 在 PATH 上找**，
  再退到几个常见安装位置 —— 不再写死绝对路径（B-27）。
* 两者都不可用时抛 :class:`DialogUnavailable`，由调用方降级为"手输路径"。

可测性
------
:func:`shell_candidates` 与 :func:`build_script` 是**纯函数**（不弹窗、不执行
外部进程），因此对话框逻辑本身可以在 CI 里被完整断言；真正弹窗的
:func:`pick` 只在有图形环境的机器上才会走到。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys


class DialogUnavailable(RuntimeError):
    """当前环境无法弹出原生对话框（无 tkinter 且非 Windows）。"""


#: 常见字体扩展名（tkinter 与 PowerShell 回退共用）
FONT_FILTER = "*.ttf;*.otf;*.ttc"

#: tkinter 的 filetypes 参数格式
FONT_FILETYPES = (("字体文件", FONT_FILTER), ("所有文件", "*.*"))


def _tk_available():
    try:
        import tkinter  # noqa: F401
    except Exception:
        return False
    return True


def shell_candidates():
    """返回用于 PowerShell 回退的候选可执行文件（按优先级）。

    **不写死绝对路径**（B-27）：先查 PATH，再查两个常见安装位置。
    返回的路径不保证存在；调用方按顺序验证。
    """
    found = shutil.which("powershell") or shutil.which("pwsh")
    out = [found] if found else []
    if sys.platform == "win32":
        system_root = os.environ.get("SystemRoot") or r"C:\Windows"
        program_files = os.environ.get("ProgramFiles") or r"C:\Program Files"
        out.append(os.path.join(system_root, "System32", "WindowsPowerShell",
                                "v1.0", "powershell.exe"))
        out.append(os.path.join(program_files, "PowerShell", "7", "pwsh.exe"))
    return [p for p in out if p]


def _existing_shell():
    for candidate in shell_candidates():
        if os.path.isfile(candidate):
            return candidate
    return None


def build_script(kind, title=None):
    """构造 WinForms 对话框的 PowerShell 脚本（**纯函数**，便于测试）。

    ``kind`` 为 ``'folder'`` 或 ``'font'``。单引号按 PowerShell 规则转义成
    两个单引号，避免标题里的引号破坏脚本（也顺手挡住注入）。
    """
    def quote(text):
        return str(text).replace("'", "''")

    if kind == "folder":
        return (
            "Add-Type -AssemblyName System.Windows.Forms;"
            "$d = New-Object System.Windows.Forms.FolderBrowserDialog;"
            "$d.Description = '%s';"
            "if ($d.ShowDialog() -eq 'OK') { [Console]::Out.Write($d.SelectedPath) }"
            % quote(title or "选择游戏目录"))
    if kind == "font":
        return (
            "Add-Type -AssemblyName System.Windows.Forms;"
            "$d = New-Object System.Windows.Forms.OpenFileDialog;"
            "$d.Filter = %s;"
            "if ($d.ShowDialog() -eq 'OK') { [Console]::Out.Write($d.FileName) }"
            % quote("字体文件|%s|所有文件|*.*" % FONT_FILTER))
    raise ValueError("未知的对话框类型：%r" % (kind,))


def _with_tk(kind, initial=None, title=None):
    """用 tkinter 弹对话框。返回所选路径；用户取消返回 ``""``。"""
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()                 # 只留对话框，不要空白主窗口
    try:
        root.attributes("-topmost", True)
    except Exception:
        pass
    try:
        if kind == "folder":
            chosen = filedialog.askdirectory(initialdir=initial or None,
                                             title=title or "选择游戏目录")
        else:
            chosen = filedialog.askopenfilename(initialdir=initial or None,
                                                title=title or "选择字体文件",
                                                filetypes=list(FONT_FILETYPES))
    finally:
        try:
            root.destroy()
        except Exception:
            pass
    return chosen or ""


def _with_powershell(kind, initial=None, title=None):
    """Windows 回退：用 PowerShell 的 WinForms 对话框。"""
    shell = _existing_shell()
    if not shell:
        raise DialogUnavailable("找不到 powershell / pwsh")
    completed = subprocess.run(
        [shell, "-NoProfile", "-STA", "-Command", build_script(kind, title)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=300)
    return (completed.stdout or "").strip()


def pick(kind, initial=None, title=None):
    """弹原生对话框，返回所选路径（取消返回 ``""``）。"""
    errors = []
    if _tk_available():
        try:
            return _with_tk(kind, initial, title)
        except Exception as exc:        # tkinter 存在但不可用（无显示等）
            errors.append("tkinter: %s" % exc)
    if sys.platform == "win32":
        try:
            return _with_powershell(kind, initial, title)
        except Exception as exc:
            errors.append("powershell: %s" % exc)
    raise DialogUnavailable(
        "无法弹出原生对话框（%s）。请手动输入路径。"
        % ("；".join(errors) or "当前平台不支持"))


def pick_folder(initial=None, title=None):
    """选择文件夹（返回 ``""`` 表示用户取消）。"""
    return pick("folder", initial, title)


def pick_font(initial=None, title=None):
    """选择字体文件（返回 ``""`` 表示用户取消）。"""
    return pick("font", initial, title)


def available():
    """当前环境是否有可能弹出对话框（供前端决定是否显示"浏览"按钮）。"""
    return _tk_available() or sys.platform == "win32"

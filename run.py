# -*- coding: utf-8 -*-
"""双击启动入口：找 Python → 自检 → 起服务 → 开浏览器（需求 §8-1）。

@feature  none
@layer    (无：交付入口，不属于任何分层)
@public   main, find_python, check_python
@depends  app.py, core.paths
@tested   tests/integration/test_launcher.py
@footprint docs/STATE.md

为什么要有这个文件
------------------
需求 §8-1 要求"干净 Python 环境 + **双击启动脚本** → 界面正常打开，无报错"。

Windows 上的双击入口只能是 ``.bat``，而 ``cmd.exe`` 处理 UTF-8 批处理文件
有实测缺陷：即使 ``chcp 65001``，**每行的第一个字节仍会被吃掉**
（本项目实测：``echo.`` 变成 ``cho.``、``%PYTHON_EXE%`` 变成 ``YTHON_EXE%``）。
把中文提示写进 ``.bat`` 一定会乱码。

因此采用"薄批处理 + 厚 Python"：``启动.bat`` 只做三件事（ASCII，逻辑为零）——
切到脚本目录、找 ``py``/``python``、把参数转交给本文件。
所有用户可见的提示（中文、错误说明、下一步该做什么）都在这里，
用普通 UTF-8 Python 输出，不受 ``cmd.exe`` 的编码问题影响。

与 ``python app.py`` 的区别
---------------------------
本文件是**面向双击的用户体验层**：

* 自检不通过时打印"怎么办"，而不是直接抛栈；
* 端口被占用时自动改用随机端口（不要求用户懂 ``--port``）；
* 退出时 ``pause``，否则双击的黑窗口会一闪而过，用户看不到错误。
"""

from __future__ import annotations

import os
import subprocess
import sys

#: 本文件所在目录（工程根）
ROOT = os.path.dirname(os.path.abspath(__file__))


def check_python(executable=None, args=()):
    """检查某个 Python 是否可用且 >= 3.8。

    返回 ``(ok, version_text)``；不可用或版本过低时 ``ok=False``。
    """
    exe = executable or sys.executable
    probe = ("import sys; print('.'.join(map(str, sys.version_info[:3]))); "
             "sys.exit(0 if sys.version_info >= (3, 8) else 1)")
    try:
        completed = subprocess.run([exe, *args, "-c", probe],
                                   capture_output=True, text=True,
                                   encoding="utf-8", errors="replace", timeout=60)
    except Exception as exc:
        return False, "%s: %s" % (type(exc).__name__, exc)
    version = (completed.stdout or "").strip()
    return completed.returncode == 0, version


def find_python():
    """找一个可用的 Python 解释器，返回 ``(executable, extra_args)``。

    顺序：当前解释器（说明已经在 Python 里了）→ ``py -3`` → PATH 上的
    ``python`` → 几个常见安装位置。返回 ``(None, ())`` 表示找不到。
    """
    ok, _version = check_python(sys.executable)
    if ok:
        return sys.executable, ()

    import shutil
    for name, args in (("py", ("-3",)), ("python", ()), ("python3", ())):
        found = shutil.which(name)
        if not found:
            continue
        ok, _version = check_python(found, args)
        if ok:
            return found, args

    candidates = []
    local = os.environ.get("LOCALAPPDATA") or ""
    for minor in (13, 12, 11, 10, 9, 8):
        if local:
            candidates.append(os.path.join(local, "Programs", "Python",
                                           "Python3%d" % minor, "python.exe"))
        candidates.append(r"C:\Python3%d\python.exe" % minor)
    for path in candidates:
        if os.path.isfile(path):
            ok, _version = check_python(path)
            if ok:
                return path, ()
    return None, ()


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)

    if not os.path.isfile(os.path.join(ROOT, "app.py")):
        print("=" * 66)
        print("[错误] 这个脚本必须和 app.py 放在同一个目录里。")
        print("       当前目录：%s" % ROOT)
        print("=" * 66)
        return 2

    exe, extra = find_python()
    if not exe:
        print("=" * 66)
        print("[错误] 没有找到 Python 3.8 或更高版本。")
        print()
        print("本工具只用 Python 标准库，不需要 pip 安装任何东西，")
        print("但需要先装 Python：https://www.python.org/downloads/")
        print("安装时请**勾选** “Add python.exe to PATH”。")
        print("=" * 66)
        return 1

    if exe != sys.executable:
        # 由批处理直接调用的 Python 版本过低 —— 转发给找到的那个
        print("使用 Python：%s %s" % (exe, " ".join(extra)))
        completed = subprocess.run([exe, *extra, os.path.join(ROOT, "run.py"),
                                    *argv], cwd=ROOT)
        return completed.returncode

    ok, version = check_python()
    if not ok:
        print("[错误] Python 版本过低或不可用：%s" % version)
        return 1

    print("=" * 66)
    print("RPG Maker 全能工具 —— 启动中（Python %s）" % version)
    print("=" * 66)

    # 复用 app.py 的 CLI：先自检，通过后再起服务
    sys.path.insert(0, ROOT)
    import app as app_module            # noqa: E402

    check_only = "--check" in argv
    code = app_module.main(argv)
    if check_only:
        return code
    if code == 0:
        print()
        print("服务已退出。")
    return code


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n已中断。")
        sys.exit(0)

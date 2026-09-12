# -*- coding: utf-8 -*-
"""开发期一次性脚本：把测试文件里脆弱的 ``_ROOT`` 推导改为锚点查找。

@feature  none
@layer    tools
@public   PATTERN, PATTERN4, REPLACEMENT, main
@depends  (stdlib only)
@tested   (一次性脚本)
@footprint docs/DEVLOG.md
@note     原写法用固定层数 ``dirname(dirname(dirname(__file__)))`` 推工程根，
          只在"测试模块恰好位于 tests/<层>/"时成立。改名为
          ``tests.features.translate.test_manifest`` 后会少算一层，指向
          ``<root>/tests``，导致所有路径断言失败（M1 实测踩到）。
          改为向上查找含 ``app.py`` 的目录，层数无关。
"""

from __future__ import annotations

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: 匹配原本的固定层数推导（3 层 = tests/<suite>/file.py）
PATTERN = re.compile(
    r"_ROOT = os\.path\.dirname\(os\.path\.dirname\(os\.path\.dirname\(os\.path\.abspath\(__file__\)\)\)\)")

REPLACEMENT = '''_ROOT = os.path.dirname(os.path.abspath(__file__))
while not os.path.isfile(os.path.join(_ROOT, "app.py")):
    parent = os.path.dirname(_ROOT)
    if parent == _ROOT:
        raise RuntimeError("无法定位工程根（未找到 app.py）")
    _ROOT = parent'''

#: tests/<suite>/<feature>/file.py 用 4 层
PATTERN4 = re.compile(
    r"_ROOT = os\.path\.dirname\(os\.path\.dirname\(os\.path\.dirname\(os\.path\.dirname\(os\.path\.abspath\(__file__\)\)\)\)\)")


def main():
    changed = []
    for dirpath, dirnames, filenames in os.walk(os.path.join(ROOT, "tests")):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for name in filenames:
            if not name.endswith(".py"):
                continue
            full = os.path.join(dirpath, name)
            with open(full, "r", encoding="utf-8") as f:
                text = f.read()
            original = text
            text = PATTERN.sub(REPLACEMENT, text)
            text = PATTERN4.sub(REPLACEMENT, text)
            if text != original:
                with open(full, "w", encoding="utf-8", newline="\n") as f:
                    f.write(text)
                changed.append(os.path.relpath(full, ROOT))
    for path in changed:
        print("patched", path)
    print("total:", len(changed))
    return 0


if __name__ == "__main__":
    sys.exit(main())

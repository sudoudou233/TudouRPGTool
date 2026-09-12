# -*- coding: utf-8 -*-
"""开发期脚本：把源码 docstring 里的 @tested 对齐到真实测试文件。

@feature  none
@layer    tools
@public   MAPPING, main
@depends  (stdlib only)
@tested   (一次性脚本)
@footprint docs/DEVLOG.md
@note     M1 收尾用。check_footprint 的 F-08 会校验 @tested 指向的路径必须
          存在；早期按"每个模块一个测试文件"的理想写的声明与实际测试布局
          不一致，本脚本按真实布局统一。
"""

from __future__ import annotations

import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: 文件 -> 正确的 @tested 值
MAPPING = {
    "core/__init__.py": "tests/unit/",
    "core/paths.py": "tests/unit/test_paths.py",
    "core/constants.py": "tests/unit/test_config.py",
    "core/config.py": "tests/unit/test_config.py",
    "core/textutil.py": "tests/unit/test_textutil.py",
    "core/engines.py": "tests/unit/test_engines.py",
    "core/registry.py": "tests/unit/test_registry.py",
    "core/context.py": "tests/unit/test_registry.py",
    "core/jobs.py": "tests/unit/test_jobs.py",
    "core/_refbridge.py": "tests/unit/test_refbridge.py",
    "core/marshal/__init__.py": "tests/compat/test_marshal_compat.py",
    "core/marshal/doc_model.py": "tests/compat/test_marshal_compat.py",
    "core/marshal/value_model.py": "tests/compat/test_marshal_compat.py",
    "core/formats/__init__.py": "tests/compat/test_formats_compat.py",
    "core/formats/lzstring.py": "tests/compat/test_formats_compat.py",
    "core/formats/mv_mz_data.py": "tests/compat/test_formats_compat.py",
    "core/formats/rgss_data.py": "tests/compat/test_formats_compat.py",
    "core/formats/mv_save.py": "tests/compat/test_formats_compat.py",
    "core/formats/rgss_save.py": "tests/compat/test_formats_compat.py",
    "core/safety/__init__.py": "tests/unit/test_atomic.py",
    "core/safety/atomic.py": "tests/unit/test_atomic.py",
    "core/safety/backup.py": "tests/compat/test_build_backup.py",
    "core/safety/fontutil.py": "tests/compat/test_build_backup.py",
    "features/__init__.py": "tests/unit/test_registry.py",
    "features/translate/__init__.py": "tests/features/translate/",
    "features/translate/manifest.py": "tests/features/translate/",
    "features/translate/translators.py": "tests/features/translate/",
    "features/translate/session.py": "tests/features/translate/",
    "features/cheats/__init__.py": "tests/features/cheats/",
    "features/cheats/manifest.py": "tests/features/cheats/",
    "ui/__init__.py": "tests/unit/test_server.py",
    "ui/server.py": "tests/unit/test_server.py",
    "ui/routes.py": "tests/unit/test_server.py",
    "app.py": "tests/unit/test_app.py, tests/integration/test_startup.py",
    "tools/check_footprint.py": "tests/unit/test_check_footprint.py",
    "tools/gen_footprint.py": "tests/unit/test_check_footprint.py",
    "tools/_dbg402.py": "(一次性调试脚本)",
    "tools/_m1_fix_future_imports.py": "(一次性脚本)",
    "tools/_m1_fix_test_root.py": "(一次性脚本)",
    "tests/__init__.py": "tests/run_all.py",
    "tests/run_all.py": "(自身即测试入口)",
}

_TESTED_RE = re.compile(r"^@tested\s+.*$", re.M)


def main():
    changed = 0
    missing = []
    for rel, value in sorted(MAPPING.items()):
        full = os.path.join(ROOT, rel.replace("/", os.sep))
        if not os.path.isfile(full):
            missing.append(rel)
            continue
        with io.open(full, encoding="utf-8") as f:
            src = f.read()
        new_line = "@tested   %s" % value
        if _TESTED_RE.search(src):
            updated = _TESTED_RE.sub(new_line, src, count=1)
        else:
            # 没有 @tested 就插在 @depends 之后，或 @layer 之后
            for anchor in ("@depends", "@layer"):
                match = re.search(r"^%s\s+.*$" % anchor, src, re.M)
                if match:
                    updated = (src[:match.end()] + "\n" + new_line
                               + src[match.end():])
                    break
            else:
                updated = src
        if updated != src:
            with io.open(full, "w", encoding="utf-8", newline="\n") as f:
                f.write(updated)
            changed += 1
            print("updated", rel, "->", value)
    if missing:
        print("\n未找到（跳过）：")
        for rel in missing:
            print("  ", rel)
    print("\n共更新 %d 个文件" % changed)
    return 0


if __name__ == "__main__":
    sys.exit(main())

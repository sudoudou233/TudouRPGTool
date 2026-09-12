# -*- coding: utf-8 -*-
"""统一测试入口：一键跑全部层，退出码可信。

@feature  none
@layer    tests
@public   main, SUITES
@depends  unittest（标准库）
@tested   (自身即测试入口)
@footprint docs/DEVLOG.md

为什么要这个入口
--------------
原两个工具的测试存在三个致命问题（见 docs/M0-现状测绘.md §5）：

* ``test_all_saves.py`` 把异常吞掉，**退出码恒为 0**（B-01 相关的验证失效）
* 修改工具 7 个测试**全都没有 ``if __name__ == "__main__"`` 守卫**，import 即执行
* 两个测试 ``import requests``（第三方依赖），干净环境直接 ImportError
* 没有一个统一命令，"全部通过"无法判定

本入口用标准库 ``unittest``，逐层运行并汇总退出码：任何一层失败即返回非零。

用法::

    python tests/run_all.py                    # 跑 unit + compat + features + integration
    python tests/run_all.py --suite unit       # 只跑一层
    python tests/run_all.py --list             # 列出各层将运行哪些测试
    python tests/run_all.py --with-local       # 额外跑真实样本层（需 TUDOU_RPGTOOL_SAMPLES）
"""

from __future__ import annotations

import argparse
import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
for path in (_ROOT, _HERE):
    if path not in sys.path:
        sys.path.insert(0, path)

#: 层 -> (起始目录, 是否默认运行, 说明)
SUITES = {
    "unit": ("unit", True, "纯单元测试（零外部依赖）"),
    "compat": ("compat", True, "原两个工具断言的可迁移版本（兼容性验证）"),
    "features": ("features", True, "各功能模块的自有测试"),
    "integration": ("integration", True, "启动服务后的端到端请求链路"),
    "local": ("local", False, "真实游戏样本测试（需环境变量指向样本，样本不入库）"),
}


def build_suite(names):
    """按层名构造合并的 TestSuite。返回 ``(suite, 加载错误列表)``。

    ``top_level_dir`` 用工程根（而非 ``tests/``）：这样功能的测试模块名是
    ``tests.features.translate.test_manifest``，**不会**与工程真实的
    ``features.translate`` 包同名冲突（后者会被优先解析，导致 ImportError）。
    """
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    errors = []
    for name in names:
        directory = os.path.join(_HERE, SUITES[name][0])
        if not os.path.isdir(directory):
            errors.append("测试层目录不存在：%s" % os.path.relpath(directory, _ROOT))
            continue
        discovered = loader.discover(start_dir=directory, top_level_dir=_ROOT,
                                    pattern="test_*.py")
        if discovered.countTestCases() == 0:
            errors.append("测试层 %s 下没有发现任何用例（目录 %s）"
                          % (name, os.path.relpath(directory, _ROOT)))
        suite.addTest(discovered)
    return suite, errors


def main(argv=None):
    parser = argparse.ArgumentParser(prog="run_all.py", description="统一测试入口")
    parser.add_argument("--suite", action="append", default=None,
                        help="只跑指定层，可重复；默认 unit+compat+features+integration")
    parser.add_argument("--with-local", action="store_true",
                        help="额外包含 local 层（真实样本）")
    parser.add_argument("--list", action="store_true", help="列出将运行的用例数")
    parser.add_argument("--quiet", action="store_true",
                        help="只输出结论行（便于 CI/脚本判定退出码）")
    parser.add_argument("-v", "--verbose", action="store_true", help="详细输出")
    args = parser.parse_args(argv)

    if args.suite:
        unknown = [s for s in args.suite if s not in SUITES]
        if unknown:
            parser.error("未知测试层：%s（可选 %s）"
                         % (", ".join(unknown), ", ".join(sorted(SUITES))))
        names = list(args.suite)
    else:
        names = [n for n, (_, default, _) in SUITES.items() if default]
        if args.with_local:
            names.append("local")

    suite, load_errors = build_suite(names)

    if args.list:
        for name in names:
            sub, _ = build_suite([name])
            print("%-12s %-4d 例  %s" % (name, sub.countTestCases(), SUITES[name][2]))
        print("%-12s %-4d 例  合计" % ("TOTAL", suite.countTestCases()))
        for err in load_errors:
            print("  ! %s" % err)
        return 1 if load_errors else 0

    quiet = args.quiet
    if not quiet:
        print("=" * 70)
        print("RPG Maker 全能工具 测试套件")
        print("工程根：%s" % _ROOT)
        print("运行层：%s" % ", ".join(names))
        print("=" * 70)

    for err in load_errors:
        print("! %s" % err)

    if quiet:
        stream = open(os.devnull, "w")
        try:
            runner = unittest.TextTestRunner(stream=stream, verbosity=0)
            result = runner.run(suite)
        finally:
            stream.close()
    else:
        runner = unittest.TextTestRunner(verbosity=2 if args.verbose else 1)
        result = runner.run(suite)

    print("结果：运行 %d，失败 %d，错误 %d，跳过 %d"
          % (result.testsRun, len(result.failures), len(result.errors),
             len(result.skipped)))
    ok = result.wasSuccessful() and not load_errors
    print("结论：%s" % ("全部通过" if ok else "存在失败"))
    if not quiet:
        print("=" * 70)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

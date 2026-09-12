# -*- coding: utf-8 -*-
"""足迹校验器自身的测试 —— 校验器必须真的会失败，否则等于没有校验。

@feature  none
@layer    tests
@public   TestMetaParsing, TestLayerInference, TestRealProjectPasses,
          TestRulesActuallyFire
@depends  tools.check_footprint
@tested   (本文件即测试)
@footprint docs/MODULES.md#tools
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import sys
import tempfile
import textwrap
import unittest

_ROOT = os.path.dirname(os.path.abspath(__file__))
while not os.path.isfile(os.path.join(_ROOT, "app.py")):
    parent = os.path.dirname(_ROOT)
    if parent == _ROOT:
        raise RuntimeError("无法定位工程根（未找到 app.py）")
    _ROOT = parent
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def load_checker():
    """按路径加载 tools/check_footprint.py（它不是包内模块）。"""
    path = os.path.join(_ROOT, "tools", "check_footprint.py")
    spec = importlib.util.spec_from_file_location("check_footprint_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CHECKER = load_checker()


class TestMetaParsing(unittest.TestCase):
    """解析模块 docstring 里的 ``@key value`` 足迹头。"""

    def parse(self, source):
        return CHECKER.parse_meta(textwrap.dedent(source))

    def test_full_header(self):
        meta, problem = self.parse('''
            # -*- coding: utf-8 -*-
            """摘要。

            @feature  translate
            @layer    core
            @public   a, b
            @public   c
            @depends  core.x
            @tested   tests/unit/test_x.py
            @footprint docs/MODULES.md#x
            @note     备注一
            @note     备注二
            """
        ''')
        self.assertIsNone(problem)
        self.assertEqual(meta["feature"], "translate")
        self.assertEqual(meta["layer"], "core")
        self.assertEqual(meta["public"], ["a", "b", "c"])
        self.assertEqual(meta["depends"], ["core.x"])
        self.assertEqual(meta["tested"], "tests/unit/test_x.py")
        self.assertEqual(meta["footprint"], "docs/MODULES.md#x")
        self.assertEqual(meta["note"], ["备注一", "备注二"])

    def test_no_docstring_reported(self):
        meta, problem = self.parse("x = 1\n")
        self.assertEqual(problem, "no-docstring")

    def test_syntax_error_reported(self):
        meta, problem = self.parse("def broken(:\n")
        self.assertIsNone(meta)
        self.assertEqual(problem, "SyntaxError")

    def test_missing_markers(self):
        meta, _problem = self.parse('"""只有摘要。"""\n')
        self.assertIsNone(meta["feature"])
        self.assertIsNone(meta["layer"])

    def test_does_not_parse_function_docstrings(self):
        """只认模块 docstring，避免把函数里的说明误当成足迹。"""
        meta, _problem = self.parse('''
            """模块摘要。"""
            def f():
                """@feature  误报
                @layer    wrong
                """
        ''')
        self.assertIsNone(meta["feature"])


class TestLayerInference(unittest.TestCase):
    def test_layer_by_prefix(self):
        cases = {
            "core/jobs.py": "core",
            "core/marshal/doc_model.py": "core",
            "features/translate/manifest.py": "features",
            "ui/server.py": "ui",
            "tools/check_footprint.py": "tools",
            "app.py": None,
        }
        for path, expected in cases.items():
            with self.subTest(path=path):
                self.assertEqual(CHECKER.expected_layer(path), expected)

    def test_module_name_for(self):
        self.assertEqual(CHECKER.module_name_for("app.py"), "app")
        self.assertEqual(CHECKER.module_name_for("core/jobs.py"), "core.jobs")


class TestRulesActuallyFire(unittest.TestCase):
    """每条规则都必须能被触发 —— 否则校验器形同虚设。

    做法：在临时目录里造一个"有缺陷的迷你工程"，跑校验器，断言
    预期的规则编号出现在错误里。
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="footprint_")
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name
        for name in ("core", "features", "ui", "tools", "docs",
                     "tests/unit", "tests/features"):
            os.makedirs(os.path.join(self.root, name), exist_ok=True)
        with open(os.path.join(self.root, "app.py"), "w", encoding="utf-8") as f:
            f.write('"""@feature  none\n@layer    app\n"""\n')
        self.write_json({"files": {"app.py": {"layer": "app"}},
                         "features": {}})

    def write_json(self, payload):
        import json
        with open(os.path.join(self.root, "docs", "footprint.json"), "w",
                  encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)

    def write(self, rel, source):
        full = os.path.join(self.root, rel.replace("/", os.sep))
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as f:
            f.write(textwrap.dedent(source))

    def run_checker(self):
        checker = CHECKER.Checker(root=self.root,
                                  footprint_path=os.path.join(self.root, "docs",
                                                              "footprint.json"))
        checker.run()
        return checker

    def rules(self, checker):
        return {f.rule for f in checker.errors}

    # ---- F-01 ----
    def test_f01_unregistered_file(self):
        self.write("core/new_module.py", '"""@feature  none\n@layer    core\n"""\n')
        self.assertIn("F-01", self.rules(self.run_checker()))

    # ---- F-02 ----
    def test_f02_missing_marks(self):
        self.write("core/nomarks.py", '"""没有任何足迹标记。"""\n')
        import json
        self.write_json({"files": {"app.py": {"layer": "app"},
                                   "core/nomarks.py": {"layer": "core"}},
                         "features": {}})
        checker = self.run_checker()
        self.assertIn("F-02", self.rules(checker))

    def test_f02_no_docstring(self):
        self.write("core/nodoc.py", "x = 1\n")
        import json
        self.write_json({"files": {"app.py": {"layer": "app"},
                                   "core/nodoc.py": {"layer": "core"}},
                         "features": {}})
        self.assertIn("F-02", self.rules(self.run_checker()))

    # ---- F-03 ----
    def test_f03_wrong_layer(self):
        self.write("core/wronglayer.py",
                   '"""@feature  none\n@layer    ui\n"""\n')
        import json
        self.write_json({"files": {"app.py": {"layer": "app"},
                                   "core/wronglayer.py": {"layer": "ui"}},
                         "features": {}})
        self.assertIn("F-03", self.rules(self.run_checker()))

    # ---- F-04 ----
    def test_f04_registered_but_missing(self):
        self.write_json({"files": {"app.py": {"layer": "app"},
                                   "core/ghost.py": {"layer": "core"}},
                         "features": {}})
        self.assertIn("F-04", self.rules(self.run_checker()))

    # ---- F-05 ----
    def test_f05_phantom_public_symbol(self):
        self.write("core/real.py", '"""@feature  none\n@layer    core\n"""\nREAL = 1\n')
        self.write_json({"files": {"app.py": {"layer": "app"},
                                   "core/real.py": {"layer": "core",
                                                    "public": ["REAL", "PHANTOM"]}},
                         "features": {}})
        checker = self.run_checker()
        self.assertIn("F-05", self.rules(checker))
        self.assertTrue(any("PHANTOM" in f.message for f in checker.errors))

    # ---- F-06 ----
    def test_f06_feature_without_manifest(self):
        os.makedirs(os.path.join(self.root, "features", "nomanifest"))
        checker = self.run_checker()
        self.assertIn("F-06", self.rules(checker))

    def test_f06_feature_without_tests(self):
        self.write("features/demo/__init__.py", "")
        self.write("features/demo/manifest.py", '''
            MANIFEST = {"id": "demo", "name": "D", "icon": "D",
                        "version": "1", "description": "d"}
        ''')
        checker = self.run_checker()
        self.assertIn("F-06", self.rules(checker))

    def test_f06_manifest_missing_required_field(self):
        self.write("features/demo/__init__.py", "")
        self.write("features/demo/manifest.py",
                   'MANIFEST = {"id": "demo"}\n')
        os.makedirs(os.path.join(self.root, "tests", "features", "demo"))
        self.write("tests/features/demo/test_x.py", "x = 1\n")
        checker = self.run_checker()
        self.assertIn("F-06", self.rules(checker))

    # ---- F-07 ----
    def test_f07_page_file_missing(self):
        self.write("features/demo/__init__.py", "")
        self.write("features/demo/manifest.py", '''
            MANIFEST = {"id": "demo", "name": "D", "icon": "D", "version": "1",
                        "description": "d",
                        "pages": [{"id": "demo", "title": "D", "module": "demo"}]}
        ''')
        os.makedirs(os.path.join(self.root, "tests", "features", "demo"))
        self.write("tests/features/demo/test_x.py", "x = 1\n")
        checker = self.run_checker()
        self.assertIn("F-07", self.rules(checker))

    # ---- F-08 ----
    def test_f08_tested_path_missing(self):
        self.write("core/t.py",
                   '"""@feature  none\n@layer    core\n@tested   tests/unit/ghost.py\n"""\n')
        self.write_json({"files": {"app.py": {"layer": "app"},
                                   "core/t.py": {"layer": "core",
                                                 "tested": "tests/unit/ghost.py"}},
                         "features": {}})
        checker = self.run_checker()
        self.assertIn("F-08", self.rules(checker))

    def test_f08_exemption_for_one_off_script(self):
        self.write("tools/oneoff.py",
                   '"""@feature  none\n@layer    tools\n@tested   (一次性脚本)\n"""\n')
        self.write_json({"files": {"app.py": {"layer": "app"},
                                   "tools/oneoff.py": {"layer": "tools",
                                                       "tested": "(一次性脚本)"}},
                         "features": {}})
        self.assertNotIn("F-08", self.rules(self.run_checker()))

    # ---- F-09 ----
    def test_f09_core_importing_ui(self):
        self.write("core/bad.py", '''
            """@feature  none
            @layer    core
            """
            import ui
            import features
        ''')
        self.write_json({"files": {"app.py": {"layer": "app"},
                                   "core/bad.py": {"layer": "core"}},
                         "features": {}})
        checker = self.run_checker()
        self.assertIn("F-09", self.rules(checker))
        self.assertEqual(len([f for f in checker.errors if f.rule == "F-09"]), 2)

    def test_f09_allows_relative_and_stdlib(self):
        self.write("core/good.py", '''
            """@feature  none
            @layer    core
            """
            import os
            from . import jobs
            from core import paths
        ''')
        self.write_json({"files": {"app.py": {"layer": "app"},
                                   "core/good.py": {"layer": "core"}},
                         "features": {}})
        self.assertNotIn("F-09", self.rules(self.run_checker()))

    # ---- F-11 ----
    def test_f11_registered_feature_without_directory(self):
        self.write_json({"files": {"app.py": {"layer": "app"}},
                         "features": {"ghost": {"id": "ghost"}}})
        self.assertIn("F-11", self.rules(self.run_checker()))

    def test_f11_directory_without_registration(self):
        self.write("features/demo/__init__.py", "")
        self.write("features/demo/manifest.py", '''
            MANIFEST = {"id": "demo", "name": "D", "icon": "D", "version": "1",
                        "description": "d"}
        ''')
        os.makedirs(os.path.join(self.root, "tests", "features", "demo"))
        self.write("tests/features/demo/test_x.py", "x = 1\n")
        self.assertIn("F-11", self.rules(self.run_checker()))

    # ---- F-12 ----
    def test_f12_missing_ui_spec(self):
        self.assertIn("F-12", self.rules(self.run_checker()))

    def test_f12_page_not_documented(self):
        os.makedirs(os.path.join(self.root, "ui", "web", "pages"))
        self.write("ui/web/pages/undocumented.js",
                   "export function render(host) {}\n")
        self.write("docs/UI_SPEC.md", "# UI 规格\n\n没有提到任何页面。\n")
        self.assertIn("F-12", self.rules(self.run_checker()))

    def test_f12_documented_page_missing(self):
        self.write("docs/UI_SPEC.md", "# UI 规格\n\n参见 pages/ghost.js\n")
        self.assertIn("F-12", self.rules(self.run_checker()))


class TestRealProjectPasses(unittest.TestCase):
    """对本工程跑校验：**M1 的完成判据之一**。"""

    def test_no_errors(self):
        checker = CHECKER.Checker(root=_ROOT)
        checker.run()
        messages = "\n".join(str(f) for f in checker.errors)
        self.assertEqual(checker.errors, [],
                         "足迹校验未通过（%d 条）：\n%s"
                         % (len(checker.errors), messages))

    def test_covers_expected_file_count(self):
        checker = CHECKER.Checker(root=_ROOT)
        checker.run()
        self.assertGreaterEqual(len(checker.source_files), 35,
                                "纳入校验的源文件过少，可能漏扫目录")

    def test_checker_exit_code_is_zero_for_this_project(self):
        import subprocess
        result = subprocess.run(
            [sys.executable, os.path.join(_ROOT, "tools", "check_footprint.py"),
             "--quiet"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            cwd=_ROOT, timeout=180)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("通过", result.stdout)

    def test_json_output_shape(self):
        import json
        import subprocess
        result = subprocess.run(
            [sys.executable, os.path.join(_ROOT, "tools", "check_footprint.py"),
             "--json"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            cwd=_ROOT, timeout=180)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["errors"], [])
        self.assertGreater(payload["checked_files"], 30)


if __name__ == "__main__":
    unittest.main(verbosity=2)

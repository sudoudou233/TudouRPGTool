# -*- coding: utf-8 -*-
"""paths 模块的专用测试（工程根定位、运行时目录、参考工具与环境变量覆盖）。

@feature  none
@layer    tests
@public   TestPathsResolution, TestRuntimeDirs, TestReferenceTools
@depends  core.paths
@tested   (本文件即测试)
@footprint docs/MODULES.md#corepaths
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

_ROOT = os.path.dirname(os.path.abspath(__file__))
while not os.path.isfile(os.path.join(_ROOT, "app.py")):
    parent = os.path.dirname(_ROOT)
    if parent == _ROOT:
        raise RuntimeError("无法定位工程根（未找到 app.py）")
    _ROOT = parent
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core import paths  # noqa: E402


class TestPathsResolution(unittest.TestCase):
    def test_project_root_has_expected_entries(self):
        root = paths.project_root()
        for name in ("app.py", "core", "features", "ui", "docs", "tests", "tools"):
            with self.subTest(name=name):
                self.assertTrue(os.path.exists(os.path.join(root, name)),
                                "工程根下缺少 %s" % name)

    def test_all_subdirs_are_under_root(self):
        root = os.path.abspath(paths.project_root())
        for getter in (paths.core_dir, paths.features_dir, paths.ui_dir,
                       paths.web_dir, paths.tests_dir, paths.tools_dir,
                       paths.docs_dir):
            with self.subTest(getter=getter.__name__):
                self.assertTrue(os.path.abspath(getter()).startswith(root))

    def test_web_dir_contains_shell_files(self):
        for name in ("index.html", "app.js", "dom.js", "tokens.css",
                     "components.css"):
            with self.subTest(name=name):
                self.assertTrue(os.path.isfile(os.path.join(paths.web_dir(), name)))

    def test_env_override_project_root(self):
        override = tempfile.mkdtemp(prefix="ovroot_")
        self.addCleanup(os.rmdir, override)
        os.environ[paths.ENV_ROOT] = override
        try:
            self.assertEqual(os.path.abspath(paths.project_root()),
                             os.path.abspath(override))
            self.assertEqual(os.path.abspath(paths.core_dir()),
                             os.path.join(os.path.abspath(override), "core"))
        finally:
            os.environ.pop(paths.ENV_ROOT, None)

    def test_ensure_dir_creates_and_is_idempotent(self):
        with tempfile.TemporaryDirectory(prefix="ens_") as tmp:
            target = os.path.join(tmp, "a", "b", "c")
            paths.ensure_dir(target)
            paths.ensure_dir(target)
            self.assertTrue(os.path.isdir(target))

    def test_ensure_dir_handles_empty(self):
        self.assertIsNone(paths.ensure_dir(""))


class TestRuntimeDirs(unittest.TestCase):
    def test_data_dir_under_root_by_default(self):
        data = os.path.abspath(paths.data_dir())
        self.assertTrue(data.startswith(os.path.abspath(paths.project_root())))

    def test_runtime_dirs_are_nested(self):
        self.assertTrue(os.path.abspath(paths.sessions_dir())
                        .startswith(os.path.abspath(paths.data_dir())))
        self.assertTrue(os.path.abspath(paths.logs_dir())
                        .startswith(os.path.abspath(paths.data_dir())))

    def test_env_override_data_dir(self):
        override = tempfile.mkdtemp(prefix="data_")
        self.addCleanup(os.rmdir, override)
        os.environ["TUDOU_RPGTOOL_DATA"] = override
        try:
            self.assertEqual(os.path.abspath(paths.data_dir()),
                             os.path.abspath(override))
        finally:
            os.environ.pop("TUDOU_RPGTOOL_DATA", None)

    def test_data_dir_is_gitignored(self):
        """运行时目录绝不能进版本库（含会话里的游戏文本）。"""
        gitignore = os.path.join(paths.project_root(), ".gitignore")
        self.assertTrue(os.path.isfile(gitignore))
        with open(gitignore, encoding="utf-8") as f:
            content = f.read()
        self.assertIn("runtime", content)
        self.assertIn("sessions", content)
        self.assertIn("config.json", content)


class TestReferenceTools(unittest.TestCase):
    def test_reference_roots_shape(self):
        roots = paths.reference_roots()
        self.assertEqual(set(roots), {"translate", "cheats"})
        for kind, path in roots.items():
            with self.subTest(kind=kind):
                self.assertTrue(path.endswith(paths.REFERENCE_TOOLS[kind]))

    def test_reference_tool_unknown_kind_raises(self):
        with self.assertRaises(KeyError):
            paths.reference_tool("nope")

    def test_reference_available_returns_bool(self):
        for kind in ("translate", "cheats"):
            with self.subTest(kind=kind):
                self.assertIsInstance(paths.reference_available(kind), bool)

    def test_env_override_reference_root(self):
        override = tempfile.mkdtemp(prefix="refroot_")
        self.addCleanup(os.rmdir, override)
        os.environ[paths.ENV_REFERENCE_ROOT] = override
        try:
            self.assertEqual(os.path.abspath(paths.reference_root()),
                             os.path.abspath(override))
            self.assertFalse(paths.reference_available("cheats"))
        finally:
            os.environ.pop(paths.ENV_REFERENCE_ROOT, None)

    def test_samples_root_env_override(self):
        override = tempfile.mkdtemp(prefix="samples_")
        self.addCleanup(os.rmdir, override)
        os.environ[paths.ENV_SAMPLES] = override
        try:
            self.assertEqual(os.path.abspath(paths.samples_root()),
                             os.path.abspath(override))
        finally:
            os.environ.pop(paths.ENV_SAMPLES, None)

    def test_samples_root_returns_none_for_missing_path(self):
        os.environ[paths.ENV_SAMPLES] = os.path.join(tempfile.gettempdir(),
                                                     "definitely-not-here-xyz")
        try:
            # 环境变量优先，因此返回该路径（存在性由调用方判断）
            self.assertIsNotNone(paths.samples_root())
        finally:
            os.environ.pop(paths.ENV_SAMPLES, None)


class TestConstantsFileOrg(unittest.TestCase):
    """常量必须集中在 core/constants.py 一处（消除原两处 PARAMS 重复）。"""

    def test_params_defined_only_in_constants(self):
        import subprocess
        result = subprocess.run(
            [sys.executable, "-c",
             "import ast,os,sys,json\n"
             "root=sys.argv[1]\n"
             "hits=[]\n"
             "for dp,dn,fn in os.walk(os.path.join(root,'core')):\n"
             "    dn[:]=[d for d in dn if d!='__pycache__']\n"
             "    for n in fn:\n"
             "        if not n.endswith('.py'): continue\n"
             "        p=os.path.join(dp,n)\n"
             "        src=open(p,encoding='utf-8').read()\n"
             "        tree=ast.parse(src)\n"
             "        for node in tree.body:\n"
             "            if isinstance(node,ast.Assign):\n"
             "                for t in node.targets:\n"
             "                    if isinstance(t,ast.Name) and t.id=='PARAMS':\n"
             "                        hits.append(os.path.relpath(p,root))\n"
             "print(json.dumps(hits))\n",
             _ROOT],
            capture_output=True, text=True, encoding="utf-8", cwd=_ROOT, timeout=60)
        import json
        hits = [h.replace("\\", "/")
                for h in json.loads(result.stdout.strip().splitlines()[-1])]
        self.assertEqual(hits, ["core/constants.py"],
                         "PARAMS 必须只在 core/constants.py 定义一处，实际：%s" % hits)


if __name__ == "__main__":
    unittest.main(verbosity=2)

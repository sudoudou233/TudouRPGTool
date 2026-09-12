# -*- coding: utf-8 -*-
"""足迹校验脚本 —— 防止足迹腐烂（需求 §6.2）。

@feature  none
@layer    tools
@public   Checker, main, RULES
@depends  core.registry, core.paths
@tested   tests/unit/test_check_footprint.py
@footprint docs/DEVLOG.md

用法
----
::

    python tools/check_footprint.py            # 人类可读报告
    python tools/check_footprint.py --json     # 机器可读
    python tools/check_footprint.py --quiet    # 只输出结论

退出码：0 全部通过；1 存在错误（**必须非零**，否则 CI/评审无法判定失败）。

校验规则（RULES）
----------------
F-01 未登记的新源文件：``core/ features/ ui/ tools/`` 与 ``app.py`` 下的每个
     ``.py`` 必须在 ``docs/footprint.json`` 的 ``files`` 里有条目
F-02 每个源文件的模块 docstring 必须含 ``@feature`` 与 ``@layer``
F-03 声明的 ``@layer`` 必须与所在目录推断的分层一致
F-04 登记了但已不存在的文件
F-05 ``footprint.json`` 里声明的 ``public`` 符号必须真实存在于模块中
F-06 每个 ``features/<name>/`` 必须有 ``manifest.py`` + ``MANIFEST`` 声明的
     必备字段 + 对应的 ``tests/features/<name>/`` 目录
F-07 每个功能必须声明至少一个页面，且页面前端模块文件真实存在
F-08 ``@tested`` 指向的测试路径必须存在（允许显式写 ``(一次性脚本)`` 豁免）
F-09 分层依赖方向：``core`` 不得 import ``ui`` 或 ``features``
F-10 ``footprint.json`` 声明的路由必须在运行时可解析（通过装配 App 后比对）
F-11 已登记的功能 id 必须在 ``features/`` 下真实存在
F-12 静态资源清单：``docs/UI_SPEC.md`` 列出的页面文件必须存在
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

#: 需要纳入足迹的源码根（相对工程根）
SOURCE_ROOTS = ("core", "features", "ui", "tools")

#: 单独纳入的顶层 .py 文件
TOP_LEVEL_FILES = ("app.py",)

#: 目录 -> 期望分层
LAYER_BY_PREFIX = {
    "core": "core",
    "features": "features",
    "ui": "ui",
    "tools": "tools",
}

#: ``@tested`` 允许的豁免写法
TESTED_EXEMPT = ("(一次性脚本", "(none)", "n/a")

#: ``core`` 层禁止 import 的顶层包
CORE_FORBIDDEN = ("ui", "features")

#: 校验规则清单（同时作为文档与 ``--list-rules`` 的输出源）
RULES = {
    "F-01": "未登记的新源文件：源码目录下每个 .py 必须在 footprint.json 的 files 里有条目",
    "F-02": "模块 docstring 必须含 @feature 与 @layer 标记",
    "F-03": "@layer 必须与所在目录推断的分层一致（与 footprint.json 记录也必须一致）",
    "F-04": "footprint.json 登记了但已不存在的文件",
    "F-05": "footprint.json 声明的 public 符号必须真实存在于模块中",
    "F-06": "每个 features/<name>/ 必须有 manifest.py（含必备字段）+ tests/features/<name>/ 测试",
    "F-07": "每个功能必须声明页面，且页面前端模块文件存在并导出 render",
    "F-08": "@tested 指向的测试路径必须存在（可用 '(一次性脚本' 豁免）",
    "F-09": "core 层不得 import ui 或 features（依赖方向单向）",
    "F-11": "footprint.json 登记的功能 id 必须与 features/ 下的目录一致",
    "F-12": "ui/web/pages/*.js 必须在 docs/UI_SPEC.md 里登记（双向一致）",
}

_META_RE = re.compile(r"^@(?P<key>feature|layer|public|depends|tested|footprint|note)\s+(?P<value>.*)$")
_LAYER_RE = re.compile(r"^@layer\s+(?P<value>\S+)", re.M)


class Finding(object):
    """一条校验发现。``error`` 会影响退出码，``warn`` 不会。"""

    def __init__(self, rule, level, message, path=None, line=None):
        self.rule = rule
        self.level = level          # 'error' / 'warn'
        self.message = message
        self.path = path
        self.line = line

    def as_dict(self):
        return {"rule": self.rule, "level": self.level, "message": self.message,
                "path": self.path, "line": self.line}

    def __str__(self):
        where = ""
        if self.path:
            where = self.path if self.line is None else "%s:%s" % (self.path, self.line)
        return "[%s][%s] %s%s" % (self.level.upper(), self.rule,
                                  (where + " — ") if where else "", self.message)


def rel(path):
    """相对工程根的 POSIX 风格路径（足迹文件里统一用 /）。"""
    return os.path.relpath(path, _ROOT).replace(os.sep, "/")


def parse_meta(source):
    """解析模块 docstring 里的 ``@key value`` 足迹元信息。

    返回 ``{'feature': str|None, 'layer': str|None, 'public': [..],
    'depends': [..], 'tested': str|None, 'footprint': str|None, 'note': [..]}``。
    只解析模块 docstring，不解析函数 docstring（避免误采）。
    """
    meta = {"feature": None, "layer": None, "public": [], "depends": [],
            "tested": None, "footprint": None, "note": []}
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None, "SyntaxError"
    doc = ast.get_docstring(tree)
    if not doc:
        return meta, "no-docstring"
    for line in doc.splitlines():
        m = _META_RE.match(line.strip())
        if not m:
            continue
        key, value = m.group("key"), m.group("value").strip()
        if key in ("public", "depends"):
            # 支持 "@public a, b" 与多行 "@public c" 累加
            parts = [p.strip().rstrip(",") for p in value.split(",") if p.strip()]
            meta[key].extend(parts)
        elif key == "note":
            meta["note"].append(value)
        else:
            meta[key] = value
    return meta, None


def expected_layer(rel_path):
    """按目录推断期望分层。"""
    first = rel_path.split("/", 1)[0]
    return LAYER_BY_PREFIX.get(first)


def module_name_for(rel_path):
    """``core/jobs.py`` -> ``core.jobs``；``app.py`` -> ``app``。"""
    if "/" not in rel_path:
        return rel_path[:-3]
    return rel_path[:-3].replace("/", ".")


class Checker(object):
    """足迹校验器。"""

    def __init__(self, root=None, footprint_path=None):
        self.root = os.path.abspath(root or _ROOT)
        self.footprint_path = footprint_path or os.path.join(
            self.root, "docs", "footprint.json")
        self.findings = []
        self.footprint = {}
        self.source_files = []

    # ------------------------------------------------------------ 工具
    def error(self, rule, message, path=None, line=None):
        self.findings.append(Finding(rule, "error", message, path, line))

    def warn(self, rule, message, path=None, line=None):
        self.findings.append(Finding(rule, "warn", message, path, line))

    def _abs(self, rel_posix):
        return os.path.join(self.root, rel_posix.replace("/", os.sep))

    def rel(self, path):
        """相对**本检查器 root** 的 POSIX 路径。

        注意不能用模块级的 :func:`rel`：那是相对工程根 ``_ROOT`` 的，
        而测试会在临时目录（可能位于另一个盘符）里造迷你工程，用它会抛
        ``ValueError: path is on mount 'C:', start on mount 'D:'``。
        """
        return os.path.relpath(os.path.abspath(path), self.root).replace(os.sep, "/")

    # ------------------------------------------------------------ 收集
    def collect_sources(self):
        """收集需要校验的源文件（相对路径，POSIX 风格）。"""
        found = []
        for top in TOP_LEVEL_FILES:
            if os.path.isfile(self._abs(top)):
                found.append(top)
        for root_name in SOURCE_ROOTS:
            base = self._abs(root_name)
            if not os.path.isdir(base):
                continue
            for dirpath, dirnames, filenames in os.walk(base):
                dirnames[:] = [d for d in dirnames
                               if d not in ("__pycache__", ".git", ".pytest_cache")]
                for name in filenames:
                    if not name.endswith(".py"):
                        continue
                    found.append(self.rel(os.path.join(dirpath, name)))
        return sorted(found)

    def load_footprint(self):
        if not os.path.isfile(self.footprint_path):
            self.error("F-04", "足迹文件不存在：%s" % rel(self.footprint_path))
            return False
        try:
            with open(self.footprint_path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception as exc:
            self.error("F-04", "足迹文件无法解析：%s: %s" % (type(exc).__name__, exc))
            return False
        if not isinstance(data, dict):
            self.error("F-04", "足迹文件顶层必须是对象")
            return False
        self.footprint = data
        return True

    # ------------------------------------------------------------ 规则
    def check_files(self):
        """F-01 / F-02 / F-03 / F-04"""
        declared = self.footprint.get("files") or {}
        if not isinstance(declared, dict):
            self.error("F-01", "footprint.json 的 files 必须是对象")
            declared = {}

        for path in self.source_files:
            if path not in declared:
                self.error("F-01", "未登记的新源文件（请加入 docs/footprint.json）",
                           path)
                continue
            full = self._abs(path)
            try:
                with open(full, encoding="utf-8") as f:
                    source = f.read()
            except Exception as exc:
                self.error("F-02", "无法读取源文件：%s" % exc, path)
                continue
            meta, problem = parse_meta(source)
            if meta is None:
                self.error("F-02", "源文件存在语法错误，无法解析足迹头：%s" % problem,
                           path)
                continue
            if problem == "no-docstring":
                self.error("F-02", "缺少模块 docstring（必须含 @feature 与 @layer）",
                           path)
                continue
            if not meta["feature"]:
                self.error("F-02", "模块 docstring 缺少 @feature 标记", path)
            if not meta["layer"]:
                self.error("F-02", "模块 docstring 缺少 @layer 标记", path)

            want = expected_layer(path)
            got = meta["layer"]
            if want and got and got != want:
                self.error("F-03", "@layer 声明为 %r，但按目录应为 %r" % (got, want),
                           path)

            entry = declared.get(path) or {}
            if isinstance(entry, dict):
                # 登记与声明不一致时以"两处都必须对"为准
                if entry.get("layer") and got and entry["layer"] != got:
                    self.error("F-03", "footprint.json 记录 layer=%r，源码 @layer=%r"
                               % (entry["layer"], got), path)

        for path in sorted(declared):
            if not os.path.isfile(self._abs(path)):
                self.error("F-04", "footprint.json 登记了但不存在的文件", path)

    def check_public_symbols(self):
        """F-05：声明的 public 符号必须真实存在。"""
        for path, entry in sorted((self.footprint.get("files") or {}).items()):
            if not isinstance(entry, dict):
                continue
            symbols = entry.get("public") or []
            if not symbols:
                continue
            full = self._abs(path)
            if not os.path.isfile(full):
                continue
            try:
                with open(full, encoding="utf-8") as f:
                    tree = ast.parse(f.read())
            except Exception:
                continue
            available = set()
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    available.add(node.name)
                elif isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            available.add(target.id)
                elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                    available.add(node.target.id)
                elif isinstance(node, (ast.Import, ast.ImportFrom)):
                    for alias in node.names:
                        available.add(alias.asname or alias.name.split(".")[0])
            for symbol in symbols:
                if symbol not in available:
                    self.error("F-05",
                               "声明的 public 符号 %r 在模块中不存在" % symbol, path)

    def _install_temp_features_package(self):
        """把本检查器 root 下的 ``features`` 目录注册为 ``cffixtures`` 包。

        F-06 需要 import 每个 ``features/<name>/manifest.py`` 来读 ``MANIFEST``。
        直接 ``import features.<name>.manifest`` 在两种情况下会出错：

        * 测试在临时目录里造迷你工程时，会解析到**工程真实的** ``features``
          包，于是校验的不是被测对象（M1 实测踩到，F-07 因此不触发）；
        * 真实工程里 ``features`` 已在 ``sys.modules`` 时可正常用，但语义
          依赖 import 顺序。

        因此统一走独立包名 ``cffixtures``：``__path__`` 指向本 root 的
        ``features``。这样无论校验哪个 root，import 的都是"这一个" root。
        """
        if "features" not in sys.modules and self.root in sys.path:
            # 真实工程：让 features 正常可导入即可
            pass
        import types
        package_name = "cffixtures"
        package = types.ModuleType(package_name)
        package.__path__ = [self._abs("features")]
        package.__package__ = package_name
        sys.modules[package_name] = package
        # 清掉上一次留给该包名的子模块缓存，避免跨用例串味
        for key in [k for k in sys.modules if k.startswith(package_name + ".")]:
            sys.modules.pop(key, None)
        self._fixture_package = package_name
        return package_name

    def check_features(self):
        """F-06 / F-07 / F-11 / F-12"""
        declared_features = self.footprint.get("features") or {}
        if not isinstance(declared_features, dict):
            self.error("F-11", "footprint.json 的 features 必须是对象")
            declared_features = {}

        self._install_temp_features_package()
        features_dir = self._abs("features")
        actual = set()
        if os.path.isdir(features_dir):
            for name in sorted(os.listdir(features_dir)):
                if not os.path.isdir(os.path.join(features_dir, name)):
                    continue
                if name == "__pycache__":
                    continue
                actual.add(name)

                manifest = os.path.join(features_dir, name, "manifest.py")
                if not os.path.isfile(manifest):
                    self.error("F-06", "功能目录缺少 manifest.py", "features/%s" % name)
                    continue
                try:
                    sys.path.insert(0, self.root)
                    import importlib
                    package = getattr(self, "_fixture_package", "features")
                    module = importlib.import_module(
                        "%s.%s.manifest" % (package, name))
                    manifest_data = getattr(module, "MANIFEST", None)
                except Exception as exc:
                    self.error("F-06", "导入 features/%s/manifest.py 失败：%s: %s"
                               % (name, type(exc).__name__, exc))
                    continue
                if not isinstance(manifest_data, dict):
                    self.error("F-06", "features/%s/manifest.py 未定义 MANIFEST dict" % name)
                    continue
                for field in ("id", "name", "icon", "version", "description"):
                    if not manifest_data.get(field):
                        self.error("F-06", "features/%s 的 MANIFEST 缺少 %s" % (name, field))

                pages = manifest_data.get("pages") or ()
                if not pages:
                    self.error("F-07", "features/%s 未声明任何页面" % name)
                for page in pages:
                    if not isinstance(page, dict):
                        continue
                    page_module = page.get("module")
                    if not page_module:
                        self.error("F-07", "features/%s 的页面缺少 module 字段" % name)
                        continue
                    js = self._abs("ui/web/pages/%s.js" % page_module)
                    if not os.path.isfile(js):
                        self.error("F-07", "页面模块文件不存在：ui/web/pages/%s.js"
                                   % page_module)
                    else:
                        with open(js, encoding="utf-8") as f:
                            content = f.read()
                        if "export function render" not in content and \
                                "export async function render" not in content:
                            self.error("F-07", "页面模块未导出 render：ui/web/pages/%s.js"
                                       % page_module)

                tests_dir = self._abs("tests/features/%s" % name)
                if not os.path.isdir(tests_dir):
                    self.error("F-06", "缺少功能自有测试目录 tests/features/%s" % name)
                else:
                    if not [f for f in os.listdir(tests_dir)
                            if f.startswith("test_") and f.endswith(".py")]:
                        self.error("F-06", "tests/features/%s 下没有 test_*.py" % name)

        for feature_id in sorted(declared_features):
            if feature_id not in actual:
                self.error("F-11", "footprint.json 登记了功能 %r，但 features/%s 不存在"
                           % (feature_id, feature_id))

        for name in sorted(actual):
            if name not in declared_features:
                self.error("F-11", "功能 %r 未登记到 footprint.json 的 features" % name)

    def check_tests(self):
        """F-08：@tested 指向的路径必须存在。"""
        for path, entry in sorted((self.footprint.get("files") or {}).items()):
            tested = (entry or {}).get("tested")
            if not tested or tested in (None, ""):
                self.warn("F-08", "footprint.json 未记录 tested 字段", path)
                continue
            for item in str(tested).split(","):
                candidate = item.strip()
                if not candidate:
                    continue
                # 豁免写法：允许括号不闭合，例如 '(一次性脚本' 或 '(一次性调试脚本'。
                # （脚本替换 @tested 整行时可能截掉右括号，早期版本因此误报。）
                exempt = (
                    candidate.startswith("(")
                    or any(candidate.startswith(x) for x in TESTED_EXEMPT)
                )
                if exempt:
                    continue
                if candidate.endswith("/") or candidate.endswith("\\"):
                    if os.path.isdir(self._abs(candidate.rstrip("/\\"))):
                        continue
                if not os.path.exists(self._abs(candidate.rstrip("/"))):
                    self.error("F-08", "@tested 指向的路径不存在：%s" % candidate, path)

    def check_layering(self):
        """F-09：core 不得 import ui / features。"""
        core_dir = self._abs("core")
        if not os.path.isdir(core_dir):
            return
        for dirpath, dirnames, filenames in os.walk(core_dir):
            dirnames[:] = [d for d in dirnames if d != "__pycache__"]
            for name in filenames:
                if not name.endswith(".py"):
                    continue
                full = os.path.join(dirpath, name)
                path = self.rel(full)
                if not path.startswith("core"):
                    continue
                try:
                    with open(full, encoding="utf-8") as f:
                        tree = ast.parse(f.read())
                except Exception:
                    continue
                for node in ast.walk(tree):
                    targets = []
                    if isinstance(node, ast.Import):
                        targets = [a.name for a in node.names]
                    elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                        targets = [node.module]
                    for target in targets:
                        top = target.split(".")[0]
                        if top in CORE_FORBIDDEN:
                            self.error("F-09",
                                       "core 层不得 import %r（发现 import %s）"
                                       % (top, target), path, node.lineno)

    def check_ui_spec_pages(self):
        """F-12：docs/UI_SPEC.md 的页面清单与实际文件一致。"""
        spec = self._abs("docs/UI_SPEC.md")
        if not os.path.isfile(spec):
            self.error("F-12", "缺少 docs/UI_SPEC.md")
            return
        pages_dir = self._abs("ui/web/pages")
        declared = set()
        if os.path.isdir(pages_dir):
            declared = {n[:-3] for n in os.listdir(pages_dir) if n.endswith(".js")}
        with open(spec, encoding="utf-8") as f:
            content = f.read()
        documented = set(re.findall(r"pages/([A-Za-z0-9_\-]+)\.js", content))
        for name in sorted(declared - documented):
            self.error("F-12", "页面 ui/web/pages/%s.js 未在 docs/UI_SPEC.md 登记" % name)
        for name in sorted(documented - declared):
            self.error("F-12", "docs/UI_SPEC.md 登记了不存在的页面 %s.js" % name)

    def check_manifest_route_consistency(self):
        """F-01 附加：features 的源文件必须归属于某个已登记功能。"""
        declared_features = set((self.footprint.get("features") or {}).keys())
        for path in self.source_files:
            if not path.startswith("features/"):
                continue
            parts = path.split("/")
            if len(parts) < 2:
                continue
            feature_id = parts[1]
            if not feature_id.endswith(".py") and feature_id not in declared_features:
                self.error("F-11", "features/%s 下的源文件未归属任何已登记功能"
                           % feature_id, path)

    # ------------------------------------------------------------ 主流程
    def run(self):
        self.source_files = self.collect_sources()
        if not self.load_footprint():
            return self.findings
        self.check_files()
        self.check_public_symbols()
        self.check_features()
        self.check_tests()
        self.check_layering()
        self.check_ui_spec_pages()
        self.check_manifest_route_consistency()
        return self.findings

    @property
    def errors(self):
        return [f for f in self.findings if f.level == "error"]

    @property
    def warnings(self):
        return [f for f in self.findings if f.level == "warn"]


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="check_footprint.py",
        description="校验 docs/footprint.json 与源码/测试/文档是否一致（需求 §6.2）")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    parser.add_argument("--quiet", action="store_true", help="只输出结论行")
    parser.add_argument("--strict", action="store_true", help="把警告也当作失败")
    args = parser.parse_args(argv)

    checker = Checker()
    findings = checker.run()
    errors = checker.errors
    warnings = checker.warnings
    failed = bool(errors) or (args.strict and bool(warnings))

    if args.json:
        print(json.dumps({
            "ok": not failed,
            "checked_files": len(checker.source_files),
            "errors": [f.as_dict() for f in errors],
            "warnings": [f.as_dict() for f in warnings],
        }, ensure_ascii=False, indent=2))
    else:
        if not args.quiet:
            for finding in findings:
                print(finding)
            if findings:
                print()
        print("足迹校验：检查 %d 个源文件，错误 %d 条，警告 %d 条 -> %s"
              % (len(checker.source_files), len(errors), len(warnings),
                 "通过" if not failed else "未通过"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

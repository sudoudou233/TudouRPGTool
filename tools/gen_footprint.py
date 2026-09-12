# -*- coding: utf-8 -*-
"""生成/刷新 docs/footprint.json（足迹校验用的机器可读映射）。

@feature  none
@layer    tools
@public   build_footprint, main
@depends  core.paths, tools/check_footprint.py
@tested   tests/unit/test_check_footprint.py
@footprint docs/MODULES.md#toolsgen_footprint

用法::

    python tools/gen_footprint.py            # 就地刷新 docs/footprint.json
    python tools/gen_footprint.py --check    # 只比较，不写盘（CI 用）

设计取舍（docs/DECISIONS.md ADR-006）
------------------------------------
``footprint.json`` 的**人类可读镜像**分两处维护，各自只写一次：

* ``docs/MODULES.md``    —— 文件 → 职责 → 公开 API → 谁调用 → 改它影响什么
* ``docs/FEATURES.md``   —— 功能 id → 名称 → 入口 → 依赖文件 → 测试 → 验证命令

本脚本**不读**这两个 markdown（避免脆弱的文档解析），只从源码 docstring 的
``@feature/@layer/@public/@depends/@tested`` 重新生成 JSON，因此 JSON 永远与
源码一致；而 markdown 与源码的一致性由 ``check_footprint.py`` 的反向检查
（F-08 测试路径存在、F-11 功能登记、F-12 页面清单）兜底。
"""

from __future__ import annotations

import argparse
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import importlib.util


def _load_checker_module():
    spec = importlib.util.spec_from_file_location(
        "check_footprint", os.path.join(_HERE, "check_footprint.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


#: 固定测试命令（供下一个 AI 一键复现；由 tests/run_all.py 提供实现）
TEST_COMMANDS = {
    "footprint": "python tools/check_footprint.py",
    "unit": "python tests/run_all.py --suite unit",
    "compat": "python tests/run_all.py --suite compat",
    "features": "python tests/run_all.py --suite features",
    "integration": "python tests/run_all.py --suite integration",
    "all": "python tests/run_all.py",
    "selfcheck": "python app.py --check",
    "sample_compare": "python tests/local/compare_engines.py  （需真实样本，见 docs/DECISIONS.md ADR-005）",
}

#: 分层说明（供 AI 快速理解依赖方向）
LAYERS = {
    "app": "唯一入口：装配 core/ui/features 并启动服务（app.py）",
    "core": "与界面无关的纯逻辑；不得 import ui 或 features（F-09 强制）",
    "features": "可插拔功能模块；通过 manifest.py 的 register(ctx) 装配",
    "ui": "界面层：HTTP 服务 + 静态资源 + 页面模块",
    "tools": "开发期脚本（足迹校验、生成器）；不参与运行时",
}


def build_footprint(root=None):
    """扫描源码并构造 footprint.json 的内容。"""
    root = root or _ROOT
    checker_mod = _load_checker_module()
    checker = checker_mod.Checker(root=root)

    files = {}
    for rel_path in checker.collect_sources():
        full = os.path.join(root, rel_path.replace("/", os.sep))
        try:
            with open(full, encoding="utf-8") as f:
                source = f.read()
        except Exception:
            continue
        meta, problem = checker_mod.parse_meta(source)
        entry = {}
        if meta:
            entry["feature"] = meta["feature"] or "none"
            entry["layer"] = meta["layer"] or ""
            entry["public"] = [s for s in meta["public"] if s]
            entry["depends"] = [s for s in meta["depends"] if s]
            entry["tested"] = meta["tested"] or ""
            entry["footprint"] = meta["footprint"] or ""
            notes = " ".join(meta["note"])
            entry["vendored"] = "vendored" in notes
            if notes:
                entry["note"] = notes
        if problem:
            entry["parse_problem"] = problem
        entry["lines"] = len(source.split("\n"))
        files[rel_path] = entry

    # ---- 功能清单：从 features/*/manifest.py 读，与源码保持同源 ----
    features = {}
    features_dir = os.path.join(root, "features")
    if os.path.isdir(features_dir):
        sys.path.insert(0, root)
        for name in sorted(os.listdir(features_dir)):
            manifest_path = os.path.join(features_dir, name, "manifest.py")
            if not os.path.isfile(manifest_path):
                continue
            module_name = "features.%s.manifest" % name
            try:
                import importlib
                module = importlib.import_module(module_name)
                data = dict(getattr(module, "MANIFEST", {}) or {})
            except Exception as exc:
                features[name] = {"error": "%s: %s" % (type(exc).__name__, exc)}
                continue
            data.pop("health", None)       # 函数对象不可序列化
            data["directory"] = "features/%s" % name
            data["manifest"] = "features/%s/manifest.py" % name
            data["tests"] = "tests/features/%s" % name
            data["api_prefix"] = data.get("api_prefix", "")
            data["pages"] = [dict(p) for p in (data.get("pages") or ())]
            features[data.get("id") or name] = data

    payload = {
        "schema": 1,
        "project": {
            "name": "RPG Maker 全能工具",
            "package": "tudou_rpgtool",
            "root_relative": ".",
            "language": "python",
            "min_python": "3.8",
            "third_party_deps": [],
            "entry": "app.py",
        },
        "generated_by": "tools/gen_footprint.py",
        "sources": {
            "roots": ["core", "features", "ui", "tools"],
            "top_level": ["app.py"],
            "static": ["ui/web/index.html", "ui/web/app.js", "ui/web/dom.js",
                       "ui/web/tokens.css", "ui/web/components.css"],
        },
        "layers": LAYERS,
        "commands": TEST_COMMANDS,
        "features": features,
        "files": files,
        "documents": {
            "AGENTS.md": "给下一个 AI 的开工指令",
            "docs/STATE.md": "当前状态快照（接手第一份要读的文件）",
            "docs/ARCHITECTURE.md": "分层、数据流、模块依赖图、关键设计取舍",
            "docs/MODULES.md": "模块地图：文件 → 职责 → 公开 API → 谁调用 → 影响面",
            "docs/FEATURES.md": "功能注册表（含新增功能的完整步骤）",
            "docs/DECISIONS.md": "决策记录 ADR",
            "docs/DEVLOG.md": "开发足迹（追加式时间线 + 迁移对照表）",
            "docs/UI_SPEC.md": "设计令牌、组件清单、页面清单、交互范式",
            "docs/ROADMAP.md": "已规划未做的功能与预留扩展点",
            "docs/OPEN-QUESTIONS.md": "需人类裁决的事项",
            "docs/M0-现状测绘.md": "M0 现状测绘报告（两个原工具的完整测绘）",
            "docs/迁移对照表.md": "原工具功能 → 新工程位置 → 测试 → 验证状态",
        },
    }
    return payload


def main(argv=None):
    parser = argparse.ArgumentParser(prog="gen_footprint.py")
    parser.add_argument("--check", action="store_true",
                        help="只比较是否一致，不写盘")
    parser.add_argument("--out", default=None, help="输出路径（默认 docs/footprint.json）")
    args = parser.parse_args(argv)

    target = args.out or os.path.join(_ROOT, "docs", "footprint.json")
    payload = build_footprint()
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"

    if args.check:
        if not os.path.isfile(target):
            print("footprint.json 不存在：%s" % target)
            return 1
        with open(target, encoding="utf-8") as f:
            current = f.read()
        if current != text:
            print("footprint.json 与源码不一致，请运行 python tools/gen_footprint.py")
            return 1
        print("footprint.json 与源码一致（%d 个文件，%d 个功能）"
              % (len(payload["files"]), len(payload["features"])))
        return 0

    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    print("已写入 %s：%d 个文件，%d 个功能"
          % (os.path.relpath(target, _ROOT), len(payload["files"]),
             len(payload["features"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())

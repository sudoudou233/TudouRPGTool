# -*- coding: utf-8 -*-
"""开发期一次性脚本（M3a 用）：修 vendored translators.py / session.py 的 import。

@feature  none
@layer    tools
@public   PLAN, main
@depends  (stdlib only)
@tested   (一次性脚本)
@footprint docs/DEVLOG.md
@note     M1 先只做静态可导入性保障；真正的功能接线在 M3a。
          M3a 完成后本脚本删除。
"""

from __future__ import annotations

import ast
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REF = r"D:\test1\rpgtool\rpgmaker_translation_tool\tool"

PLAN = {
    "features/translate/translators.py": (
        os.path.join(REF, "translators.py"),
        [
            ("from .textutil import collect_segments, rebuild",
             "from core.textutil import collect_segments, rebuild"),
            ("from . import build", "from core.safety import backup as build"),
        ],
        [
            "@feature  translate",
            "@layer    features",
            "@public   build_translator, translate_entries, TranslateError,",
            "@public   TruncatedError, GoogleTranslator, OpenAICompatibleTranslator,",
            "@public   DeepLTranslator, _http",
            "@depends  core.textutil, core.safety.backup",
            "@tested   tests/compat/test_translators.py",
            "@footprint docs/FEATURES.md#translate",
            "@note     vendored：来自 rpgmaker_translation_tool/tool/translators.py。",
            "@note     M3a 接线时改为按功能模块暴露 register(ctx)。",
        ],
    ),
    "features/translate/session.py": (
        os.path.join(REF, "session.py"),
        [
            ("from . import engines", "from core import engines"),
            ("from . import mv_mz", "from core.formats import mv_mz_data as mv_mz"),
            ("from . import vxace", "from core.formats import rgss_data as vxace"),
        ],
        [
            "@feature  translate",
            "@layer    features",
            "@public   Session, ScanOptions, DEFAULT_OPTIONS",
            "@depends  core.engines, core.formats.mv_mz_data, core.formats.rgss_data",
            "@tested   tests/compat/test_translate_job.py",
            "@footprint docs/FEATURES.md#translate",
            "@note     vendored：来自 rpgmaker_translation_tool/tool/session.py。",
            "@note     注意 engines.detect 的返回结构已是新 core 的统一结构，",
            "@note     M3a 需核对 info 字段使用点（原实现用 engine_name/supported）。",
        ],
    ),
}


def find_first_statement(lines):
    start = None
    quote = None
    i = 0
    while i < len(lines):
        s = lines[i].strip()
        if not s or s.startswith("#"):
            i += 1
            continue
        for q in ('"""', "'''"):
            if s.startswith(q):
                start, quote = i, q
                break
        if start is None:
            return None, None
        if s.endswith(quote) and len(s) > len(quote):
            return start, i
        i += 1
        while i < len(lines):
            if lines[i].rstrip().endswith(quote):
                return start, i
            i += 1
        return start, len(lines) - 1
    return None, None


def merge_header(lines, start, end, header):
    first = lines[start]
    stripped = first.strip()
    quote = '"""' if stripped.startswith('"""') else "'''"
    indent = first[: len(first) - len(first.lstrip())]
    body = stripped[len(quote):]
    if body.endswith(quote):
        body = body[: -len(quote)]
    block = list(lines[start + 1:end])
    if block and block[-1].rstrip().endswith(quote):
        block = block[:-1]

    merged = [(indent or "") + quote, body.strip(), ""]
    merged.extend(header)
    if block:
        merged.append("")
        merged.extend(block)
    merged.append((indent or "") + quote)
    out = lines[:start] + merged + lines[end + 1:]
    text = "\n".join(out)
    while "\n\n\n\n" in text:
        text = text.replace("\n\n\n\n", "\n\n\n")
    return text


def process(rel, spec):
    src, rewrites, header = spec
    full = os.path.join(ROOT, rel.replace("/", os.sep))
    if not os.path.isfile(src):
        return "MISSING-SOURCE %s" % rel
    shutil.copyfile(src, full)
    with open(full, "r", encoding="utf-8") as f:
        text = f.read()
    lines = text.split("\n")
    start, end = find_first_statement(lines)
    if start is None:
        return "NO-DOCSTRING %s" % rel
    text = merge_header(lines, start, end, header)
    for old, new in rewrites:
        if old in text:
            text = text.replace(old, new)
    try:
        ast.parse(text)
    except SyntaxError as exc:
        shutil.copyfile(src, full)
        return "SYNTAX-FAIL %s line %s: %s（已回退）" % (rel, exc.lineno, exc.msg)
    with open(full, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return "ok %s" % rel


def main():
    bad = 0
    for rel in sorted(PLAN):
        r = process(rel, PLAN[rel])
        print(r)
        if not r.startswith("ok"):
            bad += 1
    print("\nfailures:", bad)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

# -*- coding: utf-8 -*-
"""开发期一次性脚本：正确地为 vendored 源文件加足迹头（合并进模块 docstring）。

@feature  none
@layer    tools
@public   PLAN, main
@depends  (stdlib only)
@tested   (一次性脚本)
@footprint docs/DEVLOG.md
@note     前一版 tools/_m1_patch_vendored.py 把足迹头当作"第二个字符串表达式"
          插在模块 docstring 之后，导致 ``from __future__`` 不再位于文件最前，
          产生 SyntaxError。本脚本改为：先把 vendored 文件还原为参考实现的
          原始内容，再把足迹头**合并进模块 docstring 内部**（docstring 必须
          是文件中第一条语句，因此合并是唯一安全做法），最后改写 import。
"""

from __future__ import annotations

import ast
import os
import re
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REF_TRANSLATE = r"D:\test1\rpgtool\rpgmaker_translation_tool"
REF_CHEATS = r"D:\test1\rpgtool\rpgmaker_cheating_tool"

#: 目标文件 -> (参考源文件绝对路径, [(旧, 新) import 改写], 足迹头行列表)
PLAN = {
    "core/textutil.py": (
        os.path.join(REF_TRANSLATE, "tool", "textutil.py"),
        [],
        [
            "@feature  translate",
            "@layer    core",
            "@public   CONTROL_RE, split_text, has_real_text, collect_segments, rebuild",
            "@depends  (stdlib only)",
            "@tested   tests/unit/test_textutil.py",
            "@footprint docs/MODULES.md#coretextutil",
            "@note     vendored：来自 rpgmaker_translation_tool/tool/textutil.py。",
            "@note     已知问题见 docs/M0-现状测绘.md section 3.5：原注释声称支持",
            "@note     \\{ \\} \\^ \\| \\. \\! \\> \\< \\$ 这些符号型转义，但 CONTROL_RE",
            "@note     要求反斜杠后必须是字母，因此它们从不被匹配（M2a 处置）。",
            "@note     原 translate_segments() 是全仓零调用的死代码，未搬入。",
        ],
    ),
    "core/marshal/doc_model.py": (
        os.path.join(REF_CHEATS, "rmarshal.py"),
        [],
        [
            "@feature  none",
            "@layer    core",
            "@public   Node, Parser, loads, dumps, load_streams, mark_dirty, VERSION",
            "@depends  (stdlib only)",
            "@tested   tests/compat/test_marshal_roundtrip.py",
            "@footprint docs/MODULES.md#coremarshal",
            "@note     vendored：来自 rpgmaker_cheating_tool/rmarshal.py（原样搬入）。",
            "@note     已知缺陷 B-10（Parser._fixnum 重复定义，XP/VX 写回漂移）",
            "@note     在 M2a 修复；M2b 收敛后本文件删除。",
        ],
    ),
    "core/marshal/value_model.py": (
        os.path.join(REF_TRANSLATE, "tool", "marshal.py"),
        [],
        [
            "@feature  none",
            "@layer    core",
            "@public   loads, dumps, RMStr, RMIvar, RMObject, RMDict, RMSymbol,",
            "@public   RMStruct, RMUserDefined, RMUserMarshal, RMRegexp, RMData,",
            "@public   RMClass, RMModule, RMFloat",
            "@depends  (stdlib only)",
            "@tested   tests/compat/test_marshal_value_model.py",
            "@footprint docs/MODULES.md#coremarshal",
            "@note     vendored：来自 rpgmaker_translation_tool/tool/marshal.py（原样搬入）。",
            "@note     已知缺陷 B-12（bignum 写回崩溃）、B-13、B-28（gbk→cp932 误映射）",
            "@note     在 M2b 收敛时随门面层一并处置。",
        ],
    ),
    "core/formats/mv_mz_data.py": (
        os.path.join(REF_TRANSLATE, "tool", "mv_mz.py"),
        [("from .textutil import has_real_text", "from ..textutil import has_real_text")],
        [
            "@feature  translate",
            "@layer    core",
            "@public   extract, apply_to_files, TEXT_CODES, WRAPPER_KEYS",
            "@depends  core.textutil",
            "@tested   tests/compat/test_translate_extract.py",
            "@footprint docs/MODULES.md#coreformats",
            "@note     vendored：来自 rpgmaker_translation_tool/tool/mv_mz.py。",
            "@note     M2b 抽出 core/formats/jsoncodec.py 后本文件只保留业务规则。",
        ],
    ),
    "core/formats/rgss_data.py": (
        os.path.join(REF_TRANSLATE, "tool", "vxace.py"),
        [
            ("from .textutil import has_real_text", "from ..textutil import has_real_text"),
            ("from . import marshal", "from ..marshal import value_model as marshal"),
            ("from .mv_mz import TEXT_CODES", "from .mv_mz_data import TEXT_CODES"),
        ],
        [
            "@feature  translate",
            "@layer    core",
            "@public   extract, apply_to_files",
            "@depends  core.textutil, core.marshal.value_model, core.formats.mv_mz_data",
            "@tested   tests/compat/test_translate_extract.py",
            "@footprint docs/MODULES.md#coreformats",
            "@note     vendored：来自 rpgmaker_translation_tool/tool/vxace.py。",
            "@note     已知缺陷 B-02（非原子写）、B-13（original 参数未用于校验）。",
        ],
    ),
    "core/formats/mv_save.py": (
        os.path.join(REF_CHEATS, "mvdata.py"),
        [("import lzstring", "from . import lzstring")],
        [
            "@feature  cheats",
            "@layer    core",
            "@public   GameDataMV, SaveFileMV, META_KEYS",
            "@depends  core.formats.lzstring",
            "@tested   tests/compat/test_mv_save.py",
            "@footprint docs/MODULES.md#coreformats",
            "@note     vendored：来自 rpgmaker_cheating_tool/mvdata.py。",
        ],
    ),
    "core/formats/rgss_save.py": (
        os.path.join(REF_CHEATS, "rpgdata.py"),
        [("import rmarshal", "from ..marshal import doc_model as rmarshal")],
        [
            "@feature  cheats",
            "@layer    core",
            "@public   GameData, SaveFile, sync_dirty, find_top_hash",
            "@depends  core.marshal.doc_model",
            "@tested   tests/compat/test_rgss_save.py",
            "@footprint docs/MODULES.md#coreformats",
            "@note     vendored：来自 rpgmaker_cheating_tool/rpgdata.py。",
        ],
    ),
    "core/formats/lzstring.py": (
        os.path.join(REF_CHEATS, "lzstring.py"),
        [],
        [
            "@feature  cheats",
            "@layer    core",
            "@public   compress, decompress, compress_to_base64, decompress_from_base64",
            "@depends  (stdlib only)",
            "@tested   tests/compat/test_lzstring.py",
            "@footprint docs/MODULES.md#coreformats",
            "@note     vendored：来自 rpgmaker_cheating_tool/lzstring.py。",
        ],
    ),
    "core/safety/backup.py": (
        os.path.join(REF_TRANSLATE, "tool", "build.py"),
        [
            ("from . import fontutil", "from . import fontutil"),
            ("from . import marshal", "from ..marshal import value_model as marshal"),
            ("from . import mv_mz", "from ..formats import mv_mz_data as mv_mz"),
            ("from . import vxace", "from ..formats import rgss_data as vxace"),
        ],
        [
            "@feature  translate",
            "@layer    core",
            "@public   build, backup_files, restore_backup, list_backups, apply_font,",
            "@public   default_target_dir, resolve_target_dir, next_free_dir, BACKUP_PREFIX",
            "@depends  core.marshal.value_model, core.safety.fontutil",
            "@tested   tests/compat/test_build_backup.py",
            "@footprint docs/MODULES.md#coresafety",
            "@note     vendored：来自 rpgmaker_translation_tool/tool/build.py。",
            "@note     已知缺陷（M2a 必修）：B-01（rmtree 先删后拷）、B-03（字体兜底",
            "@note     覆盖不可还原）、B-04（还原不完整）、B-05（覆盖无二次确认）、",
            "@note     B-06（无回滚）、B-26（模块顶层 import winreg，非 Windows 失败）。",
        ],
    ),
    "core/safety/fontutil.py": (
        os.path.join(REF_TRANSLATE, "tool", "fontutil.py"),
        [],
        [
            "@feature  translate",
            "@layer    core",
            "@public   extract_family, safe_filename",
            "@depends  (stdlib only)",
            "@tested   tests/compat/test_fontutil.py",
            "@footprint docs/MODULES.md#coresafety",
            "@note     vendored：来自 rpgmaker_translation_tool/tool/fontutil.py。",
        ],
    ),
}

_TS_OPEN = re.compile(r'^(?P<indent>[ \t]*)(?P<q>"""|\'\'\')')


def find_first_statement(lines):
    """返回第一条语句的起止行号（0-based，含），即模块 docstring。"""
    start = None
    quote = None
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        if not stripped or stripped.startswith("#"):
            i += 1
            continue
        m = _TS_OPEN.match(lines[i])
        if not m:
            return None, None
        start = i
        quote = m.group("q")
        if stripped.endswith(quote) and len(stripped) > len(quote):
            return start, i
        i += 1
        while i < len(lines):
            if lines[i].rstrip().endswith(quote):
                return start, i
            i += 1
        return start, len(lines) - 1
    return None, None


def merge_header(lines, start, end, header):
    """把足迹头合并进模块 docstring（docstring 必须是第一条语句）。

    实现要点：**必须重建 docstring 的首行**。若原文件是单行 docstring
    （``\"\"\"摘要\"\"\"``），直接保留首行会让后续的 ``@feature`` 等行落到
    docstring 之外变成裸代码（这正是前一版失败的根因）。因此这里统一改成
    "开引号 / 原摘要 / 足迹头 / 原正文 / 闭引号" 的多行形式。
    """
    first = lines[start]
    indent = _TS_OPEN.match(first).group("indent")
    quote = _TS_OPEN.match(first).group("q")
    tail = first.strip()
    body = tail[len(quote):]
    if body.endswith(quote):
        body = body[: -len(quote)]
    block = list(lines[start + 1:end])
    if block and block[-1].rstrip().endswith(quote):
        block = block[:-1]

    summary = body.strip()
    merged = [(indent or "") + quote]
    merged.append(summary)
    merged.append("")
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
        return "MISSING-SOURCE %s <- %s" % (rel, src)
    shutil.copyfile(src, full)          # 先还原为参考实现原文
    with open(full, "r", encoding="utf-8") as f:
        text = f.read()
    lines = text.split("\n")

    start, end = find_first_statement(lines)
    if start is None:
        return "NO-DOCSTRING %s" % rel
    text = merge_header(lines, start, end, header)

    for old, new in rewrites:
        if old not in text:
            return "REWRITE-MISS %s: %r" % (rel, old)
        text = text.replace(old, new)

    # 语法自检：docstring 合并最容易踩到"头部内容里出现三引号"的坑，
    # 因此写盘前必须 ast.parse 一次。自检失败时**不能**把半成品留在盘上，
    # 必须回退为参考实现原文，否则仓库里会留下语法错误的文件。
    try:
        ast.parse(text)
    except SyntaxError as exc:
        shutil.copyfile(src, full)
        return "SYNTAX-FAIL %s: line %s: %s（已回退为参考原文）" % (
            rel, exc.lineno, exc.msg)

    with open(full, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return "ok %s" % rel


def main():
    failures = 0
    for rel in sorted(PLAN):
        result = process(rel, PLAN[rel])
        print(result)
        if not result.startswith("ok"):
            failures += 1
    print("\nfailures:", failures)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

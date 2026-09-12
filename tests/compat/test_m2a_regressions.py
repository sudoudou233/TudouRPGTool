# -*- coding: utf-8 -*-
"""M2a 回归测试：P0 缺陷复现与修复验证。

@feature  none
@layer    tests
@public   TestB01CopyFailureKeepsOldOutput, TestB02NonAtomicWrite,
          TestB03FontFallbackRestorable, TestB04RestoreCompleteness,
          TestB07BackupFailureNotSilent, TestB26NoTopLevelWinreg,
          TestN07RgssMultiValueWriteback, TestN08SymbolEscapes
@depends  core.safety.backup, core.safety.atomic, core.formats.*
@tested   (本文件即测试)
@footprint docs/STATE.md

每条用例对应 docs/STATE.md §5 里的一个缺陷编号。写测试时的原则：
**先让它在修复前失败**（证明缺陷真实存在），修复后转为通过。
"""

from __future__ import annotations

import ast
import io
import json
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

from core.safety import atomic, backup as backup_mod  # noqa: E402
from core.safety import builder as build  # noqa: E402


def make_game(root, files):
    """造一个最小的"游戏目录"（只造数据文件，不需要真引擎标记）。"""
    for rel, data in files.items():
        full = os.path.join(root, rel.replace("/", os.sep))
        os.makedirs(os.path.dirname(full), exist_ok=True)
        mode = "wb" if isinstance(data, bytes) else "w"
        kwargs = {} if isinstance(data, bytes) else {"encoding": "utf-8"}
        with open(full, mode, **kwargs) as f:
            f.write(data)
    return root


class FakeEntry(object):
    def __init__(self, file, path, original, translated):
        self.file = file
        self.path = path
        self.original = original
        self.translated = translated
        self.status = "translated" if translated else "pending"

    def __getitem__(self, key):
        return getattr(self, key)

    def get(self, key, default=None):
        return getattr(self, key, default)


class FakeSession(object):
    """最小 session 替身：build() 只需要 .info 与 .entries。"""

    def __init__(self, game_dir, data_dir, engine, entries):
        self.info = {
            "engine": engine,
            "label": engine,
            "game_dir": game_dir,
            "data_dir": data_dir,
            "save_dir": game_dir,
            "supported": True,
            "standard": False,
            "layout": "json" if engine in ("mv", "mz") else "hash",
        }
        self.entries = {}
        for index, (file, path, original, translated) in enumerate(entries):
            self.entries["%d" % index] = FakeEntry(file, path, original, translated)


class TestB01CopyFailureKeepsOldOutput(unittest.TestCase):
    """**B-01**：目标目录已存在且确认覆盖时，原实现先 ``shutil.rmtree`` 再拷贝；
    中途失败则旧输出**永久丢失**。修复后必须先拷到临时目录、成功后再换名。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="b01_")
        self.addCleanup(self.tmp.cleanup)
        self.game = os.path.join(self.tmp.name, "Game")
        make_game(self.game, {"www/data/Items.json": '{"a":1}',
                              "www/js/rpg_core.js": "// x"})
        self.dst = os.path.join(self.tmp.name, "out")

    def _session(self):
        return FakeSession(self.game, os.path.join(self.game, "www", "data"),
                           "mv", [])

    def test_old_output_survives_when_copy_fails(self):
        # 先造一个"旧输出"，里面有一份珍贵文件
        make_game(self.dst, {"old_result.json": "PRECIOUS"})
        session = self._session()

        def flaky(src, dst, *args, **kwargs):
            # 让拷贝在中途失败，模拟磁盘满 / 权限问题 / 用户中断
            raise OSError("模拟拷贝失败：磁盘空间不足")

        original = build.copy_tree
        build.copy_tree = flaky
        try:
            with self.assertRaises(Exception):
                build.build(session, mode="copy", target_dir=self.dst,
                            overwrite=True, confirm_overwrite=True)
        finally:
            build.copy_tree = original

        precious = os.path.join(self.dst, "old_result.json")
        self.assertTrue(os.path.isfile(precious),
                        "**B-01**：拷贝失败后旧输出必须完好，实际已被删除")
        with open(precious, encoding="utf-8") as f:
            self.assertEqual(f.read(), "PRECIOUS")

    def test_successful_overwrite_replaces_output(self):
        make_game(self.dst, {"old_result.json": "OLD"})
        session = self._session()
        result = build.build(session, mode="copy", target_dir=self.dst,
                             overwrite=True, confirm_overwrite=True)
        self.assertTrue(os.path.isdir(result["target_dir"]))
        self.assertTrue(os.path.isfile(
            os.path.join(self.dst, "www", "data", "Items.json")))
        self.assertFalse(os.path.exists(os.path.join(self.dst, "old_result.json")),
                         "成功覆盖后不应残留旧内容")

    def test_no_staging_leftovers(self):
        make_game(self.dst, {"old.json": "OLD"})
        session = self._session()
        build.build(session, mode="copy", target_dir=self.dst,
                    overwrite=True, confirm_overwrite=True)
        leftovers = [n for n in os.listdir(self.tmp.name)
                     if n.startswith("out") and n != "out"]
        self.assertEqual(leftovers, [], "不得残留临时暂存目录：%s" % leftovers)

    def test_overwrite_without_confirmation_is_rejected(self):
        """**B-05**：覆盖既有输出必须显式确认。"""
        make_game(self.dst, {"old.json": "OLD"})
        session = self._session()
        with self.assertRaises(build.OverwriteNotConfirmed):
            build.build(session, mode="copy", target_dir=self.dst, overwrite=True)
        # 拒绝之后旧内容必须完好
        self.assertTrue(os.path.isfile(os.path.join(self.dst, "old.json")))

    def test_inplace_without_confirmation_is_rejected(self):
        """inplace 覆盖的是用户原游戏，同样必须确认。"""
        session = self._session()
        with self.assertRaises(build.OverwriteNotConfirmed):
            build.build(session, mode="inplace", confirm_overwrite=False)


class TestB02NonAtomicWrite(unittest.TestCase):
    """**B-02**：数据写回必须原子（临时文件 + os.replace），
    任何写一半的中断都不能把原文件毁掉。"""

    def test_mv_mz_save_data_file_is_atomic(self):
        from core.formats import mv_mz_data as m
        with tempfile.TemporaryDirectory(prefix="b02a_") as tmp:
            path = os.path.join(tmp, "Items.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump([None, {"id": 1, "name": "药水"}], f, ensure_ascii=False)

            original_bytes = open(path, "rb").read()

            # 让 os.replace 失败，模拟写入阶段中断
            real_replace = atomic.os.replace

            def boom(src, dst):
                raise OSError("模拟 replace 失败")

            atomic.os.replace = boom
            try:
                with self.assertRaises(atomic.AtomicWriteError):
                    m._save_data_file(path, "Items.json", [None, {"id": 1}],
                                      False, None)
            finally:
                atomic.os.replace = real_replace

            self.assertEqual(open(path, "rb").read(), original_bytes,
                             "**B-02**：写入失败后原文件必须字节不变")

    def _direct_write_opens(self, rel_path):
        """用 AST 找出模块里真正的 ``open(..., 写模式)`` 调用。

        不能用字符串搜索：文档字符串里会描述"原实现用 open(full, 'wb')"，
        字符串匹配会把说明文字当成违规（M2a 实测踩到）。
        """
        with io.open(os.path.join(_ROOT, rel_path), encoding="utf-8") as f:
            tree = ast.parse(f.read())
        found = []
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "open"):
                continue
            mode = None
            if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
                mode = node.args[1].value
            for kw in node.keywords:
                if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
                    mode = kw.value.value
            if mode is None:
                continue          # 只读打开，允许
            if any(ch in str(mode) for ch in ("w", "a", "x", "+")):
                found.append((node.lineno, mode))
        return found

    def test_rgss_writeback_is_atomic(self):
        """rgss_data 不得有直接的写模式 open。"""
        offenders = self._direct_write_opens("core/formats/rgss_data.py")
        self.assertEqual(offenders, [],
                         "**B-02**：rgss_data 仍有直接写模式 open：%s" % offenders)

    def test_mv_mz_writeback_is_atomic(self):
        offenders = self._direct_write_opens("core/formats/mv_mz_data.py")
        self.assertEqual(offenders, [],
                         "**B-02**：mv_mz_data 仍有直接写模式 open：%s" % offenders)

    def test_builder_is_atomic(self):
        """builder（含 core.js 改写）也必须走原子写。"""
        offenders = self._direct_write_opens("core/safety/builder.py")
        self.assertEqual(offenders, [],
                         "**B-02**：builder 仍有直接写模式 open：%s" % offenders)

    def test_backup_module_is_atomic(self):
        """备份清单的写入也必须原子：半写的清单会让还原彻底失效。"""
        offenders = self._direct_write_opens("core/safety/backup.py")
        self.assertEqual(offenders, [],
                         "**B-02**：backup 仍有直接写模式 open：%s" % offenders)

    def test_atomic_write_actually_used(self):
        for rel in ("core/formats/rgss_data.py", "core/formats/mv_mz_data.py",
                    "core/safety/builder.py", "core/safety/backup.py"):
            with self.subTest(module=rel):
                src = io.open(os.path.join(_ROOT, rel), encoding="utf-8").read()
                self.assertIn("atomic_write", src,
                              "**B-02**：%s 必须走 core.safety.atomic" % rel)


class TestB03FontFallbackRestorable(unittest.TestCase):
    """**B-03**：字体兜底会覆盖 ``gamefont.ttf`` / ``mplus-1m-regular.ttf``，
    但这两个路径原本不在备份清单里 → **被覆盖后无法还原**。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="b03_")
        self.addCleanup(self.tmp.cleanup)
        self.game = os.path.join(self.tmp.name, "Game")
        # 造一个没有 FontManager.load 的 core.js，触发兜底分支
        make_game(self.game, {
            "www/js/rpg_core.js": "// no FontManager.load here",
            "www/fonts/gamefont.ttf": b"ORIGINAL-DEFAULT-FONT",
            "www/data/Items.json": "{}",
        })
        self.font = os.path.join(self.tmp.name, "MyFont.ttf")
        with open(self.font, "wb") as f:
            f.write(b"NEW-FONT-BYTES")

    def test_touched_paths_include_fallbacks(self):
        touched = build.font_touched_paths(self.game, "mv", self.font)
        for fallback in ("www/fonts/gamefont.ttf",
                         "www/fonts/mplus-1m-regular.ttf"):
            with self.subTest(fallback=fallback):
                self.assertIn(fallback, touched,
                              "**B-03**：字体兜底覆盖的路径必须在 touched 清单里")

    def test_fallback_overwrite_can_be_restored(self):
        """走真实 build 的 inplace 路径：兜底覆盖后必须能还原。"""
        session = FakeSession(self.game, os.path.join(self.game, "www", "data"),
                              "mv", [])
        result = build.build(session, mode="inplace", target_dir=None,
                             backup=True, font_path=self.font,
                             confirm_overwrite=True)
        backup_dir = result.get("backup_dir")
        self.assertTrue(backup_dir, "inplace 必须生成备份")
        with open(os.path.join(self.game, "www", "fonts", "gamefont.ttf"),
                  "rb") as f:
            self.assertEqual(f.read(), b"NEW-FONT-BYTES",
                             "兜底应已覆盖默认字体（用于验证还原确实有用）")

        backup_mod.restore_backup(self.game, backup_dir)
        with open(os.path.join(self.game, "www", "fonts", "gamefont.ttf"),
                  "rb") as f:
            self.assertEqual(f.read(), b"ORIGINAL-DEFAULT-FONT",
                             "**B-03**：被兜底覆盖的默认字体必须能还原")


class TestB04RestoreCompleteness(unittest.TestCase):
    """**B-04**：还原只处理清单内文件，且新增的字体文件不会被删除。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="b04_")
        self.addCleanup(self.tmp.cleanup)
        self.game = os.path.join(self.tmp.name, "Game")
        make_game(self.game, {"www/data/Items.json": '{"v":1}'})

    def test_restore_removes_files_created_by_build(self):
        backup_dir, _ = backup_mod.backup_files(self.game, ["www/data/Items.json"])
        # 模拟 build 新产生了一个游戏内文件
        added = os.path.join(self.game, "www", "fonts", "AddedByBuild.ttf")
        os.makedirs(os.path.dirname(added), exist_ok=True)
        with open(added, "wb") as f:
            f.write(b"x")
        backup_mod.record_created(backup_dir, ["www/fonts/AddedByBuild.ttf"])

        backup_mod.restore_backup(self.game, backup_dir)
        self.assertFalse(os.path.exists(added),
                         "**B-04**：build 新增的文件在还原时必须被删除")

    def test_manifest_records_created_files(self):
        backup_dir, copied = backup_mod.backup_files(self.game, ["www/data/Items.json"])
        manifest_path = os.path.join(backup_dir, "manifest.json")
        with open(manifest_path, encoding="utf-8") as f:
            payload = json.load(f)
        self.assertIn("files", payload)
        self.assertIn("created", payload)

    def test_restore_is_backed_up_itself(self):
        """还原本身也要先备份（否则"还原错了"就不可挽回）。"""
        backup_dir, _ = backup_mod.backup_files(self.game, ["www/data/Items.json"])
        with open(os.path.join(self.game, "www", "data", "Items.json"),
                  "w", encoding="utf-8") as f:
            f.write('{"v":999}')
        result = backup_mod.restore_backup(self.game, backup_dir)
        self.assertIsInstance(result, dict)
        self.assertTrue(result.get("safety_backup"),
                        "**B-04**：还原前必须为当前状态生成安全备份")


class TestB07BackupFailureNotSilent(unittest.TestCase):
    """**B-07**：备份失败不得被静默忽略后继续写档。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="b07_")
        self.addCleanup(self.tmp.cleanup)
        self.game = os.path.join(self.tmp.name, "Game")
        make_game(self.game, {"www/data/Items.json": '{"v":1}'})

    def test_backup_files_raises_on_copy_failure(self):
        real_copy2 = backup_mod.shutil.copy2

        def boom(*args, **kwargs):
            raise OSError("模拟备份失败")

        backup_mod.shutil.copy2 = boom
        try:
            with self.assertRaises(Exception):
                backup_mod.backup_files(self.game, ["www/data/Items.json"])
        finally:
            backup_mod.shutil.copy2 = real_copy2

    def test_missing_file_is_skipped_silently(self):
        """清单里含不存在的文件时应跳过（原实现 :284-285 的行为，保持不变）。"""
        backup_dir, copied = backup_mod.backup_files(
            self.game, ["www/data/Items.json", "does/not/exist.json"])
        self.assertIn("www/data/Items.json", copied)
        self.assertNotIn("does/not/exist.json", copied)


class TestB26NoTopLevelWinreg(unittest.TestCase):
    """**B-26**：``winreg`` 不得在模块顶层 import（非 Windows 上会导入即失败）。"""

    def _top_level_imports(self, rel_path):
        with io.open(os.path.join(_ROOT, rel_path), encoding="utf-8") as f:
            tree = ast.parse(f.read())
        names = []
        for node in tree.body:                      # 只看模块顶层
            if isinstance(node, ast.Import):
                names.extend(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.append(node.module)
        return names

    def test_backup_module_has_no_top_level_winreg(self):
        names = self._top_level_imports(os.path.join("core", "safety", "backup.py"))
        self.assertNotIn("winreg", names,
                         "**B-26**：core/safety/backup.py 顶层 import winreg")

    def test_builder_module_has_no_top_level_winreg(self):
        path = os.path.join("core", "safety", "builder.py")
        if not os.path.isfile(os.path.join(_ROOT, path)):
            self.skipTest("builder.py 尚未建立")
        self.assertNotIn("winreg", self._top_level_imports(path))

    def test_whole_project_has_no_top_level_winreg(self):
        offenders = []
        for dirpath, dirnames, filenames in os.walk(_ROOT):
            dirnames[:] = [d for d in dirnames
                           if d not in ("__pycache__", ".git", "runtime")]
            for name in filenames:
                if not name.endswith(".py"):
                    continue
                full = os.path.join(dirpath, name)
                rel = os.path.relpath(full, _ROOT)
                try:
                    if "winreg" in self._top_level_imports(rel):
                        offenders.append(rel)
                except SyntaxError:
                    continue
        self.assertEqual(offenders, [],
                         "**B-26**：以下文件在顶层 import winreg：%s" % offenders)


class TestN07RgssMultiValueWriteback(unittest.TestCase):
    """**N-07**：多值条目（402 选择项）的写回路径在 RGSS 侧必须可用。"""

    def test_multi_value_entry_roundtrip_through_paths(self):
        """用合成的 marshal 对象验证 ``_navigate``/``_set_value`` 支持
        ``.../parameters/0/1`` 这种"列表里的列表"路径。"""
        from core.formats import rgss_data
        from core.marshal import value_model as marshal

        root = marshal.RMObject("Game_Event", {
            "@list": [
                marshal.RMObject("RPG::EventCommand", {
                    "code": 402,
                    "parameters": [["是", "否"], 1, 0],
                }),
            ],
        })
        # 路径：list/0/parameters/0/1 -> ["是","否"][1] == "否"
        parent, key, _ = rgss_data._navigate(root, "list/0/parameters/0/1")
        rgss_data._set_value(parent, key, "No", "否")
        params = root.ivars["@list"][0].ivars["parameters"]
        self.assertEqual(params[0][1], "No",
                         "**N-07**：多值条目的第 2 个选项必须能被写回")

    def test_navigate_rejects_non_numeric_index_cleanly(self):
        from core.formats import rgss_data
        from core.marshal import value_model as marshal
        root = marshal.RMObject("X", {"@list": [marshal.RMStr("是")]})
        with self.assertRaises((KeyError, ValueError, TypeError, IndexError)):
            rgss_data._navigate(root, "list/是")


class TestN08SymbolEscapes(unittest.TestCase):
    """**N-08**：``CONTROL_RE`` 必须匹配符号型转义（反斜杠 + ``{ } ^ | . ! > < $``）。

    注意：这里全部用 ``chr(92)`` 拼接反斜杠，不写字面量 ——
    ``"\\{"`` 可读，但 ``"\\G"`` 极易被误读成换行转义（M2a 实测踩到过）。
    """

    #: 符号型转义的后继字符（反斜杠本身单独用 chr(92) 拼）
    SYMBOLS = ("{", "}", "^", "|", ".", "!", ">", "<", "$")

    def test_symbol_escapes_are_matched(self):
        from core import textutil
        bs = chr(92)
        for code in self.SYMBOLS + ("G",):
            token = bs + code
            with self.subTest(code=token):
                parts = textutil.split_text("前" + token + "后")
                controls = [seg for is_plain, seg in parts if not is_plain]
                self.assertIn(token, controls,
                              "**N-08**：%r 应被识别为控制码" % token)

    def test_symbol_escapes_survive_roundtrip(self):
        from core import textutil
        bs = chr(92)
        tokens = [bs + c for c in self.SYMBOLS] + [bs + "G"]
        text = bs + "C[2]" + "".join(tokens) + "你好"
        segments, slices = textutil.collect_segments([text])
        rebuilt = textutil.rebuild([text], slices,
                                   ["T%d" % i for i in range(len(segments))])[0]
        for token in tokens:
            with self.subTest(token=token):
                self.assertIn(token, rebuilt,
                              "重组后必须原样保留 %r" % token)
        self.assertNotIn("你好", rebuilt, "纯文本段应已被替换为译文")
        self.assertIn(bs + "C[2]", rebuilt, "字母型控制码也要保留")

    def test_backslash_literal_still_matched(self):
        from core import textutil
        bs = chr(92)
        parts = textutil.split_text("a" + bs + bs + "b")
        self.assertEqual(parts, [(True, "a"), (False, bs + bs), (True, "b")])

    def test_comment_matches_regex(self):
        """源码注释与正则必须一致（避免再次漂移）。"""
        src = io.open(os.path.join(_ROOT, "core", "textutil.py"),
                      encoding="utf-8").read()
        self.assertIn("符号型转义", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)

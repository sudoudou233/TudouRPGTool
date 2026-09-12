# -*- coding: utf-8 -*-
"""交付端构建与备份还原的兼容性测试（移植 build.py 的既有行为）。

@feature  translate
@layer    tests
@public   TestTargetDir, TestBackupRestore, TestCopyTree
@depends  core.safety.backup
@tested   (本文件即测试)
@footprint docs/MODULES.md#coresafety

移植来源
--------
``rpgmaker_translation_tool/tool/build.py``：
* ``default_target_dir`` :38 —— ``<父目录>/<游戏名>_汉化``，冲突追加序号
* ``next_free_dir`` :54 —— ``base`` / ``base2`` / ``base3``…
* ``_assert_safe_target`` :64 —— 拒绝磁盘根与用户主目录
* ``_copy_tree`` :23 —— 逐文件复制并报进度
* ``backup_files`` :275 / ``restore_backup`` :294 / ``list_backups`` :320

本文件只覆盖**不需要真实游戏**的部分；涉及真实数据写回的用例在 M2a 补。
已知缺陷（M2a 必修，见 docs/M0-现状测绘.md §4.1）：
B-01 目标目录先 rmtree 后拷贝、B-03 字体兜底覆盖不可还原、
B-04 还原不完整、B-05 覆盖无二次确认、B-06 无回滚、B-26 顶层 import winreg。
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

from core.safety import atomic  # noqa: E402
from core.safety import backup as backup_mod  # noqa: E402
from core.safety import builder as build  # noqa: E402


class TestTargetDir(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="build_")
        self.addCleanup(self.tmp.cleanup)
        self.game = os.path.join(self.tmp.name, "MyGame")
        os.makedirs(self.game, exist_ok=True)

    def test_default_target_dir_suffix(self):
        """``<父目录>/<游戏名>_汉化``（保持用户习惯，不改成别的命名）。"""
        target = build.default_target_dir(self.game)
        self.assertEqual(os.path.basename(target), "MyGame_汉化")
        self.assertEqual(os.path.dirname(os.path.abspath(target)),
                         os.path.abspath(self.tmp.name))

    def test_default_target_dir_conflict_gets_sequence(self):
        first = build.default_target_dir(self.game)
        os.makedirs(first)
        second = build.default_target_dir(self.game)
        self.assertNotEqual(first, second)

    def test_resolve_target_dir_with_explicit_path(self):
        explicit = os.path.join(self.tmp.name, "out")
        self.assertEqual(os.path.abspath(build.resolve_target_dir(self.game, explicit)),
                         os.path.abspath(explicit))

    def test_next_free_dir_sequence(self):
        base = os.path.join(self.tmp.name, "out")
        self.assertEqual(atomic.next_free_dir(base), base)
        os.makedirs(base)
        self.assertEqual(atomic.next_free_dir(base), base + "2")
        os.makedirs(base + "2")
        self.assertEqual(atomic.next_free_dir(base), base + "3")

    def test_safe_target_rejects_drive_root(self):
        with self.assertRaises(ValueError):
            atomic.assert_safe_target("D:\\")

    def test_safe_target_accepts_normal_dir(self):
        target = os.path.join(self.tmp.name, "ok")
        # M2a 后只剩一个实现：core.safety.atomic.assert_safe_target
        # 返回规范化后的绝对路径（旧的 vendored 版本"成功返回 None"已删除）。
        self.assertEqual(os.path.abspath(atomic.assert_safe_target(target)),
                         os.path.abspath(target))

    def test_safety_checker_rejects_dangerous_targets(self):
        """唯一的护栏实现必须拒绝危险目标。"""
        for dangerous in ("D:\\", os.path.expanduser("~")):
            with self.subTest(target=dangerous):
                with self.assertRaises(ValueError):
                    atomic.assert_safe_target(dangerous)
                with self.assertRaises(atomic.SafeTargetError):
                    atomic.assert_safe_target(dangerous)


class TestCopyTree(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="copy_")
        self.addCleanup(self.tmp.cleanup)
        self.src = os.path.join(self.tmp.name, "src")
        os.makedirs(os.path.join(self.src, "sub"), exist_ok=True)
        for rel, data in (("a.txt", b"aaa"), ("sub/b.bin", b"\x00\x01\x02")):
            with open(os.path.join(self.src, rel.replace("/", os.sep)), "wb") as f:
                f.write(data)

    def test_copies_everything_byte_exact(self):
        dst = os.path.join(self.tmp.name, "dst")
        build.copy_tree(self.src, dst)
        for rel in ("a.txt", "sub/b.bin"):
            with open(os.path.join(self.src, rel.replace("/", os.sep)), "rb") as f:
                original = f.read()
            with open(os.path.join(dst, rel.replace("/", os.sep)), "rb") as f:
                self.assertEqual(f.read(), original, "%s 复制后内容不一致" % rel)

    def test_reports_progress(self):
        """进度回调签名为 ``progress_cb(done, total)``（原实现 :47-48）。"""
        dst = os.path.join(self.tmp.name, "dst")
        seen = []
        build.copy_tree(self.src, dst,
                         progress_cb=lambda done, total: seen.append((done, total)))
        self.assertTrue(seen, "复制过程应回调进度")
        self.assertEqual(seen[-1][0], seen[-1][1],
                         "最后一次回调时已复制数应等于总数")
        totals = {total for _done, total in seen}
        self.assertEqual(len(totals), 1, "total 在整次复制中应保持稳定")
        self.assertGreaterEqual(seen[-1][1], 2)


class TestBackupRestore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="bakrestore_")
        self.addCleanup(self.tmp.cleanup)
        self.game = os.path.join(self.tmp.name, "Game")
        os.makedirs(os.path.join(self.game, "www", "data"), exist_ok=True)
        self.rel = "www/data/Items.json"
        self.target = os.path.join(self.game, self.rel.replace("/", os.sep))
        with open(self.target, "w", encoding="utf-8") as f:
            f.write('{"original": true}')

    def test_backup_creates_manifest_and_copy(self):
        backup_dir, copied = backup_mod.backup_files(self.game, [self.rel])
        self.assertTrue(os.path.isdir(backup_dir))
        manifest = os.path.join(backup_dir, "manifest.json")
        self.assertTrue(os.path.isfile(manifest))
        import json
        with open(manifest, encoding="utf-8") as f:
            payload = json.load(f)
        self.assertIn(self.rel, payload["files"])
        copied = os.path.join(backup_dir, self.rel.replace("/", os.sep))
        self.assertTrue(os.path.isfile(copied))

    def test_backup_dir_name_has_expected_prefix(self):
        backup_dir, copied = backup_mod.backup_files(self.game, [self.rel])
        self.assertTrue(os.path.basename(backup_dir).startswith(backup_mod.BACKUP_PREFIX))

    def test_restore_brings_content_back(self):
        backup_dir, copied = backup_mod.backup_files(self.game, [self.rel])
        with open(self.target, "w", encoding="utf-8") as f:
            f.write('{"translated": true}')
        # M2a 后 restore_backup 返回结构化结果（restored/removed/safety_backup）
        result = backup_mod.restore_backup(self.game, backup_dir)
        self.assertGreaterEqual(result["restored"], 1)
        self.assertIn("safety_backup", result)
        with open(self.target, encoding="utf-8") as f:
            self.assertIn("original", f.read())

    def test_list_backups_finds_created_backup(self):
        backup_dir, copied = backup_mod.backup_files(self.game, [self.rel])
        listed = backup_mod.list_backups(self.game)
        names = [item["name"] if isinstance(item, dict) else str(item)
                 for item in listed]
        self.assertTrue(any(os.path.basename(backup_dir) in str(n) for n in names),
                        "备份列表应包含刚创建的备份：%s" % names)

    def test_missing_file_is_skipped_not_crashed(self):
        """备份清单里含不存在的文件时应跳过（原实现 :284-285 的行为）。"""
        backup_dir, copied = backup_mod.backup_files(
            self.game, [self.rel, "does/not/exist.json"])
        import json
        with open(os.path.join(backup_dir, "manifest.json"), encoding="utf-8") as f:
            payload = json.load(f)
        self.assertIn(self.rel, payload["files"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

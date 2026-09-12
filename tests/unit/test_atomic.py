# -*- coding: utf-8 -*-
"""原子写入与安全护栏的单元测试（对应原缺陷 B-01/B-02/B-07/B-08）。

@feature  none
@layer    tests
@public   TestAtomicWrite, TestSafeTarget, TestSiblingBackup
@depends  core.safety.atomic
@tested   (本文件即测试)
@footprint docs/MODULES.md#coresafety
"""

from __future__ import annotations

import os
import sys
import tempfile
import threading
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


class TestAtomicWrite(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="atomic_")
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name

    def _path(self, name="target.bin"):
        return os.path.join(self.root, name)

    def test_creates_file(self):
        target = self._path()
        result = atomic.atomic_write_bytes(target, b"hello")
        self.assertEqual(result["bytes"], 5)
        with open(target, "rb") as f:
            self.assertEqual(f.read(), b"hello")

    def test_overwrites_existing(self):
        target = self._path()
        atomic.atomic_write_bytes(target, b"old")
        atomic.atomic_write_bytes(target, b"new")
        with open(target, "rb") as f:
            self.assertEqual(f.read(), b"new")

    def test_no_temp_file_left_behind(self):
        """成功后同目录不得残留临时文件（否则会污染游戏目录）。"""
        target = self._path()
        atomic.atomic_write_bytes(target, b"x")
        leftovers = [n for n in os.listdir(self.root) if n.endswith(".tmp")]
        self.assertEqual(leftovers, [])

    def test_original_intact_when_write_fails(self):
        """**核心断言**：写入失败时原文件必须字节级不变（修 B-02）。"""
        target = self._path()
        atomic.atomic_write_bytes(target, b"important-original")

        class Boom(Exception):
            pass

        # 让写入阶段失败：传入一个无法编码/写入的对象
        with self.assertRaises(atomic.AtomicWriteError):
            atomic.atomic_write_bytes(target, object())  # type: ignore[arg-type]

        with open(target, "rb") as f:
            self.assertEqual(f.read(), b"important-original")
        leftovers = [n for n in os.listdir(self.root) if n.endswith(".tmp")]
        self.assertEqual(leftovers, [], "失败后必须清理临时文件")

    def test_creates_parent_dir(self):
        target = os.path.join(self.root, "a", "b", "c.bin")
        atomic.atomic_write_bytes(target, b"deep")
        self.assertTrue(os.path.isfile(target))

    def test_text_helper_encodes_explicitly(self):
        """显式编码，避免 GBK 环境乱码（硬约束 §4.1）。"""
        target = self._path("t.txt")
        atomic.atomic_write_text(target, "中文内容·测试", encoding="utf-8")
        with open(target, "rb") as f:
            self.assertEqual(f.read(), "中文内容·测试".encode("utf-8"))

    def test_text_normalizes_newlines_by_default(self):
        """默认按原工具行为把 CRLF 规范化为 LF（写 JSON 时必需）。"""
        target = self._path("nl.txt")
        atomic.atomic_write_text(target, "a\r\nb")
        with open(target, "rb") as f:
            self.assertEqual(f.read(), b"a\nb")

    def test_text_preserves_newlines_when_asked(self):
        """需要字节级保真时用 preserve_newlines=True。"""
        target = self._path("nl2.txt")
        atomic.atomic_write_text(target, "a\r\nb", preserve_newlines=True)
        with open(target, "rb") as f:
            self.assertEqual(f.read(), b"a\r\nb")

    def test_text_utf8_roundtrip_of_control_codes(self):
        target = self._path("ctl.txt")
        text = "\\V[1]对话\\C[2]颜色\\N[3]\r\n第二行"
        atomic.atomic_write_text(target, text, preserve_newlines=True)
        with open(target, encoding="utf-8", newline="") as f:
            self.assertEqual(f.read(), text)

    def test_optional_backup(self):
        target = self._path()
        atomic.atomic_write_bytes(target, b"v1")
        result = atomic.atomic_write_bytes(target, b"v2", backup=True)
        self.assertIsNotNone(result["backup"])
        with open(result["backup"], "rb") as f:
            self.assertEqual(f.read(), b"v1")
        with open(target, "rb") as f:
            self.assertEqual(f.read(), b"v2")

    def test_no_backup_when_file_absent(self):
        result = atomic.atomic_write_bytes(self._path("new.bin"), b"x", backup=True)
        self.assertIsNone(result["backup"])

    def test_unique_temp_paths_differ(self):
        target = self._path()
        a = atomic.unique_temp_path(target)
        b = atomic.unique_temp_path(target)
        self.assertNotEqual(a, b)
        for path in (a, b):
            os.remove(path)
        self.assertEqual(os.path.dirname(os.path.abspath(a)),
                         os.path.dirname(os.path.abspath(target)),
                         "临时文件必须在同目录，否则 os.replace 失去原子性")

    def test_concurrent_writes_to_distinct_files(self):
        """并发写不同文件必须全部成功，且各自内容完整。

        这是真实场景（批量写回多个数据文件）的形状。
        """
        errors = []

        def worker(index):
            try:
                atomic.atomic_write_bytes(self._path("f%d.bin" % index),
                                          bytes([index]) * 2048, fsync=False)
            except Exception as exc:      # pragma: no cover
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(1, 9)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        for index in range(1, 9):
            with open(self._path("f%d.bin" % index), "rb") as f:
                self.assertEqual(f.read(), bytes([index]) * 2048)

    def test_repeated_writes_stay_whole(self):
        """连续覆盖写：每次都必须读到某一次的完整内容，绝不出现撕裂。

        ⚠ 已知平台限制（已实测）：**同一进程内多线程并发替换同一路径**
        在 Windows 上会因 ``os.replace`` 与其它线程持有的句柄竞争而抛
        ``PermissionError``（WinError 5）。因此本工程对同一文件的写入
        由 :class:`core.jobs.JobManager` 的有界工作池串行化 —— 每个任务
        只写自己的目标文件，不会出现两个线程抢同一路径。
        本用例覆盖的正是这个受支持的形状。
        """
        target = self._path("repeat.bin")
        payloads = [bytes([i]) * 4096 for i in range(1, 9)]
        for data in payloads:
            atomic.atomic_write_bytes(target, data, fsync=False)
            with open(target, "rb") as f:
                self.assertEqual(f.read(), data)
        leftovers = [n for n in os.listdir(self.root) if n.endswith(".tmp")]
        self.assertEqual(leftovers, [], "不得残留临时文件")


class TestSiblingBackup(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="bak_")
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name

    def test_backup_naming_contains_timestamp_and_bak(self):
        target = os.path.join(self.root, "Save01.rvdata2")
        with open(target, "wb") as f:
            f.write(b"save")
        path = atomic.sibling_backup(target)
        self.assertTrue(path.startswith(target))
        self.assertTrue(path.endswith(".bak"))
        self.assertIn("_", os.path.basename(path))

    def test_backup_content_identical(self):
        target = os.path.join(self.root, "a.bin")
        with open(target, "wb") as f:
            f.write(b"\x00\x01\x02binary")
        path = atomic.sibling_backup(target)
        with open(path, "rb") as f, open(target, "rb") as g:
            self.assertEqual(f.read(), g.read())

    def test_repeated_backups_do_not_overwrite(self):
        target = os.path.join(self.root, "a.bin")
        with open(target, "wb") as f:
            f.write(b"1")
        first = atomic.sibling_backup(target, stamp="fixed")
        second = atomic.sibling_backup(target, stamp="fixed")
        self.assertNotEqual(first, second)
        self.assertTrue(os.path.isfile(first) and os.path.isfile(second))

    def test_missing_file_raises(self):
        """**修 B-07**：备份失败必须抛错，不能被静默吞掉后继续写档。"""
        with self.assertRaises(atomic.SafeTargetError):
            atomic.sibling_backup(os.path.join(self.root, "nope.bin"))

    def test_move_mode(self):
        target = os.path.join(self.root, "m.bin")
        with open(target, "wb") as f:
            f.write(b"data")
        path = atomic.sibling_backup(target, copy=False)
        self.assertFalse(os.path.exists(target))
        self.assertTrue(os.path.isfile(path))


class TestSafeTarget(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="safe_")
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name

    def test_accepts_normal_dir(self):
        target = os.path.join(self.root, "out")
        self.assertEqual(atomic.assert_safe_target(target),
                         os.path.abspath(target))

    def test_rejects_empty(self):
        with self.assertRaises(atomic.SafeTargetError):
            atomic.assert_safe_target("")

    def test_rejects_drive_root(self):
        with self.assertRaises(atomic.SafeTargetError):
            atomic.assert_safe_target("D:\\")

    def test_rejects_user_home(self):
        with self.assertRaises(atomic.SafeTargetError):
            atomic.assert_safe_target(os.path.expanduser("~"))

    def test_rejects_inside_game_dir(self):
        """修 B-01 相关：不得把输出写进游戏目录（会先 rmtree 再拷贝）。"""
        game = os.path.join(self.root, "game")
        os.makedirs(game, exist_ok=True)
        with self.assertRaises(atomic.SafeTargetError):
            atomic.assert_safe_target(os.path.join(game, "out"), game_dir=game)

    def test_rejects_game_dir_itself(self):
        game = os.path.join(self.root, "game")
        os.makedirs(game, exist_ok=True)
        with self.assertRaises(atomic.SafeTargetError):
            atomic.assert_safe_target(game, game_dir=game)

    def test_allows_inside_game_when_explicit(self):
        game = os.path.join(self.root, "game")
        os.makedirs(game, exist_ok=True)
        target = os.path.join(game, "out")
        self.assertEqual(atomic.assert_safe_target(target, game_dir=game,
                                                   allow_inside_game=True),
                         os.path.abspath(target))

    def test_sibling_dir_of_game_is_allowed(self):
        game = os.path.join(self.root, "game")
        os.makedirs(game, exist_ok=True)
        target = os.path.join(self.root, "game_汉化")
        self.assertEqual(atomic.assert_safe_target(target, game_dir=game),
                         os.path.abspath(target))

    def test_next_free_dir(self):
        base = os.path.join(self.root, "out")
        self.assertEqual(atomic.next_free_dir(base), base)
        os.makedirs(base)
        self.assertEqual(atomic.next_free_dir(base), base + "2")
        os.makedirs(base + "2")
        self.assertEqual(atomic.next_free_dir(base), base + "3")


if __name__ == "__main__":
    unittest.main(verbosity=2)

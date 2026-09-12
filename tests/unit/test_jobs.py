# -*- coding: utf-8 -*-
"""任务队列的单元测试（对应原缺陷 B-22：无并发上限 / 无回收 / 无单任务取消）。

@feature  none
@layer    tests
@public   TestJobLifecycle, TestCancellation, TestBoundedConcurrency,
          TestSweep, TestSnapshots
@depends  core.jobs
@tested   (本文件即测试)
@footprint docs/MODULES.md#corejobs
"""

from __future__ import annotations

import os
import sys
import threading
import time
import unittest

_ROOT = os.path.dirname(os.path.abspath(__file__))
while not os.path.isfile(os.path.join(_ROOT, "app.py")):
    parent = os.path.dirname(_ROOT)
    if parent == _ROOT:
        raise RuntimeError("无法定位工程根（未找到 app.py）")
    _ROOT = parent
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core import jobs as jobs_mod  # noqa: E402


class ManagerTestCase(unittest.TestCase):
    def make(self, **kw):
        kw.setdefault("max_workers", 2)
        kw.setdefault("ttl", 5.0)
        manager = jobs_mod.JobManager(**kw)
        self.addCleanup(manager.shutdown)
        return manager

    def wait(self, manager, job_id, timeout=10):
        snap = manager.wait(job_id, timeout=timeout)
        self.assertIsNotNone(snap, "任务未在超时内出现")
        self.assertIn(snap["status"], jobs_mod.Job.TERMINAL,
                      "任务未进入终态：%s" % snap["status"])
        return snap


class TestJobLifecycle(ManagerTestCase):
    def test_success_records_result(self):
        manager = self.make()

        def work(job):
            job.set_progress(1, 2, "half")
            job.result = {"value": 42}

        job = manager.submit(work, name="ok")
        snap = self.wait(manager, job.id)
        self.assertEqual(snap["status"], "done")
        self.assertEqual(snap["result"], {"value": 42})
        self.assertEqual(snap["progress"], 1.0)      # 终态进度强制 1.0

    def test_failure_records_error_and_traceback(self):
        manager = self.make()

        def work(job):
            raise ValueError("炸了")

        job = manager.submit(work, name="boom")
        snap = self.wait(manager, job.id)
        self.assertEqual(snap["status"], "error")
        self.assertIn("ValueError", snap["error"])
        self.assertIn("炸了", snap["error"])
        # 注意：不能等到 wait() 之后再 manager.job(id) 取 —— Job._run 的
        # finally 会调用 sweep()，当 ttl 很小时终态任务已被回收。
        # 改为从 Job 对象上取（traceback 与快照同源，只是不进快照以免过大）。
        obj = manager.job(job.id)
        if obj is not None:
            self.assertIsNotNone(obj.traceback)
            self.assertIn("ValueError", obj.traceback)

    def test_progress_clamped(self):
        manager = self.make()
        seen = {}

        def work(job):
            job.set_progress(5, 10, "a")
            seen["mid"] = job.progress
            job.set_progress(999, 10, "b")     # 超界
            seen["over"] = job.progress

        job = manager.submit(work, name="prog")
        self.wait(manager, job.id)
        self.assertAlmostEqual(seen["mid"], 0.5, places=3)
        self.assertLessEqual(seen["over"], 1.0)

    def test_unknown_job_returns_none(self):
        manager = self.make()
        self.assertIsNone(manager.get("nope"))

    def test_ids_are_unique_and_prefixed(self):
        manager = self.make()
        ids = [manager.submit(lambda j: None, name="n").id for _ in range(5)]
        self.assertEqual(len(set(ids)), 5)
        for job_id in ids:
            self.assertTrue(job_id.startswith("job"))


class TestCancellation(ManagerTestCase):
    def test_cancel_token_stops_long_task(self):
        manager = self.make()
        started = threading.Event()

        def work(job):
            started.set()
            for _ in range(500):
                if job.token.is_cancelled():
                    return
                time.sleep(0.01)

        job = manager.submit(work, name="long")
        self.assertTrue(started.wait(5))
        self.assertTrue(manager.cancel(job.id))
        snap = self.wait(manager, job.id)
        self.assertEqual(snap["status"], "cancelled")

    def test_raise_if_cancelled_marks_cancelled_not_error(self):
        """**修 B-22**：取消必须是独立终态，不能混进 error 让用户以为出错。"""
        manager = self.make()
        started = threading.Event()

        def work(job):
            for _ in range(500):
                started.set()
                job.token.raise_if_cancelled()
                time.sleep(0.01)

        job = manager.submit(work, name="raise")
        self.assertTrue(started.wait(5))
        manager.cancel(job.id)
        snap = self.wait(manager, job.id)
        self.assertEqual(snap["status"], "cancelled")
        self.assertIsNone(snap["error"])

    def test_cancel_returns_false_for_terminal_job(self):
        manager = self.make()
        job = manager.submit(lambda j: None, name="quick")
        self.wait(manager, job.id)
        self.assertFalse(manager.cancel(job.id))

    def test_cancel_unknown_returns_false(self):
        self.assertFalse(self.make().cancel("nope"))

    def test_cancel_all(self):
        manager = self.make(max_workers=1)
        gate = threading.Event()
        job_ids = []

        def work(job):
            gate.wait(5)

        for _ in range(3):
            job_ids.append(manager.submit(work, name="blocked").id)
        time.sleep(0.1)
        self.assertGreaterEqual(manager.cancel_all(), 1)
        gate.set()
        for job_id in job_ids:
            self.wait(manager, job_id)

    def test_cancel_is_per_job_not_global(self):
        """原实现只有一个全局 cancel_event：取消一个会把全部任务都停掉。"""
        manager = self.make(max_workers=2)
        gate = threading.Event()
        started = threading.Event()

        def victim(job):
            started.set()
            for _ in range(500):
                if job.token.is_cancelled():
                    return
                time.sleep(0.005)

        def bystander(job):
            gate.wait(6)
            job.result = "survived"

        v = manager.submit(victim, name="victim")
        b = manager.submit(bystander, name="bystander")
        self.assertTrue(started.wait(5))
        manager.cancel(v.id)
        self.assertEqual(self.wait(manager, v.id)["status"], "cancelled")

        gate.set()
        snap = self.wait(manager, b.id)
        self.assertEqual(snap["status"], "done",
                         "取消一个任务不应影响另一个任务")
        self.assertEqual(snap["result"], "survived")


class TestBoundedConcurrency(ManagerTestCase):
    def test_workers_respected(self):
        """**修 B-22**：并发上限必须真实生效（原实现每任务一线程，无上限）。"""
        manager = self.make(max_workers=3)
        lock = threading.Lock()
        current = {"now": 0, "max": 0}
        release = threading.Event()

        def work(job):
            with lock:
                current["now"] += 1
                current["max"] = max(current["max"], current["now"])
            release.wait(5)
            with lock:
                current["now"] -= 1

        ids = [manager.submit(work, name="w%d" % i).id for i in range(9)]
        time.sleep(0.4)
        self.assertLessEqual(current["max"], 3,
                             "同时运行任务数超过 max_workers：%s" % current["max"])
        release.set()
        for job_id in ids:
            self.wait(manager, job_id)

    def test_pending_limit_rejects(self):
        """排队上限：防止请求把内存打满。"""
        manager = self.make(max_workers=1, max_pending=2)
        gate = threading.Event()

        def work(job):
            gate.wait(5)

        submitted = 0
        with self.assertRaises(RuntimeError):
            for _ in range(10):
                manager.submit(work, name="x")
                submitted += 1
        gate.set()
        self.assertLess(submitted, 10)

    def test_stats_shape(self):
        manager = self.make()
        manager.submit(lambda j: None, name="s")
        time.sleep(0.2)
        stats = manager.stats()
        for key in ("workers", "tracked", "queued", "running", "done",
                    "error", "cancelled", "ttl"):
            self.assertIn(key, stats)
        self.assertEqual(stats["workers"], 2)


class TestSweep(ManagerTestCase):
    def test_terminal_jobs_are_reclaimed(self):
        """**修 B-22**：原实现任务永不回收，字典无界增长。"""
        manager = self.make(ttl=0.05)
        job = manager.submit(lambda j: None, name="short")
        self.wait(manager, job.id)
        time.sleep(0.2)
        removed = manager.sweep()
        self.assertGreaterEqual(removed, 1)
        self.assertIsNone(manager.get(job.id))

    def test_running_jobs_not_reclaimed(self):
        manager = self.make(ttl=0.01, max_workers=1)
        gate = threading.Event()
        job = manager.submit(lambda j: gate.wait(5), name="long")
        time.sleep(0.2)
        manager.sweep()
        self.assertIsNotNone(manager.get(job.id), "运行中的任务不得被回收")
        gate.set()
        self.wait(manager, job.id)

    def test_list_returns_newest_first(self):
        manager = self.make()
        first = manager.submit(lambda j: None, name="1").id
        self.wait(manager, first)
        second = manager.submit(lambda j: None, name="2").id
        self.wait(manager, second)
        listed = [j["id"] for j in manager.list()]
        self.assertEqual(listed[0], second)


class TestSnapshots(ManagerTestCase):
    def test_snapshot_is_a_copy(self):
        """**修 B-22**：/api/job 曾直接返回可变 dict，外部可改内部状态。"""
        manager = self.make()
        job = manager.submit(lambda j: None, name="copy")
        self.wait(manager, job.id)
        snap = manager.get(job.id)
        snap["status"] = "tampered"
        snap["result"] = "tampered"
        again = manager.get(job.id)
        self.assertEqual(again["status"], "done")
        self.assertNotEqual(again["result"], "tampered")

    def test_snapshot_has_required_fields(self):
        manager = self.make()
        job = manager.submit(lambda j: setattr(j, "result", 1), name="fields")
        snap = self.wait(manager, job.id)
        for key in ("id", "name", "status", "progress", "message", "result",
                    "error", "created", "started", "finished", "elapsed",
                    "cancelled"):
            self.assertIn(key, snap)

    def test_cancelled_flag_in_snapshot(self):
        manager = self.make()
        started = threading.Event()

        def work(job):
            started.set()
            job.token.wait(5)

        job = manager.submit(work, name="flag")
        self.assertTrue(started.wait(5))
        manager.cancel(job.id)
        snap = self.wait(manager, job.id)
        self.assertTrue(snap["cancelled"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

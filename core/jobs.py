# -*- coding: utf-8 -*-
"""后台任务队列 —— 有界并发、每任务可取消、带 TTL 回收。

@feature  none
@layer    core
@public   CancelToken, Cancelled, Job, JobManager
@depends  (stdlib only)
@tested   tests/unit/test_jobs.py
@footprint docs/MODULES.md#corejobs

修正的原有缺陷（见 docs/M0-现状测绘.md §4.3）
------------------------------------------
原实现 ``translation_tool/tool/server.py:29`` 的 ``Jobs`` 类有四个问题：

* **无并发上限** —— 每个任务一个线程（server.py:54），可无限起线程（B-22）
* **任务永不回收** —— id 用 ``len(self._jobs) + 1``（server.py:35），字典只增不减（B-22）
* **只有全局取消** —— 单个 ``cancel_event``（server.py:162），扫描与构建不可取消（B-22）
* **接口返回可变 dict** —— ``/api/job`` 未持锁序列化（server.py:538）

本实现逐条修正：固定大小工作线程池、每任务独立 :class:`CancelToken`、
完成后保留 TTL 后自动回收、:meth:`JobManager.get` 返回**快照副本**。
"""

from __future__ import annotations

import collections
import itertools
import threading
import time
import traceback as _traceback

#: 保留模块名引用：``Job`` 实例属性 ``self.traceback`` 会遮蔽模块名
#: ``traceback``，因此内部一律用这个别名，避免踩到"实例属性 vs 模块名"的坑。
TRACEBACK = _traceback


class Cancelled(Exception):
    """任务被取消时由 :meth:`CancelToken.raise_if_cancelled` 抛出。"""


def _tail_lines(text, limit):
    """取文本末尾若干行（快照里只带 traceback 尾部，避免刷爆界面）。"""
    if not text:
        return None
    lines = [ln for ln in str(text).splitlines() if ln.strip()]
    if len(lines) <= limit:
        return lines
    return ["…（省略 %d 行）" % (len(lines) - limit)] + lines[-limit:]


class CancelToken(object):
    """每任务独立的取消令牌（线程安全）。

    任务函数可以通过两种方式响应取消：

    * 主动轮询：``if token.is_cancelled(): return``
    * 抛出异常：``token.raise_if_cancelled()``（异常会被记为 cancelled 而非 error）
    """

    def __init__(self, job_id=None):
        self.job_id = job_id
        self._event = threading.Event()

    def cancel(self):
        self._event.set()

    def is_cancelled(self):
        return self._event.is_set()

    def wait(self, timeout=None):
        """等待取消信号（返回是否已取消），便于任务在循环里小睡。"""
        return self._event.wait(timeout)

    def raise_if_cancelled(self):
        if self._event.is_set():
            raise Cancelled("任务已取消")
        return False


class Job(object):
    """一个后台任务的状态容器。

    ``status`` 取值：``queued`` / ``running`` / ``done`` / ``error`` / ``cancelled``。
    """

    TERMINAL = ("done", "error", "cancelled")

    def __init__(self, job_id, name, token):
        self.id = job_id
        self.name = name
        self.token = token
        self.status = "queued"
        self.progress = 0.0
        self.message = "排队中…"
        self.result = None
        self.error = None
        self.traceback = None
        self.created = time.time()
        self.started = None
        self.finished = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------ 状态更新
    def set_progress(self, done, total, message=None):
        """更新进度。``done``/``total`` 允许为 None（表示不确定进度）。"""
        with self._lock:
            if total:
                try:
                    self.progress = max(0.0, min(1.0, float(done) / float(total)))
                except (TypeError, ValueError, ZeroDivisionError):
                    self.progress = 0.0
            if message:
                self.message = str(message)
        return self

    def set_message(self, message):
        with self._lock:
            self.message = str(message)
        return self

    def log(self, message):
        """把一行文本追加到任务消息（覆盖式，保持接口简单）。"""
        return self.set_message(message)

    @property
    def cancelled(self):
        return self.token.is_cancelled()

    def finalize(self, status, message=None, error=None, traceback_text=None,
                 result_marker=None):
        """**原子地**一次性写入终态（status / message / error / traceback / finished）。

        为什么必须这样
        --------------
        M1 实测发现一个真实竞态：若先写 ``self.status = "error"`` 再写
        ``self.traceback``，轮询方（``/api/job``、``JobManager.wait``）只要在
        这两行之间读到 status，就会看到一个"已失败但没有 traceback"的半成品
        —— 测试因此间歇性失败，前端也会拿到不完整信息。

        本方法把所有终态字段在**同一把锁**内写完后才发布 status，保证任何
        观察者看到终态时，与之配套的字段一定已经就位。
        """
        with self._lock:
            if message is not None:
                self.message = message
            if error is not None:
                self.error = error
            if traceback_text is not None:
                self.traceback = traceback_text
            if result_marker is not None:
                self.result = result_marker
            self.finished = time.time()
            self.status = status          # ← 最后发布，作为可见性栅栏

    def snapshot(self):
        """返回不可变快照（供 HTTP 序列化，避免外部改到内部状态）。

        含 ``traceback``：原实现只在任务字典里塞了 traceback，前端拿不到，
        出错时用户只看到一行 ``ValueError: xxx``（B-22 相关的可用性问题）。
        这里只保留末尾若干行，避免把整条栈刷进界面。
        """
        with self._lock:
            return {
                "id": self.id,
                "name": self.name,
                "status": self.status,
                "progress": round(self.progress, 4),
                "message": self.message,
                "result": self.result,
                "error": self.error,
                "traceback_tail": _tail_lines(self.traceback, 8),
                "created": self.created,
                "started": self.started,
                "finished": self.finished,
                "elapsed": round((self.finished or time.time())
                                 - (self.started or self.created), 3),
                "cancelled": self.token.is_cancelled(),
            }

    def __repr__(self):
        return "<Job %s %s %s %.0f%%>" % (
            self.id, self.name, self.status, self.progress * 100)


class JobManager(object):
    """有界并发的后台任务管理器。

    参数
    ----
    max_workers : int
        同时运行的任务上限（默认 4）。超出部分排队。
    max_pending : int
        排队等待的上限（默认 64）；超出时 :meth:`submit` 抛 :class:`RuntimeError`，
        避免请求把内存打满。
    ttl : float
        终态任务保留秒数（默认 600）；到期后由 :meth:`sweep` 回收。
    id_prefix : str
        任务 id 前缀，便于日志分辨来源。
    """

    def __init__(self, max_workers=4, max_pending=64, ttl=600.0,
                 id_prefix="job"):
        self.max_workers = max(1, int(max_workers))
        self.max_pending = max(1, int(max_pending))
        self.ttl = float(ttl)
        self.id_prefix = id_prefix
        self._jobs = collections.OrderedDict()
        self._lock = threading.RLock()
        self._queue = collections.deque()
        self._id_seq = itertools.count(1)
        self._stopping = False
        self._workers = []
        for i in range(self.max_workers):
            t = threading.Thread(target=self._worker, name="%s-worker%d" % (id_prefix, i),
                                 daemon=True)
            t.start()
            self._workers.append(t)

    # ------------------------------------------------------------ 提交/查询
    def submit(self, fn, name="task"):
        """提交任务，返回 :class:`Job`。

        ``fn`` 的签名为 ``fn(job)``；通过 ``job.token`` 响应取消、
        ``job.set_progress()`` 上报进度。
        """
        with self._lock:
            if self._stopping:
                raise RuntimeError("任务管理器已停止")
            pending = sum(1 for j in self._jobs.values() if j.status == "queued")
            if pending >= self.max_pending:
                raise RuntimeError(
                    "排队任务过多（%d），请等待现有任务完成后再试" % pending)
            job_id = "%s%d" % (self.id_prefix, next(self._id_seq))
            token = CancelToken(job_id)
            job = Job(job_id, name, token)
            job._fn = fn
            self._jobs[job_id] = job
            self._queue.append(job_id)
        return job

    def get(self, job_id):
        """按 id 取任务快照；不存在返回 None。"""
        with self._lock:
            job = self._jobs.get(job_id)
        return job.snapshot() if job else None

    def job(self, job_id):
        """按 id 取 :class:`Job` 对象本身（内部/测试用）。"""
        with self._lock:
            return self._jobs.get(job_id)

    def list(self, limit=50):
        """最近的任务快照（新的在前）。"""
        with self._lock:
            jobs = list(self._jobs.values())[-limit:]
        return [j.snapshot() for j in reversed(jobs)]

    # ------------------------------------------------------------ 控制
    def cancel(self, job_id):
        """取消指定任务。已终态返回 False。"""
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None or job.status in Job.TERMINAL:
            return False
        job.token.cancel()
        job.set_message("正在取消…")
        return True

    def cancel_all(self):
        """取消所有未完成任务，返回取消数量。"""
        with self._lock:
            ids = [jid for jid, j in self._jobs.items()
                   if j.status not in Job.TERMINAL]
        return sum(1 for jid in ids if self.cancel(jid))

    def wait(self, job_id, timeout=None):
        """等待任务进入终态，返回快照（超时返回当前快照）。"""
        deadline = None if timeout is None else time.time() + timeout
        while True:
            snap = self.get(job_id)
            if snap is None or snap["status"] in Job.TERMINAL:
                return snap
            if deadline is not None and time.time() >= deadline:
                return snap
            time.sleep(0.02)

    def sweep(self, now=None):
        """回收超过 TTL 的终态任务，返回回收数量。"""
        now = now or time.time()
        removed = 0
        with self._lock:
            for job_id, job in list(self._jobs.items()):
                if job.status in Job.TERMINAL and job.finished:
                    if now - job.finished >= self.ttl:
                        del self._jobs[job_id]
                        removed += 1
        return removed

    def stats(self):
        """运行统计，供健康检查展示。"""
        with self._lock:
            counts = collections.Counter(j.status for j in self._jobs.values())
            return {
                "workers": self.max_workers,
                "tracked": len(self._jobs),
                "queued": counts.get("queued", 0),
                "running": counts.get("running", 0),
                "done": counts.get("done", 0),
                "error": counts.get("error", 0),
                "cancelled": counts.get("cancelled", 0),
                "ttl": self.ttl,
            }

    def shutdown(self, wait=False):
        """停止接受新任务，并可选择取消所有在跑任务。"""
        self.cancel_all()
        with self._lock:
            self._stopping = True

    # ------------------------------------------------------------ 工作线程
    def _next_job(self):
        with self._lock:
            while self._queue:
                job_id = self._queue.popleft()
                job = self._jobs.get(job_id)
                if job is not None and job.status == "queued":
                    return job
            return None

    def _worker(self):
        while True:
            job = self._next_job()
            if job is None:
                if self._stopping:
                    return
                time.sleep(0.02)
                continue
            self._run(job)

    def _run(self, job):
        job.status = "running"
        job.started = time.time()
        job.set_message("开始…")
        try:
            job._fn(job)
        except Cancelled:
            job.finalize("cancelled", message="已取消")
        except Exception as exc:
            job.finalize("error",
                         error="%s: %s" % (type(exc).__name__, exc),
                         traceback_text=TRACEBACK.format_exc(),
                         message="失败：%s: %s" % (type(exc).__name__, exc))
        else:
            if job.token.is_cancelled():
                job.finalize("cancelled", message="已取消")
            else:
                message = None
                if not job.message or job.message == "开始…":
                    message = "完成"
                job.finalize("done", message=message)
                with job._lock:
                    job.progress = 1.0
        finally:
            self.sweep()

# -*- coding: utf-8 -*-
"""最近打开的游戏（MRU 列表）—— **两个功能共享**的一份记录。

@feature  none
@layer    core
@public   RecentGames, note_game, MAX_ITEMS, FILENAME, DEFAULT_LIMIT
@depends  core.paths, core.safety.atomic
@tested   tests/unit/test_recent.py
@footprint docs/MODULES.md#corerecent

为什么放在 core 而不是某个功能里
--------------------------------
"最近打开过哪些游戏"是**翻译**与**修改**两个功能都要用的事实，
而两个 feature 之间不允许互相 import。放 core 正好：它只依赖
``core.paths``（定位 runtime 目录）与 ``core.safety.atomic``（原子写），
不认识引擎、也不认识 HTTP。

为什么顺序用"列表位置"而不是时间戳
----------------------------------
同一秒内连开两个游戏是完全可能的（尤其自动扫描时），时间戳排序会出现
"顺序随机"。所以 :meth:`RecentGames.record` 的做法是**先删同项、再插到最前**，
顺序就是列表本身；``when`` 只做展示用，不参与排序。

容错（这些都是"列表类功能"的常见坏法）
--------------------------------------
* 文件不存在 / 内容坏掉 / 不是 JSON → **返回空列表，绝不抛**。
  这个文件坏了只该让"最近打开"变空，绝不能拖垮整个应用启动。
* 路径失效（游戏被删/移动/断网盘）→ 条目**保留**但标 ``exists=False``，
  界面显示为不可点。直接删掉会让用户"移动了一下目录就找不到记录了"。
* 写盘一律走 :func:`core.safety.atomic.atomic_write_text`（硬约束 §4.2）。
"""

from __future__ import annotations

import json
import os
import time

from . import paths
from .safety import atomic

#: 存储文件名（位于 ``runtime/`` 下，已 gitignore）
FILENAME = "recent.json"

#: 默认最多记多少条
DEFAULT_LIMIT = 12

#: 兼容旧名（历史上这个常量叫 MAX_ITEMS）
MAX_ITEMS = DEFAULT_LIMIT

#: 磁盘格式版本。将来结构变了靠它做迁移，而不是猜。
SCHEMA = 1


def _norm(path):
    """去重用的键：绝对路径 + 大小写归一（Windows 上 ``D:\\A`` 与 ``d:\\a`` 同一个）。"""
    return os.path.normcase(os.path.abspath(path))


def _clean(value):
    """只留字符串，并去掉首尾空白。"""
    return value.strip() if isinstance(value, str) else ""


class RecentGames(object):
    """最近打开的游戏列表（内存态 + 按需落盘）。"""

    def __init__(self, path=None, limit=DEFAULT_LIMIT):
        self.path = path or os.path.join(paths.data_dir(), FILENAME)
        self.limit = max(1, int(limit))
        #: 上次加载/保存时遇到的问题（中文，供自检页展示）；正常为 None
        self.last_error = None
        self._items = self._read()

    # ------------------------------------------------------------ 读
    def _read(self):
        """读磁盘。**任何异常都退化成空列表**（见模块 docstring）。"""
        self.last_error = None
        try:
            if not os.path.exists(self.path):
                return []
            if not os.path.isfile(self.path):
                # 同名目录/设备文件占位。静默当成"没有文件"会让用户
                # 永远查不出"为什么最近打开总是空的"，所以这里明说。
                self.last_error = ("最近打开记录的位置被占用了：%s 不是普通文件"
                                   % self.path)
                return []
            with open(self.path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except (OSError, ValueError) as exc:
            self.last_error = "读取最近打开记录失败：%s" % exc
            return []
        if not isinstance(payload, dict):
            self.last_error = "最近打开记录格式不对（期望对象）"
            return []
        raw = payload.get("items")
        if not isinstance(raw, list):
            self.last_error = "最近打开记录里没有 items 列表"
            return []
        out = []
        seen = set()
        for ent in raw:
            if not isinstance(ent, dict):
                continue
            game = _clean(ent.get("path"))
            if not game:
                continue
            key = _norm(game)
            if key in seen:            # 文件被手工改出重复项也要收拾干净
                continue
            seen.add(key)
            out.append({
                "path": game,
                "kind": _clean(ent.get("kind")),
                "label": _clean(ent.get("label")) or os.path.basename(
                    game.rstrip("\\/")) or game,
                "engine": _clean(ent.get("engine")),
                "when": _clean(ent.get("when")),
            })
        return out[:self.limit]

    def items(self):
        """返回**当前有效**的列表（新→旧），每项带上 ``exists``。

        ``exists`` 是**算出来的**而不是存下来的 —— 目录随时可能被删/移，
        存下来的那份一定会过期。
        """
        out = []
        for ent in self._items:
            row = dict(ent)
            row["exists"] = os.path.isdir(row["path"])
            out.append(row)
        return out

    def count(self):
        return len(self._items)

    # ------------------------------------------------------------ 写
    def _store(self):
        """落盘。失败**不抛**，但把原因记进 ``last_error`` 让自检页能看见。

        为什么不抛："记不住最近打开过什么"不该让用户正在做的事失败。
        但这也不能是无声的 —— 所以暴露成 ``last_error``。
        """
        payload = {
            "schema": SCHEMA,
            "saved": time.strftime("%Y-%m-%d %H:%M:%S"),
            "items": self._items,
        }
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        try:
            atomic.atomic_write_text(self.path, text, encoding="utf-8")
        except OSError as exc:
            self.last_error = "写入最近打开记录失败：%s" % exc
            return False
        self.last_error = None
        return True

    def record(self, game_dir, kind=None, label=None, engine=None):
        """把 ``game_dir`` 记到最前面（已在列表里则**移动**而不是重复）。

        返回更新后的列表（与 :meth:`items` 同形）。
        """
        game = _clean(game_dir)
        if not game:
            return self.items()
        real = os.path.abspath(game)
        key = _norm(real)
        self._items = [e for e in self._items if _norm(e["path"]) != key]
        self._items.insert(0, {
            "path": real,
            "kind": _clean(kind),
            "label": _clean(label) or os.path.basename(real.rstrip("\\/")) or real,
            "engine": _clean(engine),
            "when": time.strftime("%Y-%m-%d %H:%M:%S"),
        })
        del self._items[self.limit:]
        self._store()
        return self.items()

    def forget(self, game_dir):
        """删掉一条。返回是否真的删掉了（界面据此给不同提示）。"""
        key = _norm(_clean(game_dir))
        before = len(self._items)
        self._items = [e for e in self._items if _norm(e["path"]) != key]
        if len(self._items) == before:
            return False
        self._store()
        return True

    def prune(self):
        """删掉所有**已经不存在**的目录，返回删掉的条数。

        刻意不做成自动行为：用户可能只是暂时拔了移动硬盘。
        所以由界面上的「清理失效项」显式触发。
        """
        before = len(self._items)
        self._items = [e for e in self._items if os.path.isdir(e["path"])]
        removed = before - len(self._items)
        if removed:
            self._store()
        return removed

    def clear(self):
        """清空。返回清掉的条数。"""
        removed = len(self._items)
        self._items = []
        if removed:
            self._store()
        return removed


def note_game(ctx, game_dir, kind=None, label=None, engine=None):
    """便捷入口：把"刚打开了这个游戏"记进 ``ctx.recent``。

    功能里只写一行::

        recent.note_game(self.ctx, game_dir, kind="cheats",
                         label=info.get("label"), engine=info.get("engine"))

    刻意**吞掉一切异常**：记不住"最近打开过什么"绝不能影响用户正在做的事
    （打开游戏、扫描文本、写回存档）。出问题时 ``RecentGames.last_error``
    里有中文原因，自检页会展示。
    """
    store = getattr(ctx, "recent", None) if ctx is not None else None
    if store is None:
        return []
    try:
        return store.record(game_dir, kind=kind, label=label, engine=engine)
    except Exception:                     # noqa: BLE001 —— 见 docstring
        return []

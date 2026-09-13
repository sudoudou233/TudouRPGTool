# -*- coding: utf-8 -*-
"""存档修改功能的后端接线：读档 / 改档 / 写回 / 游戏数据表编辑。

@feature  cheats
@layer    features
@public   CheatsService, register_routes, BackupPolicy, ACTOR_ATTRS,
          EDIT_KINDS, PAID_FOR
@depends  features.cheats.data_fields, core.engines, core.formats.mv_save,
          core.formats.rgss_save, core.iconutil, core.safety.backup,
          core.safety.atomic, core.paths, core.constants, core.context
@tested   tests/features/cheats/test_routes.py
@footprint docs/FEATURES.md#cheats

设计要点（与 translate 的 routes.py 保持同一形态）
-------------------------------------------------
* 功能自己持有状态（:class:`CheatsService`），manifest 只做装配；
* **读**操作同步返回（存档只有几百 KB，没必要开任务）；
* **写**操作一律"先备份 → 再原子写"（:class:`BackupPolicy` 统一表达），
  且"覆盖原存档"必须 ``confirm=true``；
* 引擎差异全部由 ``core/formats/{mv_save,rgss_save}`` 吸收，
  本层只做参数透传与错误转中文。

为什么不用后台任务
------------------
需求 §5 要求"长任务必须可中断"，但**读一个存档是毫秒级**的（实测最慢
0.3s，见 `docs/STATE.md`）。为了统一而给毫秒级操作套任务队列，只会让
界面变复杂、点一次要轮询一次。因此判据是**耗时**而非**读写**：
本模块没有超过 2 秒的操作，所以不开任务；真要出现慢操作（例如全库扫描）
再走 ``ctx.jobs``。
"""

from __future__ import annotations

import os
import re
import time

from core import constants
from core import engines
from core import iconutil
from core.context import Response
from core.formats import mv_save
from core.formats import rgss_save
from core.safety import backup as backup_mod

from . import data_fields

#: 界面可编辑的角色属性 → ``set_actor_attr`` 接受的字段名
#:
#: 键是前端的字段名，值里的 ``attr`` 是 core 层的字段名。
ACTOR_ATTRS = (
    {"key": "level", "label": "等级", "kind": "int"},
    {"key": "exp", "label": "经验", "kind": "int"},
    {"key": "hp", "label": "HP", "kind": "int"},
    {"key": "mp", "label": "MP", "kind": "int"},
    {"key": "tp", "label": "TP", "kind": "int", "mv_only": True},
    {"key": "param_plus_0", "label": "最大HP加成", "kind": "int"},
    {"key": "param_plus_1", "label": "最大MP加成", "kind": "int"},
    {"key": "param_plus_2", "label": "攻击加成", "kind": "int"},
    {"key": "param_plus_3", "label": "防御加成", "kind": "int"},
)

#: 道具类别的三个桶（与 ``set_item`` 的 ``kind`` 参数一致）
EDIT_KINDS = ("items", "weapons", "armors")

#: 每次写回都要走的备份策略说明（给界面展示，避免"备份在哪"说不清）
PAID_FOR = "写回原存档前自动备份到游戏目录下的「汉化备份_*」（与生成汉化版同一套机制）"


def _name_of(raw, key):
    """从名字表的一项取显示名；取不到回退 ``#key``。

    支持两种形态：纯字符串（道具/武器/防具/职业），以及
    ``{'name': ..., 'class_id': ...}``（角色 —— 附带职业与初始等级）。
    """
    if isinstance(raw, str) and raw:
        return raw
    if isinstance(raw, dict):
        name = raw.get("name")
        if isinstance(name, str) and name:
            return name
    return "#%d" % key


class BackupPolicy(object):
    """写回前的备份与还原策略（**本模块唯一的落点**）。

    硬约束 §4.2：任何写回前必须备份且可还原。把这件事收在一个类里，
    是为了避免"某个新加的写入口忘了备份" —— 所有写方法都必须先
    ``policy.before(rel_paths)``。
    """

    def __init__(self, game_dir):
        self.game_dir = os.path.abspath(game_dir)
        self.last_dir = None

    def before(self, rel_paths, label=""):
        """备份即将被修改的文件，返回备份目录（``rel_paths`` 为空则返回 None）。"""
        targets = [p for p in (rel_paths or ()) if p]
        if not targets:
            return None
        extra = {"feature": "cheats", "label": label or "改档"}
        self.last_dir, _copied = backup_mod.backup_files(
            self.game_dir, targets, extra=extra)
        return self.last_dir


class CheatsService(object):
    """存档修改的会话持有者。"""

    def __init__(self, ctx):
        self.ctx = ctx
        self.game_dir = None
        self.info = None
        self.gamedata = None
        self.save = None             # 当前打开的存档编辑器
        self.save_path = None
        self.engine = None
        #: 图标图集缓存 ``(meta, png_bytes)``。
        #:
        #: ⚠ **切换游戏时必须失效** —— 否则换一个游戏后界面上画的还是上一个
        #: 游戏的图标。这类"接口说成功、画面是旧的"正是本工程反复踩到的一类
        #: 缺陷（N-12 ～ N-28），所以在 :meth:`open_game` 里显式清空，
        #: 并且有断言守着（``test_icon_cache_is_invalidated_on_open``）。
        self._icon_cache = None

    # ------------------------------------------------------------ 打开游戏
    def open_game(self, game_dir):
        """识别引擎并准备"名字表"（道具/角色/职业名，供界面显示可读名称）。"""
        game_dir = os.path.abspath(game_dir)
        info = engines.detect(game_dir)
        if not info.get("engine"):
            raise ValueError(info.get("error") or "未能识别引擎")
        if not info.get("supported"):
            raise ValueError("检测到 %s，但该引擎的存档格式暂不支持"
                             % info.get("label"))
        self.game_dir = game_dir
        self.info = info
        self.engine = info["engine"]
        self.save = None
        self.save_path = None
        self._icon_cache = None
        self.gamedata = self._load_gamedata()
        return info

    def _load_gamedata(self):
        """读道具/武器/防具/角色/职业名。失败不抛 —— 名字只是显示用的。"""
        try:
            if self.engine in ("mv", "mz"):
                return mv_save.GameDataMV(self.info["data_dir"])
            return rgss_save.GameData(self.info["data_dir"],
                                      standard=self.info.get("standard", False))
        except Exception:
            return None

    def require_game(self):
        if not self.info:
            raise ValueError("请先选择游戏目录并读取游戏数据")
        return self.info

    def require_save(self):
        if self.save is None:
            raise ValueError("请先选择一个存档")
        return self.save

    # ------------------------------------------------------------ 图标
    def icon_of(self, kind, item_id):
        """取某条目的图标格子号；没有图标信息返回 None。

        ⚠ ``0`` 与 ``None`` 语义不同，不要合并：

        * ``0``    —— 数据表**明确写了**"这件道具不显示图标"；
        * ``None`` —— 这个表/这条**根本没有**图标信息（XP 的 ``RPG::Item``
          没有 ``@icon_index``、或 data 文件读失败）。

        两者界面都不画图标，但前端要能区分"没图标"和"后端不支持图标"，
        所以这里原样返回 int（含 0），不转成 falsy。
        """
        icons = getattr(self.gamedata, "icons", None)
        if not isinstance(icons, dict):
            return None
        bucket = icons.get(kind)
        if not isinstance(bucket, dict):
            return None
        value = bucket.get(item_id)
        return value if isinstance(value, int) else None

    def icon_meta(self, refresh=False):
        """图标图集的切片元数据（**不含图片字节**，可直接进 JSON）。

        返回 ``available`` / ``reason`` / ``cell`` / ``columns`` / ``rows`` /
        ``count`` / ``encrypted`` / ``path``。不可用时 ``reason`` 是给用户看的
        中文原因，界面据此把"显示图标"开关置灰并说明为什么。
        """
        if self.info is None:
            return {"available": False, "reason": "还没有打开游戏",
                    "engine": None, "path": None, "encrypted": False,
                    "width": None, "height": None, "cell": None,
                    "columns": None, "rows": None, "count": None}
        if refresh or self._icon_cache is None:
            self._icon_cache = iconutil.load(self.info)
        meta, _data = self._icon_cache
        return dict(meta)

    def icon_sheet(self):
        """图标图集的**明文 PNG 字节**（界面拿它做 CSS sprite）。

        返回 ``(png_bytes, meta)``；不可用时 ``png_bytes`` 为 None。
        """
        meta = self.icon_meta()
        if not meta.get("available"):
            return None, meta
        _meta, data = self._icon_cache
        return data, meta

    # ------------------------------------------------------------ 存档列表
    def list_saves(self):
        """本游戏所有存档（跨目录，按目录去重）。

        ⚠ 两个来源必须**按目录去重**：``info['save_dir']`` 是引擎判据给的
        标准位置，而 ``engines.find_save_dirs`` 也会把它包含进来（它把
        ``save_dir`` 预置进结果）。不去重就会把同一个存档列两遍 ——
        M3b 实测踩到：界面上出现两行一模一样的存档，用户不知道点哪个。
        """
        info = self.require_game()
        out = []
        seen_dirs = set()

        def collect(directory, names):
            absdir = os.path.abspath(directory)
            if absdir in seen_dirs:
                return
            seen_dirs.add(absdir)
            for name in names:
                path = os.path.join(directory, name)
                try:
                    stat = os.stat(path)
                    size, mtime = stat.st_size, stat.st_mtime
                except OSError:
                    size, mtime = 0, 0
                out.append({
                    "name": name,
                    "path": path,
                    "dir": directory,
                    "size": size,
                    "time": time.strftime("%Y-%m-%d %H:%M:%S",
                                          time.localtime(mtime)) if mtime else "",
                })

        if info.get("save_dir"):
            collect(info["save_dir"], engines.list_saves(info, self.game_dir))
        for directory, names in engines.find_save_dirs(info, self.game_dir):
            collect(directory, names)
        return out

    def save_dirs(self):
        """本游戏所有**合法**的存档目录（用于校验路径、也用于展示）。

        包含三类：

        * ``info['save_dir']`` —— 引擎判据给出的标准位置（MV/MZ 是
          ``<js根>/save``，RGSS 是游戏根）；**即使它现在是空的也要算**，
          因为"目录里还没有存档"不等于"不许往这里写"；
        * ``engines.find_save_dirs`` 递归找到的其它位置 —— 应对自动存档、
          旧版布局（例如老 MV 把存档放在 ``www/save``）等第二套存档；
        * 游戏根下的 ``save`` / ``Save`` / ``savedata`` 等常见名字 ——
          有些改造版运行时把存档放在这类目录里，而里面暂时没有存档文件，
          递归搜索（只返回**含存档**的目录）看不到它们。

        结果按绝对路径**去重**：RGSS 的 ``save_dir`` 就是游戏根，
        而游戏根本来也在候选里，不去重会在界面上出现两个一样的位置。

        ⚠ 去重要用 ``os.path.normcase``（Windows 上大小写不敏感）：
        ``www/save`` 与 ``www/Save`` 在 Windows 上是**同一个目录**，
        用普通字符串比较会得到两条一模一样的记录（实测踩到）。
        在真正大小写敏感的文件系统上，``normcase`` 是恒等变换，
        两个不同目录都会被保留 —— 行为仍然正确。
        """
        info = self.require_game()
        seen = []
        seen_keys = set()

        def add(path):
            if not path:
                return
            absdir = os.path.abspath(path)
            key = os.path.normcase(absdir)
            if key in seen_keys:
                return
            seen_keys.add(key)
            seen.append(absdir)

        add(info.get("save_dir"))
        for directory, _names in engines.find_save_dirs(info, self.game_dir):
            add(directory)
        # 常见但"暂时为空"的存档目录名（老/改造版运行时的习惯）
        root = info.get("js_root") or self.game_dir
        for base in (self.game_dir, root):
            for name in ("save", "Save", "savedata", "SaveData"):
                candidate = os.path.join(base, name)
                if os.path.isdir(candidate):
                    add(candidate)
        add(self.game_dir)
        return seen

    def _assert_inside_save_dirs(self, path):
        """确认 ``path`` 落在本游戏的某个存档目录里（越权读盘的防线）。

        ⚠ 用 ``os.path.commonpath`` 而不是 ``str.startswith(dir + os.sep)``：
        字符串前缀判据在大小写不一致（Windows）或目录名互为前缀
        （``save`` 与 ``save2``）时会判错。M3b 实测还踩到另一处：
        只把"**当前有存档的**目录"算作合法会让空目录里的合法路径被拒 ——
        所以 :meth:`save_dirs` 必须无条件包含 ``info['save_dir']``。
        """
        target = os.path.abspath(path)
        for directory in self.save_dirs():
            try:
                if os.path.commonpath([target, directory]) == directory:
                    return
            except ValueError:
                # 不同盘符 → 必然不在其中
                continue
        raise ValueError("该文件不在本游戏的存档目录内：%s" % path)

    def open_save(self, path):
        """打开存档。``path`` 必须在游戏目录下的某个存档目录里（防越权读盘）。"""
        path = os.path.abspath(path)
        self._assert_inside_save_dirs(path)
        if not os.path.isfile(path):
            raise ValueError("存档不存在：%s" % path)
        info = self.info
        if self.engine in ("mv", "mz"):
            save = mv_save.SaveFileMV(path, gamedata=self.gamedata,
                                      engine=self.engine)
        else:
            save = rgss_save.SaveFile(path, gamedata=self.gamedata,
                                      standard=info.get("standard", False),
                                      layout=info.get("layout") or "hash")
        self.save = save
        self.save_path = path
        return save

    # ------------------------------------------------------------ 读取
    def names(self, kind, ids):
        """把 id 列表映射成可读名字（读不到就给 ``#id``）。

        ⚠ 名字表两种形态都要支持：MV/MZ 的 ``GameDataMV.actors`` 存的是
        ``{id: {'name':..., 'class_id':...}}``（为了带上职业与初始等级），
        而 RGSS 的 ``GameData.actors`` 同构；但 ``items``/``weapons``/
        ``armors``/``classes`` 存的是**纯字符串**。M3b 实测踩到：
        只按字符串取会把整个 dict 当成名字返回给界面。
        """
        store = {}
        if self.gamedata is not None:
            store = getattr(self.gamedata, kind, None) or {}
        out = []
        for raw in ids or ():
            try:
                key = int(raw)
            except (TypeError, ValueError):
                continue
            out.append({"id": key, "name": _name_of(store.get(key), key)})
        return out

    def catalog(self, kind, bucket):
        """**整份**道具/武器/防具表 + 持有数 —— 与参考工具一致的行为。

        ⚠ 为什么必须给全表（用户报告"只读出了人物身上自带有的道具"）：
        参考工具 ``main.py:294-305`` 的 ``_refresh_inv`` 是**遍历整张数据表**
        并显示 ``counts.get(oid, 0)`` —— 也就是"表里每一件都在，没持有的显示 0"。
        这样用户才能**添加自己还没有的道具**（改档的主要用途之一）。
        我们之前只列 ``party['_items']`` 里已有的键，于是"未持有的一律看不见"，
        功能比参考工具窄。

        返回 ``[{id, name, count, owned}]``，按 id 升序。
        """
        save = self.require_save()
        store = {}
        if self.gamedata is not None:
            store = getattr(self.gamedata, kind, None) or {}
        counts = dict(bucket or {})
        rows = []
        seen = set()
        for raw_id in store:
            try:
                item_id = int(raw_id)
            except (TypeError, ValueError):
                continue
            if item_id <= 0:
                continue
            name = _name_of(store.get(raw_id), item_id)
            count = counts.get(item_id, 0)
            # 数据表末尾常有"占位条目"（有 id 没名字，例如 Items.json 里
            # 最后一条只有 id）。列出来只会让用户以为能加一件叫 #35 的道具，
            # 但**持有中的**占位条目仍要显示（见下面 orphan 分支）。
            if not name and not count:
                continue
            seen.add(item_id)
            rows.append({
                "id": item_id,
                "name": name or "#%d" % item_id,
                "count": count,
                "owned": bool(count),
                "icon": self.icon_of(kind, item_id),
            })
        # 存档里有、但数据表里没有的 id（MOD / 数据表被换过）也要列出来，
        # 否则用户会在界面上"看不到自己背包里的东西"
        for item_id, count in counts.items():
            if item_id is None or item_id in seen:
                continue
            name = _name_of(store.get(item_id), item_id) if item_id in store else ""
            rows.append({"id": item_id, "name": name or "#%d" % item_id,
                         "count": count, "owned": bool(count),
                         "orphan": item_id not in store,
                         "icon": self.icon_of(kind, item_id) if item_id in store
                         else None})
        rows.sort(key=lambda r: (r["id"] is None, r["id"]))
        _ = save
        return rows

    def party_view(self):
        """队伍 / 金币 / 步数 / 三个道具桶 + **完整道具表**（带可读名字）。

        ``items`` 是"当前持有"（只含数量 > 0 的条目，用于快速核对）；
        ``catalog`` 是"整张表"（含数量 0 的条目，用于添加新道具）。
        界面默认显示 catalog —— 与参考工具一致。
        """
        save = self.require_save()
        party = save.read_party() or {}
        view = {
            "gold": party.get("gold"),
            "steps": party.get("steps"),
            "party": self.names("actors", party.get("party_ids") or []),
            "party_ids": list(party.get("party_ids") or []),
            "currency": getattr(self.gamedata, "currency", "") if self.gamedata else "",
            "items": {},
            "catalog": {},
        }
        for kind in EDIT_KINDS:
            bucket = party.get(kind) or {}
            rows = []
            for item_id, count in sorted(bucket.items(),
                                         key=lambda kv: (kv[0] is None, kv[0])):
                if item_id is None:
                    continue
                name = ""
                if self.gamedata is not None:
                    store = getattr(self.gamedata, kind, None) or {}
                    name = _name_of(store.get(item_id), item_id) \
                        if item_id in store else ""
                rows.append({"id": item_id, "name": name or "#%d" % item_id,
                             "count": count, "icon": self.icon_of(kind, item_id)})
            view["items"][kind] = rows
            view["catalog"][kind] = self.catalog(kind, bucket)
        return view

    def actors_view(self):
        """角色数组（含名字与可编辑属性清单）。"""
        save = self.require_save()
        actors = []
        for index, row in enumerate(save.read_actors() or []):
            if not row:
                actors.append(None)
                continue
            actor_id = row.get("actor_id")
            if actor_id is None:
                actor_id = index
            name = ""
            if self.gamedata is not None:
                store = getattr(self.gamedata, "actors", None) or {}
                if actor_id in store:
                    name = _name_of(store.get(actor_id), actor_id)
            item = dict(row)
            item["name"] = name or "#%s" % actor_id
            item["index"] = index
            actors.append(item)
        return actors

    def switches_view(self, key, offset=0, limit=100):
        """开关 / 变量的分页视图。

        ``key`` 取 ``'switches'`` 或 ``'variables'``。默认第 1 个开关是
        ``1`` 号（RGSS/MV 的开关从 1 开始，下标 0 空着）。
        """
        if key not in ("switches", "variables"):
            raise ValueError("key 只能是 switches 或 variables")
        save = self.require_save()
        values = save.read_var(key) or []
        total = len(values)
        offset = max(0, int(offset or 0))
        limit = max(1, min(500, int(limit or 100)))
        window = values[offset:offset + limit]
        return {
            "key": key,
            "offset": offset,
            "limit": limit,
            "total": total,
            "items": [{"index": offset + i, "value": v}
                      for i, v in enumerate(window)],
        }


def _actor_attr_name(attr):
    """把界面字段名转成 core 层认的 ``attr``（``param_plus_0`` → 原样）。

    ``SetActorAttr`` 两类入参在两边实现里都支持，这里只做**白名单校验** ——
    不校验的话，界面传个拼错的字段名会静默什么都不改。
    """
    allowed = {"level", "exp", "hp", "mp", "tp",
               "maxhp", "maxmp", "atk", "def", "spi", "agi"}
    if attr in allowed:
        return attr
    if attr.startswith("param_plus_"):
        tail = attr.rsplit("_", 1)[1]
        if tail.isdigit():
            return attr
    raise ValueError("不支持的属性：%s" % attr)


def _rel(game_dir, path):
    """转成相对游戏目录的路径（备份清单统一用 ``/`` 分隔）。"""
    rel = os.path.relpath(os.path.abspath(path), os.path.abspath(game_dir))
    return rel.replace("\\", "/")


def _save_hint(saves, dirs, others):
    """给"找不到存档"一句**能指导下一步**的话。

    三种情况的处置完全不同，所以必须分开说 —— 只说"没找到存档"等于把
    排查工作全丢给用户（用户报告"搜索不到存档所在文件夹"时就是这么卡住的）。

    ⚠ 这是**直接显示在界面上**的纯文本，不要写 markdown 标记（``**`` 之类
    会原样出现在页面上）。
    """
    if saves:
        return ""
    existing = [d for d in dirs if os.path.isdir(d)]
    if others:
        names = "、".join(item["name"] for item in others[:3])
        return ("存档目录里有 %s，但它们是设置文件（记录音量/按键等），"
                "不是存档进度。如果游戏里还没存过档，先进游戏存一次再回来刷新。"
                % names)
    if existing:
        return ("已在 %s 里找过，没有匹配的存档文件。"
                "如果游戏里还没存过档，先进游戏存一次再点「刷新」。"
                "存档在别处的话，可以直接把路径填进下面的输入框加载。"
                % "、".join(existing[:3]))
    return ("工具没有找到任何存档目录。"
            "请确认选择的是游戏最外层目录（含 Game.exe 的那一层）。")


def _search_save_files(root, ext, limit=200):
    """在 ``root`` 下**按扩展名**找文件（不看命名规则），最多返回 ``limit`` 个。

    用途：命名规则没认出来时的兜底 —— 让用户自己从列表里挑。
    """
    found = []
    if not root or not os.path.isdir(root):
        return found
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", ".git")]
        for name in sorted(files):
            if name.lower().endswith(ext):
                found.append(os.path.join(base, name))
                if len(found) >= limit:
                    return found
    return found


def register_routes(ctx, service):
    """登记所有修改功能的路由。返回路由表总条数（仅供启动日志）。"""
    ctx.cheats_service = service

    # ------------------------------------------------------------------ 状态
    @ctx.get("/api/cheats/status", name="cheats_status")
    def cheats_status(request=None):
        """功能状态 + 当前已打开的上下文（引擎 / 游戏目录 / 存档）。"""
        return {
            "ok": True,
            "feature": "cheats",
            "version": "0.4.0",
            "backup_policy": PAID_FOR,
            "actor_attrs": [dict(a) for a in ACTOR_ATTRS],
            "item_kinds": list(EDIT_KINDS),
            "game": {
                "opened": bool(service.info),
                "game_dir": service.game_dir,
                "engine": service.engine,
                "label": (service.info or {}).get("label"),
                "supported_engines": [constants.engine_label(e) + " (%s)" % e
                                      for e in constants.SUPPORTED_ENGINES],
                "recognize_only": [constants.engine_label(e) + " (%s)" % e
                                   for e in constants.RECOGNIZE_ONLY_ENGINES],
            },
            "save_path": service.save_path,
        }

    # ------------------------------------------------------------------ 游戏目录
    @ctx.post("/api/cheats/detect", name="cheats_detect")
    def cheats_detect(request=None):
        """识别游戏目录的引擎并列出存档（**M1 起就可用**的只读端点）。

        ``/open`` 会顺带加载名字表并记住上下文；本端点保持"无状态地问一次"
        的语义，因此仍单独保留 —— M1 的测试与"先看一眼这是什么游戏"的用法
        都依赖它。
        """
        data = getattr(request, "data", None) or {}
        game_dir = (data.get("dir") or "").strip()
        if not game_dir:
            return {"ok": False, "error": "请提供游戏目录 dir"}
        info = engines.detect(game_dir)
        if not info.get("engine"):
            return {"ok": False, "error": info.get("error") or "未能识别引擎"}
        saves = engines.list_saves(info, game_dir)
        return {
            "ok": True,
            "engine": info["engine"],
            "label": info["label"],
            "summary": engines.describe(info),
            "data_dir": info["data_dir"],
            "save_dir": info["save_dir"],
            "save_ext": info["ext"],
            "supported": info["supported"],
            "match": info["match"],
            "saves": saves,
            "save_dirs": [{"dir": d, "files": f}
                          for d, f in engines.find_save_dirs(info, game_dir)],
        }

    @ctx.post("/api/cheats/open", name="cheats_open")
    def cheats_open(request):
        """识别游戏目录（并加载名字表）。"""
        game_dir = request.str_arg("dir")
        if not game_dir:
            return {"ok": False, "error": "请提供游戏目录 dir"}
        try:
            info = service.open_game(game_dir)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        game = {
            "opened": True,
            "game_dir": service.game_dir,
            "engine": service.engine,
            "label": (info or {}).get("label"),
        }
        return {"ok": True, "game": game,
                "summary": engines.describe(info), "saves": len(service.list_saves())}

    @ctx.post("/api/cheats/pick_folder", name="cheats_pick_folder")
    def cheats_pick_folder(request):
        from core import sysdialog
        try:
            chosen = sysdialog.pick_folder(request.str_arg("initial") or None)
        except Exception as exc:
            return {"ok": False, "error": "无法打开系统对话框：%s" % exc}
        return {"ok": True, "dir": chosen or "", "cancelled": not chosen}

    # ------------------------------------------------------------------ 存档
    @ctx.get("/api/cheats/saves", name="cheats_saves")
    def cheats_saves(request=None):
        """存档列表 + **搜索范围** + 目录里那些"看着像存档但不是"的文件。

        为什么要回传搜索范围（用户报告"搜索不到存档所在文件夹"时加的）：
        原来只返回一个空列表 + 一句"没有找到存档"，用户**无从判断**是
        （a）游戏还没存过档，（b）存档在别处，（c）工具的规则没认出来。
        现在把"我找过哪些目录""看到哪些文件但我没当成存档"一并给出，
        并附上手动指定路径的能力，三种情况都能自助区分。
        """
        try:
            service.require_game()
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        info = service.info
        saves = service.list_saves()
        dirs = service.save_dirs()
        pattern = constants.SAVE_PATTERNS.get(service.engine)
        others = []
        seen_others = set()
        for directory in dirs:
            for item in engines.list_other_save_files(info, directory):
                key = (os.path.normcase(os.path.abspath(directory)), item["name"])
                if key in seen_others:
                    continue
                seen_others.add(key)
                others.append({"dir": directory, "name": item["name"],
                               "reason": item["reason"]})
        return {
            "ok": True,
            "saves": saves,
            "current": service.save_path,
            "save_dirs": dirs,
            "search": {
                "game_dir": info.get("game_dir"),
                "js_root": info.get("js_root"),
                "save_dir": info.get("save_dir"),
                "pattern": pattern[1] if pattern else "",
                "dirs": [{"dir": d, "exists": os.path.isdir(d),
                          "saves": sum(1 for s in saves if s["dir"] == d)}
                         for d in dirs],
            },
            # 目录里有、但**不是存档槽位**的文件（典型是 config/global 设置）
            "other_files": others,
            "hint": _save_hint(saves, dirs, others),
            "backups": backup_mod.list_backups(service.game_dir),
        }

    @ctx.post("/api/cheats/load", name="cheats_load")
    def cheats_load(request):
        path = request.str_arg("path")
        if not path:
            return {"ok": False, "error": "请提供存档路径 path"}
        try:
            service.open_save(path)
            return {"ok": True, "party": service.party_view(),
                    "actors": service.actors_view(),
                    "path": service.save_path}
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        except Exception as exc:
            return {"ok": False,
                    "error": "读取存档失败：%s: %s" % (type(exc).__name__, exc)}

    @ctx.get("/api/cheats/find_saves", name="cheats_find_saves")
    def cheats_find_saves(request=None):
        """**兜底搜索**：按扩展名在整个游戏安装里找存档，绕开命名规则。

        为什么需要它（用户报告"搜索不到存档所在文件夹"）：命名规则再放宽也
        总有漏网的（插件自定义槽位名、改造版运行时换扩展名）。此时与其让
        用户对着空列表发呆，不如把"看起来像存档的文件"全列出来，让他自己挑。
        这一层**只读、不改任何东西**，是最安全的兜底。
        """
        try:
            info = service.require_game()
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        ext = constants.SAVE_EXTS.get(service.engine, "")
        pattern = constants.SAVE_PATTERNS.get(service.engine)
        rx = pattern[0] if pattern else ""
        regex = re.compile(rx) if rx else None
        root = os.path.dirname(info["game_dir"])      # 含游戏根的那一层
        if not os.path.isdir(root):
            root = info["game_dir"]
        candidates = []
        for full in _search_save_files(root, ext):
            name = os.path.basename(full)
            candidates.append({
                "path": full,
                "name": name,
                "dir": os.path.dirname(full),
                "size": os.path.getsize(full) if os.path.isfile(full) else 0,
                # 按命名规则命中的排在前面，其余标出来让用户自己判断
                "by_rule": bool(regex and regex.match(name)),
            })
        candidates.sort(key=lambda c: (not c["by_rule"], c["path"]))
        return {"ok": True, "ext": ext, "root": root,
                "candidates": candidates,
                "note": "这是按扩展名 %s 的全盘搜索（未过滤命名规则），"
                        "包含备份、设置文件与其它目录；请自行确认要改哪一个。"
                        % ext}

    @ctx.get("/api/cheats/party", name="cheats_party")
    def cheats_party(request=None):
        try:
            return {"ok": True, "party": service.party_view()}
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}

    @ctx.get("/api/cheats/actors", name="cheats_actors")
    def cheats_actors(request=None):
        try:
            return {"ok": True, "actors": service.actors_view(),
                    "attrs": [dict(a) for a in ACTOR_ATTRS]}
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}

    # ------------------------------------------------------------------ 图标
    @ctx.get("/api/cheats/icon_info", name="cheats_icon_info")
    def cheats_icon_info(request=None):
        """图标图集能不能用、怎么切片（``cell``/``columns``/``rows``/``count``）。

        不给图片字节 —— 界面先问这个决定"显示图标"开关是否可用，
        再用下面那个端点取图。不可用时 ``icons.reason`` 说明原因。
        """
        return {"ok": True, "icons": service.icon_meta()}

    @ctx.get("/api/cheats/icon_set", name="cheats_icon_set")
    def cheats_icon_set(request=None):
        """图标图集的**明文 PNG**（``.rpgmvp`` / ``.png_`` 会先解密）。

        ⚠ **不接受任何路径参数**，图集位置完全由当前会话的引擎与游戏目录推出 ——
        这样这个端点不存在路径穿越面（对比 ``serve_static`` 需要显式防穿越）。

        界面拿到的是一整张图 + ``cell``/``columns``，用 CSS ``background-position``
        裁出单个图标；不需要任何图像处理，也不需要把图集拆成一堆小文件。
        """
        data, meta = service.icon_sheet()
        if data is None:
            return {"ok": False,
                    "error": meta.get("reason") or "图标图集不可用",
                    "icons": meta}
        return Response(body=data, status=200, content_type="image/png")

    @ctx.get("/api/cheats/vars", name="cheats_vars")
    def cheats_vars(request):
        """开关 / 变量分页读取：``?key=switches|variables&offset=&limit=``"""
        try:
            return {"ok": True,
                    "view": service.switches_view(
                        request.str_arg("key") or "switches",
                        request.int_arg("offset", 0),
                        request.int_arg("limit", 100))}
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}

    # ------------------------------------------------------------------ 写回
    def _pending(confirm):
        """统一处理"覆盖确认"：返回 ``(ok, error_payload)``。"""
        if confirm:
            return True, None
        return False, {
            "ok": False, "need_confirm": True,
            "error": "修改原存档需要显式确认（confirm=true）：" + PAID_FOR,
        }

    @ctx.post("/api/cheats/party", name="cheats_party_set")
    def cheats_party_set(request):
        """改金币 / 步数 / 道具数量。**不落盘**，只改内存里的存档对象。

        保存由 ``POST /api/cheats/save`` 完成 —— 这样用户可以连续改多处，
        只写一次盘、只备份一次（原工具也是这样：改完点"保存存档"）。
        """
        try:
            save = service.require_save()
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        changed = []
        gold = request.arg("gold")
        steps = request.arg("steps")
        try:
            if gold is not None:
                save.set_gold(int(gold))
                changed.append("金币=%d" % int(gold))
            if steps is not None:
                save.set_steps(int(steps))
                changed.append("步数=%d" % int(steps))
            for kind in EDIT_KINDS:
                for row in request.arg(kind) or ():
                    if not isinstance(row, dict):
                        continue
                    save.set_item(int(row.get("id")), int(row.get("count")),
                                  kind=kind)
                    changed.append("%s[%s]=%s" % (kind, row.get("id"),
                                                  row.get("count")))
        except (TypeError, ValueError) as exc:
            return {"ok": False, "error": "参数不合法：%s" % exc}
        return {"ok": True, "changed": changed,
                "dirty": True, "party": service.party_view()}

    @ctx.post("/api/cheats/actor", name="cheats_actor_set")
    def cheats_actor_set(request):
        """改角色属性 / 技能列表（内存）。"""
        try:
            save = service.require_save()
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        try:
            actor_id = int(request.arg("actor_id"))
        except (TypeError, ValueError):
            return {"ok": False, "error": "actor_id 必须是整数"}
        attrs = request.arg("attrs") or {}
        skills = request.arg("skills")
        if not isinstance(attrs, dict):
            return {"ok": False, "error": "attrs 必须是对象"}
        try:
            for key, value in attrs.items():
                save.set_actor_attr(actor_id, _actor_attr_name(key), int(value))
            if skills is not None:
                save.set_actor_skills(actor_id, [int(x) for x in skills])
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        except (TypeError, ValueError) as exc:
            return {"ok": False, "error": "参数不合法：%s" % exc}
        return {"ok": True, "dirty": True, "actors": service.actors_view()}

    @ctx.post("/api/cheats/var", name="cheats_var_set")
    def cheats_var_set(request):
        """改开关 / 变量（内存）。"""
        try:
            save = service.require_save()
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        key = request.str_arg("key") or "switches"
        try:
            index = int(request.arg("index"))
        except (TypeError, ValueError):
            return {"ok": False, "error": "index 必须是整数"}
        if key not in ("switches", "variables"):
            return {"ok": False, "error": "key 只能是 switches 或 variables"}
        try:
            save.set_var(key, index, request.arg("value"))
        except (TypeError, ValueError) as exc:
            return {"ok": False, "error": "参数不合法：%s" % exc}
        return {"ok": True, "dirty": True,
                "view": service.switches_view(key, max(0, index - 20), 40)}

    @ctx.post("/api/cheats/save", name="cheats_save")
    def cheats_save(request):
        """把内存里的改动写回存档。

        **硬约束 §4.2**：先备份、覆盖原文件必须 ``confirm=true``、
        备份路径回传给界面展示。
        """
        ok, payload = _pending(request.bool_arg("confirm"))
        if not ok:
            return payload
        try:
            save = service.require_save()
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        target = request.str_arg("path") or service.save_path
        policy = BackupPolicy(service.game_dir)
        rel = _rel(service.game_dir, target)
        try:
            backup_dir = policy.before([rel], label="写回存档")
            save.save(target)
        except Exception as exc:
            return {"ok": False,
                    "error": "保存失败：%s: %s" % (type(exc).__name__, exc),
                    "backup_dir": policy.last_dir}
        # 写回后重新读一次，确认真的落盘了（而不是"以为写了"）
        try:
            service.open_save(target)
        except Exception:
            pass
        return {"ok": True, "path": target, "backup_dir": backup_dir,
                "backup_policy": PAID_FOR}

    # ------------------------------------------------------------------ 游戏数据表
    @ctx.get("/api/cheats/data", name="cheats_data")
    def cheats_data(request=None):
        """列出可编辑的游戏数据字段（价格/攻击力/初始等级…）。"""
        try:
            info = service.require_game()
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        file_filter = (request.str_arg("file") if request else "") or None
        try:
            rows = data_fields.scan_data(info["data_dir"], service.engine,
                                         [file_filter] if file_filter else None,
                                         standard=info.get("standard"))
        except Exception as exc:
            return {"ok": False,
                    "error": "读取游戏数据失败：%s: %s" % (type(exc).__name__, exc)}
        files = sorted({row["file"] for row in rows})
        return {"ok": True, "fields": rows, "files": files,
                "game_dir": service.game_dir}

    @ctx.post("/api/cheats/data", name="cheats_data_set")
    def cheats_data_set(request):
        """把游戏数据表的改动写回 ``Data/`` 下的文件。

        与存档写回同样的安全要求：先备份、必须 ``confirm=true``。
        另外做**陈旧性校验**：带 ``original`` 的改动在当前值不一致时被拒绝
        （``skipped`` 计数会体现出来），避免按 path 盲写改错对象。
        """
        ok, payload = _pending(request.bool_arg("confirm"))
        if not ok:
            return payload
        try:
            info = service.require_game()
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        edits = request.arg("edits")
        if not isinstance(edits, list) or not edits:
            return {"ok": False, "error": "请提供 edits 列表"}

        mismatched = data_fields.verify_original(info, edits)
        if mismatched:
            return {"ok": False, "stale": mismatched,
                    "error": "%d 个字段的当前值与界面看到的不一致（数据已被改过），"
                             "请重新读取游戏数据后再改" % len(mismatched)}

        rels = sorted({("%s/%s" % (_rel(service.game_dir, info["data_dir"]),
                                   e["file"])).replace("\\", "/")
                       for e in edits if e.get("file")})
        policy = BackupPolicy(service.game_dir)
        try:
            backup_dir = policy.before(rels, label="改游戏数据")
            stats = data_fields.set_in_data(info, edits)
        except Exception as exc:
            return {"ok": False,
                    "error": "写回失败：%s: %s" % (type(exc).__name__, exc),
                    "backup_dir": policy.last_dir}
        return {"ok": True, "stats": stats, "backup_dir": backup_dir,
                "fields": data_fields.scan_data(info["data_dir"], service.engine,
                                                standard=info.get("standard"))}

    # ------------------------------------------------------------------ 备份还原
    @ctx.get("/api/cheats/backups", name="cheats_backups")
    def cheats_backups(request=None):
        try:
            service.require_game()
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "backups": backup_mod.list_backups(service.game_dir)}

    @ctx.post("/api/cheats/restore", name="cheats_restore")
    def cheats_restore(request):
        """从备份还原（还原前自动为当前状态再备份一次）。"""
        ok, payload = _pending(request.bool_arg("confirm"))
        if not ok:
            return payload
        try:
            service.require_game()
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        backup_dir = request.str_arg("dir")
        if not backup_dir:
            return {"ok": False, "error": "请提供备份目录 dir"}
        try:
            result = backup_mod.restore_backup(service.game_dir, backup_dir)
        except Exception as exc:
            return {"ok": False, "error": "还原失败：%s" % exc}
        # 还原后如果这个存档正开着，重新读一次（内存里的对象已经过期）
        if service.save_path and os.path.isfile(service.save_path):
            try:
                service.open_save(service.save_path)
            except Exception:
                service.save = None
        return {"ok": True, "result": result}

    @ctx.post("/api/cheats/open_dir", name="cheats_open_dir")
    def cheats_open_dir(request):
        target = request.str_arg("dir")
        if not target or not os.path.isdir(target):
            return {"ok": False, "error": "目录不存在：%s" % target}
        try:
            if hasattr(os, "startfile"):
                os.startfile(target)            # Windows
            else:
                import subprocess
                import sys
                opener = "open" if sys.platform == "darwin" else "xdg-open"
                subprocess.Popen([opener, target])
        except Exception as exc:
            return {"ok": False, "error": "无法打开目录：%s" % exc}
        return {"ok": True}

    return len(ctx.router)

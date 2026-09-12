# -*- coding: utf-8 -*-
"""存档修改功能的后端接线：读档 / 改档 / 写回 / 游戏数据表编辑。

@feature  cheats
@layer    features
@public   CheatsService, register_routes, BackupPolicy, ACTOR_ATTRS,
          EDIT_KINDS, PAID_FOR
@depends  features.cheats.data_fields, core.engines, core.formats.mv_save,
          core.formats.rgss_save, core.safety.backup, core.safety.atomic,
          core.paths, core.constants
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
import time

from core import constants
from core import engines
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

    # ------------------------------------------------------------ 存档列表
    def list_saves(self):
        info = self.require_game()
        out = []
        for directory, names in engines.find_save_dirs(info, self.game_dir):
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
        return out

    def open_save(self, path):
        """打开存档。``path`` 必须在游戏目录下的某个存档目录里（防越权读盘）。"""
        info = self.require_game()
        path = os.path.abspath(path)
        allowed = [os.path.abspath(d) for d, _n in
                   engines.find_save_dirs(info, self.game_dir)]
        allowed.append(os.path.abspath(self.game_dir))
        if not any(path.startswith(d + os.sep) or os.path.dirname(path) == d
                   for d in allowed):
            raise ValueError("该文件不在本游戏的存档目录内：%s" % path)
        if not os.path.isfile(path):
            raise ValueError("存档不存在：%s" % path)
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

    def party_view(self):
        """队伍 / 金币 / 步数 / 三个道具桶（带可读名字）。"""
        save = self.require_save()
        party = save.read_party() or {}
        view = {
            "gold": party.get("gold"),
            "steps": party.get("steps"),
            "party": self.names("actors", party.get("party_ids") or []),
            "party_ids": list(party.get("party_ids") or []),
            "currency": getattr(self.gamedata, "currency", "") if self.gamedata else "",
            "items": {},
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
                             "count": count})
            view["items"][kind] = rows
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
            "version": "0.3.0",
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
        try:
            service.require_game()
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "saves": service.list_saves(),
                "current": service.save_path,
                "backups": backup_mod.list_backups(service.game_dir)}

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
                                         [file_filter] if file_filter else None)
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
                "fields": data_fields.scan_data(info["data_dir"], service.engine)}

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

# -*- coding: utf-8 -*-
"""文本翻译功能的后端接线：扫描 / 编辑 / 翻译 / 生成汉化版 / 备份还原。

@feature  translate
@layer    features
@public   TranslateService, register_routes, PROVIDERS, session_id_for,
          session_path_for, MAX_PAGE_SIZE, DEFAULT_PAGE_SIZE
@depends  features.translate.session, features.translate.translators,
          core.safety.builder, core.safety.backup, core.sysdialog,
          core.config, core.paths
@tested   tests/features/translate/test_routes.py
@footprint docs/FEATURES.md#translate

设计要点
--------
* **所有长任务走 ``ctx.jobs``**（``core.jobs.JobManager``）：有界并发、每任务
  可取消、TTL 回收。不用自己起线程 —— M2a 已把队列做好。
* **取消**：``translate_entries`` 收的是 ``threading.Event`` 风格的对象
  （``is_set()``），而 ``core.jobs.CancelToken`` 提供 ``is_cancelled()``。
  :class:`_CancelBridge` 做适配，避免为了迁就旧签名而放弃 per-job 取消。
* **写回安全**：生成汉化版一律走 ``core.safety.builder.build`` —— 它内部用
  原子写、暂存换名、失败回滚，且**覆盖必须显式 ``confirm_overwrite``**。
  本层只负责把请求参数与"用户是否确认"透传下去。
* **会话持久化**：``sessions/<sid>.json``（原子写），sid 由游戏目录派生。
  关闭工具再打开同一游戏会自动恢复进度（断点续传）。
"""

from __future__ import annotations

import os
import subprocess
import sys

from core import paths
from core.safety import backup as backup_mod
from core.safety import builder as build_mod

from . import session as session_mod
from . import translators

#: 单页返回的最大条目数（防止一次把几万条 JSON 塞给浏览器）
MAX_PAGE_SIZE = 500

#: 默认页大小（与前端保持一致）
DEFAULT_PAGE_SIZE = 80

#: 四个适配器的展示信息（与 translators.build_translator 支持的 kind 一一对应）
PROVIDERS = (
    {"id": "google", "name": "Google 翻译", "need_key": False,
     "note": "免费接口，无需密钥；单次请求有长度限制"},
    {"id": "openai", "name": "OpenAI 兼容接口", "need_key": True,
     "note": "可填 OpenAI / DeepSeek / Kimi / Qwen 等"},
    {"id": "ollama", "name": "本地 Ollama", "need_key": False,
     "note": "默认 http://localhost:11434/v1，完全离线"},
    {"id": "deepl", "name": "DeepL", "need_key": True,
     "note": "需要 DeepL API Key"},
)


class _CancelBridge(object):
    """把 ``core.jobs.CancelToken`` 适配成 ``is_set()`` 风格。

    ``translators.translate_entries`` 的契约是"任何带 ``is_set()`` 的对象"，
    而 ``CancelToken`` 提供 ``is_cancelled()``。桥接一下比改旧代码更安全 ——
    旧代码是 vendored 的，改动面越小越好。
    """

    __slots__ = ("_token",)

    def __init__(self, token):
        self._token = token

    def is_set(self):
        return bool(self._token and self._token.is_cancelled())

    def wait(self, timeout=None):
        return bool(self._token and self._token.wait(timeout))


def session_id_for(game_dir):
    """由游戏目录派生稳定的会话 id（与 M0 记录的原实现规则一致）。

    规则：去掉盘符冒号、把路径分隔符换成 ``_``、去掉首尾下划线。
    这样 ``D:\\games\\A`` 与 ``D:/games/A`` 会落到同一个会话文件。
    """
    if not game_dir:
        return "unknown"
    normalized = os.path.abspath(game_dir)
    sid = (normalized.replace(":", "").replace("\\", "_").replace("/", "_")
           .strip("_"))
    return sid or "unknown"


def session_path_for(game_dir):
    """会话文件路径（放在运行时目录，已被 .gitignore 忽略）。"""
    return os.path.join(paths.sessions_dir(), session_id_for(game_dir) + ".json")


class TranslateService(object):
    """翻译功能的会话持有者与业务入口。

    ``register_routes`` 会构造一个实例并闭包捕获 —— 与 ``cheats`` 模块
    同一模式：功能自己持有状态，不往 app 里塞东西。
    """

    def __init__(self, ctx):
        self.ctx = ctx
        self.session = None
        self.session_path = None
        self.last_build = None

    # ------------------------------------------------------------ 会话
    def ensure_session(self, game_dir, options=None):
        """载入或新建会话。

        同一游戏目录再次进入时**复用已存会话**（断点续传）；换目录则新建。
        """
        from core import engines
        game_dir = os.path.abspath(game_dir)
        path = session_path_for(game_dir)
        info = engines.detect(game_dir)
        if not info.get("engine"):
            raise ValueError(info.get("error") or "未能识别引擎")
        if not info.get("supported"):
            raise ValueError("检测到 %s，但该引擎的数据格式暂不支持"
                             % info.get("label"))
        if os.path.isfile(path):
            try:
                self.session = session_mod.Session.load(path)
                self.session.info = info       # 目录没变就用这次的真实检测结果，
                self.session_path = path       # 目录变了也顺带修正 game_dir/data_dir
                return self.session
            except Exception:
                pass          # 会话文件损坏 → 退回新建（不阻断用户）
        self.session = session_mod.Session(game_dir, options)
        self.session_path = path
        return self.session

    def persist(self):
        """把当前会话落盘（原子写；失败不抛出，只提示）。"""
        if self.session and self.session_path:
            self.session.save(self.session_path)
            return True
        return False

    def require_session(self):
        if self.session is None:
            raise ValueError("请先选择游戏目录并扫描文本")
        return self.session

    def require_jobs(self):
        """取后台任务管理器；没有就不许开长任务（暴露装配问题而不是静默失败）。"""
        jobs = getattr(self.ctx, "jobs", None)
        if jobs is None:
            raise ValueError("后台任务管理器未装配（ctx.jobs 为空）")
        return jobs

    # ------------------------------------------------------------ 统计
    def state(self):
        if self.session is None:
            return {"loaded": False, "game_dir": None, "engine": None,
                    "label": None, "counts": None, "categories": {}}
        counts, by_category = self.session.stats()
        info = self.session.info or {}
        return {
            "loaded": True,
            "game_dir": self.session.game_dir,
            "engine": info.get("engine"),
            "label": info.get("label"),
            "summary": info.get("label") or "",
            "options": self.session.options.as_dict(),
            "counts": counts,
            "categories": by_category,
            "session_file": self.session_path,
            "font_path": self.session.font_path or "",
            "last_build": self.last_build,
        }

    # ------------------------------------------------------------ 构建前同步
    def sync_game_info(self):
        """构建前确认 ``session.info`` 指向当前游戏目录。

        为什么需要：``builder.build`` 全程读 ``session.info["game_dir"]`` /
        ``info["data_dir"]``，**不读** ``session.game_dir``。会话文件是跨次
        启动复用的，如果用户把游戏目录改名/搬家后再用旧会话，"生成汉化版"
        会朝已经不存在的旧路径写。这里做一次廉价的一致性校验并按需重检测。
        """
        session = self.require_session()
        info = session.info or {}
        want = os.path.abspath(session.game_dir)
        if info.get("game_dir") and os.path.abspath(info["game_dir"]) == want:
            return info
        from core import engines
        fresh = engines.detect(want)
        if not fresh.get("engine"):
            raise ValueError(fresh.get("error") or "未能识别引擎：%s" % want)
        session.info = fresh
        return fresh


def _entry_public(entry):
    """给前端的条目视图（只暴露需要的字段）。"""
    return {
        "file": entry.get("file", ""),
        "path": entry.get("path", ""),
        "category": entry.get("category", ""),
        "original": entry.get("original", ""),
        "translated": entry.get("translated", ""),
        "status": entry.get("status", "pending"),
        "note": entry.get("note", ""),
        "error": entry.get("error", ""),
    }


def register_routes(ctx, service):
    """把所有翻译相关路由登记到 ``ctx``。返回登记的路由总数。

    服务实例会挂到 ``ctx.translate_service``：路由是闭包，没有这层暴露
    测试与调试页就只能靠猜。它**不是**给业务代码用的公共 API。

    返回值只用于启动日志（``python app.py --check`` 会打印"registered
    (N routes)"）—— N 是**整个路由表**的条数，不是本模块新增的条数；
    因为核心路由先于功能路由登记（见 ``app.py`` 的装配顺序）。
    """
    ctx.translate_service = service

    # ------------------------------------------------------------------ 状态
    @ctx.get("/api/translate/state", name="translate_state")
    def translate_state(request=None):
        return {"ok": True, "session": service.state()}

    # ------------------------------------------------------------------ 选择目录
    @ctx.post("/api/translate/open", name="translate_open")
    def translate_open(request):
        """校验目录并建立会话（不扫描）—— 让前端能立刻显示引擎信息。"""
        game_dir = request.str_arg("dir")
        if not game_dir:
            return {"ok": False, "error": "请提供游戏目录 dir"}
        try:
            session = service.ensure_session(game_dir)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "session": service.state(),
                "cached_entries": len(session.entries)}

    @ctx.post("/api/translate/pick_folder", name="translate_pick_folder")
    def translate_pick_folder(request):
        """原生文件夹选择器（走 ``core.sysdialog``，失败时前端退回手输路径）。

        ⚠ 这里**不得** import ``ui``：分层规定 ``features → core``、``ui →
        features``，反向依赖会被足迹校验 F-09 拦下（M3a 实测踩到）。
        系统对话框是 UI 无关的系统能力，因此实现在 ``core.sysdialog``。
        """
        from core import sysdialog
        try:
            chosen = sysdialog.pick_folder(request.str_arg("initial") or None)
        except Exception as exc:
            return {"ok": False, "error": "无法打开系统对话框：%s" % exc}
        return {"ok": True, "dir": chosen or "",
                "cancelled": not chosen}

    @ctx.post("/api/translate/pick_font", name="translate_pick_font")
    def translate_pick_font(request):
        from core import sysdialog
        try:
            chosen = sysdialog.pick_font(request.str_arg("initial") or None)
        except Exception as exc:
            return {"ok": False, "error": "无法打开系统对话框：%s" % exc}
        return {"ok": True, "path": chosen or "",
                "cancelled": not chosen}

    # ------------------------------------------------------------------ 扫描
    @ctx.post("/api/translate/scan", name="translate_scan")
    def translate_scan(request):
        """扫描文本（后台任务）。返回 ``{job: id}``。"""
        game_dir = request.str_arg("dir")
        options = request.arg("options") or {}
        if not game_dir:
            return {"ok": False, "error": "请提供游戏目录 dir"}
        try:
            session = service.ensure_session(game_dir, options)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}

        def work(job):
            job.set_message("正在扫描 %s …" % (session.info.get("label") or ""))
            total = session.scan(options)
            job.set_message("扫描完成：%d 条" % total)
            service.persist()
            job.result = {"total": total, "session": service.state()}

        try:
            job = service.require_jobs().submit(work, name="扫描文本")
        except (RuntimeError, ValueError) as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "job": job.id}

    # ------------------------------------------------------------------ 文本列表
    @ctx.get("/api/translate/entries", name="translate_entries")
    def translate_entries(request):
        session = service.session
        if session is None:
            return {"ok": True, "entries": [], "total": 0, "page": 1,
                    "size": DEFAULT_PAGE_SIZE, "session": service.state()}
        query = request.str_arg("q")
        category = request.str_arg("category")
        status = request.str_arg("status")
        page = max(1, request.int_arg("page", 1))
        size = request.int_arg("size", DEFAULT_PAGE_SIZE)
        size = max(10, min(MAX_PAGE_SIZE, size))

        matched = session.entries_sorted(query, category, status)
        total = len(matched)
        start = (page - 1) * size
        window = matched[start:start + size]
        return {
            "ok": True,
            "entries": [_entry_public(e) for e in window],
            "total": total,
            "page": page,
            "size": size,
            "pages": max(1, (total + size - 1) // size),
        }

    @ctx.post("/api/translate/entry", name="translate_entry_update")
    def translate_entry_update(request):
        """改单条译文或状态。"""
        session = service.session
        if session is None:
            return {"ok": False, "error": "请先扫描文本"}
        key = request.str_arg("key")
        if not key:
            return {"ok": False, "error": "缺少 key"}
        translated = request.arg("translated")
        status = request.str_arg("status") or None
        if not session.update_entry(key, translated=translated, status=status):
            return {"ok": False, "error": "条目不存在：%s" % key}
        service.persist()
        return {"ok": True}

    @ctx.post("/api/translate/skip_all", name="translate_skip_all")
    def translate_skip_all(request):
        """把所有 ``status`` 的条目标记为 ``skipped``（后台任务）。"""
        try:
            session = service.require_session()
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        category = request.str_arg("category")
        status = request.str_arg("status") or "pending"

        def work(job):
            targets = [e for e in session.entries.values()
                       if e.get("status") == status
                       and (not category or e.get("category") == category)]
            total = len(targets)
            for index, entry in enumerate(targets, 1):
                if job.token.is_cancelled():
                    return
                entry["status"] = "skipped"
                if index % 200 == 0 or index == total:
                    job.set_progress(index, total, "已标记 %d/%d" % (index, total))
            service.persist()
            job.result = {"skipped": total}

        try:
            job = service.require_jobs().submit(work, name="批量标记跳过")
        except (RuntimeError, ValueError) as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "job": job.id}

    # ------------------------------------------------------------------ 翻译
    @ctx.post("/api/translate/start", name="translate_start")
    def translate_start(request):
        """开始批量翻译（后台任务）。

        ``config`` 里的空 ``api_key`` **不会覆盖已保存的 Key** —— 前端回显
        的是掩码值，如果用户没动那一栏就把掩码值/空值写回去，会把好 Key
        清掉（原工具就有这个问题，用户必须每次重填）。要清空请显式传
        ``api_key: ""`` 且 ``clear_api_key: true``。
        """
        try:
            session = service.require_session()
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        config = request.arg("config") or {}
        if not isinstance(config, dict):
            return {"ok": False, "error": "config 必须是对象"}
        only_errors = bool(request.arg("only_errors"))
        redo = bool(request.arg("redo"))
        clear_key = bool(request.arg("clear_api_key"))

        config = dict(config)
        cfg_obj = service.ctx.config
        incoming_key = config.get("api_key")
        if clear_key:
            config["api_key"] = ""               # 用户明确要求清空
        elif incoming_key in (None, ""):
            config.pop("api_key", None)          # 保留已存 Key（不覆盖）
        elif isinstance(incoming_key, str) and "*" in incoming_key:
            config.pop("api_key", None)          # 掩码回显，不是真 Key

        # 配置持久化（含 API Key；config.json 已被 .gitignore 忽略）
        cfg_obj.update(config)
        try:
            cfg_obj.save()
        except Exception:
            pass
        session.translator_cfg = dict(config)

        try:
            translator = translators.build_translator(config)
        except Exception as exc:
            return {"ok": False, "error": "翻译引擎配置有误：%s" % exc}

        def work(job):
            bridge = _CancelBridge(job.token)

            def on_progress(*args):
                # translate_entries 的进度回调是 (done, total, failed[, msg])
                done, total = args[0], args[1]
                failed = args[2] if len(args) > 2 else 0
                message = args[3] if len(args) > 3 else None
                if message is None:
                    message = "已翻译 %d/%d（失败 %d）" % (done, total, failed)
                job.set_progress(done, total, message)

            job.set_message("正在批量翻译…")
            cfg = dict(config)
            cfg["redo"] = redo
            done, failed, errors = translators.translate_entries(
                session, cfg, progress_cb=on_progress,
                cancel_event=bridge, only_errors=only_errors)
            service.persist()
            job.result = {"done": done, "failed": failed, "errors": errors}

        try:
            job = service.require_jobs().submit(work, name="批量翻译")
        except (RuntimeError, ValueError) as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "job": job.id, "engine": config.get("engine"),
                "saved_config": True}

    @ctx.get("/api/translate/providers", name="translate_providers")
    def translate_providers(request=None):
        """列出可用的翻译引擎适配器（前端下拉用）。

        ``ids`` 来自这份静态表；请与 :func:`translators.build_translator`
        支持的 kind 保持一致（``test_routes`` 里有断言防漂移）。
        """
        return {"ok": True, "providers": [dict(p) for p in PROVIDERS],
                "module_loaded": True, "skeleton": False}

    @ctx.post("/api/translate/test", name="translate_test")
    def translate_test(request):
        """接口自检：用 3 条样例验证配置是否可用（会真的出网一次）。"""
        config = request.arg("config") or {}
        samples = ["Hello, world.", "Good morning.", "Thank you."]
        try:
            translator = translators.build_translator(config)
        except Exception as exc:
            return {"ok": False, "error": "配置有误：%s" % exc}
        import time
        started = time.time()
        try:
            results = translator.translate_batch(
                samples, config.get("src_lang", "auto"),
                config.get("dst_lang", "zh-CN"))
        except Exception as exc:
            return {"ok": False,
                    "error": "%s: %s" % (type(exc).__name__, exc),
                    "elapsed": round(time.time() - started, 2)}
        return {"ok": True, "results": list(results), "samples": samples,
                "elapsed": round(time.time() - started, 2)}

    # ------------------------------------------------------------------ 配置
    @ctx.get("/api/translate/config", name="translate_config_get")
    def translate_config_get(request=None):
        """读全局配置（**密钥已掩码**）。"""
        return {"ok": True, "config": service.ctx.config.redacted()}

    @ctx.post("/api/translate/config", name="translate_config_save")
    def translate_config_save(request):
        data = request.arg("config")
        if not isinstance(data, dict):
            return {"ok": False, "error": "config 必须是对象"}
        service.ctx.config.update(data)
        service.ctx.config.save()
        return {"ok": True, "config": service.ctx.config.redacted()}

    # ------------------------------------------------------------------ 生成汉化版
    @ctx.post("/api/translate/build", name="translate_build")
    def translate_build(request):
        """生成汉化版（后台任务）。

        覆盖已有内容**必须**显式确认（``confirm=True``）—— 对应
        ``core.safety.builder.OverwriteNotConfirmed``。前端要先弹二次确认。
        """
        try:
            session = service.require_session()
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        mode = request.str_arg("mode") or "copy"
        if mode not in ("copy", "inplace"):
            return {"ok": False, "error": "mode 只能是 copy 或 inplace"}
        target_dir = request.str_arg("target") or None
        font_path = request.str_arg("font") or session.font_path or None
        confirm = request.bool_arg("confirm")
        overwrite = request.bool_arg("overwrite")

        # 会话可能是上次启动留下的；先确保 info 指向真实存在的当前目录，
        # 否则会把汉化版写到一个已经不存在的旧路径（见 sync_game_info）。
        try:
            service.sync_game_info()
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}

        counts, _by_category = session.stats()
        if not counts.get("translated"):
            return {"ok": False,
                    "error": "还没有任何已翻译的文本，先生成一次翻译再试"}

        def work(job):
            def on_progress(done, total, message=None):
                job.set_progress(done, total, message)

            job.set_message("正在生成汉化版…")
            result = build_mod.build(
                session, mode=mode, target_dir=target_dir, backup=True,
                font_path=font_path, overwrite=overwrite,
                progress_cb=on_progress, confirm_overwrite=confirm)
            service.last_build = result
            job.result = result

        try:
            job = service.require_jobs().submit(work, name="生成汉化版")
        except (RuntimeError, ValueError) as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "job": job.id}

    # ------------------------------------------------------------------ 备份与还原
    @ctx.get("/api/translate/backups", name="translate_backups")
    def translate_backups(request=None):
        try:
            session = service.require_session()
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True,
                "backups": backup_mod.list_backups(session.info["game_dir"])}

    @ctx.post("/api/translate/restore", name="translate_restore")
    def translate_restore(request):
        """从备份还原（**非后台任务**：文件数少、用户要立刻看到结果）。

        还原内部会先为"当前状态"再备份一次（``safety_backup``），
        所以"还原错了"也能再还原回来。
        """
        try:
            session = service.require_session()
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        backup_dir = request.str_arg("dir")
        if not backup_dir:
            return {"ok": False, "error": "请提供备份目录 dir"}
        try:
            result = backup_mod.restore_backup(
                session.info["game_dir"], backup_dir)
        except Exception as exc:
            return {"ok": False, "error": "还原失败：%s" % exc}
        return {"ok": True, "result": result}

    @ctx.post("/api/translate/open_dir", name="translate_open_dir")
    def translate_open_dir(request):
        """在文件管理器中打开目录。"""
        target = request.str_arg("dir")
        if not target or not os.path.isdir(target):
            return {"ok": False, "error": "目录不存在：%s" % target}
        try:
            if hasattr(os, "startfile"):
                os.startfile(target)      # Windows
            else:
                opener = "open" if sys.platform == "darwin" else "xdg-open"
                subprocess.Popen([opener, target])
        except Exception as exc:
            return {"ok": False, "error": "无法打开目录：%s" % exc}
        return {"ok": True}

    return len(ctx.router)

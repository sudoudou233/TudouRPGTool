# -*- coding: utf-8 -*-
"""
Game session: scanned entries + translation state.

@feature  translate
@layer    features
@public   Session, ScanOptions, DEFAULT_OPTIONS
@depends  core.engines, core.formats.mv_mz_data, core.formats.rgss_data
@tested   tests/features/translate/
@footprint docs/FEATURES.md#translate
@note     vendored：来自 rpgmaker_translation_tool/tool/session.py。
@note     注意 engines.detect 的返回结构已是新 core 的统一结构，
@note     M3a 需核对 info 字段使用点（原实现用 engine_name/supported）。
"""

from __future__ import annotations

import json
import os

from core import engines
from core.formats import mv_mz_data as mv_mz
from core.formats import rgss_data as vxace


DEFAULT_OPTIONS = {
    "include_comments": False,
    "include_notes": False,
    "include_event_names": False,
    "include_animations": True,
}


class ScanOptions:
    def __init__(self, options=None):
        opts = dict(DEFAULT_OPTIONS)
        opts.update(options or {})
        self.include_comments = bool(opts.get("include_comments"))
        self.include_notes = bool(opts.get("include_notes"))
        self.include_event_names = bool(opts.get("include_event_names"))
        self.include_animations = bool(opts.get("include_animations"))

    def as_dict(self):
        return {
            "include_comments": self.include_comments,
            "include_notes": self.include_notes,
            "include_event_names": self.include_event_names,
            "include_animations": self.include_animations,
        }


class Session:
    def __init__(self, game_dir, options=None):
        self.game_dir = os.path.abspath(game_dir)
        self.info = engines.detect(self.game_dir)
        self.options = ScanOptions(options)
        self.entries = {}
        self.cache = {}
        self.translator_cfg = {}
        self.font_path = ""

    def key_for(self, entry):
        return "%s|%s" % (entry["file"], entry["path"])

    def scan(self, options=None):
        self.options = ScanOptions(options or self.options.as_dict())
        if not self.info["supported"]:
            raise ValueError(self.info.get("error") or "不支持的引擎")
        engine = self.info["engine"]
        if engine in ("mv", "mz"):
            raw = mv_mz.extract(self.info["data_dir"], self.options)
        else:
            raw = vxace.extract(self.info["data_dir"], self.options)
        self.entries = {}
        for e in raw:
            self.entries[self.key_for(e)] = e
        return len(self.entries)

    def entries_sorted(self, q="", category="", status=""):
        out = []
        ql = q.strip().lower()
        for e in self.entries.values():
            if category and e["category"] != category:
                continue
            if status and e["status"] != status:
                continue
            if ql:
                hay = (e["original"] + " " + e.get("translated", "") + " " +
                       e.get("note", "") + " " + e["path"]).lower()
                if ql not in hay:
                    continue
            out.append(e)
        return out

    def update_entry(self, key, translated=None, status=None):
        e = self.entries.get(key)
        if not e:
            return False
        if translated is not None:
            e["translated"] = translated
        if status is not None:
            e["status"] = status
            if status == "translated" and e["translated"]:
                self.cache[e["original"]] = e["translated"]
        if e["status"] == "translated" and e["translated"]:
            self.cache[e["original"]] = e["translated"]
        return True

    def stats(self):
        counts = {"total": 0, "translated": 0, "pending": 0, "skipped": 0, "error": 0}
        by_cat = {}
        for e in self.entries.values():
            counts["total"] += 1
            counts[e["status"]] = counts.get(e["status"], 0) + 1
            by_cat[e["category"]] = by_cat.get(e["category"], 0) + 1
        return counts, by_cat

    def save(self, path):
        payload = {
            "game_dir": self.game_dir,
            "info": self.info,
            "options": self.options.as_dict(),
            "translator_cfg": self.translator_cfg,
            "font_path": self.font_path,
            "cache": self.cache,
            "entries": list(self.entries.values()),
        }
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, path)

    @classmethod
    def load(cls, path):
        with open(path, encoding="utf-8") as f:
            payload = json.load(f)
        s = cls(payload["game_dir"], payload.get("options"))
        s.info = payload.get("info") or engines.detect(payload["game_dir"])
        s.cache = payload.get("cache") or {}
        s.translator_cfg = payload.get("translator_cfg") or {}
        s.font_path = payload.get("font_path") or ""
        s.entries = {}
        for e in payload.get("entries") or []:
            s.entries[s.key_for(e)] = e
        return s

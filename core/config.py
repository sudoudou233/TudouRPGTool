# -*- coding: utf-8 -*-
"""全局设置读写（含 API Key 的本地持久化）。

@feature  none
@layer    core
@public   AppConfig, load_config, save_config, DEFAULTS, redacted
@depends  (stdlib only)
@tested   tests/unit/test_config.py
@footprint docs/MODULES.md#coreconfig

迁移来源：rpgmaker_translation_tool/tool/config.py:25/37（``load_config`` /
``save_config``）。行为保持不变（缺字段用默认值补齐、原子写），但落盘位置与
掩码能力做了修正：

* 原实现把 ``config.json`` 写在工具目录（``CONFIG_PATH``，tool/config.py:11），
  现在由调用方注入 ``config_path``，默认仍为工程根，避免隐式副作用。
* 新增 :func:`redacted`，用于日志/接口返回时掩码 API Key
  （原工具 /api/config 原样返回含 Key 的完整配置）。
"""

from __future__ import annotations

import json
import os

from . import paths

#: 配置默认值。键名与沿用原工具，保证旧 config.json 可直接迁移。
DEFAULTS = {
    # ---- 翻译引擎 ----
    "engine": "openai",
    "base_url": "https://api.deepseek.com",
    "api_key": "",
    "model": "deepseek-v4-flash",
    "src_lang": "auto",
    "dst_lang": "zh-CN",
    "workers": 8,
    "batch_size": 40,
    # ---- 界面/其他 ----
    "last_game_dir": "",
    "last_output_dir": "",
    "font_path": "",
}

#: 需要在对外返回/日志里掩码的键名（大小写不敏感）。
SECRET_KEYS = ("api_key", "apikey", "token", "secret", "password")


def default_config_path():
    """默认配置文件路径（工程根 ``config.json``，已被 .gitignore 忽略）。"""
    return os.path.join(paths.project_root(), "config.json")


class AppConfig(object):
    """配置对象：字典语义 + 便捷属性 + 显式落盘。

    用法::

        cfg = AppConfig.load()          # 读默认位置的 config.json
        cfg["workers"] = 4
        cfg.save()

    设计取舍：不采用"每次 set 就写盘"的自动持久化，避免界面输入过程中
    频繁 IO；由调用方在"保存设置"时显式调用 :meth:`save`。
    """

    def __init__(self, data=None, path=None):
        merged = dict(DEFAULTS)
        if isinstance(data, dict):
            merged.update(data)
        self._data = merged
        self.path = path or default_config_path()

    # ------------------------------------------------------------ 字典语义
    def __getitem__(self, key):
        return self._data[key]

    def __setitem__(self, key, value):
        self._data[key] = value

    def __contains__(self, key):
        return key in self._data

    def get(self, key, default=None):
        return self._data.get(key, default)

    def update(self, other):
        if isinstance(other, dict):
            self._data.update(other)
        return self

    def as_dict(self):
        """返回内部字典的浅拷贝。"""
        return dict(self._data)

    # ------------------------------------------------------------ 便捷属性
    @property
    def engine(self):
        return self._data.get("engine") or DEFAULTS["engine"]

    @property
    def api_key(self):
        return self._data.get("api_key") or ""

    @property
    def workers(self):
        try:
            return max(1, int(self._data.get("workers", DEFAULTS["workers"])))
        except (TypeError, ValueError):
            return DEFAULTS["workers"]

    @property
    def batch_size(self):
        try:
            return max(1, int(self._data.get("batch_size", DEFAULTS["batch_size"])))
        except (TypeError, ValueError):
            return DEFAULTS["batch_size"]

    # ------------------------------------------------------------ 落盘
    def save(self, path=None):
        """原子写（临时文件 + ``os.replace``）。返回写入路径。"""
        target = path or self.path or default_config_path()
        write_config(self._data, target)
        self.path = target
        return target

    @classmethod
    def load(cls, path=None):
        """读配置；文件不存在或损坏时回落到默认值（不抛异常）。"""
        target = path or default_config_path()
        return cls(read_config(target), path=target)

    # ------------------------------------------------------------ 输出安全
    def redacted(self):
        """返回掩码后的副本，供接口返回 / 日志打印。"""
        return redacted(self._data)


def read_config(path):
    """读 JSON 配置；任何失败都返回空 dict（由 :class:`AppConfig` 补默认值）。"""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def write_config(data, path):
    """原子写 JSON 配置：临时文件 + ``os.replace``。

    沿用 rpgmaker_translation_tool/tool/config.py:37-43 的原子写手法。
    """
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    payload = dict(DEFAULTS)
    payload.update(data or {})
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    return path


def redacted(data):
    """把疑似密钥的值替换为掩码，保留"是否已配置"的信息。

    保留前后各 2 个字符便于用户核对，长度不足一律替换为 ``***``。
    """
    out = {}
    for key, value in (data or {}).items():
        if str(key).lower() in SECRET_KEYS and isinstance(value, str) and value:
            out[key] = "***" if len(value) <= 4 else "%s***%s" % (value[:2], value[-2:])
        else:
            out[key] = value
    return out


def load_config(path=None):
    """兼容原工具的函数式接口，返回 dict。"""
    return AppConfig.load(path).as_dict()


def save_config(cfg, path=None):
    """兼容原工具的函数式接口，返回落盘后的完整 dict。"""
    target = path or default_config_path()
    write_config(cfg, target)
    loaded = dict(DEFAULTS)
    loaded.update(cfg or {})
    return loaded

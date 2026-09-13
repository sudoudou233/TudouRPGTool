# -*- coding: utf-8 -*-
"""一次性迁移：修复会话里**地图事件对话**的旧路径（N-25）。

@feature  none
@layer    tools
@public   main, fix_path, migrate_session, session_files
@depends  core.paths
@tested   (一次性脚本；其修法由 tests/features/translate/
          test_path_and_output_regressions.py 的断言守住)
@footprint docs/STATE.md

背景
----
`mv_mz_data.extract` 给**地图事件**的对话条目拼路径时漏了 `list` 这一层：

    实际产出：events/2/pages/0/1/parameters/0      ← 缺 "list"
    正确形状：events/2/pages/0/list/1/parameters/0

后果与 N-15 完全一样：**扫描、界面、统计全都正常**，只有"生成汉化版"按路径
写回时定位失败，被 `except` 吞掉 —— 整张地图的对话静默丢失。
实测某游戏 45,037 条里丢了 24,709 条（54.86%），用户报"对话文本没有被翻译到"。

代码已修（`mv_mz_data` 的 `events/%d/pages/%d/list`）。但**已经扫过的会话**
里存的是旧路径，直接重建会丢掉用户已完成的翻译 —— 因此本脚本就地修路径。

它只做一件事：按正则把 `events/<数字>/pages/<数字>/<剩余>` 改写成
`events/<数字>/pages/<数字>/list/<剩余>`，并把条目按新的 key（`file|path`）
重新归位。幂等：已经带 `list` 的条目原样保留。

用法::

    python tools/fix_session_paths.py            # 列出会话，逐个检查
    python tools/fix_session_paths.py --apply    # 就地修复（先备份）
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
while not os.path.isfile(os.path.join(ROOT, "app.py")):
    ROOT = os.path.dirname(ROOT)
sys.path.insert(0, ROOT)

from core import paths  # noqa: E402

#: ``events/12/pages/0/1/parameters/0`` -> 在 ``pages/0`` 之后补 ``list``
_OLD_MAP_PATH = re.compile(r"^(events/\d+/pages/\d+)/(?!list/)(.+)$")


def fix_path(path):
    """返回修正后的路径；不需要修则原样返回。幂等。"""
    if not isinstance(path, str):
        return path
    match = _OLD_MAP_PATH.match(path)
    if not match:
        return path
    return "%s/list/%s" % (match.group(1), match.group(2))


def migrate_session(payload):
    """就地修正 ``entries`` 的 path 与 key。返回 (修改条数, 总条数)。"""
    entries = payload.get("entries") or []
    if isinstance(entries, dict):
        items = list(entries.values())
    else:
        items = list(entries)

    changed = 0
    rebuilt = {}
    for entry in items:
        if not isinstance(entry, dict):
            continue
        old = entry.get("path")
        new = fix_path(old)
        if new != old:
            entry["path"] = new
            changed += 1
        key = "%s|%s" % (entry.get("file", ""), entry.get("path", ""))
        rebuilt[key] = entry

    if isinstance(entries, dict):
        entries.clear()
        entries.update(rebuilt)
    else:
        payload["entries"] = list(rebuilt.values())
    return changed, len(rebuilt)


def session_files():
    directory = paths.sessions_dir()
    if not os.path.isdir(directory):
        return []
    return sorted(os.path.join(directory, n) for n in os.listdir(directory)
                  if n.endswith(".json"))


def main(argv=None):
    parser = argparse.ArgumentParser(description="修复会话里地图事件对话的旧路径")
    parser.add_argument("--apply", action="store_true",
                        help="就地修复（默认只做干跑，不改文件）")
    parser.add_argument("--file", default=None, help="只处理指定的会话文件")
    args = parser.parse_args(argv)

    files = [args.file] if args.file else session_files()
    if not files:
        print("没有找到任何会话文件（%s）" % paths.sessions_dir())
        return 1

    total_changed = 0
    for path in files:
        try:
            with open(path, encoding="utf-8") as f:
                payload = json.load(f)
        except Exception as exc:
            print("跳过（读不了）：%s：%s" % (os.path.basename(path), exc))
            continue
        entries = payload.get("entries") or []
        count = len(entries)
        changed, rebuilt = migrate_session(payload)
        print("%-58s %6d 条，需修 %6d 条"
              % (os.path.basename(path)[:58], count, changed))
        if not changed:
            continue
        total_changed += changed
        if not args.apply:
            continue
        backup = "%s.bak_%s" % (path, time.strftime("%Y%m%d%H%M%S"))
        shutil.copy2(path, backup)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, path)
        print("    已修复并备份到 %s" % os.path.basename(backup))

    print()
    if args.apply:
        print("共修复 %d 条。" % total_changed)
    else:
        print("共需修复 %d 条。加 --apply 才会写盘。" % total_changed)
    return 0


if __name__ == "__main__":
    sys.exit(main())

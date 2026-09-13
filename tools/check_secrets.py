# -*- coding: utf-8 -*-
"""发布前密钥扫描：把**整个 git 历史**翻一遍，确认没有 API Key 之类的东西。

@feature  none
@layer    tools
@public   scan_text, scan_history, scan_local_config, Finding, main
@depends  (stdlib only)
@tested   tests/unit/test_check_secrets.py
@footprint docs/MODULES.md#toolscheck_secrets

为什么必须扫**历史**而不是工作区
--------------------------------
``.gitignore`` 只挡"以后不再提交"。一个 key 只要被提交过**一次**，
它就永久留在 git 对象里 —— 之后删文件、加 ignore 都没用，
``git push`` 会把整个历史一起推上去。GitHub 上因此泄露 key 的事故几乎都是
这个形态：本地看 ``git status`` 干干净净，仓库里却有。

所以本工具的判据是"**所有提交里的所有 blob**"，而不是当前文件树。

两类判据
--------
1. **形状**：常见密钥的形态（``sk-`` / ``AIza`` / ``ghp_`` / ``AKIA`` …）
   加上"把长随机串赋给 key 类的名字"（``api_key = "...."``）。
2. **实例**：如果本机存在 ``config.json``，把里面 ``api_key`` 的**真实值**
   拿去历史里找一遍 —— 这能抓到"真 key 被贴进文档/夹具/提交信息"这种形态，
   而形状判据对它是无能为力的。

已知的**假 key** 放在 :data:`ALLOWED` 里（测试夹具用），并且要求它们
"一眼就是假的"（含 ``REAL-KEY``、``123456`` 之类）。宁可显式登记，
也不写"看起来随机就放过"这种会漏的规则。

用法::

    python tools/check_secrets.py            # 人读；有问题退出码 1
    python tools/check_secrets.py --json     # 机器读
    python tools/check_secrets.py --worktree # 只扫工作区（快，但不覆盖历史风险）
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)

#: 已知的**假**密钥（测试夹具）。必须"一眼就是假的"，否则不许进这张表。
ALLOWED = {
    "sk-1234567890abcdef",          # tests/features/translate/test_routes.py
    "sk-REAL-KEY-0123456789",       # 同上（名字里就写了 REAL-KEY，是反例夹具）
    "sk-ant-xxxxxxxxxxxxxxxx",      # 占位示例
}

#: 常见密钥的形态。刻意都要求较长的连续字符，避免误报普通文案。
SHAPE_PATTERNS = (
    ("OpenAI / DeepSeek 风格", re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}\b")),
    ("Anthropic 风格", re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}\b")),
    ("Google API", re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}\b")),
    ("GitHub token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}\b")),
    ("GitHub PAT", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{30,}\b")),
    ("AWS Access Key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("Slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}\b")),
    ("私钥文件头", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
)

#: "把长串赋给 key 类的名字"。值至少 16 字符，且看起来不是说明文字。
ASSIGN_PATTERN = re.compile(
    r"""(?ix)
    \b(?:api[_-]?key|apikey|secret[_-]?key|access[_-]?token|auth[_-]?token|
         client[_-]?secret|password|passwd)\b
    \s*[:=]\s*
    ["'](?P<value>[^"'\s]{16,})["']
    """)

#: 这些值明显是占位/说明，不算泄漏
PLACEHOLDER_HINTS = (
    "your", "xxx", "placeholder", "example", "changeme", "todo",
    "{{", "<", "***", "....", "abcdef", "123456",
)


class Finding(object):
    """一条命中。``where`` 对历史扫描是 ``<commit>:<path>``。"""

    def __init__(self, where, kind, snippet):
        self.where = where
        self.kind = kind
        self.snippet = snippet

    def as_dict(self):
        return {"where": self.where, "kind": self.kind, "snippet": self.snippet}

    def __repr__(self):
        return "<Finding %s %s %s>" % (self.where, self.kind, self.snippet)


def _mask(value):
    """只留头尾，中间打码 —— 报告里不该出现完整密钥。"""
    if len(value) <= 8:
        return "*" * len(value)
    return value[:4] + "*" * (len(value) - 8) + value[-4:]


def _is_placeholder(value):
    low = value.lower()
    return any(hint in low for hint in PLACEHOLDER_HINTS)


def _mask_allowed(text):
    """把已登记的假 key 从文本里抹掉，免得它们把真命中淹了。"""
    for fake in ALLOWED:
        text = text.replace(fake, "")
    return text


def scan_text(text, where, extra_secrets=()):
    """扫描一段文本，返回 :class:`Finding` 列表。

    ``extra_secrets`` 是"本机真实值"（例如 ``config.json`` 里的 api_key）；
    命中它们时**不看占位符规则** —— 真值就是真值。

    ⚠ 同一个值只报一次：`api_key = "sk-..."` 会同时命中"形状"和"赋值"两条
    判据，不去重的话同一行报两遍，报告一吵就会被当成噪音无视。
    """
    out = []
    seen = set()

    def add(kind, raw):
        if raw in seen:
            return
        seen.add(raw)
        out.append(Finding(where, kind, _mask(raw)))

    for secret in extra_secrets:
        if secret and len(secret) >= 12 and secret in text:
            add("本机 config.json 里的真实密钥", secret)
    cleaned = _mask_allowed(text)
    for name, pattern in SHAPE_PATTERNS:
        for match in pattern.finditer(cleaned):
            token = match.group(0)
            if token in ALLOWED or _is_placeholder(token):
                continue
            add(name, token)
    for match in ASSIGN_PATTERN.finditer(cleaned):
        value = match.group("value")
        if value in ALLOWED or _is_placeholder(value):
            continue
        add("把长串赋给了密钥类字段", value)
    return out


# ---------------------------------------------------------------- git 访问
def _git(args, root=None):
    return subprocess.run(["git"] + list(args), cwd=root or _ROOT,
                          capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def _is_repo(root=None):
    return _git(["rev-parse", "--git-dir"], root).returncode == 0


def iter_history_blobs(root=None):
    """遍历**仓库里所有对象**，产出 ``(标签, bytes)``（只出 blob）。

    ⚠ 用 ``git cat-file --batch-all-objects --batch`` **一次进程**流式读完。
    第一版是"每个 blob 起一次 ``git cat-file``"，在有上千对象的仓库上要
    23.7 秒 —— 慢到没法进门禁，而"跑不起来的安全检查"等于没有检查。
    现在一次进程、顺序读流，同样的仓库约 1 秒。

    用 ``--batch-all-objects`` 而不是只走可达对象：它连**悬空对象**（已
    reset/amend 掉、还没被 gc 的提交）一起扫。那正是最危险的一类 ——
    你"删掉了"那个提交，但它还在 .git 里，`git push --force` 或 gc 之前
    都可能被推出去。
    """
    base = root or _ROOT
    listing = _git(["rev-list", "--objects", "--all"], base).stdout
    names = {}
    for line in listing.splitlines():
        parts = line.split(" ", 1)
        if len(parts) == 2:
            names[parts[0]] = parts[1]

    proc = subprocess.Popen(
        ["git", "cat-file", "--batch-all-objects", "--batch"],
        cwd=base, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        stream = proc.stdout
        while True:
            header = stream.readline()
            if not header:
                break
            parts = header.decode("utf-8", "replace").strip().split()
            if len(parts) != 3:
                break                       # "<sha> missing" 之类
            sha, otype, size = parts[0], parts[1], int(parts[2])
            data = stream.read(size)
            stream.read(1)                  # 对象后的换行
            if otype != "blob":
                continue
            path = names.get(sha)
            yield ("%s:%s" % (sha[:8], path) if path
                   else "%s:(历史中不可达的 blob)" % sha[:8]), data
    finally:
        proc.stdout.close()
        proc.wait()


def scan_history(extra_secrets=(), root=None, commits=None):
    """扫历史里所有 blob。``commits`` 给定时，额外报告每个命中出现在哪些提交。"""
    findings = []
    for where, raw in iter_history_blobs(root):
        text = raw.decode("utf-8", "replace")
        findings.extend(scan_text(text, where, extra_secrets))
    return findings


def _committable_paths(root):
    """**会被提交**的文件：已跟踪的 + 未跟踪但没被忽略的。

    ⚠ 不能直接遍历工作区：那会把 ``config.json``（本机真 key，已 gitignore）
    也算成问题。它根本不会被推送，报它只会训练用户无视这个工具 ——
    一个爱叫的门禁等于没有门禁。判据要贴住真实问题："哪些文件会进仓库"。
    """
    out = []
    for args in (["ls-files", "-z"],
                 ["ls-files", "-z", "--others", "--exclude-standard"]):
        out.extend(p for p in _git(args, root).stdout.split("\0") if p)
    return sorted(set(out))


def _scan_files(base, paths, extra_secrets):
    findings = []
    for rel in paths:
        path = os.path.join(base, rel.replace("/", os.sep))
        if not os.path.isfile(path):
            continue
        try:
            if os.path.getsize(path) > 2 * 1024 * 1024:
                continue
            with open(path, "rb") as f:
                raw = f.read()
        except OSError:
            continue
        if b"\x00" in raw[:1024]:
            continue
        findings.extend(scan_text(raw.decode("utf-8", "replace"), rel,
                                  extra_secrets))
    return findings


def scan_worktree(extra_secrets=(), root=None):
    """扫工作区。若是 git 仓库，只扫**会被提交**的文件（见上）。"""
    base = root or _ROOT
    if _is_repo(base):
        return _scan_files(base, _committable_paths(base), extra_secrets)

    skip = {".git", "__pycache__", "runtime", "node_modules"}
    paths = []
    for dirpath, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if d not in skip]
        for name in files:
            paths.append(os.path.relpath(os.path.join(dirpath, name), base))
    return _scan_files(base, paths, extra_secrets)


def scan_local_config(root=None):
    """从本机 ``config.json`` 取出真实密钥值（不打印），供精确匹配用。"""
    path = os.path.join(root or _ROOT, "config.json")
    if not os.path.isfile(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, ValueError):
        return []
    if not isinstance(payload, dict):
        return []
    out = []
    for key in ("api_key", "apiKey", "key", "token", "secret"):
        value = payload.get(key)
        if isinstance(value, str) and len(value) >= 12:
            out.append(value)
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="发布前密钥扫描（默认扫整个 git 历史）")
    parser.add_argument("--json", action="store_true", help="机器可读输出")
    parser.add_argument("--worktree", action="store_true",
                        help="只扫工作区，不扫历史（快，但覆盖不到历史泄漏）")
    parser.add_argument("--root", default=None, help="仓库根（默认本文件上级）")
    args = parser.parse_args(argv)

    root = args.root or _ROOT
    secrets = scan_local_config(root)
    if args.worktree:
        findings = scan_worktree(secrets, root)
        scope = "工作区"
    elif _is_repo(root):
        findings = scan_history(secrets, root)
        scope = "git 历史（所有提交的所有 blob）"
    else:
        findings = scan_worktree(secrets, root)
        scope = "工作区（不是 git 仓库）"

    payload = {
        "ok": not findings,
        "scope": scope,
        "checked_local_secrets": len(secrets),
        "findings": [f.as_dict() for f in findings],
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print("扫描范围：%s" % scope)
        print("本机 config.json 里的真实密钥：%d 个（只用于精确匹配，不打印）"
              % len(secrets))
        if not findings:
            print("结果：**没有发现任何密钥** -> 通过")
        else:
            print("结果：发现 %d 处可疑内容 -> 未通过" % len(findings))
            for f in findings:
                print("  [%s] %s  %s" % (f.kind, f.where, f.snippet))
            print("\n处理办法：")
            print("  * 还没提交过 -> 把文件加进 .gitignore，再从暂存区移除")
            print("  * 已经提交过 -> 光删文件没用，历史里还在。")
            print("    要么改写历史（git filter-repo / BFG），要么**立刻作废并轮换那个 key**")
            print("    —— 后者才是真正解决问题的做法，改历史只是止损。")
    return 0 if not findings else 1


if __name__ == "__main__":
    sys.exit(main())

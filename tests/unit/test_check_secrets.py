# -*- coding: utf-8 -*-
"""``tools/check_secrets.py``（发布前密钥扫描）的测试。

@feature  none
@layer    tests
@public   TestScanText, TestScanWorktree, TestScanHistory, TestRealRepoIsClean
@depends  tools/check_secrets.py
@tested   (本文件即测试)
@footprint docs/MODULES.md#toolscheck_secrets

这个文件里最重要的不是"能扫出 key"，而是 :class:`TestScanHistory` ——
它在一个合成仓库里**先提交一个 key、再删掉它、再提交一次**，
然后断言扫描器**仍然能找到**。

原因是本工程反复强调的那条纪律：`.gitignore` 只挡"以后不再提交"。
一个 key 只要进过一次提交，它就永久留在 git 对象里，`git push` 会把整个
历史一起推上去 —— 本地 `git status` 干干净净，远端仓库里却有。
所以"扫历史"这件事本身必须被测试证明有效，否则它只是给了用户虚假的安全感。
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest

_ROOT = os.path.dirname(os.path.abspath(__file__))
while not os.path.isfile(os.path.join(_ROOT, "app.py")):
    parent = os.path.dirname(_ROOT)
    if parent == _ROOT:
        raise RuntimeError("无法定位工程根（未找到 app.py）")
    _ROOT = parent
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import tools.check_secrets as secrets                      # noqa: E402

#: 一个**没进白名单**的假 key，形状像真的（20+ 位）。
#:
#: ⚠ 刻意用**拼接**而不是字面量：这个扫描器要扫自己所在的仓库，
#: 直接写成一整串的话（"sk-live-" 后面紧接 20 位），它会把**自己的测试文件**
#: 报成泄漏 —— 门禁自己把自己绊倒。拆开后文件里不再出现"key 形状"的连续串
#: （前缀后面紧跟引号），正则匹配不到，而运行时拼出来的值仍然是完整的、
#: 能真正测到判据。由 :class:`TestSelfScan` 守住这一点。
#: （写这段注释时也踩了同一个坑：第一版把整串写进了注释里，照样被报。）
PLANTED = "sk-live-" + "9f3ac21b7e4d6058a1c2"
#: 赋值式泄漏用的另一个（没有 sk- 前缀，靠"赋给 api_key"这条判据命中）
PLANTED2 = "d41f8a2c9b7e5" + "061"
#: 私钥头，同样拆开
PEM_HEAD = "-----BEGIN RSA " + "PRIVATE KEY-----"


def git(args, cwd):
    return subprocess.run(["git"] + list(args), cwd=cwd, capture_output=True,
                          text=True, encoding="utf-8", errors="replace")


def init_repo(path):
    """在 ``path`` 里建一个能提交的 git 仓库（不依赖全局 git 配置）。"""
    git(["init", "--quiet"], path)
    git(["config", "user.email", "t@example.com"], path)
    git(["config", "user.name", "tester"], path)
    git(["config", "commit.gpgsign", "false"], path)
    return path


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with io.open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


# ---------------------------------------------------------------------------
# 文本判据
# ---------------------------------------------------------------------------
class TestScanText(unittest.TestCase):

    def test_finds_openai_style_key(self):
        hits = secrets.scan_text('key = "%s"' % PLANTED, "x.py")
        self.assertTrue(hits, "没扫出 sk- 形状的密钥")
        self.assertTrue(any("OpenAI" in h.kind for h in hits))

    def test_finds_assignment_to_key_like_names(self):
        hits = secrets.scan_text('api_key: "%s"' % PLANTED2, "cfg.json")
        self.assertTrue(hits, "没扫出 api_key 赋值")

    def test_ignores_the_allowlisted_fixtures(self):
        """测试夹具里那几个**故意**的假 key 不该一直报警（否则门禁会被无视）。"""
        for fake in secrets.ALLOWED:
            with self.subTest(fake=fake):
                self.assertEqual(secrets.scan_text('k = "%s"' % fake, "t.py"), [])

    def test_allowlist_is_not_stale(self):
        """白名单里的每一项都必须**真的还在用**，否则该删掉（避免越积越松）。"""
        path = os.path.join(_ROOT, "tests", "features", "translate",
                            "test_routes.py")
        with open(path, encoding="utf-8") as f:
            blob = f.read()
        for fake in secrets.ALLOWED:
            if fake in ("sk-ant-xxxxxxxxxxxxxxxx",):
                continue                     # 这条是形态示例，不是夹具
            with self.subTest(fake=fake):
                self.assertIn(fake, blob,
                              "白名单里的 %r 已经没人用了，请删掉它" % fake)

    def test_same_value_is_reported_only_once(self):
        """同一个 key 同时命中"形状"和"赋值"两条判据时只报一次。

        不去重的话同一行报两遍，报告一吵就会被当成噪音无视 ——
        一个会被无视的门禁等于没有门禁。
        """
        hits = secrets.scan_text('api_key = "%s"' % PLANTED, "cfg.json")
        self.assertEqual(len(hits), 1, [h.as_dict() for h in hits])

    def test_real_local_secret_is_flagged_even_if_it_looks_like_a_placeholder(self):
        """本机真实值优先于"占位符"规则 —— 真值就是真值。"""
        value = "my-super-secret-value-1234"
        hits = secrets.scan_text("doc says %s" % value, "README.md",
                                 extra_secrets=[value])
        self.assertTrue(hits)
        self.assertTrue(any("真实密钥" in h.kind for h in hits))

    def test_ignores_documented_placeholders(self):
        text = ('api_key = "your-api-key-here"\n'
                'api_key = "xxxxxxxxxxxxxxxxxxxx"\n'
                'api_key = "<YOUR_KEY>"\n'
                'api_key = "1234567890123456"\n'
                'api_key = "short"\n')
        self.assertEqual(secrets.scan_text(text, "README.md"), [])

    def test_findings_are_masked(self):
        """报告里**不能出现完整密钥** —— 那等于又泄露一次。"""
        hits = secrets.scan_text('k = "%s"' % PLANTED, "x.py")
        for h in hits:
            self.assertNotIn(PLANTED, h.snippet)
            self.assertIn("*", h.snippet)

    def test_private_key_header(self):
        hits = secrets.scan_text(PEM_HEAD + "\nMIIE", "id_rsa")
        self.assertTrue(any("私钥" in h.kind for h in hits))

    def test_github_and_aws_shapes(self):
        for token in ("ghp_" + "a" * 36, "AKIA" + "B" * 16):
            with self.subTest(token=token[:8]):
                self.assertTrue(secrets.scan_text(token, "x"), token)


# ---------------------------------------------------------------------------
# 工作区
# ---------------------------------------------------------------------------
class TestScanWorktree(unittest.TestCase):

    def setUp(self):
        try:
            self.tmp = tempfile.TemporaryDirectory(prefix="secrets_",
                                                   ignore_cleanup_errors=True)
        except TypeError:                       # Python 3.8 / 3.9
            self.tmp = tempfile.TemporaryDirectory(prefix="secrets_")
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name

    def test_finds_a_planted_key(self):
        write(os.path.join(self.root, "sub", "cfg.py"),
              'API_KEY = "%s"\n' % PLANTED)
        hits = secrets.scan_worktree(root=self.root)
        self.assertEqual(len(hits), 1, hits)
        self.assertIn("cfg.py", hits[0].where)

    def test_skips_binary_files(self):
        path = os.path.join(self.root, "blob.bin")
        with open(path, "wb") as f:
            f.write(b"\x00\x01\x02" + PLANTED.encode("ascii"))
        self.assertEqual(secrets.scan_worktree(root=self.root), [])

    def test_skips_runtime_and_git_dirs(self):
        """``runtime/`` 是用户自己的数据（里面有真 key 很正常），不该被扫。"""
        write(os.path.join(self.root, "runtime", "secret.txt"), PLANTED)
        write(os.path.join(self.root, ".git", "x.txt"), PLANTED)
        self.assertEqual(secrets.scan_worktree(root=self.root), [])

    def test_skips_gitignored_files_in_a_repo(self):
        """已 gitignore 的文件**不会被推送**，报它只会让门禁变成噪音。

        典型例子就是本机 ``config.json``：里面有真 key，但它永远不会进仓库。
        判据要贴住真实问题 —— "哪些文件会进仓库"。
        """
        init_repo(self.root)
        write(os.path.join(self.root, ".gitignore"), "config.json\n")
        write(os.path.join(self.root, "config.json"),
              json.dumps({"api_key": PLANTED}))
        write(os.path.join(self.root, "kept.py"), "x = 1\n")
        self.assertEqual(secrets.scan_worktree(root=self.root), [],
                         "已 gitignore 的 config.json 被误报了")

    def test_but_an_untracked_not_ignored_file_is_flagged(self):
        """没被忽略的未跟踪文件**会**被 `git add -A` 带进去，所以要报。"""
        init_repo(self.root)
        write(os.path.join(self.root, "notes.txt"), PLANTED + "\n")
        hits = secrets.scan_worktree(root=self.root)
        self.assertEqual(len(hits), 1, "未跟踪但没忽略的文件漏报了")

    def test_clean_tree_is_clean(self):
        write(os.path.join(self.root, "a.py"), "print('hello')\n")
        self.assertEqual(secrets.scan_worktree(root=self.root), [])


# ---------------------------------------------------------------------------
# 历史（**本文件最重要的部分**）
# ---------------------------------------------------------------------------
class TestScanHistory(unittest.TestCase):

    def setUp(self):
        try:
            self.tmp = tempfile.TemporaryDirectory(prefix="secrets_git_",
                                                   ignore_cleanup_errors=True)
        except TypeError:                       # Python 3.8 / 3.9
            self.tmp = tempfile.TemporaryDirectory(prefix="secrets_git_")
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name
        if git(["--version"], self.root).returncode != 0:
            self.skipTest("没有 git")
        init_repo(self.root)

    def commit(self, message):
        git(["add", "-A"], self.root)
        result = git(["commit", "--quiet", "-m", message], self.root)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_key_committed_then_deleted_is_still_found(self):
        """**核心断言**：提交过的 key，删掉文件也还在历史里。

        这正是"加个 .gitignore 就安全了"这个想法错在哪：
        ignore 只影响以后的提交，历史里的对象一个都不会少。
        """
        target = os.path.join(self.root, "config.py")
        write(target, 'API_KEY = "%s"\n' % PLANTED)
        self.commit("加入配置（含真 key）")

        os.remove(target)
        self.commit("删掉配置文件")
        self.assertFalse(os.path.exists(target), "文件应当已被删除")

        # 工作区现在是干净的……
        self.assertEqual(secrets.scan_worktree(root=self.root), [])
        # ……但历史里还在
        hits = secrets.scan_history(root=self.root)
        self.assertTrue(hits, "扫历史没找到已删除的 key —— 这个守卫是空转的")
        self.assertTrue(any("config.py" in h.where for h in hits),
                        "命中里没有路径信息：%s" % [h.where for h in hits])

    def test_key_added_to_gitignore_but_committed_is_still_found(self):
        """补了 .gitignore **也**没用 —— 已经进过对象库就是进过了。"""
        target = os.path.join(self.root, "tokens.txt")
        write(target, PLANTED + "\n")
        self.commit("误提交 token")
        write(os.path.join(self.root, ".gitignore"), "tokens.txt\n")
        os.remove(target)
        self.commit("加 ignore 并删除文件")

        self.assertTrue(secrets.scan_history(root=self.root),
                        "补 .gitignore 之后历史里就查不到了？说明判据不对")

    def test_clean_history_is_clean(self):
        write(os.path.join(self.root, "a.py"), "print('hello')\n")
        self.commit("clean")
        self.assertEqual(secrets.scan_history(root=self.root), [])

    def test_real_local_config_value_is_matched_against_history(self):
        """本机 config.json 里的真实值要拿去历史里精确匹配。"""
        write(os.path.join(self.root, "config.json"),
              json.dumps({"api_key": PLANTED2}))
        write(os.path.join(self.root, "docs.md"), "笔记：%s\n" % PLANTED2)
        self.commit("把 key 贴进了文档")
        os.remove(os.path.join(self.root, "docs.md"))
        self.commit("删掉文档")

        found = secrets.scan_local_config(self.root)
        self.assertEqual(found, [PLANTED2])
        hits = secrets.scan_history(extra_secrets=found, root=self.root)
        self.assertTrue(any("真实密钥" in h.kind for h in hits),
                        "没按真实值匹配到：%s" % [h.kind for h in hits])


# ---------------------------------------------------------------------------
# CLI 与本仓库
# ---------------------------------------------------------------------------
class TestCli(unittest.TestCase):

    def setUp(self):
        try:
            self.tmp = tempfile.TemporaryDirectory(prefix="secrets_cli_",
                                                   ignore_cleanup_errors=True)
        except TypeError:                       # Python 3.8 / 3.9
            self.tmp = tempfile.TemporaryDirectory(prefix="secrets_cli_")
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name

    def run_cli(self, *extra):
        """跑 CLI 并把它的输出吞掉。

        ⚠ 必须吞：有一个用例**故意**让扫描器报出泄漏，它会在测试输出里打
        "发现 1 处可疑内容 -> 未通过"。测试全绿时却满屏这种字样，会训练人
        无视这个工具 —— 和"爱叫的门禁等于没有门禁"是同一件事。
        """
        buf = io.StringIO()
        stdout, sys.stdout = sys.stdout, buf
        try:
            code = secrets.main(["--root", self.root] + list(extra))
        finally:
            sys.stdout = stdout
        return code, buf.getvalue()

    def test_exit_code_is_zero_on_clean_tree(self):
        write(os.path.join(self.root, "a.py"), "x = 1\n")
        code, _out = self.run_cli("--worktree")
        self.assertEqual(code, 0)

    def test_exit_code_is_one_when_found(self):
        """门禁必须**非零退出**，否则 CI 不会拦下来。"""
        write(os.path.join(self.root, "a.py"), 'k = "%s"\n' % PLANTED)
        code, out = self.run_cli("--worktree")
        self.assertEqual(code, 1)
        self.assertIn("未通过", out)

    def test_json_output_shape(self):
        write(os.path.join(self.root, "a.py"), 'k = "%s"\n' % PLANTED)
        code, out = self.run_cli("--worktree", "--json")
        payload = json.loads(out)
        self.assertEqual(code, 1)
        self.assertFalse(payload["ok"])
        self.assertEqual(len(payload["findings"]), 1)
        self.assertNotIn(PLANTED, out, "报告里出现了完整密钥")

    def test_human_output_offers_a_way_out(self):
        """报错时要告诉人怎么办 —— 尤其"已经提交过"那种情况。"""
        write(os.path.join(self.root, "a.py"), 'k = "%s"\n' % PLANTED)
        _code, out = self.run_cli("--worktree")
        self.assertIn("轮换", out)
        self.assertIn("gitignore", out)


class TestSelfScan(unittest.TestCase):
    """扫描器要能扫**自己所在的仓库** —— 包括这个测试文件。"""

    def test_fixtures_are_not_key_shaped(self):
        """夹具只能用拼接构造。

        写成字面量的话，扫描器会把本文件自己报成泄漏；而如果为了绕开它
        去加白名单，那几条"证明扫描器有效"的测试就会因为白名单而失效 ——
        等于把门禁拆了。所以这里钉住"文件里不许出现 key 形状的连续串"。
        """
        with open(os.path.abspath(__file__), encoding="utf-8") as f:
            source = f.read()
        self.assertEqual(secrets.scan_text(source, "self"), [],
                         "本测试文件里有 key 形状的字面量 —— 请改成拼接构造")
        # 反向确认：拼出来的值仍然**是**会被判据命中的（否则就是自欺）
        self.assertTrue(secrets.scan_text("k=%s" % PLANTED, "x"),
                        "PLANTED 已经不像 key 了，测试变成空转")


class TestRealRepoIsClean(unittest.TestCase):
    """本仓库自己的历史必须是干净的（这是发布前的最后一道闸）。"""

    @classmethod
    def setUpClass(cls):
        cls.scanned = False
        if git(["--version"], _ROOT).returncode != 0:
            raise unittest.SkipTest("没有 git")
        cls.secrets = secrets.scan_local_config(_ROOT)
        cls.findings = secrets.scan_history(extra_secrets=cls.secrets,
                                           root=_ROOT)

    def test_history_has_no_secrets(self):
        self.assertEqual(
            [f.as_dict() for f in self.findings], [],
            "git 历史里发现了疑似密钥 —— 发 GitHub 前必须处理（先轮换 key）")

    def test_local_config_is_not_tracked(self):
        """本机 config.json（含真 key）绝不能被跟踪。"""
        out = git(["ls-files", "--error-unmatch", "config.json"], _ROOT)
        self.assertNotEqual(out.returncode, 0,
                            "config.json 被 git 跟踪了 —— 里面有真实 API Key")

    def test_gitignore_covers_the_secret_paths(self):
        """`.gitignore` 必须覆盖真实会存密钥的位置。"""
        with open(os.path.join(_ROOT, ".gitignore"), encoding="utf-8") as f:
            text = f.read()
        for pattern in ("config.json", "runtime/"):
            with self.subTest(pattern=pattern):
                self.assertIn(pattern, text,
                              ".gitignore 少了 %s —— 密钥可能会被提交" % pattern)


if __name__ == "__main__":
    unittest.main(verbosity=2)

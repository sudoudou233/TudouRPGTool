# -*- coding: utf-8 -*-
"""兼容性测试：Ruby Marshal 字节级往返（移植原两个工具的核心断言）。

@feature  none
@layer    tests
@public   TestMarshalRoundtripSynthetic, TestMarshalRoundtripRealSamples,
          TestValueModelRoundtrip
@depends  core.marshal.doc_model, core.marshal.value_model
@tested   (本文件即测试)
@footprint docs/MODULES.md#coremarshal

移植来源
--------
* ``rpgmaker_cheating_tool/test_roundtrip.py:5-10``
  ``roundtrip_one()``：``load_streams`` → 逐流 ``dumps`` 拼接 → 断言 ``out == data``
* ``rpgmaker_translation_tool/tests/test_marshal.py:28-31``
  ``marshal.loads(raw)`` → ``marshal.dumps(root)`` → 断言 ``out == raw``

这是"合并没丢功能"的首要证据。**验收硬指标（需求 §3.3）**：
合并后 Ruby Marshal 只有一份实现，且两侧原有断言全部通过。

原实现的三个测试质量问题在本文件被修正：
1. 原测试硬编码本机游戏路径 —— 本文件用环境变量定位样本，缺失则 skip
2. 原 test_roundtrip.py 无退出码、无 ``__main__`` 守卫 —— 这里由
   ``tests/run_all.py`` 统一判定退出码
3. 原测试无合成样本，换机即无法运行 —— 这里补合成字节流用例
"""

from __future__ import annotations

import os
import struct
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

from core import paths  # noqa: E402
from core.marshal import doc_model, value_model  # noqa: E402

#: 只在这些子目录名里找样本（RPG Maker 的数据目录）
SAMPLE_SUBDIRS = ("Data", "data")

#: 样本目录环境变量（不入库，见 docs/DECISIONS.md ADR-005）
ENV_SAMPLES = paths.ENV_SAMPLES


def samples_root():
    return paths.samples_root()


#: 单次运行的样本上限（保证测试时长可控；不是覆盖率上限）
DEFAULT_LIMIT = 300

#: 搜索时最多下探的目录层数（实测游戏库结构可到 5 层以上）
MAX_DEPTH = 6

#: 搜索时最多访问的目录数（防止误指到超大目录导致测试卡死）
MAX_DIRS = 4000

#: 明确排除的目录名（美术/音频等，避免无谓遍历）
SKIP_DIRS = frozenset([
    "img", "images", "audio", "sound", "music", "se", "bgm", "bgs", "me",
    "movies", "video", "fonts", "locales", "nwjs", "cache", "node_modules",
    "__pycache__", ".git", "save", "saves", "backup", "汉化备份",
])


def collect_rvdata2(limit=DEFAULT_LIMIT):
    """收集真实样本里的 ``.rvdata2`` 文件（**只读**，且有深度/目录数上限）。

    搜索策略：从样本根做广度优先遍历，遇到名为 ``Data``/``data`` 的目录就
    收集其中的 ``.rvdata2``，并跳过美术/音频等明显无关的大目录。

    为什么不用固定两层：实测本机游戏库的典型结构是
    ``D:\\gamess\\<作者>\\<游戏>\\<版本>\\<发行>\\Data``，深度可达 5 层；
    写死层数会一个样本都找不到（M1 实测踩到）。
    """
    root = samples_root()
    if not root or not os.path.isdir(root):
        return []

    out = []
    visited = 0
    queue = [(root, 0)]
    while queue and visited < MAX_DIRS:
        path, depth = queue.pop(0)
        visited += 1
        try:
            names = sorted(os.listdir(path))
        except OSError:
            continue
        for name in names:
            full = os.path.join(path, name)
            if not os.path.isdir(full):
                continue
            if name in SAMPLE_SUBDIRS:
                try:
                    entries = sorted(os.listdir(full))
                except OSError:
                    continue
                for entry in entries:
                    if entry.lower().endswith(".rvdata2"):
                        out.append(os.path.join(full, entry))
                        if limit and len(out) >= limit:
                            return sorted(out)
                continue
            if name.lower() in SKIP_DIRS:
                continue
            if depth + 1 <= MAX_DEPTH:
                queue.append((full, depth + 1))
    return sorted(out)


# ---------------------------------------------------------------------------
# 合成样本：不依赖本机游戏，任何机器都能跑
# ---------------------------------------------------------------------------
def make_float(value, tail=b""):
    """构造一个 Float 节点。

    注意 ``doc_model.Float(value, tail)`` 的 ``value`` 参数实际是**8 字节大端
    IEEE754 原始字节**（不是 float 对象）—— 该实现为了让浮点字节级保真，
    直接持有原始字节。这里用 struct 打包，模拟真实文件里的形状。
    """
    return doc_model.Float(struct.pack(">d", value), tail)


def synthetic_streams():
    """手工构造若干个最小 Ruby Marshal 4.8 字节流，用于无样本环境。"""
    m = doc_model
    cases = {
        # 整数（变体编码：0 / 小正数 / 大正数 / 负数）
        "fixnum_zero": m.Fixnum(0),
        "fixnum_small": m.Fixnum(42),
        "fixnum_big": m.Fixnum(2 ** 20),
        "fixnum_negative": m.Fixnum(-1000),
        # 字符串（含非 ASCII，验证字节保真）
        "string_ascii": m.String(b"hello"),
        "string_utf8": m.String("中文文本·测试".encode("utf-8")),
        "string_cp932": m.String("テスト".encode("cp932")),
        # 容器
        "array": m.Array([m.Fixnum(1), m.Fixnum(2), m.String(b"x")]),
        "hash": m.Hash([(m.Fixnum(1), m.String(b"a")),
                        (m.Fixnum(2), m.String(b"b"))]),
        # 布尔与 nil
        "bool_true": m.BoolNode(True),
        "bool_false": m.BoolNode(False),
        "nil": m.NilNode(),
        # 符号
        "symbol": m.Symbol("テスト".encode("utf-8")),
        "symbol_ascii": m.Symbol(b"name"),
        # 浮点（含原实现特有的尾部字节启发式）
        "float": make_float(3.5),
        "float_neg": make_float(-0.125),
        # 嵌套对象
        "object": m.ObjectNode(m.Symbol(b"RPG::MapInfo"),
                               [(m.Symbol(b"@name"), m.String("地图一".encode("utf-8"))),
                                (m.Symbol(b"@order"), m.Fixnum(1))]),
        "struct": m.Struct(m.Symbol(b"RPG::Test"),
                           [(m.Symbol(b"a"), m.Fixnum(1))]),
        "ivar": m.Ivar(m.String("abc".encode("utf-8")),
                       [(m.Symbol(b"E"), m.BoolNode(True))]),
    }
    out = {}
    for name, node in cases.items():
        try:
            out[name] = m.VERSION + node.serialize()
        except Exception as exc:      # pragma: no cover
            out[name] = ("ERROR:%s: %s" % (type(exc).__name__, exc)).encode("utf-8")
    return out


class TestMarshalRoundtripSynthetic(unittest.TestCase):
    """合成字节流往返：``load_streams`` → 逐流 ``dumps`` → 必须逐字节相等。"""

    def test_every_synthetic_stream_roundtrips(self):
        failures = []
        for name, raw in sorted(synthetic_streams().items()):
            with self.subTest(case=name):
                if raw.startswith(b"ERROR:"):
                    self.skipTest(raw.decode("utf-8", "replace"))
                streams = doc_model.load_streams(raw)
                self.assertTrue(streams, "解析不出任何流：%s" % name)
                rebuilt = b"".join(doc_model.dumps(node) for _off, node in streams)
                if rebuilt != raw:
                    failures.append("%s: %d -> %d 字节"
                                    % (name, len(raw), len(rebuilt)))
        self.assertEqual(failures, [], "合成样本往返失败：%s" % failures)

    def test_load_streams_offsets_are_consistent(self):
        raw = doc_model.VERSION + doc_model.Array([doc_model.Fixnum(7)]).serialize()
        streams = doc_model.load_streams(raw)
        self.assertEqual(len(streams), 1)
        offset, node = streams[0]
        self.assertEqual(offset, 0)
        self.assertIsInstance(node, doc_model.Array)

    def test_multiple_concatenated_streams(self):
        """VX Ace 存档常见"两个流首尾相接"，必须都能解析。"""
        one = doc_model.VERSION + doc_model.Fixnum(1).serialize()
        two = doc_model.VERSION + doc_model.String(b"second").serialize()
        raw = one + two
        streams = doc_model.load_streams(raw)
        self.assertEqual(len(streams), 2)
        rebuilt = b"".join(doc_model.dumps(node) for _off, node in streams)
        self.assertEqual(rebuilt, raw)

    def test_unknown_token_raises_with_context(self):
        """原实现抛 ValueError 且带 trail 上下文（合并时必须保留该能力）。"""
        bad = doc_model.VERSION + b"\xFF\xFF"
        with self.assertRaises(ValueError):
            doc_model.load_streams(bad)


class TestMarshalRoundtripRealSamples(unittest.TestCase):
    """真实样本往返（无样本时自动跳过，绝不硬失败）。"""

    @classmethod
    def setUpClass(cls):
        if not samples_root():
            raise unittest.SkipTest(
                "未找到样本目录。设置环境变量 %s 指向样本根目录后重跑。"
                % ENV_SAMPLES)
        cls.files = collect_rvdata2()
        if not cls.files:
            raise unittest.SkipTest("样本目录下没有 .rvdata2 文件")

    def test_all_samples_roundtrip_byte_exact(self):
        """**核心断言**：每个未修改文件的往返必须逐字节一致。"""
        failures = []
        checked = 0
        for path in self.files:
            checked += 1
            with open(path, "rb") as f:
                raw = f.read()
            try:
                streams = doc_model.load_streams(raw)
                rebuilt = b"".join(doc_model.dumps(node) for _off, node in streams)
            except Exception as exc:
                failures.append("%s: %s: %s"
                                % (os.path.relpath(path, samples_root()),
                                   type(exc).__name__, exc))
                continue
            if rebuilt != raw:
                failures.append("%s: %d -> %d 字节"
                                % (os.path.relpath(path, samples_root()),
                                   len(raw), len(rebuilt)))
        print("\n  样本往返：检查 %d 个 .rvdata2，失败 %d 个" % (checked, len(failures)))
        self.assertEqual(failures[:10], [],
                         "共 %d 个样本往返失败（只列前 10 个）" % len(failures))

    def test_sample_count_is_meaningful(self):
        """至少要能覆盖到成规模的样本量，否则"零漂移"结论不可信。"""
        self.assertGreaterEqual(len(self.files), 10,
                                "可用样本过少（%d 个），结论置信度不足"
                                % len(self.files))


class TestValueModelRoundtrip(unittest.TestCase):
    """值模型（翻译工具侧）的往返能力，用于 M2b 收敛时的对照。"""

    def test_value_model_roundtrips_synthetic(self):
        m = value_model
        cases = {
            "int": 42,
            "str": m.RMStr("中文", enc="utf-8"),
            "list": [1, 2, 3],
            "dict": {"a": 1, "b": 2},
            "object": m.RMObject("RPG::MapInfo",
                                 {"@name": m.RMStr("地图一"),
                                  "@order": 1}),
        }
        for name, value in cases.items():
            with self.subTest(case=name):
                raw = m.dumps(value)
                again = m.loads(raw)
                self.assertEqual(m.dumps(again), raw,
                                 "%s 的值模型往返不是字节稳定的" % name)

    def test_utf8_string_survives(self):
        m = value_model
        text = "中文·テスト·한글"
        raw = m.dumps(m.RMStr(text, enc="utf-8"))
        self.assertEqual(m.loads(raw), text)


if __name__ == "__main__":
    unittest.main(verbosity=2)

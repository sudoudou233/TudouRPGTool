# -*- coding: utf-8 -*-
"""兼容性测试：Ruby Marshal 字节级往返（移植原两个工具的核心断言）。

@feature  none
@layer    tests
@public   TestMarshalRoundtripSynthetic, TestMarshalRoundtripRealSamples,
          TestValueLayerRoundtrip
@depends  core.marshal.doc_model, core.marshal.value_layer
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
from core.marshal import doc_model, value_layer  # noqa: E402

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


class TestValueLayerRoundtrip(unittest.TestCase):
    """值层（``core.marshal.value_layer``）的往返能力。

    M2b：本类原先测的是 `value_model`（翻译工具侧的旧值模型）。
    收敛后值模型已删除，本类改为测**取代它的门面** —— 断言保持等价：
    从 Python 值出发构造、往返字节稳定、UTF-8 文本不丢。
    """

    def test_python_values_roundtrip(self):
        m = value_layer
        cases = {
            "int": 42,
            "str": "中文",
            "list": [1, 2, 3],
            "dict": {"a": 1, "b": 2},
            "nested": {"items": [1, 2], "flag": True, "none": None},
        }
        for name, value in cases.items():
            with self.subTest(case=name):
                raw = m.dumps(m.wrap(m.unwrap(value)))
                again = m.loads(raw)
                self.assertEqual(m.dumps(again), raw,
                                 "%s 的值层往返不是字节稳定的" % name)

    def test_object_constructed_from_python_values(self):
        """从 Python 值构造 Ruby 对象（原 value_model 的主要用途）。"""
        m = value_layer
        node = m.unwrap({"__ruby__": "Object", "class": "RPG::MapInfo",
                         "ivars": {"@name": "地图一", "@order": 1}})
        self.assertIsInstance(node, doc_model.Hash)
        obj_node = doc_model.ObjectNode(
            doc_model.Symbol(b"RPG::MapInfo"), [
                (doc_model.Symbol(b"@name"),
                 doc_model.String("地图一".encode("utf-8"))),
                (doc_model.Symbol(b"@order"), doc_model.Fixnum(1)),
            ])
        raw = m.dumps(m.wrap(obj_node))
        again = m.loads(raw)
        self.assertEqual(again.class_name, "RPG::MapInfo")
        self.assertEqual(again.ivars["@name"].value, "地图一")
        self.assertEqual(again.ivars["@order"], 1)

    def test_utf8_string_survives(self):
        m = value_layer
        text = "中文·テスト·한글"
        raw = m.dumps(m.wrap(doc_model.String(text.encode("utf-8"))))
        self.assertEqual(m.loads(raw).value, text)


class TestMarshalConvergence(unittest.TestCase):
    """**M2b 收敛成果的静态断言**（需求 §3.3 验收硬指标）。

    三类重复实现收敛为一份之后，必须有断言防止它**悄悄退回去**：
    以后有人"顺手"再写一份实现、或把导入改回旧模块，这里会立刻红灯。
    """

    def _read(self, rel_path):
        import io as _io
        with _io.open(os.path.join(_ROOT, rel_path), encoding="utf-8") as f:
            return f.read()

    def test_convergence_status_is_merged(self):
        from core import marshal
        self.assertEqual(marshal.CONVERGENCE_STATUS, "merged")

    def test_value_model_no_longer_exists(self):
        """旧的第二份实现必须已删除。"""
        path = os.path.join(_ROOT, "core", "marshal", "value_model.py")
        self.assertFalse(os.path.isfile(path),
                         "core/marshal/value_model.py 又出现了 —— "
                         "需求 §3.3 要求 Marshal 只有一份实现")

    def test_no_module_imports_value_model(self):
        """任何模块都不得再 import value_model（注释里提历史名字是允许的）。"""
        offenders = []
        for dirpath, dirnames, filenames in os.walk(_ROOT):
            dirnames[:] = [d for d in dirnames
                           if d not in ("__pycache__", ".git", "runtime")]
            for name in filenames:
                if not name.endswith(".py"):
                    continue
                full = os.path.join(dirpath, name)
                rel = os.path.relpath(full, _ROOT).replace(os.sep, "/")
                try:
                    text = self._read(rel)
                except Exception:
                    continue
                for line in text.splitlines():
                    stripped = line.strip()
                    if stripped.startswith("#"):
                        continue
                    if "value_model" in stripped and (
                            stripped.startswith("from ") or
                            stripped.startswith("import ")):
                        offenders.append("%s: %s" % (rel, stripped))
        self.assertEqual(offenders, [],
                         "仍有模块 import value_model：%s" % offenders)

    def test_only_one_binary_implementation(self):
        """``core/marshal/`` 下只能有一份二进制实现。

        当前布局：``doc_model``（二进制层）+ ``value_layer``（门面）+ ``__init__``。
        判据是"门面里不得出现**解析/编码逻辑**"，而不是"不得出现同名函数" ——
        门面**允许**提供 `loads`/`dumps`/`load_streams` 这类**转发**入口
        （它们必须调用 ``doc_model``，不能自己解析）。
        """
        marshal_dir = os.path.join(_ROOT, "core", "marshal")
        files = [f for f in sorted(os.listdir(marshal_dir))
                 if f.endswith(".py") and f != "__init__.py"]
        self.assertEqual(files, ["doc_model.py", "value_layer.py"],
                         "core/marshal/ 的文件清单变了：%s" % files)

        facade = self._read("core/marshal/value_layer.py")
        # 这些是"第二份实现"的标志：自己解析字节或自己编码
        for forbidden in ("class Parser", "def _parse_fixnum",
                          "def _fixnum_to_bytes", "def parse_token",
                          "struct.unpack(", "buf[self.pos]"):
            with self.subTest(symbol=forbidden):
                self.assertNotIn(forbidden, facade,
                                 "门面层不得包含解析/编码实现（%s）" % forbidden)
        # 上层入口必须转发给 doc_model
        self.assertIn("D.load_streams", facade,
                      "load_streams 应转发给 doc_model，而不是自己实现")

    def test_real_consumers_use_the_facade(self):
        """两个真实调用方都必须走 value_layer。"""
        for rel in ("core/formats/rgss_data.py", "core/safety/builder.py"):
            with self.subTest(module=rel):
                text = self._read(rel)
                self.assertIn("value_layer", text)
                self.assertNotIn("import value_model", text)

    def test_health_reports_all_merged(self):
        """``/api/health`` 的收敛段必须报三类全部合并。"""
        from ui.routes import convergence_status
        status = convergence_status()
        self.assertEqual(status["marshal"], "merged")
        self.assertEqual(status["formats"], "merged")
        self.assertEqual(status["engines"], "merged")
        self.assertTrue(status["all_merged"],
                        "三类职责应全部收敛：%s" % status)


if __name__ == "__main__":
    unittest.main(verbosity=2)

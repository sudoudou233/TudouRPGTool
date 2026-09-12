# -*- coding: utf-8 -*-
"""M3a 接线期发现并修复的缺陷的回归测试（N-12 / N-13 / N-14 / N-15）。

@feature  translate
@layer    tests
@public   TestN15MVEventPathShape, TestN14SymLinkResolution,
          TestN13TextOfProxies, TestN12ContainerNormalization,
          TestRealGameScanVolume
@depends  core.marshal.doc_model, core.marshal.value_layer,
          core.formats.rgss_data, core.formats.mv_mz_data
@tested   (本文件即测试)
@footprint docs/STATE.md

背景
----
M2b 把 `core/formats/rgss_data.py` 从 `value_model` 切到 `value_layer`、
把 Marshal 收敛为"文档模型 + 值层门面"之后，**VX Ace 的提取量从 6 千余条
掉到 115 条，而且不报错**。三个原因叠加，逐个修掉：

* **N-14** `SymLink`（Ruby Marshal 的符号表引用）没有被解析 → ``class_name``
  退化成 ``"symbol#6"`` → 所有 ``class_name == "RPG::EventCommand"`` 判断失效
* **N-13** 字符串在值层是 ``RMStr`` **代理**，``isinstance(v, str)`` 不成立 →
  ``_text_of`` 返回 None → 文本被当作"没有内容"
* **N-12** ``RPG::Map#@events`` 是 **Hash**，而 vendored 代码用 ``enumerate``
  当列表遍历 → ``RMDict.__getitem__(0)`` 抛 ``KeyError: 0``

M3a 接线（写 `features/translate/routes.py` 的构建用例）时又发现第四个
同性质的坑：

* **N-15** MV/MZ 事件条目的路径多拼了一层 ``/list/``（``1/list/list/1/...``）
  → 扫描/统计/界面全部正常，但 ``apply_to_files`` 按路径写回时定位失败 →
  **所有事件对话与选择项都写不进汉化版，且不报错**

本文件把这些"静默丢功能"的坑钉死，并加一条真实样本的量级断言：
**提取量骤降必须被测试发现**，而不是等到用户发现译文变少。
"""

from __future__ import annotations

import json
import os
import sys
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
from core.formats import mv_mz_data  # noqa: E402
from core.formats import rgss_data  # noqa: E402
from core.marshal import doc_model as D  # noqa: E402
from core.marshal import value_layer as V  # noqa: E402


def sym(name):
    return D.Symbol(name.encode("utf-8"))


def st(text):
    return D.String(text.encode("utf-8"))


def build_common_events():
    """构造一个形状与真实 ``CommonEvents.rvdata2`` 一致的节点树。

    刻意用 **SymLink** 表示第二条及以后命令的类名/ivar 名 —— 真实文件里
    只有第一次出现的符号是全名，之后都是符号表引用。这正是 N-14 的触发条件。

    **两遍构造**：SymLink 里存的是**符号表下标**，下标取决于解析器遇到符号的
    顺序。为了让夹具与真实字节流一致（而不是靠手数下标 —— 开发本测试时就
    数错过一次），第一遍先造"全用 Symbol"的版本并解析出符号表，
    再按该表的真实下标造第二遍。

    注意两点（都实测踩过）：

    * 用 ``doc_model.load_streams`` 而不是 ``loads`` —— 只有前者会把
      ``_parser`` 回填到根节点，符号表才拿得到；
    * ``doc_model`` 的序列化器**不会**把重复的 Symbol 输出成 SymLink
      （每次都写全名），所以第一遍的符号表就是"按首次出现顺序"建立的。
    """
    def param_node(value):
        """参数可以是字符串（文本）也可以是整数（控制码参数）。"""
        if isinstance(value, str):
            return st(value)
        if isinstance(value, bool):
            return D.BoolNode(value)
        return D.Fixnum(int(value))

    def command(code, params, use_symlink, table):
        if use_symlink:
            classsym = D.SymLink(table[b"RPG::EventCommand"])
            keys = (D.SymLink(table[b"@indent"]), D.SymLink(table[b"@code"]),
                    D.SymLink(table[b"@parameters"]))
        else:
            classsym = D.Symbol(b"RPG::EventCommand")
            keys = (D.Symbol(b"@indent"), D.Symbol(b"@code"),
                    D.Symbol(b"@parameters"))
        return D.ObjectNode(classsym, [
            (keys[0], D.Fixnum(0)),
            (keys[1], D.Fixnum(code)),
            (keys[2], D.Array([param_node(p) for p in params])),
        ])

    def build(table, use_symlink):
        event = D.ObjectNode(D.Symbol(b"RPG::CommonEvent"), [
            (D.Symbol(b"@name"), st("开场")),
            (D.Symbol(b"@list"), D.Array([
                command(101, ["", 0, 0, 2], False, table),
                command(401, ["你好，旅行者。"], use_symlink, table),
                command(401, ["\\V[1]欢迎。"], use_symlink, table),
                command(402, ["是", "否"], use_symlink, table),
            ])),
        ])
        return D.Array([D.NilNode(), event])

    # 先造一个"只含符号"的小树，解析出**真实下标**。
    #
    # 为什么不用主夹具探符号表：``doc_model`` 的序列化器对每个 Symbol 节点
    # 都会写出全名（不做符号去重），所以同一名字会出现多次、下标随结构变化，
    # 靠"数一遍主夹具"得到的下标不可靠（开发本测试时在这里反复出错）。
    # 用一张只含所需符号的小表就稳定了。
    symbol_table = D.Array([D.Symbol(name) for name in (
        b"RPG::CommonEvent", b"@name", b"@list", b"RPG::EventCommand",
        b"@indent", b"@code", b"@parameters")])
    probe = D.load_streams(D.dumps(symbol_table))[0][1]
    table = {name: index
             for index, name in enumerate(probe._parser.symbols)}
    for required in (b"RPG::EventCommand", b"@indent", b"@code", b"@parameters"):
        if required not in table:
            raise AssertionError(
                "夹具符号表缺少 %r（实际 %r）—— 探针构造变了？"
                % (required, sorted(table)))
    # 第二遍：按真实下标使用 SymLink
    return build(table, True)


def wrap_with_symbols(node):
    """序列化 → 解析 → 包成值层对象（模拟真实读取路径）。

    ⚠ 必须用 ``doc_model.load_streams`` 而不是 ``doc_model.loads``：
    只有前者会把 ``_parser`` 回填到根节点，``SymLink`` 才有符号表可查。
    ``V.loads`` 内部已经改用 ``load_streams``（见 value_layer 的说明），
    所以这里直接调 ``V.loads`` 即可。
    """
    raw = node.raw if getattr(node, "raw", None) else D.dumps(node)
    return V.loads(raw)


class TestN14SymLinkResolution(unittest.TestCase):
    """**N-14**：``SymLink`` 必须能解析出真实符号名。"""

    def setUp(self):
        self.root = wrap_with_symbols(build_common_events())

    def _commands(self):
        event = rgss_data._pairs_of(self.root)[1][1]
        return rgss_data._pairs_of_values(rgss_data._iv(event, "@list"))

    def test_symlink_commands_resolve_class_name(self):
        commands = self._commands()
        for index, cmd in enumerate(commands):
            with self.subTest(index=index):
                self.assertEqual(cmd.class_name, "RPG::EventCommand",
                                 "SymLink 的 class_name 未解析（N-14 复发）")

    def test_symlink_ivar_keys_resolve(self):
        cmd = self._commands()[1]
        names = list(cmd.ivars.keys())
        for expected in ("@indent", "@code", "@parameters"):
            with self.subTest(key=expected):
                self.assertIn(expected, names,
                              "SymLink 的 ivar 名未解析（N-14 复发）：%s" % names)
        self.assertEqual(cmd.ivars["@code"], 401)

    def test_doc_model_sym_name_resolves_symlink(self):
        """`doc_model._sym_name` 自身也必须解析（值层只是转发它）。"""
        node = D.loads(D.dumps(build_common_events()))
        event = node.items[1]
        lst = D.ivar(event, "@list")
        second = lst.items[1]
        self.assertEqual(D._sym_name(second.classsym), "RPG::EventCommand")

    def test_unresolvable_symlink_keeps_placeholder(self):
        """拿不到符号表时保留可辨认占位，而不是返回 None。

        返回 None 会把"解析不出名字"伪装成"没有这个字段"，排查时更难。
        """
        orphan = D.SymLink(99)
        self.assertEqual(D._sym_name(orphan), "symbol#99")

    def test_symlink_proxy_also_resolves(self):
        """值层代理的 ``class_name`` / ivar 名也要解析 SymLink（它转发 doc_model）。

        注意本用例必须**走真实字节流**：符号表是解析 0x3A 标记时建立的，
        直接构造 ``SymLink`` 节点再序列化，解析侧的符号表里没有对应条目。
        真实文件里符号总是先以全名出现过一次 —— 夹具也照这个规律造。
        """
        root = wrap_with_symbols(build_common_events())
        event = rgss_data._pairs_of(root)[1][1]
        commands = rgss_data._pairs_of_values(rgss_data._iv(event, "@list"))
        second = commands[1]            # 这一条用的是 SymLink
        self.assertEqual(second.class_name, "RPG::EventCommand")
        self.assertIn("@indent", second.ivars.keys())
        self.assertEqual(second.ivars["@code"], 401)


class TestN13TextOfProxies(unittest.TestCase):
    """**N-13**：``_text_of`` 必须能处理值层字符串代理与 Ivar 包装。"""

    def test_plain_string_proxy(self):
        self.assertEqual(rgss_data._text_of(V.wrap(st("文本"))), "文本")

    def test_ivar_wrapped_string(self):
        node = D.Ivar(st("包裹"), [(sym("encoding"), sym("UTF_8"))])
        self.assertEqual(rgss_data._text_of(V.wrap(node)), "包裹")

    def test_plain_python_str(self):
        self.assertEqual(rgss_data._text_of("原生"), "原生")

    def test_non_text_returns_none(self):
        for value in (None, 42, V.wrap(D.Fixnum(1)), V.wrap(D.Array([]))):
            with self.subTest(value=type(value).__name__):
                self.assertIsNone(rgss_data._text_of(value))

    def test_bytes_proxy_is_decoded(self):
        """节点本身（非代理）也要能取文本 —— ``_text_of`` 内部会先 wrap 语义。"""
        self.assertEqual(rgss_data._text_of(st("字节")), "字节")


class TestN12ContainerNormalization(unittest.TestCase):
    """**N-12**：同一字段可能是 Array 或 Hash，遍历必须两种都支持。"""

    def test_hash_container_pairs(self):
        """``RPG::Map#@events`` 是 Hash（键为事件 id）—— 必须按 pairs 遍历。"""
        node = D.Hash([(D.Fixnum(1), st("a")), (D.Fixnum(2), st("b"))])
        pairs = rgss_data._pairs_of(V.wrap(node))
        self.assertEqual([k for k, _v in pairs], [1, 2])

    def test_array_container_pairs(self):
        node = D.Array([st("a"), st("b")])
        pairs = rgss_data._pairs_of(V.wrap(node))
        self.assertEqual([k for k, _v in pairs], [0, 1])

    def test_native_list_and_dict(self):
        self.assertEqual(rgss_data._pairs_of(["a", "b"]), [(0, "a"), (1, "b")])
        self.assertEqual(rgss_data._pairs_of({"x": 1}), [("x", 1)])

    def test_ivar_wrapped_container(self):
        """VX Ace 的 ``@list`` / ``@parameters`` 常见 Ivar 包装。"""
        node = D.Ivar(D.Array([st("a")]), [(sym("E"), D.BoolNode(True))])
        self.assertEqual(len(rgss_data._pairs_of_values(V.wrap(node))), 1)

    def test_none_and_unknown_yield_empty(self):
        for value in (None, 42, "字符串", object()):
            with self.subTest(value=type(value).__name__):
                self.assertEqual(rgss_data._pairs_of(value), [])


class TestRealGameScanVolume(unittest.TestCase):
    """真实样本上的**量级**断言 —— 提取量骤降必须被测试发现。

    没有这条断言，N-12/13/14 那类"静默丢功能"只会在用户发现译文变少时
    才暴露。下界取得很保守（远低于实际值），只用来抓"数量级崩塌"。
    """

    #: (游戏目录, 期望引擎, 条目数下界, 说明)
    BASELINE = (
        (r"D:\gamess\boli\B7794\博麗霊夢は洗脳されてしまいました", "vxace", 5000,
         "VX Ace：对话占多数，实测约 1.65 万条"),
        (r"D:\gamess\JIANTATA\1-6\PC-1\ToT 1.16.2.2 CN1.0", "vxace", 10000,
         "VX Ace 第二样本，实测约 4.8 万条"),
        (r"D:\gamess\痴女の触手 官中版\痴女の触手 官中版", "mv", 1000,
         "MV，实测约 2.3 千条"),
        (r"D:\gamess\demon\DD_V07c_Windows\DD_V07c_Windows", "mz", 20000,
         "MZ，实测约 5.7 万条"),
    )

    @classmethod
    def setUpClass(cls):
        if not paths.samples_root():
            raise unittest.SkipTest(
                "未找到样本目录，跳过。设置 %s 后重跑。" % paths.ENV_SAMPLES)
        missing = [g for g, _e, _n, _d in cls.BASELINE if not os.path.isdir(g)]
        if missing:
            raise unittest.SkipTest("样本路径不存在：%s" % missing[:2])

    def test_scan_volume_meets_floor(self):
        from features.translate.session import Session
        for game, engine, floor, note in self.BASELINE:
            with self.subTest(game=os.path.basename(game)[:28]):
                session = Session(game)
                total = session.scan()
                self.assertEqual(session.info["engine"], engine)
                self.assertGreaterEqual(
                    total, floor,
                    "提取量低于下界（%s）：实际 %d，下界 %d —— "
                    "这类崩塌通常意味着有一类内容被静默丢弃"
                    % (note, total, floor))

    def test_vxace_yields_dialogue_not_just_terms(self):
        """VX Ace 必须**包含对话**，而不只是界面术语。

        N-12/13/14 的表现就是"只剩界面术语、对话全没了"，
        只看总数可能被术语数量掩盖，所以单独断言类别。
        """
        from features.translate.session import Session
        game = r"D:\gamess\boli\B7794\博麗霊夢は洗脳されてしまいました"
        session = Session(game)
        session.scan()
        _counts, by_category = session.stats()
        self.assertGreater(by_category.get("对话", 0), 1000,
                           "VX Ace 的对话条目过少：%s" % by_category)
        self.assertGreater(by_category.get("名称", 0), 100,
                           "VX Ace 的名称条目过少：%s" % by_category)


class TestN15MVEventPathShape(unittest.TestCase):
    """**N-15**：MV/MZ 事件条目的路径必须能被 ``apply_to_files`` 落下去。

    缺陷形态：``_walk_event_list`` 多拼了一层 ``/list/``，产出
    ``1/list/list/1/parameters/0``。**扫描、统计、界面全部正常**，
    所以只有"生成汉化版之后打开游戏看"才会发现剧情还是原文。
    这里直接对"路径能不能定位到真实文本"下断言 —— 不依赖 UI、不依赖构建。
    """

    #: 真实的 MV ``CommonEvents.json`` 形状（``list`` 是 ``obj["list"]``）
    COMMON_EVENTS = [
        None,
        {"id": 1, "name": "开场", "list": [
            {"code": 101, "indent": 0, "parameters": [""]},
            {"code": 401, "indent": 0, "parameters": ["你好，旅行者。"]},
            {"code": 402, "indent": 0, "parameters": [["是", "否"], 1, 0]},
            {"code": 0, "indent": 0, "parameters": []},
        ]},
    ]

    def setUp(self):
        from features.translate.session import ScanOptions
        self.entries = []
        mv_mz_data._walk_event_list(self.entries, "CommonEvents.json",
                                    self.COMMON_EVENTS[1]["list"], "1/list",
                                    "公共事件 1", False)
        self.opts = ScanOptions()

    def test_event_paths_contain_list_exactly_once(self):
        self.assertTrue(self.entries, "事件指令一条都没提取到")
        for entry in self.entries:
            with self.subTest(path=entry["path"]):
                self.assertNotIn("list/list", entry["path"],
                                 "**N-15**：路径里出现了重复的 list 层：%s"
                                 % entry["path"])

    def test_event_paths_resolve_to_real_text(self):
        """路径必须真的指向原文 —— 这才是"能写回"的判据。"""
        self.assertTrue(self.entries)
        for entry in self.entries:
            parent, key = mv_mz_data._set_by_path(
                json.loads(json.dumps(self.COMMON_EVENTS, ensure_ascii=False)),
                entry["path"])
            with self.subTest(path=entry["path"]):
                self.assertEqual(parent[key], entry["original"],
                                 "路径定位到的不是原文（写回会改错东西）")

    def test_choice_paths_resolve(self):
        """402 选择项是"列表里的列表"，子下标不能省。"""
        choices = [e for e in self.entries if e["category"] == "选择项"]
        self.assertEqual([e["original"] for e in choices], ["是", "否"])
        for entry in choices:
            parent, key = mv_mz_data._set_by_path(
                json.loads(json.dumps(self.COMMON_EVENTS, ensure_ascii=False)),
                entry["path"])
            self.assertEqual(parent[key], entry["original"])

    def test_set_by_path_normalizes_last_key_to_container_type(self):
        """末段键类型必须与父容器一致（N-15 的第二处）。

        路径段来自 ``split("/")``，永远是字符串；父容器是 ``list`` 时键必须
        是 ``int``。原实现只归一化中间段，末段原样返回字符串 →
        ``list[str]`` 抛 ``TypeError``，被上层吞掉即"静默丢条目"。
        """
        data = {"a": [{"b": "旧值"}]}
        for path in ("a/0/b", "a/0"):
            parent, key = mv_mz_data._set_by_path(data, path)
            with self.subTest(path=path):
                expected = int if isinstance(parent, list) else str
                self.assertIsInstance(key, expected,
                                      "末段键类型与容器不符：%r → %r" % (path, key))
            parent[key] = "新值"          # 不抛异常即说明类型对了
        self.assertEqual(data["a"][0], "新值")

    def test_scan_and_writeback_agree_on_path(self):
        """端到端：``extract`` 产出的路径必须能被 ``apply_to_files`` 认出来。

        只测 ``_walk_event_list`` 不够 —— 真实链路是 ``extract`` 组装路径、
        ``apply_to_files`` 消费它；两者的前缀约定必须一致。
        """
        import tempfile
        from features.translate.session import Session

        with tempfile.TemporaryDirectory(prefix="n15_") as tmp:
            game = os.path.join(tmp, "game")
            os.makedirs(os.path.join(game, "js"))
            os.makedirs(os.path.join(game, "data"))
            with open(os.path.join(game, "js", "rpg_core.js"), "w") as f:
                f.write("//\n")
            path = os.path.join(game, "data", "CommonEvents.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.COMMON_EVENTS, f, ensure_ascii=False)

            session = Session(game)
            session.scan()
            self.assertEqual(session.info["engine"], "mv")
            for entry in session.entries.values():
                entry["translated"] = "T-" + entry["original"]
                entry["status"] = "translated"

            stats = mv_mz_data.apply_to_files(session.info,
                                              {"CommonEvents.json": list(session.entries.values())})
            self.assertEqual(stats["entries"], len(session.entries),
                             "有条目没写进去（N-15 复发）：%s" % stats)

            with open(path, encoding="utf-8") as f:
                after = json.load(f)
            self.assertEqual(after[1]["list"][1]["parameters"][0], "T-你好，旅行者。",
                             "事件对话没有写进数据文件")
            self.assertEqual(after[1]["list"][2]["parameters"][0],
                             ["T-是", "T-否"], "选择项没有写进数据文件")


if __name__ == "__main__":
    unittest.main(verbosity=2)

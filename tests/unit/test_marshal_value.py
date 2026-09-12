# -*- coding: utf-8 -*-
"""值层门面（``core/marshal/value_layer.py``）的单元测试。

@feature  none
@layer    tests
@public   TestWrapScalars, TestObjectProxy, TestMutationReachesNode,
          TestByteStability, TestHashAndArray, TestUnwrap
@depends  core.marshal.value_layer, core.marshal.doc_model
@tested   (本文件即测试)
@footprint docs/MODULES.md#coremarshal
"""

from __future__ import annotations

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

from core.marshal import doc_model as D  # noqa: E402
from core.marshal import value_layer as V  # noqa: E402


def sym(name):
    return D.Symbol(name.encode("utf-8"))


def st(text):
    return D.String(text.encode("utf-8"))


def make_actor():
    """构造一个形状接近真实存档的节点树。"""
    return D.ObjectNode(sym("Game_Actor"), [
        (sym("@name"), st("主角")),
        (sym("@level"), D.Fixnum(8)),
        (sym("@hp"), D.Fixnum(1045)),
        (sym("@skills"), D.Array([D.Fixnum(2), D.Fixnum(3), D.Fixnum(4)])),
        (sym("@exp"), D.Hash([(D.Fixnum(1), D.Fixnum(3600))])),
        (sym("@param_plus"), D.Array([D.Fixnum(0) for _ in range(8)])),
    ])


def tree_bytes(node):
    return D.VERSION + node.serialize()


class TestWrapScalars(unittest.TestCase):
    def test_nil_and_bools(self):
        self.assertIsNone(V.wrap(D.NilNode()))
        self.assertIs(V.wrap(D.BoolNode(True)), True)
        self.assertIs(V.wrap(D.BoolNode(False)), False)

    def test_integers_come_back_as_int(self):
        for value in (0, 1, -1, 122, 65536, -70000):
            with self.subTest(value=value):
                wrapped = V.wrap(D.Fixnum(value))
                self.assertIsInstance(wrapped, int)
                self.assertEqual(wrapped, value)

    def test_bignum_is_int(self):
        # Bignum(sign, digits)：sign 是 b'+'/b'-'，digits 是 16 位数字组
        # （不是原始字节 —— M2b 实测踩到过）
        node = D.Bignum(b'+', [0, 1])
        wrapped = V.wrap(node)
        self.assertIsInstance(wrapped, int)
        self.assertEqual(wrapped, node.value)

    def test_none_wraps_to_none(self):
        self.assertIsNone(V.wrap(None))


class TestObjectProxy(unittest.TestCase):
    def setUp(self):
        self.obj = V.wrap(make_actor())

    def test_is_ruby_object(self):
        self.assertTrue(V.is_ruby_object(self.obj))

    def test_class_name(self):
        self.assertEqual(self.obj.class_name, "Game_Actor")

    def test_ivars_read_with_and_without_at(self):
        """**关键**：``rgss_data`` 两种写法都用，必须都读得到。"""
        self.assertEqual(self.obj.ivars["@name"].value, "主角")
        self.assertEqual(self.obj.ivars["name"].value, "主角")

    def test_ivars_get_and_contains(self):
        self.assertEqual(self.obj.get("@level"), 8)
        self.assertIn("@level", self.obj.ivars)
        self.assertIn("level", self.obj.ivars)
        self.assertNotIn("@nope", self.obj.ivars)
        self.assertIsNone(self.obj.get("@nope"))

    def test_ivars_keys_and_len(self):
        keys = self.obj.ivars.keys()
        self.assertIn("@name", keys)
        self.assertEqual(len(self.obj.ivars), 6)

    def test_missing_key_raises(self):
        with self.assertRaises(KeyError):
            self.obj.ivars["@nope"]

    def test_ivars_eq_dict(self):
        self.assertEqual(self.obj.ivars, {
            "@name": "主角", "@level": 8, "@hp": 1045,
            "@skills": [2, 3, 4], "@exp": {1: 3600},
            "@param_plus": [0] * 8,
        })

    def test_str_proxy_equality_with_plain_str(self):
        self.assertEqual(self.obj.ivars["@name"], "主角")
        self.assertIn("主", self.obj.ivars["@name"])


class TestMutationReachesNode(unittest.TestCase):
    """改值层对象 = 改底层 Node（这是字节保真的前提）。"""

    def setUp(self):
        self.node = make_actor()
        self.obj = V.wrap(self.node)

    def test_set_existing_scalar(self):
        self.obj.ivars["@level"] = 77
        self.assertEqual(self.obj.ivars["@level"], 77)
        # 直接查 Node 也要变
        pairs = dict((D._sym_name(k), v) for k, v in self.node.ivars)
        self.assertEqual(pairs["@level"].value, 77)

    def test_set_without_at_prefix_reuses_existing_key(self):
        """用不带 ``@`` 的键写，必须改到已有的 ``@level``，而不是新建 ``level``。"""
        before = len(self.node.ivars)
        self.obj.ivars["level"] = 55
        self.assertEqual(len(self.node.ivars), before, "不应新建重复键")
        self.assertEqual(self.obj.ivars["@level"], 55)

    def test_set_new_key_adds_at_prefix_by_default(self):
        self.obj.ivars["@nickname"] = "小主"
        self.assertEqual(self.obj.ivars["@nickname"].value, "小主")
        self.assertIn("@nickname", self.obj.ivars.keys())

    def test_list_element_mutation(self):
        self.obj.ivars["@skills"][0] = 99
        self.assertEqual(list(self.obj.ivars["@skills"]), [99, 3, 4])

    def test_list_append(self):
        self.obj.ivars["@skills"].append(50)
        self.assertEqual(list(self.obj.ivars["@skills"]), [2, 3, 4, 50])

    def test_param_plus_indexed_write(self):
        """``rgss_data`` 的 ``param_plus_N`` 写回路径。"""
        self.obj.ivars["@param_plus"][0] = 300
        self.assertEqual(list(self.obj.ivars["@param_plus"])[0], 300)

    def test_hash_write_existing_and_new(self):
        exp = self.obj.ivars["@exp"]
        exp[1] = 9999
        self.assertEqual(exp[1], 9999)
        exp[2] = 5
        self.assertEqual(exp[2], 5)

    def test_dirty_flag_set(self):
        self.node.dirty = False
        self.obj.ivars["@level"] = 1
        self.assertTrue(self.node.dirty)

    def test_delete_ivar(self):
        del self.obj.ivars["@hp"]
        self.assertNotIn("@hp", self.obj.ivars)


class TestByteStability(unittest.TestCase):
    """**核心硬指标**：未改动的内容必须字节级原样保留。"""

    def test_untouched_roundtrip_is_byte_exact(self):
        raw = tree_bytes(make_actor())
        self.assertEqual(V.dumps(V.loads(raw)), raw)

    def test_touched_then_roundtrip_is_stable(self):
        """改过之后，再往返必须稳定（不因序列化器抖动而变化）。"""
        raw = tree_bytes(make_actor())
        obj = V.loads(raw)
        obj.ivars["@level"] = 77
        once = V.dumps(obj)
        twice = V.dumps(V.loads(once))
        self.assertEqual(once, twice)

    def test_untouched_subtree_keeps_raw_bytes(self):
        """只改一个字段时，其它子树的序列化字节不应变化。"""
        raw = tree_bytes(make_actor())
        obj = V.loads(raw)
        node = obj.node
        # 记录 level 变化前后 name 子树的原始字节
        name_node = [v for k, v in node.ivars if D._sym_name(k) == "@name"][0]
        before = name_node.serialize()
        obj.ivars["@level"] = 77
        self.assertEqual(name_node.serialize(), before,
                         "未触碰的子树必须吐出原始字节")

    def test_load_streams_wraps_every_stream(self):
        one = tree_bytes(make_actor())
        two = D.VERSION + D.Fixnum(42).serialize()
        streams = V.load_streams(one + two)
        self.assertEqual(len(streams), 2)
        self.assertEqual(streams[0][1].class_name, "Game_Actor")
        self.assertEqual(streams[1][1], 42)


class TestHashAndArray(unittest.TestCase):
    def test_array_iteration_and_indexing(self):
        arr = V.wrap(D.Array([D.Fixnum(1), st("x"), D.NilNode()]))
        self.assertEqual(len(arr), 3)
        self.assertEqual(arr[0], 1)
        self.assertEqual(arr[1].value, "x")
        self.assertIsNone(arr[2])
        self.assertEqual(list(arr), [1, "x", None])

    def test_array_contains(self):
        arr = V.wrap(D.Array([D.Fixnum(1), D.Fixnum(2)]))
        self.assertIn(1, arr)
        self.assertNotIn(9, arr)

    def test_hash_int_keys(self):
        h = V.wrap(D.Hash([(D.Fixnum(1), D.Fixnum(10)),
                           (D.Fixnum(7), D.Fixnum(70))]))
        self.assertEqual(h[1], 10)
        self.assertEqual(h[7], 70)
        self.assertIn(7, h)
        self.assertNotIn(3, h)
        self.assertEqual(sorted(h.keys()), [1, 7])

    def test_hash_str_keys(self):
        h = V.wrap(D.Hash([(sym("@a"), D.Fixnum(1))]))
        self.assertEqual(h["@a"], 1)
        self.assertEqual(h["a"], 1)

    def test_hash_get_default(self):
        h = V.wrap(D.Hash([]))
        self.assertEqual(h.get(5, "d"), "d")

    def test_hashdef_default_value(self):
        node = D.HashDef([(D.Fixnum(1), D.Fixnum(10))], D.Fixnum(0))
        h = V.wrap(node)
        self.assertEqual(h[1], 10)
        self.assertEqual(h[99], 0, "HashDef 缺失键应返回默认值")


class TestUnwrap(unittest.TestCase):
    def test_proxy_returns_same_node(self):
        node = make_actor()
        obj = V.wrap(node)
        self.assertIs(V.unwrap(obj), node)

    def test_node_passthrough(self):
        node = D.Fixnum(3)
        self.assertIs(V.unwrap(node), node)

    def test_python_values_become_nodes(self):
        self.assertIsInstance(V.unwrap(None), D.NilNode)
        self.assertIsInstance(V.unwrap(True), D.BoolNode)
        self.assertIsInstance(V.unwrap(5), D.Fixnum)
        self.assertIsInstance(V.unwrap(1.5), D.Float)
        self.assertIsInstance(V.unwrap("文本"), D.String)
        self.assertIsInstance(V.unwrap(b"bytes"), D.String)
        self.assertIsInstance(V.unwrap([1, 2]), D.Array)
        self.assertIsInstance(V.unwrap({"a": 1}), D.Hash)

    def test_unsupported_type_raises(self):
        with self.assertRaises(V.MarshalValueError):
            V.unwrap(object())

    def test_roundtrip_through_unwrap(self):
        value = {"a": 1, "b": [1, 2, "文本"], "c": None, "d": True}
        node = V.unwrap(value)
        self.assertEqual(V.wrap(node), value)


if __name__ == "__main__":
    unittest.main(verbosity=2)

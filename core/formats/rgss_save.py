# -*- coding: utf-8 -*-
"""
RPG Maker RGSS (XP / VX / VX Ace) save & data access.

@feature  cheats
@layer    core
@public   GameData, SaveFile, sync_dirty, find_top_hash
@depends  core.marshal.doc_model, core.safety.atomic
@tested   tests/compat/test_formats_compat.py, tests/compat/test_m2a_regressions.py,
          tests/features/cheats/test_routes.py
@footprint docs/MODULES.md#coreformats
@note     vendored：来自 rpgmaker_cheating_tool/rpgdata.py。
@note     **M3b 修复两处**：
@note     1) B-02 残留：save() 原先直接 ``open(path, 'wb')`` → 改原子写；
@note     2) 句柄泄漏：``open(path,'rb').read()`` 依赖 GC 关闭文件
@note        （Windows 上会让后续替换/删除失败）→ 改 ``with`` 语句。


Handles both the stock Ruby Marshal format (XP .rxdata / VX .rvdata) and the
modified "MTool" Marshal used by this VX Ace build (.rvdata2), with
byte-faithful re-serialization for everything that is not edited.
"""
import os

from ..marshal import doc_model as rmarshal
from ..safety import atomic


def _symname(parser, s):
    if isinstance(s, rmarshal.Symbol):
        return s.name.decode('utf-8', 'replace')
    if isinstance(s, rmarshal.SymLink):
        i = s.index
        if 0 <= i < len(parser.symbols):
            return parser.symbols[i].decode('utf-8', 'replace')
        return 'L%d' % i
    return str(s)


def _strval(n, parser):
    if isinstance(n, rmarshal.Ivar):
        return _strval(n.inner, parser)
    if isinstance(n, rmarshal.String):
        return n.value.decode('utf-8', 'replace')
    return ''


def _intval(n):
    if isinstance(n, rmarshal.Fixnum):
        return n.value
    if isinstance(n, rmarshal.Bignum):
        return n.value
    return None


class GameData:
    """Names/definitions read from the Data folder."""

    def __init__(self, datadir, standard=False):
        self.datadir = datadir
        self.standard = standard
        self.items = {}
        self.weapons = {}
        self.armors = {}
        self.actors = {}
        self.classes = {}
        self._load_names()

    def _load_table(self, fname):
        for name in (fname, fname.replace('.rvdata2', '.rvdata'),
                     fname.replace('.rvdata2', '.rxdata')):
            path = os.path.join(self.datadir, name)
            if not os.path.exists(path):
                continue
            # 显式 with：原实现是 open(path,'rb').read()，依赖 GC 关句柄 ——
            # Windows 上句柄没关会让后续的替换/删除失败（M3b 修）
            with open(path, 'rb') as f:
                buf = f.read()
            nodes = rmarshal.load_streams(buf, standard=self.standard)
            if not nodes:
                return []
            node = nodes[0][1]
            if isinstance(node, rmarshal.Array):
                return node
            return []
        return []

    def _load_names(self):
        arr = self._load_table('Items.rvdata2')
        if arr:
            p = arr._parser
            for obj in arr.items:
                if obj is None or isinstance(obj, rmarshal.NilNode):
                    continue
                d = {_symname(p, k): v for k, v in obj.ivars}
                oid = _intval(d.get('@id'))
                if oid is None:
                    continue
                self.items[oid] = _strval(d.get('@name'), p)
        for fname, store in [('Weapons.rvdata2', self.weapons),
                             ('Armors.rvdata2', self.armors)]:
            arr = self._load_table(fname)
            if not arr:
                continue
            p = arr._parser
            for obj in arr.items:
                if obj is None or isinstance(obj, rmarshal.NilNode):
                    continue
                d = {_symname(p, k): v for k, v in obj.ivars}
                oid = _intval(d.get('@id'))
                if oid is None:
                    continue
                store[oid] = _strval(d.get('@name'), p)
        arr = self._load_table('Actors.rvdata2')
        if arr:
            p = arr._parser
            for obj in arr.items:
                if obj is None or isinstance(obj, rmarshal.NilNode):
                    continue
                d = {_symname(p, k): v for k, v in obj.ivars}
                oid = _intval(d.get('@id'))
                if oid is None:
                    continue
                self.actors[oid] = {
                    'name': _strval(d.get('@name'), p),
                    'class_id': _intval(d.get('@class_id')),
                    'initial_level': _intval(d.get('@initial_level')),
                }
        arr = self._load_table('Classes.rvdata2')
        if arr:
            p = arr._parser
            for obj in arr.items:
                if obj is None or isinstance(obj, rmarshal.NilNode):
                    continue
                d = {_symname(p, k): v for k, v in obj.ivars}
                oid = _intval(d.get('@id'))
                if oid is None:
                    continue
                self.classes[oid] = _strval(d.get('@name'), p)


def _children(node):
    """Yield child nodes of a container (used by the dirty propagation)."""
    if isinstance(node, rmarshal.Array):
        return node.items
    if isinstance(node, rmarshal.Hash) or isinstance(node, rmarshal.HashDef):
        out = []
        for k, v in node.entries:
            out.append(k)
            out.append(v)
        if isinstance(node, rmarshal.HashDef):
            out.append(node.default)
        return out
    if isinstance(node, rmarshal.ObjectNode) or isinstance(node, rmarshal.Ivar):
        out = [node.classsym] if isinstance(node, rmarshal.ObjectNode) else [node.inner]
        for k, v in node.ivars:
            out.append(k)
            out.append(v)
        return out
    if isinstance(node, rmarshal.Struct):
        out = [node.classsym]
        for k, v in node.members:
            out.append(k)
            out.append(v)
        return out
    if isinstance(node, rmarshal.Usermarshal):
        return [node.classsym, node.inner]
    if isinstance(node, rmarshal.Userdef):
        return [node.classsym]
    return []


def sync_dirty(root):
    """Mark every ancestor of a dirty node dirty (recursively)."""
    own = getattr(root, 'dirty', False)
    for c in _children(root):
        if sync_dirty(c):
            own = True
    if own:
        root.dirty = True
    return own


def find_top_hash(node):
    if isinstance(node, rmarshal.Hash):
        return node
    return None


def _as_array(node):
    """把一个"角色容器"节点归一化成 :class:`rmarshal.Array`。

    两种真实形态都要支持（见 ``read_actors`` 的 N-09 说明）：

    * ``ObjectNode``（``Game_Actors``，改造版 VX Ace 常见）：取它的第一个
      实例变量值（``@data``），若是数组就用它；
    * ``Array``（stock XP/VX）：直接就是数组。

    返回 ``None`` 表示两种都不是（调用方按"读不到"处理，不抛异常）。
    """
    if isinstance(node, rmarshal.Array):
        return node
    ivars = getattr(node, 'ivars', None)
    if not ivars:
        return None
    for _key, value in ivars:
        if isinstance(value, rmarshal.Array):
            return value
    return None


def _read_var_array(container):
    """从 ``Game_Switches`` / ``Game_Variables`` 节点里取出 ``@data`` 数组。"""
    if isinstance(container, rmarshal.Array):
        return container
    ivars = getattr(container, 'ivars', None) or []
    for _key, value in ivars:
        if isinstance(value, rmarshal.Array):
            return value
    return None


class SaveFile:
    """RGSS save file editor.

    layout='hash'     -> modified VX Ace save (top-level Hash, possibly two
                         concatenated streams)
    layout='contents' -> stock XP / VX save ([header, contents] array where
                         contents is [system, switches, variables,
                         self_switches, actors, party, troop, map, player])
    standard=True     -> stock Ruby Marshal integer encoding (XP / VX)
    """
    PARAMS = ['最大HP', '最大MP', '攻击', '防御', '魔攻', '魔防', '速度', '幸运']
    CONTENTS_INDEX = {'system': 0, 'switches': 1, 'variables': 2,
                      'self_switches': 3, 'actors': 4, 'party': 5,
                      'troop': 6, 'map': 7, 'player': 8}

    def __init__(self, path, gamedata=None, standard=False, layout='hash'):
        self.path = path
        self.gamedata = gamedata
        self.standard = standard
        self.layout = layout
        with open(path, 'rb') as f:     # 显式 with（原实现泄漏句柄，M3b 修）
            self.raw = f.read()
        self.streams = rmarshal.load_streams(self.raw, standard=standard)

    # ---------------------------------------------------------------- lookup
    def _top(self, stream_node):
        if self.layout == 'hash':
            return stream_node if isinstance(stream_node, rmarshal.Hash) else None
        # stock format: [header, contents]
        if isinstance(stream_node, rmarshal.Array) and len(stream_node.items) >= 2:
            contents = stream_node.items[1]
            return contents if isinstance(contents, rmarshal.Array) else None
        return None

    def _get(self, stream_node, key):
        top = self._top(stream_node)
        if top is None:
            return None
        if self.layout == 'hash':
            p = stream_node._parser
            for k, v in top.entries:
                if _symname(p, k) == key:
                    return v
            return None
        idx = self.CONTENTS_INDEX.get(key)
        if idx is None or idx >= len(top.items):
            return None
        return top.items[idx]

    def _ivar(self, obj, name):
        p = obj._parser if hasattr(obj, '_parser') else self.streams[0][1]._parser
        for k, v in obj.ivars:
            if _symname(p, k) == name:
                return v
        return None

    def _party(self, stream_node):
        return self._get(stream_node, 'party')

    def _actors(self, stream_node):
        return self._get(stream_node, 'actors')

    def _new_fixnum(self, value):
        return rmarshal.Fixnum(value, std=self.standard)

    # ---------------------------------------------------------------- reading
    def read_party(self, stream_index=0):
        party = self._party(self.streams[stream_index][1])
        if party is None:
            return {}
        p = self.streams[stream_index][1]._parser
        items = self._hash_ints(self._ivar(party, '@items'))
        weapons = self._hash_ints(self._ivar(party, '@weapons'))
        armors = self._hash_ints(self._ivar(party, '@armors'))
        party_actors = self._ivar(party, '@actors')
        party_ids = []
        if isinstance(party_actors, rmarshal.Array):
            party_ids = [_intval(x) for x in party_actors.items]
        return {
            'gold': _intval(self._ivar(party, '@gold')),
            'steps': _intval(self._ivar(party, '@steps')),
            'items': items,
            'weapons': weapons,
            'armors': armors,
            'party_ids': party_ids,
        }

    def _hash_ints(self, h):
        if not isinstance(h, rmarshal.Hash):
            return {}
        p = self.streams[0][1]._parser
        return {_intval(k): _intval(v) for k, v in h.entries}

    def read_actors(self, stream_index=0):
        """读角色数组。

        ⚠ 2026-09-12 M2a 修复 **N-09**：原实现写死
        ``arr = [v for k, v in actors_node.ivars][0]``，即假设
        ``contents[4]`` 是 **对象**（``Game_Actors``，内部 ``@data`` 才是数组）。
        但 stock XP/VX 存档里 ``contents[4]`` 直接就是**数组**
        （``ObjectNode.ivars`` 不存在）→ ``AttributeError: 'Array' object has
        no attribute 'ivars'``。

        这个缺陷原先一直没被发现，因为本机**没有 XP/VX 样本**，而
        ``test_all_saves.py`` 跑的是改造版 VX Ace（``hash`` 布局 + 对象形态）。
        是 M2a 新加的合成 VX/XP 样本把它暴露出来的。

        现在两种形态都支持：对象取第一个 ivar（``@data``），数组直接用。
        """
        actors_node = self._actors(self.streams[stream_index][1])
        if actors_node is None:
            return []
        arr = _as_array(actors_node)
        if arr is None:
            return []
        result = []
        p = self.streams[stream_index][1]._parser
        for i, a in enumerate(arr.items):
            if a is None or isinstance(a, rmarshal.NilNode):
                result.append(None)
                continue
            d = {_symname(p, k): v for k, v in a.ivars}
            exp_hash = self._hash_ints(d.get('@exp'))
            exp = list(exp_hash.values())[0] if exp_hash else 0
            param_plus = []
            pp = d.get('@param_plus')
            if isinstance(pp, rmarshal.Array):
                param_plus = [_intval(x) for x in pp.items]
            result.append({
                'actor_id': _intval(d.get('@actor_id')) or _intval(d.get('@id')),
                'class_id': _intval(d.get('@class_id')),
                'level': _intval(d.get('@level')),
                'exp': exp,
                'hp': _intval(d.get('@hp')),
                'mp': _intval(d.get('@mp')),
                'tp': _intval(d.get('@tp')),
                'param_plus': param_plus,
                'maxhp': _intval(d.get('@maxhp')),
                'maxmp': _intval(d.get('@maxmp')),
                'atk': _intval(d.get('@atk')),
                'def': _intval(d.get('@def')),
                'spi': _intval(d.get('@spi')),
                'agi': _intval(d.get('@agi')),
                'skills': [_intval(x) for x in d.get('@skills').items]
                           if isinstance(d.get('@skills'), rmarshal.Array) else [],
            })
        return result

    # ---------------------------------------------------------------- editing
    def _mark(self, node):
        node.dirty = True

    def read_var(self, key, stream_index=0):
        """Read a Game_Switches / Game_Variables @data array."""
        sn = self.streams[stream_index][1]
        obj = self._get(sn, key)
        if obj is None:
            return []
        d = obj.ivars
        arr = d[0][1] if d else None
        if not isinstance(arr, rmarshal.Array):
            return []
        out = []
        for x in arr.items:
            if isinstance(x, rmarshal.BoolNode):
                out.append(1 if x.value else 0)
            elif isinstance(x, rmarshal.Fixnum) or isinstance(x, rmarshal.Bignum):
                out.append(x.value)
            else:
                out.append(0)
        return out

    def set_var(self, key, index, value):
        value = int(value)
        for idx, (off, sn) in enumerate(self.streams):
            obj = self._get(sn, key)
            if obj is None:
                continue
            d = obj.ivars
            arr = d[0][1] if d else None
            if not isinstance(arr, rmarshal.Array):
                continue
            while len(arr.items) <= index:
                arr.items.append(self._new_fixnum(0))
            node = arr.items[index]
            if isinstance(node, rmarshal.Fixnum):
                node.set_value(value)
            elif isinstance(node, rmarshal.BoolNode):
                arr.items[index] = self._new_fixnum(1 if value else 0)
            else:
                arr.items[index] = self._new_fixnum(value)
            arr.dirty = True
            obj.dirty = True

    def set_gold(self, value, all_streams=True):
        for idx, (off, sn) in enumerate(self.streams):
            if not all_streams and idx != 0:
                continue
            party = self._party(sn)
            g = self._ivar(party, '@gold')
            if isinstance(g, rmarshal.Fixnum):
                g.set_value(int(value))

    def set_steps(self, value, all_streams=True):
        for idx, (off, sn) in enumerate(self.streams):
            if not all_streams and idx != 0:
                continue
            party = self._party(sn)
            s = self._ivar(party, '@steps')
            if isinstance(s, rmarshal.Fixnum):
                s.set_value(int(value))

    def set_item(self, id_, count, kind='items', all_streams=True):
        for idx, (off, sn) in enumerate(self.streams):
            if not all_streams and idx != 0:
                continue
            party = self._party(sn)
            h = self._ivar(party, '@' + kind)
            if not isinstance(h, rmarshal.Hash):
                continue
            count = int(count)
            found = None
            for pos, (k, v) in enumerate(h.entries):
                if _intval(k) == id_:
                    found = (pos, v)
                    break
            if found and count > 0:
                pos, v = found
                if isinstance(v, rmarshal.Fixnum):
                    v.set_value(count)
                    h.dirty = True
            elif found and count <= 0:
                del h.entries[found[0]]
                h.dirty = True
            elif count > 0:
                h.entries.append((self._new_fixnum(id_), self._new_fixnum(count)))
                h.dirty = True

    def set_actor_attr(self, actor_id, attr, value):
        value = int(value)
        for idx, (off, sn) in enumerate(self.streams):
            actors_node = self._actors(sn)
            if actors_node is None:
                continue
            # N-09：容器可能是对象（Game_Actors）也可能是数组（stock XP/VX）
            arr = _as_array(actors_node)
            if arr is None or actor_id >= len(arr.items):
                continue
            a = arr.items[actor_id]
            if a is None or isinstance(a, rmarshal.NilNode):
                continue
            p = sn._parser
            d = {_symname(p, k): v for k, v in a.ivars}
            if attr in ('level', 'exp', 'hp', 'mp', 'tp',
                        'maxhp', 'maxmp', 'atk', 'def', 'spi', 'agi'):
                node = d.get('@' + attr)
                if isinstance(node, rmarshal.Fixnum):
                    node.set_value(value)
                    a.dirty = True
                elif attr == 'exp' and isinstance(node, rmarshal.Hash):
                    for k, v in node.entries:
                        if isinstance(v, rmarshal.Fixnum):
                            v.set_value(value)
                    node.dirty = True
                    a.dirty = True
            elif attr.startswith('param_plus'):
                idx2 = int(attr.split('_')[2])
                pp = d.get('@param_plus')
                if isinstance(pp, rmarshal.Array) and idx2 < len(pp.items):
                    if isinstance(pp.items[idx2], rmarshal.Fixnum):
                        pp.items[idx2].set_value(value)
                        pp.dirty = True
                        a.dirty = True

    def set_actor_skills(self, actor_id, skills):
        skills = [int(x) for x in skills]
        for idx, (off, sn) in enumerate(self.streams):
            actors_node = self._actors(sn)
            if actors_node is None:
                continue
            # N-09：容器可能是对象（Game_Actors）也可能是数组（stock XP/VX）
            arr = _as_array(actors_node)
            if arr is None or actor_id >= len(arr.items):
                continue
            a = arr.items[actor_id]
            if a is None or isinstance(a, rmarshal.NilNode):
                continue
            p = sn._parser
            d = {_symname(p, k): v for k, v in a.ivars}
            sk = d.get('@skills')
            if isinstance(sk, rmarshal.Array):
                sk.items = [self._new_fixnum(x) for x in skills]
                sk.dirty = True
                a.dirty = True

    # ---------------------------------------------------------------- output
    def save(self, path=None):
        """写回存档（**原子写**）。

        ⚠ **B-02 残留修复（M3b）**：原实现 ``open(path, 'wb')`` 直接截断 ——
        RGSS 存档动辄几百 KB，写到一半中断就把玩家存档毁了。现在走
        :func:`core.safety.atomic.atomic_write_bytes`。

        注意：写回前对每条流的根节点做 ``sync_dirty``，因为序列化器按
        ``dirty`` 决定"复用原始字节"还是"重新编码"，漏标会让改动丢失。
        """
        path = path or self.path
        for _offset, node in self.streams:
            sync_dirty(node)
        out = b''.join(rmarshal.dumps(node) for _offset, node in self.streams)
        atomic.atomic_write_bytes(path, out)
        return path

# -*- coding: utf-8 -*-
"""
RPG Maker MV / MZ save & data access.

@feature  cheats
@layer    core
@public   GameDataMV, SaveFileMV, META_KEYS
@depends  core.formats.lzstring
@tested   tests/compat/test_formats_compat.py
@footprint docs/MODULES.md#coreformats
@note     vendored：来自 rpgmaker_cheating_tool/mvdata.py。


MV  saves (www/save/file*.rpgsave)  are LZString(base64) of JSON, using the
game's modified JsonEx (objects carry "@c"/"@"/"@r"/"@a" metadata keys).
MZ  saves (save/file*.rmmzsave) are zlib-compressed JSON stored as UTF-8 text
(the compressed bytes are round-tripped through a latin-1 string first).

The editor only changes primitive values (numbers) and hash entries, so all
JsonEx metadata stays valid and the save remains loadable.
"""
import json
import os
import zlib

from . import lzstring

META_KEYS = {'@c', '@a', '@', '@r'}


def _unwrap_list(x):
    """MV JsonEx wraps arrays as {'@c': id, '@a': [...]}; MZ keeps them plain."""
    if isinstance(x, dict) and isinstance(x.get('@a'), list):
        return x['@a']
    if isinstance(x, list):
        return x
    return None


def _clean_ints(d):
    """dict (item ids -> counts) with possible '@c' metadata -> {int: int}."""
    out = {}
    for k, v in d.items():
        if k in META_KEYS:
            continue
        try:
            out[int(k)] = int(v)
        except (TypeError, ValueError):
            continue
    return out


class GameDataMV:
    """Names/definitions read from the game's data/*.json files."""

    def __init__(self, datadir):
        self.datadir = datadir
        self.items = {}
        self.weapons = {}
        self.armors = {}
        self.actors = {}
        self.classes = {}
        self.title = ''
        self._load_names()

    def _load_json(self, fname):
        path = os.path.join(self.datadir, fname)
        if not os.path.exists(path):
            return None
        with open(path, 'r', encoding='utf-8-sig') as fh:
            return json.load(fh)

    def _load_names(self):
        for fname, store in [('Items.json', self.items),
                             ('Weapons.json', self.weapons),
                             ('Armors.json', self.armors),
                             ('Classes.json', self.classes)]:
            data = self._load_json(fname)
            if not isinstance(data, list):
                continue
            for ent in data:
                if not isinstance(ent, dict):
                    continue
                oid = ent.get('id')
                name = ent.get('name')
                if isinstance(oid, int) and isinstance(name, str):
                    store[oid] = name
        data = self._load_json('Actors.json')
        if isinstance(data, list):
            for ent in data:
                if not isinstance(ent, dict):
                    continue
                oid = ent.get('id')
                if not isinstance(oid, int):
                    continue
                self.actors[oid] = {
                    'name': ent.get('name', ''),
                    'class_id': ent.get('classId'),
                    'initial_level': ent.get('initialLevel'),
                }
        sysdata = self._load_json('System.json')
        if isinstance(sysdata, dict):
            self.title = sysdata.get('gameTitle', '')
            self.currency = sysdata.get('currencyUnit', '')


class SaveFileMV:
    """MV / MZ save file editor (unified interface with rpgdata.SaveFile)."""

    PARAMS = ['最大HP', '最大MP', '攻击', '防御', '魔攻', '魔防', '速度', '幸运']

    def __init__(self, path, gamedata=None, engine='mv'):
        self.path = path
        self.gamedata = gamedata
        self.engine = engine
        self.raw = open(path, 'rb').read()
        self.data = self._load(self.raw)

    # ------------------------------------------------------------- (de)code
    @staticmethod
    def _load(raw):
        if raw and raw[0] == 0x78:  # MZ: zlib stream stored as UTF-8 text
            latin = raw.decode('utf-8')
            zbytes = latin.encode('latin-1')
            text = zlib.decompress(zbytes).decode('utf-8')
            return json.loads(text)
        text = lzstring.decompress_from_base64(raw.decode('utf-8', 'replace'))
        return json.loads(text)

    @staticmethod
    def _dump(data, engine):
        text = json.dumps(data, ensure_ascii=False, separators=(',', ':'))
        if engine == 'mz':
            zbytes = zlib.compress(text.encode('utf-8'), 1)
            return zbytes.decode('latin-1').encode('utf-8')
        return lzstring.compress_to_base64(text).encode('utf-8')

    # ---------------------------------------------------------------- lookup
    def _party(self):
        return self.data.get('party') or {}

    def _actors_node(self):
        return self.data.get('actors') or {}

    # ---------------------------------------------------------------- reading
    def read_party(self, stream_index=0):
        p = self._party()
        actors = _unwrap_list(p.get('_actors')) or []
        return {
            'gold': p.get('_gold'),
            'steps': p.get('_steps'),
            'items': _clean_ints(p.get('_items') or {}),
            'weapons': _clean_ints(p.get('_weapons') or {}),
            'armors': _clean_ints(p.get('_armors') or {}),
            'party_ids': [int(x) for x in actors],
        }

    def read_actors(self, stream_index=0):
        arr = _unwrap_list(self._actors_node().get('_data')) or []
        result = []
        for i, a in enumerate(arr):
            if not a or not isinstance(a, dict):
                result.append(None)
                continue
            exp = 0
            e = a.get('_exp')
            if isinstance(e, dict):
                vals = [v for k, v in e.items() if k not in META_KEYS
                        and isinstance(v, (int, float))]
                exp = int(vals[0]) if vals else 0
            try:
                aid = int(a.get('_actorId', i) or i)
            except (TypeError, ValueError):
                aid = i
            result.append({
                'actor_id': aid,
                'class_id': a.get('_classId'),
                'level': a.get('_level'),
                'exp': exp,
                'hp': a.get('_hp'),
                'mp': a.get('_mp'),
                'tp': a.get('_tp'),
                'param_plus': _unwrap_list(a.get('_paramPlus')) or [],
                'skills': _unwrap_list(a.get('_skills')) or [],
            })
        return result

    def read_var(self, key, stream_index=0):
        node = self.data.get(key)
        if not isinstance(node, dict):
            return []
        arr = _unwrap_list(node.get('_data')) or []
        if key == 'switches':
            return [1 if v else 0 for v in arr]
        return [v if v is not None else 0 for v in arr]

    # ---------------------------------------------------------------- editing
    def set_gold(self, value, all_streams=True):
        self._party()['_gold'] = int(value)

    def set_steps(self, value, all_streams=True):
        self._party()['_steps'] = int(value)

    def set_item(self, id_, count, kind='items', all_streams=True):
        h = self._party().get('_' + kind)
        if not isinstance(h, dict):
            h = {}
            self._party()['_' + kind] = h
        count = int(count)
        if count <= 0:
            h.pop(str(id_), None)
        else:
            h[str(id_)] = count

    def set_actor_attr(self, actor_id, attr, value):
        arr = _unwrap_list(self._actors_node().get('_data')) or []
        if actor_id >= len(arr):
            return
        a = arr[actor_id]
        if not a or not isinstance(a, dict):
            return
        value = int(value)
        if attr in ('level', 'exp', 'hp', 'mp', 'tp'):
            if attr == 'exp':
                e = a.get('_exp')
                if isinstance(e, dict):
                    for k in list(e.keys()):
                        if k not in META_KEYS:
                            e[k] = value
                    if not any(k not in META_KEYS for k in e):
                        e[str(a.get('_classId', 1))] = value
            else:
                a['_' + attr] = value
        elif attr.startswith('param_plus'):
            idx2 = int(attr.split('_')[2])
            pp = a.get('_paramPlus')
            lst = _unwrap_list(pp)
            if lst is None:
                lst = []
                a['_paramPlus'] = lst
            while len(lst) <= idx2:
                lst.append(0)
            lst[idx2] = value

    def set_actor_skills(self, actor_id, skills):
        skills = [int(x) for x in skills]
        arr = _unwrap_list(self._actors_node().get('_data')) or []
        if actor_id >= len(arr):
            return
        a = arr[actor_id]
        if not a or not isinstance(a, dict):
            return
        sk = a.get('_skills')
        lst = _unwrap_list(sk)
        if lst is None:
            lst = skills
            a['_skills'] = lst
        else:
            lst[:] = skills

    def set_var(self, key, index, value):
        node = self.data.get(key)
        if not isinstance(node, dict):
            node = {'_data': []}
            self.data[key] = node
        arr = _unwrap_list(node.get('_data'))
        if arr is None:
            arr = []
            node['_data'] = arr
        while len(arr) <= index:
            arr.append(0)
        if key == 'switches':
            arr[index] = bool(value)
        elif isinstance(value, str) and value.lstrip('-').isdigit():
            arr[index] = int(value)
        else:
            try:
                arr[index] = int(value)
            except (TypeError, ValueError):
                arr[index] = value

    # ---------------------------------------------------------------- output
    def save(self, path=None):
        path = path or self.path
        with open(path, 'wb') as f:
            f.write(self._dump(self.data, self.engine))
        return path

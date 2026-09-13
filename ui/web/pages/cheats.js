/* ---------------------------------------------------------------------------
 * 存档修改功能页 —— 读档 / 改数值 / 写回 / 游戏数据表编辑 / 备份还原
 *
 * @feature  cheats
 * @layer    ui
 * @public   render
 * @depends  /dom.js, /api/cheats/*
 * @tested   tests/integration/test_cheats_page.py（静态契约）
 * @footprint docs/UI_SPEC.md
 *
 * 迁移来源：rpgmaker_cheating_tool/main.py 的 tkinter 界面
 * （顶栏选目录 / 存档下拉 / 队伍·金币页 / 道具页 / 角色页 / 开关变量页 / 状态栏）。
 * 按 ADR-001 **逻辑层迁移、界面层重写**，因此这里是"同样的能力、不同的交互"，
 * 逐条对照 docs/迁移对照表.md §B.2（B-30 ～ B-37）。
 *
 * 硬约束（docs/UI_SPEC.md §5）：
 *   * 默认零破坏 —— 改数值只改**内存**，点「保存」才写盘，且写盘前自动备份
 *   * 破坏性操作二次确认，并在文案里写明改哪些文件、备份在哪里
 *   * 覆盖类按钮用 .btn.danger；保存后**展示备份路径**
 *   * 页面不得写具体颜色值，只用 tokens.css 令牌与 components.css 的类
 *
 * 与原工具的一处**有意差异**：原工具每次改一项就立刻写盘（`main.py` 的
 * `_apply` 直接 save），一旦改错只能靠"撤销"按钮逐项回退。这里改成
 * "先改内存、再统一保存"，于是备份只做一次、也能整体放弃（刷新页面即可）。
 * ------------------------------------------------------------------------- */

import {
  el, getJSON, postJSON, toast, confirmDialog, escapeHTML,
} from '/dom.js';

/** 存档下拉 / 列表里显示的时间与体积 */
const PAGE_SWITCHES = 60;

/** 图标开关的持久化键（纯显示偏好，与存档内容无关） */
const ICON_PREF_KEY = 'tudou.rpgtool.cheats.showIcons';

/** 图标图集地址。
 *
 * ⚠ 单独提成常量而不是内联写 `url(...)`：`tests/integration/test_cheats_page.py`
 * 会用「端点路径紧跟在引号/反引号之后」的规则扫描页面，确认**每个后端端点
 * 都有界面入口**（防死接口）。写在 `url(/api/...)` 里它就看不见，会被报成
 * 死接口 —— 与其放宽扫描器，不如把地址提出来（本来也是更好的写法）。 */
const ICON_SET_URL = '/api/cheats/icon_set';

/* localStorage 在 Node 冒烟探针（tools/web_probe.mjs）里不存在，隐私模式下
   也会抛 —— 所以统一走这两个吞异常的助手。存不了只是"下次要再点一下"，
   绝不能因此让整个页面挂掉。 */
function loadPref(key, fallback) {
  try {
    if (typeof localStorage === 'undefined') return fallback;
    const raw = localStorage.getItem(key);
    return raw === null ? fallback : raw;
  } catch (err) {
    return fallback;
  }
}

function savePref(key, value) {
  try {
    if (typeof localStorage !== 'undefined') localStorage.setItem(key, value);
  } catch (err) {
    /* 只是显示偏好，存不上不影响功能 */
  }
}

const state = {
  game: null,
  saves: [],
  current: null,
  dirty: false,
  vars: { key: 'switches', offset: 0, view: null },
  data: { fields: [], files: [], filter: '' },
  actorAttrs: [],
  itemKinds: [],
  party: null,
  //: 图标图集信息（后端 /api/cheats/icon_info 的原样结果）
  icons: { available: false, reason: '还没读取游戏数据' },
  //: 用户**想不想**看图标（与"现在能不能看"分开存）——
  //: 合成一个布尔量的话，"图集不可用"时被强制关掉的开关会覆盖掉用户偏好，
  //: 换个能看到图标的游戏就莫名其妙变成关闭状态。
  iconWant: loadPref(ICON_PREF_KEY, '1') !== '0',
  //: 图标控件：``{box, label, hint}``
  iconSwitch: null,
  dataHost: null,
  actorsHost: null,
  varsHost: null,
  statusHost: null,
};

export async function render(host) {
  state.dirty = false;
  state.current = null;

  host.append(buildDirCard());
  host.append(buildSaveCard());
  host.append(buildPartyCard());
  host.append(buildActorsCard());
  host.append(buildVarsCard());
  host.append(buildDataTableCard());

  state.statusHost = el('section', { class: 'card' });
  host.append(state.statusHost);
  renderStatus();

  await loadStatus();
}

/* ---------------------------------------------------------------------------
 * 卡片 1：游戏目录
 * ------------------------------------------------------------------------- */
function buildDirCard() {
  const dirInput = el('input', {
    type: 'text', id: 'ch-dir',
    placeholder: '例如 D:\\games\\我的游戏（含 www / data / Data 的那一层）',
  });
  const browseBtn = el('button', { class: 'btn', type: 'button', text: '浏览…' });
  browseBtn.addEventListener('click', async () => {
    browseBtn.disabled = true;
    try {
      const res = await postJSON('/api/cheats/pick_folder', { initial: dirInput.value });
      if (res.cancelled || !res.dir) return;
      dirInput.value = res.dir;
      await openGame(res.dir);
    } catch (err) {
      toast('无法打开系统对话框：' + err.message + '（可直接粘贴路径）', 'warn', 8000);
    } finally {
      browseBtn.disabled = false;
    }
  });

  const openBtn = el('button', {
    class: 'btn primary', type: 'button', text: '读取游戏数据', id: 'ch-open',
  });
  openBtn.addEventListener('click', () => openGame(dirInput.value.trim()));

  return el('section', { class: 'card' }, [
    el('h2', {}, [el('span', { class: 'step', text: '1' }),
      document.createTextNode('游戏目录')]),
    el('div', {
      class: 'card-sub',
      text: '选择包含 www / data / Data 文件夹的那一层。识别与存档发现走 core/engines.py（全工程唯一实现）。',
    }),
    el('div', { class: 'row' }, [dirInput, browseBtn, openBtn]),
    el('div', { class: 'chips', id: 'ch-engine' }),
  ]);
}

async function openGame(dir) {
  if (!dir) { toast('请先填写游戏目录', 'warn'); return; }
  try {
    const res = await postJSON('/api/cheats/open', { dir });
    state.game = res.game;
    applyEngineChips(res);
    toast(`已识别：${res.summary || ''}（${res.saves} 个存档）`, 'ok', 6000);
    // ⚠ 换了游戏必须先把上一个游戏的表格清掉：那些行里的 id/图标索引
    // 是**上一个游戏**的数据表，配上新游戏的名字表与图集会显示成
    // "看着像新的、其实是旧的" —— 正是本工程反复踩到的那一类缺陷。
    clearSaveViews('已切换游戏，请重新选择存档。');
    await loadIconInfo();
    await loadSaves();
    await loadData(false);
  } catch (err) {
    toast('读取失败：' + err.message, 'error', 12000);
  }
}

/** 清空依赖"当前存档"的三块视图（换游戏 / 换存档时用）。 */
function clearSaveViews(hint) {
  state.party = null;
  state.current = null;
  for (const id of ['ch-items', 'ch-actors', 'ch-vars']) {
    const host = document.getElementById(id);
    if (!host) continue;
    host.textContent = '';
    if (hint) host.append(el('div', { class: 'hint', text: hint }));
  }
}

function applyEngineChips(res) {
  const host = document.getElementById('ch-engine');
  if (!host) return;
  host.textContent = '';
  if (!res || !res.ok) {
    host.append(el('span', { class: 'chip', text: '尚未识别引擎' }));
    return;
  }
  const game = res.game || {};
  host.append(el('span', { class: 'chip ok', html: `引擎 <b>${escapeHTML(game.engine || '?')}</b>` }));
  host.append(el('span', { class: 'chip', text: game.label || '' }));
  host.append(el('span', { class: 'chip', text: game.game_dir || '' }));
}

/* ---------------------------------------------------------------------------
 * 卡片 2：存档选择
 * ------------------------------------------------------------------------- */
function buildSaveCard() {
  const listHost = el('div', { id: 'ch-saves' });
  return el('section', { class: 'card' }, [
    el('h2', {}, [el('span', { class: 'step', text: '2' }),
      document.createTextNode('选择存档')]),
    el('div', {
      class: 'card-sub',
      text: '读入存档后可改数值。改动先放在内存里，点「保存存档」才写盘 —— 写盘前会自动备份。',
    }),
    listHost,
  ]);
}

async function loadSaves() {
  const host = document.getElementById('ch-saves');
  if (!host) return;
  host.textContent = '';
  let res;
  try {
    res = await getJSON('/api/cheats/saves');
  } catch (err) {
    host.append(el('div', { class: 'hint', text: err.message }));
    return;
  }
  state.saves = res.saves || [];
  if (!state.saves.length) {
    renderNoSaves(host, res);
    return;
  }

  /* 多套存档（自动存档等）必须提醒 —— 迁移对照表 B-31/B-03 的原行为，
     漏掉会让用户以为"只改了一个存档"，实际游戏读的是另一个 */
  const dirs = [...new Set(state.saves.map((s) => s.dir))];
  if (dirs.length > 1) {
    host.append(el('div', {
      class: 'warn-text',
      text: `注意：发现 ${dirs.length} 个含存档的目录（可能有自动存档等第二套存档），`
        + '修改时请确认改的是游戏实际读取的那一个。',
    }));
  }
  const dirHost = el('div', { class: 'chips' });
  for (const dir of dirs) {
    dirHost.append(el('span', { class: 'chip mono', text: dir }));
  }
  host.append(dirHost);

  const tbody = el('tbody', {});
  state.saves.forEach((save, index) => {
    const current = res.current && save.path === res.current;
    tbody.append(el('tr', {}, [
      el('td', {}, [el('span', { class: 'code', text: save.name })]),
      el('td', { class: 'nowrap', text: save.time }),
      el('td', { class: 'num', text: fmtSize(save.size) }),
      el('td', { class: 'hint mono', text: save.dir }),
      el('td', {}, [current
        ? el('span', { class: 'tag ok', text: '已载入' })
        : el('button', {
          class: 'btn sm primary', type: 'button', text: '载入',
          // id 供前端冒烟探针真的"点一下载入"用（tests/integration/test_web_syntax.py
          // 的 --game 流程），不是给样式用的
          id: `ch-load-${index}`,
          onclick: () => loadSave(save.path),
        })]),
    ]));
  });
  host.append(el('div', { class: 'table-wrap' }, [
    el('table', {}, [
      el('thead', {}, [el('tr', {}, [
        el('th', { text: '存档' }), el('th', { text: '时间' }),
        el('th', { text: '大小' }), el('th', { text: '目录' }), el('th', { text: '操作' }),
      ])]),
      tbody,
    ]),
  ]));

  if (res.backups && res.backups.length) {
    host.append(el('div', {
      class: 'hint',
      text: `游戏目录下已有 ${res.backups.length} 个备份（最新的：${res.backups[0].name}）。`,
    }));
  }
}

/**
 * 「一个存档都没找到」时该显示什么。
 *
 * ⚠ 这里以前只有一句「这个游戏目录下没有找到存档。」—— 用户看到这句话
 * 完全无从判断是**游戏还没存过档**、**存档在别处**、还是**工具的规则没认出来**
 * （实测就卡在这里：报告的"搜索不到存档所在文件夹"）。
 *
 * 现在把三种情况的线索一次性摊开：
 *   1. 我找过哪些目录（并给出「打开」按钮，用户自己一看就明白）
 *   2. 目录里有哪些"看着像存档但不是"的文件 —— 例如 `config.rpgsave`
 *      是设置而不是进度，恰恰是"目录里有文件却列表为空"时最迷惑人的东西
 *   3. 两步兜底：手动填路径，或全盘按扩展名搜一遍让用户自己挑
 */
function renderNoSaves(host, res) {
  const search = res.search || {};
  host.append(el('div', { class: 'empty' }, [
    el('div', { text: '没有找到存档文件。' }),
    el('div', {
      class: 'hint',
      text: res.hint || '如果游戏里还没存过档，先进游戏存一次再点「刷新」。',
    }),
  ]));

  /* ---- 找过哪些目录 ---- */
  const dirs = (search.dirs || []);
  if (dirs.length) {
    const tbody = el('tbody', {});
    for (const item of dirs) {
      tbody.append(el('tr', {}, [
        el('td', {}, [el('span', { class: 'code', text: item.dir })]),
        el('td', { class: 'nowrap' }, [item.exists
          ? el('span', { class: 'tag ok', text: '存在' })
          : el('span', { class: 'tag skipped', text: '不存在' })]),
        el('td', { class: 'num', text: String(item.saves) }),
        el('td', {}, [el('button', {
          class: 'btn sm', type: 'button', text: '打开',
          disabled: !item.exists,
          onclick: () => openInExplorer(item.dir),
        })]),
      ]));
    }
    host.append(el('div', { class: 'hint', text: '工具搜索过这些目录：' }));
    host.append(el('div', { class: 'table-wrap' }, [
      el('table', {}, [
        el('thead', {}, [el('tr', {}, [
          el('th', { text: '目录' }), el('th', { text: '状态' }),
          el('th', { text: '存档数' }), el('th', { text: '操作' }),
        ])]),
        tbody,
      ]),
    ]));
    if (search.pattern) {
      host.append(el('div', {
        class: 'hint',
        text: `本引擎（${state.game && state.game.engine || ''}）的存档命名规则：${search.pattern}`,
      }));
    }
  }

  /* ---- 目录里那些"不是存档"的文件 ---- */
  const others = res.other_files || [];
  if (others.length) {
    host.append(el('div', { class: 'warn-text', text: '注意：目录里有下面这些文件，但它们不是存档进度：' }));
    const list = el('ul', { class: 'muted' });
    for (const item of others.slice(0, 8)) {
      list.append(el('li', {}, [
        el('span', { class: 'code', text: item.name }),
        document.createTextNode(` —— ${item.reason}`),
      ]));
    }
    host.append(list);
  }

  /* ---- 兜底 1/2：手动填路径 ---- */
  const manual = el('input', {
    type: 'text', placeholder: '把存档文件的完整路径粘到这里（例如 …\\www\\save\\file1.rpgsave）',
  });
  const manualBtn = el('button', {
    class: 'btn sm primary', type: 'button', text: '强制加载这个文件',
    onclick: () => loadSave(manual.value.trim()),
  });
  host.append(el('hr', { class: 'divider' }));
  host.append(el('div', { class: 'row' }, [manual, manualBtn]));

  /* ---- 兜底 2/2：全盘按扩展名搜 ---- */
  const scanBtn = el('button', {
    class: 'btn sm', type: 'button', text: '在整个游戏目录里搜一遍',
  });
  const scanHost = el('div');
  scanBtn.addEventListener('click', async () => {
    scanBtn.disabled = true;
    scanHost.textContent = '';
    try {
      const found = await getJSON('/api/cheats/find_saves');
      const list = found.candidates || [];
      scanHost.append(el('div', { class: 'hint', text: found.note || '' }));
      if (!list.length) {
        scanHost.append(el('div', {
          class: 'empty',
          text: `在 ${found.root} 里没有找到任何 ${found.ext} 文件 —— `
            + '说明这个游戏确实还没有存档，先进游戏存一次再回来刷新。',
        }));
        return;
      }
      const tbody = el('tbody', {});
      for (const item of list.slice(0, 50)) {
        tbody.append(el('tr', {}, [
          el('td', {}, [el('span', { class: 'code', text: item.name })]),
          el('td', { class: 'hint mono', text: item.dir }),
          el('td', { class: 'num', text: fmtSize(item.size) }),
          el('td', {}, [item.by_rule
            ? el('span', { class: 'tag ok', text: '符合命名规则' })
            : el('span', { class: 'tag warn', text: '名字不常见' })]),
          el('td', {}, [el('button', {
            class: 'btn sm primary', type: 'button', text: '加载',
            onclick: () => loadSave(item.path),
          })]),
        ]));
      }
      scanHost.append(el('div', { class: 'table-wrap' }, [
        el('table', {}, [
          el('thead', {}, [el('tr', {}, [
            el('th', { text: '文件' }), el('th', { text: '目录' }),
            el('th', { text: '大小' }), el('th', { text: '匹配' }), el('th', { text: '操作' }),
          ])]),
          tbody,
        ]),
      ]));
    } catch (err) {
      scanHost.append(el('div', { class: 'error-text', text: '搜索失败：' + err.message }));
    } finally {
      scanBtn.disabled = false;
    }
  });
  host.append(el('div', { class: 'row' }, [scanBtn]));
  host.append(scanHost);
}

async function loadSave(path) {
  try {
    const res = await postJSON('/api/cheats/load', { path });
    state.current = res.path;
    state.dirty = false;
    renderParty(res.party);
    renderActors(res.actors);
    await loadVars('switches', 0);
    await loadSaves();
    await loadBackups();
    renderStatus();
    toast('存档已载入', 'ok');
  } catch (err) {
    toast('载入失败：' + err.message, 'error', 12000);
  }
}

/* ---------------------------------------------------------------------------
 * 卡片 3：金币 / 步数 / 道具
 * ------------------------------------------------------------------------- */
function buildPartyCard() {
  const gold = el('input', { type: 'number', id: 'ch-gold' });
  const steps = el('input', { type: 'number', id: 'ch-steps' });
  const applyBtn = el('button', { class: 'btn primary', type: 'button', text: '应用数值' });
  applyBtn.addEventListener('click', () => applyParty({}));

  const iconRow = buildIconSwitch();
  const itemHost = el('div', { id: 'ch-items' });

  return el('section', { class: 'card' }, [
    el('h2', {}, [el('span', { class: 'step', text: '3' }),
      document.createTextNode('金币 / 步数 / 道具')]),
    el('div', { class: 'card-sub', text: '改动只改内存，需要点最下方的「保存存档」才会写回文件。' }),
    el('div', { class: 'grid' }, [
      field('金币', gold),
      field('步数', steps),
      el('div', { class: 'field' }, [el('label', { text: ' ' }), applyBtn]),
    ]),
    iconRow,
    itemHost,
  ]);
}

/* ---------------------------------------------------------------------------
 * 游戏内图标
 *
 * 为什么需要（用户报告）：有些道具的名字是乱码、纯数字或者干脆没有名字，
 * 列表里根本认不出哪件是哪件；前面挂一个游戏内图标就一眼能对上。
 *
 * 数据表里本来就有 iconIndex（RGSS 是 @icon_index）—— "IconSet 里的第几格"。
 * 后端把整张图集（必要时先解密 .rpgmvp / .png_）连同 cell/columns 一起给出，
 * 这里用 background-position 裁出单格。不裁图、不生成小文件、零依赖。
 * ------------------------------------------------------------------------- */

function buildIconSwitch() {
  const box = el('input', {
    type: 'checkbox', id: 'ch-icon-toggle',
  });
  const label = el('label', { class: 'switch', for: 'ch-icon-toggle' }, [
    box, el('span', { class: 'track' }), document.createTextNode('显示游戏内图标'),
  ]);
  const hint = el('span', { class: 'hint', id: 'ch-icon-hint' });
  box.addEventListener('change', () => {
    state.iconWant = box.checked;
    savePref(ICON_PREF_KEY, box.checked ? '1' : '0');
    syncIconVisibility();
  });
  state.iconSwitch = { box, label, hint };
  applyIconAvailability();
  return el('div', { class: 'row' }, [label, hint]);
}

/** 拉一次图集信息，决定开关是否可用、以及为什么不可用。 */
async function loadIconInfo() {
  try {
    const res = await getJSON('/api/cheats/icon_info');
    state.icons = res.icons || { available: false, reason: '接口没有返回图标信息' };
  } catch (err) {
    state.icons = { available: false, reason: '取图标信息失败：' + err.message };
  }
  applyIconAvailability();
}

function applyIconAvailability() {
  const sw = state.iconSwitch;
  if (!sw) return;
  const info = state.icons || {};
  const usable = !!info.available;
  // 开关位置 = "用户想开" ∧ "这个游戏能开"
  sw.box.checked = usable && state.iconWant;
  sw.box.disabled = !usable;
  sw.label.className = usable ? 'switch' : 'switch disabled';
  sw.label.setAttribute('aria-disabled', usable ? 'false' : 'true');
  if (!usable) {
    sw.hint.textContent = info.reason || '图标不可用';
  } else {
    sw.hint.textContent = `图集 ${info.count} 格，每格 ${info.cell}px`
      + (info.encrypted ? '（已从加密资源解密）' : '')
      + '；没有图标的条目显示虚线空位。';
  }
  syncIconVisibility();
}

/** 只切 class，不重建表格 —— 免得抖掉用户"输了数还没点应用"的内容。 */
function syncIconVisibility() {
  const host = document.getElementById('ch-items');
  if (!host) return;
  const sw = state.iconSwitch;
  const on = !!(sw && sw.box.checked && (state.icons || {}).available);
  host.className = on ? '' : 'hide-icons';
}

/** 单个图标：用整张图集做 sprite，按原始像素显示（像素画不缩放才不糊）。 */
function iconCell(index, label) {
  const info = state.icons || {};
  const cell = info.cell || 0;
  const columns = info.columns || 0;
  const count = info.count || 0;
  const title = `${label || ''} #${index}`.trim();
  // index 为 0 / null / 越界都画虚线空位：0 在引擎里就是"不显示图标"
  if (!cell || !columns || !index || index < 0 || index >= count) {
    return el('span', {
      class: 'icon-cell blank', title: index ? `${title}（超出图集范围）` : `${label || ''} 没有图标`,
      style: { width: `${cell || 18}px`, height: `${cell || 18}px` },
    });
  }
  const col = index % columns;
  const row = Math.floor(index / columns);
  return el('span', {
    class: 'icon-cell',
    title: `${title}（第 ${row + 1} 行第 ${col + 1} 列）`,
    style: {
      width: `${cell}px`,
      height: `${cell}px`,
      backgroundImage: `url(${ICON_SET_URL})`,
      // 第 0 行/列要写 "0" 而不是 "-0px"（CSS 等价，但输出干净、断言也锋利）
      backgroundPosition: `${offset(col * cell)} ${offset(row * cell)}`,
    },
  });
}

/** sprite 偏移：0 就写 0px，其余写负像素。 */
function offset(pixels) {
  return pixels ? `-${pixels}px` : '0px';
}

/** 名称单元格：图标 + 名字 + id。
 *
 * ⚠ **无条件**生成图标格（只要图集可用），由 ``.hide-icons`` 控制显示 ——
 * 这样开关只是切 class，不需要重画表格，用户输了数还没点「应用」的内容
 * 不会被抖掉。图集不可用时后端不给 ``icon``，这里也就不画。 */
function nameCell(row) {
  const kids = [];
  if ((state.icons || {}).available) {
    kids.push(iconCell(row.icon, row.name));
  }
  kids.push(el('div', {}, [
    el('div', { text: row.name }),
    el('div', { class: 'hint mono', text: `#${row.id}` }),
  ]));
  return el('td', {}, [el('div', { class: 'name-cell' }, kids)]);
}

function field(label, control) {
  return el('div', { class: 'field' }, [el('label', { text: label }), control]);
}

function renderParty(party) {
  if (!party) return;
  state.party = party;
  const gold = document.getElementById('ch-gold');
  const steps = document.getElementById('ch-steps');
  if (gold) gold.value = party.gold === null || party.gold === undefined ? '' : party.gold;
  if (steps) steps.value = party.steps === null || party.steps === undefined ? '' : party.steps;

  const host = document.getElementById('ch-items');
  if (!host) return;
  host.textContent = '';
  syncIconVisibility();

  if (party.party && party.party.length) {
    host.append(el('div', { class: 'row' }, [
      el('span', { class: 'hint', text: '队伍成员' }),
      el('span', { class: 'chips' }, party.party.map((member) =>
        el('span', { class: 'chip', html: `${escapeHTML(member.name)} <b>#${member.id}</b>` }))),
    ]));
    host.append(el('div', {
      class: 'hint',
      text: '队伍成员只读显示 —— 原工具也只能看不能改（docs/FEATURES.md 已标注这一等价性）。',
    }));
  }

  const kinds = state.itemKinds.length ? state.itemKinds
    : Object.keys(party.catalog || party.items || {});
  for (const kind of kinds) {
    const label = { items: '道具', weapons: '武器', armor: '防具',
                    armors: '防具' }[kind] || kind;
    const catalog = (party.catalog || {})[kind] || [];
    // 兼容：后端没给 catalog 时退回"只列持有"（旧行为）
    const rows = catalog.length ? catalog : ((party.items || {})[kind] || []);

    /* 与参考工具一致：**列出整张数据表**（没持有的显示 0），
       这样才可能添加自己还没有的道具。上面再加搜索与"只看持有"两个开关 ——
       35 件还好，几百件时没有筛子就没法用。 */
    const search = el('input', { type: 'text', placeholder: '搜索名称或 id' });
    const onlyOwned = el('input', { type: 'checkbox' });
    const filterRow = el('div', { class: 'row' });
    const tbody = el('tbody', {});
    const counter = el('span', { class: 'hint' });

    const draw = () => {
      const query = search.value.trim().toLowerCase();
      const owned = onlyOwned.checked;
      tbody.textContent = '';
      let shown = 0;
      for (const row of rows) {
        if (owned && !row.count) continue;
        if (query
            && !String(row.name).toLowerCase().includes(query)
            && !String(row.id).includes(query)) {
          continue;
        }
        shown += 1;
        const input = el('input', { type: 'number', value: String(row.count), min: '0' });
        input.addEventListener('keydown', (ev) => {
          if (ev.key === 'Enter') applyParty({ [kind]: [{ id: row.id, count: input.value }] });
        });
        tbody.append(el('tr', {}, [
          nameCell(row),
          el('td', {}, [input]),
          el('td', {}, [el('span', {
            class: 'tag ' + (row.count ? 'translated' : 'skipped'),
            text: row.count ? '持有' : '未持有',
          })]),
          el('td', {}, [el('button', {
            class: 'btn sm', type: 'button', text: '应用',
            onclick: () => applyParty({ [kind]: [{ id: row.id, count: input.value }] }),
          })]),
        ]));
      }
      if (!shown) {
        tbody.append(el('tr', {}, [
          el('td', { class: 'hint', colspan: '4', text: '没有符合条件的条目' }),
        ]));
      }
      counter.textContent = `显示 ${shown} / ${rows.length} 项`;
    };
    search.addEventListener('input', draw);
    onlyOwned.addEventListener('change', draw);
    filterRow.append(search,
      el('label', { class: 'check' }, [onlyOwned, document.createTextNode('只看已持有')]),
      counter);

    const addInput = el('input', { type: 'number', placeholder: '数量', value: '1' });
    const addId = el('input', { type: 'number', placeholder: '物品 id' });
    host.append(el('hr', { class: 'divider' }));
    host.append(el('div', { class: 'row' }, [
      el('b', { text: label }),
      el('span', { class: 'hint', text: `${rows.length} 项（含未持有）` }),
    ]));
    host.append(filterRow);
    host.append(el('div', { class: 'table-wrap' }, [
      el('table', {}, [
        el('thead', {}, [el('tr', {}, [
          el('th', { text: '名称' }), el('th', { text: '数量' }),
          el('th', { text: '状态' }), el('th', { text: '操作' }),
        ])]),
        tbody,
      ]),
    ]));
    host.append(el('div', { class: 'row' }, [
      el('span', { class: 'hint', text: '直接按 id 设置：' }),
      addId, addInput,
      el('button', {
        class: 'btn sm', type: 'button', text: '设置数量',
        onclick: () => applyParty({ [kind]: [{ id: addId.value, count: addInput.value }] }),
      }),
    ]));
    draw();
  }
}

async function applyParty(body) {
  try {
    const res = await postJSON('/api/cheats/party', body);
    renderParty(res.party);
    markDirty();
    toast('已应用（记得保存存档）', 'ok', 2200);
  } catch (err) {
    toast('修改失败：' + err.message, 'error', 10000);
  }
}

/* ---------------------------------------------------------------------------
 * 卡片 4：角色
 * ------------------------------------------------------------------------- */
function buildActorsCard() {
  state.actorsHost = el('div', { id: 'ch-actors' });
  return el('section', { class: 'card' }, [
    el('h2', {}, [el('span', { class: 'step', text: '4' }),
      document.createTextNode('角色')]),
    el('div', {
      class: 'card-sub',
      text: '等级 / 经验 / HP / MP / TP 与 8 项属性加成。技能列表按 id 整体替换（与原工具一致）。',
    }),
    state.actorsHost,
  ]);
}

function renderActors(actors) {
  const host = state.actorsHost || document.getElementById('ch-actors');
  if (!host) return;
  host.textContent = '';
  const list = (actors || []).filter(Boolean);
  if (!list.length) {
    host.append(el('div', { class: 'empty', text: '没有角色数据' }));
    return;
  }
  const attrs = state.actorAttrs.length ? state.actorAttrs
    : [{ key: 'level', label: '等级' }, { key: 'exp', label: '经验' },
      { key: 'hp', label: 'HP' }, { key: 'mp', label: 'MP' }];

  for (const actor of list) {
    const inputs = {};
    const grid = el('div', { class: 'grid' });
    for (const attr of attrs) {
      const value = actor[attr.key] !== undefined ? actor[attr.key] : '';
      const input = el('input', { type: 'number', value: String(value) });
      inputs[attr.key] = input;
      grid.append(field(attr.label, input));
    }
    const skillsInput = el('input', {
      type: 'text', placeholder: '技能 id，逗号分隔（留空则不改）',
      value: (actor.skills || []).join(','),
    });

    const applyBtn = el('button', { class: 'btn primary', type: 'button', text: '应用' });
    applyBtn.addEventListener('click', async () => {
      const payload = {};
      for (const [key, input] of Object.entries(inputs)) {
        if (input.value !== '') payload[key] = input.value;
      }
      skillsInput.value.trim()
        ? await applyActor(actor.index, payload,
          skillsInput.value.split(',').map((s) => s.trim()).filter(Boolean))
        : await applyActor(actor.index, payload, null);
    });

    host.append(el('div', { class: 'card-sub' }, [
      el('b', { text: actor.name }),
      el('span', { class: 'hint', text: `  (#${actor.actor_id} · 职业 ${actor.class_id || '—'})` }),
    ]));
    host.append(grid);
    host.append(el('div', { class: 'row' }, [
      el('span', { class: 'hint', text: '技能列表' }), skillsInput, applyBtn,
    ]));
    host.append(el('hr', { class: 'divider' }));
  }
}

async function applyActor(actorId, attrs, skills) {
  try {
    const body = { actor_id: actorId, attrs };
    if (skills) body.skills = skills;
    const res = await postJSON('/api/cheats/actor', body);
    renderActors(res.actors);
    markDirty();
    toast('已应用（记得保存存档）', 'ok', 2200);
  } catch (err) {
    toast('修改失败：' + err.message, 'error', 10000);
  }
}

/* ---------------------------------------------------------------------------
 * 卡片 5：开关 / 变量
 * ------------------------------------------------------------------------- */
function buildVarsCard() {
  state.varsHost = el('div', { id: 'ch-vars' });
  const kindSel = el('select', { id: 'ch-var-kind' });
  kindSel.append(el('option', { value: 'switches', text: '开关 (Switches)' }));
  kindSel.append(el('option', { value: 'variables', text: '变量 (Variables)' }));
  kindSel.addEventListener('change', () => loadVars(kindSel.value, 0));

  const jumpInput = el('input', { type: 'number', placeholder: '跳到编号', min: '0' });
  const jumpBtn = el('button', {
    class: 'btn sm', type: 'button', text: '跳转',
    onclick: () => loadVars(kindSel.value, Math.max(0, Number(jumpInput.value) - 20)),
  });

  return el('section', { class: 'card' }, [
    el('h2', {}, [el('span', { class: 'step', text: '5' }),
      document.createTextNode('开关 / 变量')]),
    el('div', {
      class: 'card-sub',
      text: '编号从 1 开始（下标 0 是占位）。开关显示为「开 / 关」，变量直接填整数。',
    }),
    el('div', { class: 'row' }, [kindSel, jumpInput, jumpBtn]),
    state.varsHost,
  ]);
}

async function loadVars(key, offset) {
  try {
    const res = await getJSON(
      `/api/cheats/vars?key=${encodeURIComponent(key)}&offset=${offset}&limit=${PAGE_SWITCHES}`);
    state.vars = { key, offset, view: res.view };
    renderVars();
  } catch (err) {
    const host = state.varsHost || document.getElementById('ch-vars');
    if (host) {
      host.textContent = '';
      host.append(el('div', { class: 'hint', text: err.message }));
    }
  }
}

function renderVars() {
  const host = state.varsHost || document.getElementById('ch-vars');
  const view = state.vars.view;
  if (!host || !view) return;
  host.textContent = '';

  const tbody = el('tbody', {});
  for (const row of view.items) {
    const number = row.index + 1;
    let control;
    if (view.key === 'switches') {
      const box = el('input', { type: 'checkbox' });
      box.checked = !!row.value;
      box.addEventListener('change', () =>
        setVar(view.key, row.index, box.checked));
      control = el('label', { class: 'check' }, [box,
        document.createTextNode(box.checked ? '开' : '关')]);
    } else {
      const input = el('input', { type: 'number', value: String(row.value) });
      input.addEventListener('keydown', (ev) => {
        if (ev.key === 'Enter') setVar(view.key, row.index, input.value);
      });
      control = el('div', { class: 'row' }, [input, el('button', {
        class: 'btn sm', type: 'button', text: '应用',
        onclick: () => setVar(view.key, row.index, input.value),
      })]);
    }
    tbody.append(el('tr', {}, [
      el('td', { class: 'num nowrap', text: String(number) }),
      el('td', {}, [control]),
    ]));
  }

  host.append(el('hr', { class: 'divider' }));
  host.append(el('div', { class: 'row' }, [
    el('span', {
      class: 'hint',
      text: `第 ${view.offset + 1} – ${view.offset + view.items.length} 项，共 ${view.total} 项`,
    }),
    el('span', { class: 'spacer' }),
    el('button', {
      class: 'btn sm', type: 'button', text: '上一页',
      disabled: view.offset <= 0,
      onclick: () => loadVars(view.key, Math.max(0, view.offset - PAGE_SWITCHES)),
    }),
    el('button', {
      class: 'btn sm', type: 'button', text: '下一页',
      disabled: view.offset + PAGE_SWITCHES >= view.total,
      onclick: () => loadVars(view.key, view.offset + PAGE_SWITCHES),
    }),
  ]));
  host.append(el('div', { class: 'table-wrap' }, [
    el('table', {}, [
      el('thead', {}, [el('tr', {}, [
        el('th', { text: '编号' }), el('th', { text: '值' }),
      ])]),
      tbody,
    ]),
  ]));
}

async function setVar(key, index, value) {
  try {
    await postJSON('/api/cheats/var', { key, index, value });
    markDirty();
    await loadVars(key, state.vars.offset);
    toast('已应用（记得保存存档）', 'ok', 2000);
  } catch (err) {
    toast('修改失败：' + err.message, 'error', 10000);
  }
}

/* ---------------------------------------------------------------------------
 * 卡片 6：游戏数据表（不在存档里的那部分）
 * ------------------------------------------------------------------------- */
function buildDataTableCard() {
  state.dataHost = el('div', { id: 'ch-data' });
  return el('section', { class: 'card' }, [
    el('h2', {}, [el('span', { class: 'step', text: '6' }),
      document.createTextNode('游戏数据表')]),
    el('div', {
      class: 'card-sub',
      text: '改的是 Data/ 下的数据文件（价格、攻击力、初始等级等），与存档无关，'
        + '改完后所有存档都会生效。写回前会自动备份。',
    }),
    state.dataHost,
  ]);
}

async function loadData(render = true) {
  const host = state.dataHost || document.getElementById('ch-data');
  if (!host) return;
  if (render) host.textContent = '';
  let res;
  try {
    res = await getJSON('/api/cheats/data'
      + (state.data.filter ? `?file=${encodeURIComponent(state.data.filter)}` : ''));
  } catch (err) {
    host.textContent = '';
    host.append(el('div', { class: 'hint', text: err.message }));
    return;
  }
  state.data.fields = res.fields || [];
  state.data.files = res.files || [];
  if (render) renderData();
}

function renderData() {
  const host = state.dataHost || document.getElementById('ch-data');
  if (!host) return;
  host.textContent = '';

  const fileSel = el('select', {});
  fileSel.append(el('option', { value: '', text: '全部数据文件' }));
  for (const name of state.data.files) {
    fileSel.append(el('option', { value: name, text: name }));
  }
  fileSel.value = state.data.filter;
  fileSel.addEventListener('change', () => {
    state.data.filter = fileSel.value;
    loadData(true);
  });

  host.append(el('div', { class: 'row' }, [
    fileSel,
    el('span', { class: 'hint', text: `可编辑字段 ${state.data.fields.length} 项` }),
    el('span', { class: 'spacer' }),
    el('button', {
      class: 'btn sm primary', type: 'button', text: '写回数据表',
      disabled: !state.data.fields.length,
      onclick: () => writeData(),
    }),
  ]));

  if (!state.data.fields.length) {
    host.append(el('div', { class: 'empty', text: '先在上面读取游戏数据。' }));
    return;
  }

  const tbody = el('tbody', {});
  for (const item of state.data.fields) {
    let control;
    if (item.kind === 'bool') {
      const box = el('input', { type: 'checkbox' });
      box.checked = !!item.value;
      box.dataset.original = String(item.value);
      box.addEventListener('change', markDirty);
      control = box;
    } else {
      const input = el('input', {
        type: item.kind === 'int' ? 'number' : 'text',
        value: item.value === null || item.value === undefined ? '' : String(item.value),
      });
      input.dataset.original = String(item.value);
      input.addEventListener('input', markDirty);
      control = input;
    }
    control.dataset.file = item.file;
    control.dataset.path = item.path;
    control.dataset.kind = item.kind;

    tbody.append(el('tr', {}, [
      el('td', {}, [
        el('div', { text: item.name || '—' }),
        el('div', { class: 'hint mono', text: `${item.file} · ${item.path}` }),
      ]),
      el('td', { class: 'nowrap', text: item.label }),
      el('td', {}, [control]),
      el('td', { class: 'hint', text: kindLabel(item.kind) }),
    ]));
  }
  host.append(el('div', { class: 'table-wrap' }, [
    el('table', {}, [
      el('thead', {}, [el('tr', {}, [
        el('th', { text: '对象' }), el('th', { text: '字段' }),
        el('th', { text: '值' }), el('th', { text: '类型' }),
      ])]),
      tbody,
    ]),
  ]));
}

function kindLabel(kind) {
  return { int: '整数', bool: '开关', text: '文本' }[kind] || kind;
}

/** 收集改动过的字段（只发用户真的改了的，减少误覆盖面）。 */
function collectDataEdits() {
  const edits = [];
  for (const node of document.querySelectorAll('#ch-data [data-path]')) {
    const original = node.dataset.original;
    let value;
    if (node.type === 'checkbox') {
      value = node.checked;
      if (String(original) === String(value)) continue;
    } else {
      value = node.value;
      if (value === original) continue;
    }
    edits.push({
      file: node.dataset.file,
      path: node.dataset.path,
      kind: node.dataset.kind,
      value,
      original: node.type === 'checkbox' ? (original === 'true') : original,
    });
  }
  return edits;
}

async function writeData() {
  const edits = collectDataEdits();
  if (!edits.length) {
    toast('没有检测到改动', 'warn');
    return;
  }
  const game = (state.game && state.game.game_dir) || '（当前游戏）';
  const files = [...new Set(edits.map((e) => e.file))].join('、');
  const ok = await confirmDialog('确认写回游戏数据表？',
    `将修改 <span class="code">${escapeHTML(game)}</span> 下的 <b>${escapeHTML(files)}</b>`
    + `（共 ${edits.length} 个字段）。<br><br>`
    + '这些改动会作用于<b>所有存档</b>。写回前会自动备份到游戏目录下的「汉化备份_*」。',
    '确认写回');
  if (!ok) return;
  try {
    const res = await postJSON('/api/cheats/data', { edits, confirm: true });
    state.data.fields = res.fields || [];
    renderData();
    await loadBackups();
    toast(`写回完成：${res.stats.entries} 个字段`
      + (res.backup_dir ? '（已备份）' : ''), 'ok', 8000);
  } catch (err) {
    toast('写回失败：' + err.message, 'error', 15000);
  }
}


/* ---------------------------------------------------------------------------
 * 卡片 7：保存 / 备份 / 还原
 * ------------------------------------------------------------------------- */
function renderStatus() {
  const host = state.statusHost;
  if (!host) return;
  host.textContent = '';
  host.append(el('h2', {}, [el('span', { class: 'step', text: '✓' }),
    document.createTextNode('保存与备份')]));

  const saveBtn = el('button', { class: 'btn danger', type: 'button', text: '保存存档' });
  saveBtn.addEventListener('click', () => saveCurrent(saveBtn));

  const reloadBtn = el('button', { class: 'btn', type: 'button', text: '放弃改动并重新载入' });
  reloadBtn.addEventListener('click', async () => {
    if (!state.current) return;
    const ok = await confirmDialog('放弃改动？',
      '内存里未保存的修改会全部丢失，并重新从磁盘读取存档。', '放弃并重载');
    if (ok) loadSave(state.current);
  });

  host.append(el('div', { class: 'row' }, [
    el('span', {
      class: 'chip ' + (state.dirty ? 'warn' : ''),
      text: state.dirty ? '有未保存的改动' : '没有未保存的改动',
    }),
    el('span', { class: 'hint', text: state.current || '尚未载入存档' }),
    el('span', { class: 'spacer' }),
    reloadBtn, saveBtn,
  ]));
  if (!state.dirty) saveBtn.disabled = false;
  host.append(el('div', { class: 'hint', id: 'ch-policy',
    text: '写回原存档前会自动备份到游戏目录下的「汉化备份_*」，随时可以还原。' }));
  host.append(el('div', { id: 'ch-backups' }));
}

function markDirty() {
  state.dirty = true;
  renderStatus();
}

async function saveCurrent(button) {
  if (!state.current) { toast('请先载入一个存档', 'warn'); return; }
  const ok = await confirmDialog('确认写回原存档？',
    `将修改 <span class="code">${escapeHTML(state.current)}</span>。<br><br>`
    + '写回前会自动把将被修改的文件备份到游戏目录下的「汉化备份_*」，'
    + '保存后界面会显示备份位置。',
    '确认写回');
  if (!ok) return;
  button.disabled = true;
  try {
    const res = await postJSON('/api/cheats/save', { confirm: true });
    state.dirty = false;
    renderStatus();
    await loadBackups();
    showBackupPath(res);
    toast('存档已写回', 'ok', 6000);
  } catch (err) {
    toast('保存失败：' + err.message, 'error', 15000);
  } finally {
    button.disabled = false;
  }
}

/** 硬约束 §4.2：写回后必须展示备份路径。 */
function showBackupPath(res) {
  const host = document.getElementById('ch-backups');
  if (!host || !res || !res.backup_dir) return;
  const row = el('div', { class: 'row' }, [
    el('span', { class: 'hint', text: '本次备份位置' }),
    el('span', { class: 'code', text: res.backup_dir }),
    el('button', {
      class: 'btn sm', type: 'button', text: '打开备份目录',
      onclick: () => openInExplorer(res.backup_dir),
    }),
  ]);
  host.prepend(row);
}

async function loadBackups() {
  const host = document.getElementById('ch-backups');
  if (!host) return;
  let res;
  try {
    res = await getJSON('/api/cheats/backups');
  } catch (err) {
    return;
  }
  /* 保留"本次备份位置"那一行（它是 prepend 进去的） */
  const keep = host.querySelector('.row');
  const anchor = keep && keep.textContent.includes('本次备份位置') ? keep : null;
  host.textContent = '';
  if (anchor) host.append(anchor);

  const list = res.backups || [];
  if (!list.length) return;
  const tbody = el('tbody', {});
  for (const item of list) {
    tbody.append(el('tr', {}, [
      el('td', {}, [el('span', { class: 'code', text: item.name })]),
      el('td', { class: 'num', text: String(item.files) }),
      el('td', { class: 'nowrap', text: item.time }),
      el('td', {}, [item.has_manifest
        ? el('span', { class: 'tag ok', text: '可还原' })
        : el('span', { class: 'tag warn', text: '旧版备份' })]),
      el('td', {}, [el('button', {
        class: 'btn sm danger', type: 'button', text: '还原',
        onclick: () => restoreBackup(item),
      })]),
    ]));
  }
  host.append(el('hr', { class: 'divider' }));
  host.append(el('div', { class: 'hint', text: `备份列表（${list.length} 个，新的在前）` }));
  host.append(el('div', { class: 'table-wrap' }, [
    el('table', {}, [
      el('thead', {}, [el('tr', {}, [
        el('th', { text: '备份' }), el('th', { text: '文件数' }),
        el('th', { text: '时间' }), el('th', { text: '状态' }), el('th', { text: '操作' }),
      ])]),
      tbody,
    ]),
  ]));
}

async function restoreBackup(item) {
  const game = (state.game && state.game.game_dir) || '（当前游戏）';
  const ok = await confirmDialog('确认还原？',
    `将用备份 <span class="code">${escapeHTML(item.name)}</span> 覆盖 `
    + `<span class="code">${escapeHTML(game)}</span> 下的文件。<br><br>`
    + '当前状态会先被自动再备份一次 —— 所以「还原错了」还可以再还原回来。',
    '确认还原');
  if (!ok) return;
  try {
    const res = await postJSON('/api/cheats/restore', { dir: item.dir, confirm: true });
    toast(`还原完成：恢复 ${res.result.restored || 0} 个文件`, 'ok', 7000);
    if (state.current) await loadSave(state.current);
    await loadData(true);
  } catch (err) {
    toast('还原失败：' + err.message, 'error', 15000);
  }
}

async function openInExplorer(dir) {
  if (!dir) return;
  try {
    await postJSON('/api/cheats/open_dir', { dir });
  } catch (err) {
    toast('无法打开目录：' + err.message, 'warn');
  }
}

/* ---------------------------------------------------------------------------
 * 初始化 / 小工具
 * ------------------------------------------------------------------------- */
async function loadStatus() {
  try {
    const res = await getJSON('/api/cheats/status');
    state.actorAttrs = res.actor_attrs || [];
    state.itemKinds = res.item_kinds || [];
    if (res.game && res.game.opened) {
      state.game = res.game;
      applyEngineChips({ ok: true, game: res.game });
      await loadSaves();
      await loadData(true);
      /* 重新拉一次角色列表：切换页面回来时，下拉里要能直接改，
         否则用户得先"载入存档"才能看到角色（其实数据一直都在） */
      if (res.save_path) {
        const actors = await getJSON('/api/cheats/actors').catch(() => null);
        if (actors && actors.actors) renderActors(actors.actors);
      }
    }
  } catch (err) {
    /* 首屏失败不打扰用户；每个操作都会各自报错 */
  }
}

function fmtSize(bytes) {
  const n = Number(bytes || 0);
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

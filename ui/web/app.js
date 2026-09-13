/* ---------------------------------------------------------------------------
 * 应用外壳：导航、功能状态表、页面路由、诊断
 *
 * @feature  none
 * @layer    ui
 * @public   boot renderNav renderFeatureTable mountPage
 * @depends  dom.js
 * @tested   tools/check_footprint.py, tests/integration/test_web_syntax.py
 * @footprint docs/UI_SPEC.md#shell
 *
 * 关键设计（需求 §5.1「界面自动出现该功能的入口」）：
 *   1. 启动时 GET /api/nav 取导航 —— 后端由 features 下的 manifest.py 自动发现
 *   2. 点击导航项时动态 import(`/pages/${module}.js`) 并调用其 render(host)
 *   3. 因此新增功能 = 新增 features/<name>/ 目录 + 新增 ui/web/pages/<id>.js，
 *      本文件与 index.html 都**不需要修改**
 *
 * ⚠ 写注释时的硬规矩（**踩过一次，整个前端白屏**）：
 *   块注释里不得出现「星号紧跟斜杠」这个两字符序列。它会在块注释内部
 *   **提前闭合注释**，后面的散文就变成代码 —— 表现是模块解析失败、
 *   app.js 一行都不执行，页面永远停在「加载中…」，而且除了浏览器控制台
 *   之外没有任何提示。
 *   最典型的来源是**通配路径**：把「features 斜杠星号」与「斜杠 manifest.py」
 *   直接连写就会命中（本项目原先就是这么写的）。改用
 *   features/<name>/manifest.py，或者把星号换成「全部」二字，都能避开。
 *   这一条由 tests/integration/test_web_syntax.py 用 node --check 强制。
 * ------------------------------------------------------------------------- */

import { $, el, getJSON, postJSON, toast, escapeHTML } from './dom.js';

const state = { nav: [], pages: [], current: null, recent: [], module: null };

/** 需求 §3.3 要求收敛的三类重复实现（用于顶栏"收敛 x/3"指示）。 */
const CONVERGENCE_KEYS = ['engines', 'formats', 'marshal'];

/* ------------------------------------------------------------------ 启动 */
async function boot() {
  bindChrome();
  await Promise.all([loadHealth(), loadFeatures(), loadNav(), loadRecent()]);
  renderNav();
  renderRecent();
  renderFeatureTable();
  // 默认打开第一个功能页
  if (state.nav.length) {
    mountPage(state.nav[0].id);
  } else {
    $('#view').append(el('div', { class: 'empty', text: '没有已启用的功能模块。请检查 features/ 目录与 manifest.py。' }));
  }
}

function bindChrome() {
  $('#btn-refresh').addEventListener('click', async () => {
    await Promise.all([loadHealth(), loadFeatures(), loadNav(), loadRecent()]);
    renderNav();
    renderRecent();
    renderFeatureTable();
    if (state.current) mountPage(state.current);
    toast('状态已刷新', 'ok');
  });
  $('#btn-paths').addEventListener('click', () => showDiag('/api/paths'));
  $('#btn-health').addEventListener('click', () => showDiag('/api/health'));
  /* 功能页打开一个游戏后会派发 recent-changed —— 外壳据此刷新下拉。
     用事件而不是让页面直接调外壳函数：页面模块只依赖 dom.js 与 /api，
     不需要知道外壳长什么样（新增功能不必改外壳，这条是需求 §8-6 的证据）。 */
  document.addEventListener('recent-changed', () => {
    loadRecent().then(renderRecent).catch(() => {});
  });
}

/* ------------------------------------------------------------------ 数据加载 */
async function loadHealth() {
  try {
    const health = await getJSON('/api/health');
    $('#app-version').textContent = `v${health.app?.version || '?'} · Python ${health.python}`;
    const chips = $('#health-chips');
    chips.innerHTML = '';
    chips.append(
      el('span', { class: 'chip ' + (health.ok ? 'ok' : 'danger'), html: `状态 <b>${health.ok ? '正常' : '异常'}</b>` }),
      el('span', { class: 'chip', html: `功能 <b>${health.registry?.count ?? 0}</b>` }),
      el('span', { class: 'chip', html: `路由 <b>${health.ui?.routes ?? 0}</b>` }),
      el('span', { class: 'chip', html: `任务 <b>${health.jobs?.running ?? 0}/${health.jobs?.workers ?? 0}</b>` }),
      // M2b 收敛进度：需求 §3.3 要求三类重复实现各只剩一份。
      // 数据来自 /api/health 的 convergence 段 —— 让"是否收敛完"成为可观测事实，
      // 而不是只写在文档里。取代原先的"待收敛参考实现"计数（桥接层已删除）。
      el('span', {
        class: 'chip ' + (health.convergence?.all_merged ? 'ok' : 'warn'),
        html: `收敛 <b>${CONVERGENCE_KEYS
          .filter((k) => health.convergence?.[k] === 'merged').length}/${CONVERGENCE_KEYS.length}</b>`,
      }),
    );
  } catch (err) {
    $('#app-version').textContent = '无法连接服务';
    toast('健康检查失败：' + err.message, 'error');
  }
}

async function loadFeatures() {
  try {
    const payload = await getJSON('/api/features');
    state.features = payload;
  } catch (err) {
    state.features = { features: [], errors: [err.message] };
  }
  try {
    const payload = await getJSON('/api/pages');
    state.pages = payload.pages || [];
  } catch (err) {
    state.pages = [];
  }
}

async function loadNav() {
  try {
    const payload = await getJSON('/api/nav');
    state.nav = payload.items || [];
    state.disabledNav = payload.disabled || [];
  } catch (err) {
    state.nav = [];
    toast('导航加载失败：' + err.message, 'error');
  }
}

/* ------------------------------------------------------------------ 导航 */
function renderNav() {
  const host = $('#nav');
  host.innerHTML = '';
  if (!state.nav.length) {
    host.append(el('span', { class: 'hint', text: '未加载任何功能模块' }));
    return;
  }
  for (const item of state.nav) {
    const btn = el('button', {
      class: 'nav-item' + (state.current === item.id ? ' active' : ''),
      type: 'button',
      dataset: { feature: item.id },
      onclick: () => mountPage(item.id),
    }, [
      el('span', { class: 'icon', text: item.icon || '' }),
      el('span', { text: item.name }),
    ]);
    host.append(btn);
  }
  for (const id of (state.disabledNav || [])) {
    host.append(el('button', { class: 'nav-item disabled', type: 'button', disabled: true, text: `${id}（已禁用）` }));
  }
}

/* ------------------------------------------------------------------ 最近打开 */
async function loadRecent() {
  try {
    const payload = await getJSON('/api/recent');
    state.recent = payload.items || [];
    state.recentNote = payload.error || '';
  } catch (err) {
    state.recent = [];
    state.recentNote = '最近打开记录读取失败：' + err.message;
  }
}

/*: 哪个功能用过这个游戏（下拉里的小标签） */
const KIND_LABEL = { translate: '翻译', cheats: '改档' };

function renderRecent() {
  const host = $('#recent');
  if (!host) return;
  host.innerHTML = '';
  if (!state.recent.length) {
    host.append(el('span', { class: 'hint', text: '还没有打开过游戏' }));
    return;
  }
  const list = el('div', { class: 'dropdown-menu', id: 'recent-menu' });
  for (const item of state.recent) {
    const usable = item.exists !== false;
    const row = el('div', {
      class: 'dropdown-item' + (usable ? '' : ' disabled'),
      dataset: { path: item.path },
      title: usable ? item.path : `${item.path}（目录已不存在）`,
    }, [
      el('span', { class: 'grow', text: item.label || item.path }),
      item.engine ? el('span', { class: 'tag', text: item.engine }) : null,
      item.kind ? el('span', { class: 'tag', text: KIND_LABEL[item.kind] || item.kind }) : null,
      el('button', {
        class: 'btn sm ghost', type: 'button', text: '×',
        title: '从列表里移除（不动磁盘上的文件）',
        onclick: (ev) => { ev.stopPropagation(); forgetRecent(item.path); },
      }),
    ]);
    if (usable) row.addEventListener('click', () => openRecent(item.path));
    list.append(row);
  }
  list.append(el('div', { class: 'dropdown-sep' }));
  list.append(el('div', { class: 'dropdown-item' }, [
    el('button', {
      class: 'btn sm', type: 'button', text: '清理失效项',
      onclick: () => pruneRecent(),
    }),
    el('button', {
      class: 'btn sm danger', type: 'button', text: '全部清除',
      onclick: () => clearRecent(),
    }),
  ]));
  host.append(el('details', { class: 'dropdown', id: 'recent-dropdown' }, [
    el('summary', { class: 'nav-item' }, [
      el('span', { class: 'icon', text: '近' }),
      el('span', { text: `最近打开 (${state.recent.length})` }),
    ]),
    list,
  ]));
  if (state.recentNote) {
    host.append(el('span', { class: 'hint', text: state.recentNote }));
  }
}

/** 在当前功能页里打开这个游戏。
 *
 * 页面模块**可选**导出 ``openGame(path)``；没导出就明确告知，而不是静默失败 ——
 * 静默失败正是本工程反复踩到的那一类缺陷。 */
async function openRecent(path) {
  const module = state.module;
  if (!module || typeof module.openGame !== 'function') {
    toast('当前页面不支持从列表直接打开，请用页面上的「浏览…」选择目录', 'warn', 7000);
    return;
  }
  try {
    await module.openGame(path);
    const box = $('#recent-dropdown');
    if (box) box.open = false;
  } catch (err) {
    toast('打开失败：' + err.message, 'error', 10000);
  }
}

async function forgetRecent(path) {
  try {
    const res = await postJSON('/api/recent/forget', { path });
    state.recent = res.items || [];
    renderRecent();
  } catch (err) {
    toast('移除失败：' + err.message, 'error');
  }
}

async function pruneRecent() {
  try {
    const res = await postJSON('/api/recent/prune', {});
    state.recent = res.items || [];
    renderRecent();
    toast(res.removed ? `清理了 ${res.removed} 条失效记录` : '没有失效的记录', 'ok');
  } catch (err) {
    toast('清理失败：' + err.message, 'error');
  }
}

async function clearRecent() {
  try {
    const res = await postJSON('/api/recent/clear', {});
    state.recent = res.items || [];
    renderRecent();
    toast(res.removed ? `已清除 ${res.removed} 条记录` : '列表本来就是空的', 'ok');
  } catch (err) {
    toast('清除失败：' + err.message, 'error');
  }
}

/* ------------------------------------------------------------------ 功能状态表 */
function renderFeatureTable() {
  const body = $('#feature-rows');
  body.innerHTML = '';
  const features = (state.features && state.features.features) || [];
  if (!features.length) {
    body.append(el('tr', {}, [el('td', { colspan: 6, class: 'muted', text: '没有已加载的功能模块' })]));
  }
  for (const feature of features) {
    const health = feature.health || {};
    body.append(el('tr', {}, [
      el('td', { text: `${feature.icon || ''} ${feature.name}` }),
      el('td', {}, [el('span', { class: 'code', text: feature.id })]),
      el('td', { text: feature.version || '—' }),
      el('td', {}, [el('span', {
        class: 'tag ' + (feature.ok ? 'ok' : 'error'),
        text: feature.ok ? '已加载' : '加载失败',
      })]),
      el('td', { class: 'muted', text: feature.detail || '见 /api/health' }),
      el('td', { class: 'muted', text: (feature.pages || []).map((p) => p.id).join(', ') || '—' }),
    ]));
  }
  const errHost = $('#feature-errors');
  errHost.innerHTML = '';
  const errors = (state.features && state.features.errors) || [];
  for (const msg of errors) {
    errHost.append(el('div', { class: 'error-text', text: '⚠ ' + msg }));
  }
}

/* ------------------------------------------------------------------ 页面路由 */
async function mountPage(featureId) {
  const item = state.nav.find((x) => x.id === featureId);
  if (!item) return;
  state.current = featureId;
  renderNav();

  const host = $('#view');
  host.innerHTML = '';
  const page = (item.pages || [])[0];
  if (!page) {
    host.append(el('div', { class: 'empty', text: `功能 ${item.name} 未声明任何页面。` }));
    return;
  }
  try {
    const module = await import(`/pages/${page.module}.js`);
    if (typeof module.render !== 'function') {
      throw new Error(`页面模块 ${page.module}.js 未导出 render(host)`);
    }
    // 记住当前模块：外壳的「最近打开」下拉要靠它的 openGame(path) 打开游戏。
    // 切页时先清空，避免"点最近打开却在上一个页面里执行"。
    state.module = module;
    await module.render(host, { nav: item, features: state.features });
  } catch (err) {
    state.module = null;
    host.append(el('div', { class: 'card' }, [
      el('h2', { text: `页面加载失败：${page.title}` }),
      el('div', { class: 'error-text', text: err.message }),
      el('div', { class: 'hint', text: `期望文件：ui/web/pages/${page.module}.js，需导出 render(host, ctx)` }),
    ]));
    toast('页面加载失败：' + err.message, 'error');
  }
}

/* ------------------------------------------------------------------ 诊断面板 */
async function showDiag(path) {
  const out = $('#diag-out');
  try {
    const payload = await getJSON(path);
    out.textContent = JSON.stringify(payload, null, 2);
    out.style.display = 'block';
  } catch (err) {
    out.textContent = '请求失败：' + err.message;
    out.style.display = 'block';
  }
}

/* ------------------------------------------------------------------ go */
window.addEventListener('DOMContentLoaded', () => {
  boot().catch((err) => {
    document.body.append(el('div', { class: 'card', style: { margin: '16px' } }, [
      el('h2', { text: '启动失败' }),
      el('div', { class: 'error-text', text: err && err.message ? err.message : String(err) }),
    ]));
  });
});

export { boot, renderNav, renderFeatureTable, mountPage, renderRecent, escapeHTML };

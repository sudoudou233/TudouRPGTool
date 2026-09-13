/* ---------------------------------------------------------------------------
 * 前端冒烟探针：在 Node 里用最小 DOM shim **真实执行** ui/web 的前端代码
 *
 * @feature  none
 * @layer    tools
 * @public   (CLI：node tools/web_probe.mjs <baseUrl> <webDir> [--json])
 * @depends  ui/web/index.html, ui/web/app.js, /api/*
 * @tested   tests/integration/test_web_syntax.py
 * @footprint docs/UI_SPEC.md
 *
 * 为什么需要它（**踩过一次，整个前端白屏**）
 * ----------------------------------------
 * ui/web/app.js 的块注释里出现过「星号紧跟斜杠」的两字符序列（来源是
 * 通配路径 `features/*` + `/manifest.py` 被写在一起）。它在注释内部**提前
 * 闭合了注释**，后面的散文变成代码 → 模块解析失败 → app.js 一行都不执行
 * → 页面永远停在「加载中…」。
 *
 * 而当时全部 800+ 测试都是**文本断言**（"文件里有 export render"、
 * "调用了某个端点"），**没有任何一条真的解析或执行过这些 js**。这个缺口
 * 就是白屏能一路发到用户手里的原因。
 *
 * 本探针补上这一层：把 index.html 建成最小 DOM，按真实路径加载并执行
 * app.js（静态 import 改成可链接的模块图，动态 import 改成同样的加载器），
 * 打真实接口，最后报告 DOM 是否从「加载中…」变成了可交互内容。
 *
 * 用法
 * ----
 *   node tools/web_probe.mjs http://127.0.0.1:8802 ui/web            # 人读
 *   node tools/web_probe.mjs http://127.0.0.1:8802 ui/web --json     # 机器读
 *
 * 需要 Node（可选依赖）：没装 Node 时测试会 skip，而不是失败 ——
 * 本工程的主体约束是"零第三方依赖（Python 标准库）"，Node 只用于这层
 * 前端冒烟，不是运行必需。
 * ------------------------------------------------------------------------- */

import { readFile } from 'node:fs/promises';
import vm from 'node:vm';

const BASE = (process.argv[2] || 'http://127.0.0.1:8793').replace(/\/$/, '');
const WEB = process.argv[3] || 'ui/web';
const AS_JSON = process.argv.includes('--json');
/* --game <目录>：可选。给了就**真的驱动修改页**（填目录 → 点读取 →
   点载入），然后统计道具列表里渲染出来的图标格。这是"图标真的显示出来"
   的唯一硬证据 —— 光断言端点存在证明不了界面画对了。 */
const GAME = (() => {
  const i = process.argv.indexOf('--game');
  return i >= 0 ? (process.argv[i + 1] || '') : '';
})();

/* ---------------------------------------------------------------- DOM shim */
class N {
  constructor(tag, doc) {
    this.tagName = String(tag).toUpperCase();
    this.ownerDocument = doc;
    this.childNodes = [];
    this.attributes = {};
    this.dataset = {};
    this.style = {};
    this._text = '';
    this._html = '';
    this._listeners = {};
  }
  get className() { return this.attributes.class || ''; }
  set className(v) { this.attributes.class = v; }
  get children() { return this.childNodes.filter((c) => c instanceof N); }
  get isConnected() { return true; }
  append(...nodes) {
    for (const n of nodes) {
      if (n === null || n === undefined) continue;
      this.childNodes.push(n);
      if (n instanceof N) n.parentNode = this;
    }
  }
  appendChild(n) { this.append(n); return n; }
  prepend(n) { this.childNodes.unshift(n); if (n instanceof N) n.parentNode = this; }
  remove() {
    const p = this.parentNode;
    if (p) p.childNodes = p.childNodes.filter((c) => c !== this);
  }
  setAttribute(k, v) { this.attributes[k] = v; }
  getAttribute(k) { return this.attributes[k]; }
  addEventListener(type, fn) { (this._listeners[type] ||= []).push(fn); }
  /* 真的"点一下"：把注册过的监听器按顺序调用。
     有了它，探针就能驱动界面（填目录 → 点读取 → 点载入），
     而不是只能断言"卡片渲染出来了" —— 见下面的 --game 流程。 */
  dispatchEvent(event) {
    const type = (event && event.type) || 'click';
    for (const fn of (this._listeners[type] || [])) fn(event || { type, target: this });
    return true;
  }
  click() { return this.dispatchEvent({ type: 'click', target: this }); }
  /* 表单控件的值：真实 DOM 里 .value / .checked 是 property，
     没设过时才回落到同名 attribute（也就是"默认值"）。这里照同样的语义。 */
  get value() {
    if (this._value !== undefined) return this._value;
    const attr = this.attributes.value;
    return attr === undefined ? '' : String(attr);
  }
  set value(v) { this._value = String(v); }
  get checked() {
    if (this._checked !== undefined) return this._checked;
    return 'checked' in this.attributes;
  }
  set checked(v) { this._checked = !!v; }
  querySelector(sel) { return this._findAll(sel)[0] || null; }
  querySelectorAll(sel) { return this._findAll(sel); }
  _matches(sel) {
    if (sel.startsWith('#')) return this.attributes.id === sel.slice(1);
    if (sel.startsWith('.')) {
      return (this.attributes.class || '').split(/\s+/).includes(sel.slice(1));
    }
    if (sel.startsWith('[')) {
      const m = /^\[([\w-]+)(?:="([^"]*)")?\]$/.exec(sel);
      if (!m) return false;
      if (m[2] === undefined) return m[1] in this.dataset || m[1] in this.attributes;
      return this.dataset[m[1]] === m[2];
    }
    return this.tagName === sel.toUpperCase();
  }
  _findAll(sel) {
    const parts = sel.split(',').map((s) => s.trim()).filter(Boolean);
    const out = [];
    const walk = (n) => {
      for (const c of n.childNodes) {
        if (!(c instanceof N)) continue;
        if (parts.some((p) => c._matches(p))) out.push(c);
        walk(c);
      }
    };
    walk(this);
    return out;
  }
  get textContent() {
    let s = this._text;
    for (const c of this.childNodes) s += c instanceof N ? c.textContent : String(c);
    return s;
  }
  set textContent(v) { this.childNodes = []; this._text = String(v); }
  get innerHTML() { return this._html; }
  set innerHTML(v) { this.childNodes = []; this._html = String(v); }
}

class Doc extends N {
  constructor() { super('#document', null); this.ownerDocument = this; }
  createElement(tag) { return new N(tag, this); }
  createTextNode(t) { return String(t); }
  getElementById(id) {
    let found = null;
    const walk = (n) => {
      for (const c of n.childNodes) {
        if (!(c instanceof N)) continue;
        if (!found && c.attributes.id === id) found = c;
        walk(c);
      }
    };
    walk(this);
    return found;
  }
  get body() {
    if (!this._body) { this._body = new N('body', this); this.childNodes.push(this._body); }
    return this._body;
  }
  get documentElement() { return this; }
}

/* 从真实 index.html 建初始 DOM（只用到 id 挂载点 —— 页面模块也只依赖这个） */
const html = await readFile(`${WEB}/index.html`, 'utf8');
const doc = new Doc();
for (const m of html.matchAll(/<(\w+)([^>]*\bid="([^"]+)"[^>]*)>/g)) {
  const node = new N(m[1], doc);
  node.setAttribute('id', m[3]);
  doc.body.append(node);
}

/* ---------------------------------------------------------------- globals */
const pageProblems = [];
const sandboxConsole = {
  log: () => {},
  debug: () => {},
  warn: (...a) => { pageProblems.push('warn: ' + a.join(' ')); },
  error: (...a) => { pageProblems.push('error: ' + a.join(' ')); },
};
const realFetch = globalThis.fetch;
const calls = [];
const pageFetch = async (url, init) => {
  const full = String(url).startsWith('http') ? String(url) : BASE + String(url);
  calls.push(((init && init.method) || 'GET') + ' ' + String(url));
  return realFetch(full, init);
};

const listeners = {};
const win = {
  addEventListener: (t, fn) => { (listeners[t] ||= []).push(fn); },
  fetch: pageFetch,
  console: sandboxConsole,
  setTimeout, clearTimeout, queueMicrotask,
  document: doc,
  location: { href: BASE + '/', origin: BASE },
};

globalThis.document = doc;
globalThis.window = win;
globalThis.fetch = pageFetch;
globalThis.Node = N;

/* ------------------------------------------------- 模块加载器（按文件路径） */
const nsCache = new Map();
const rawModules = new Map();

function ensureModule(norm) {
  if (rawModules.has(norm)) return rawModules.get(norm);
  const promise = (async () => {
    const src = await readFile(norm, 'utf8');
    const deps = [...src.matchAll(/from\s+'([^']+)'/g)].map((m) => m[1]);
    const resolved = {};
    for (const spec of deps) {
      const depPath = spec.startsWith('/')
        ? `${WEB}${spec}`
        : new URL(spec, 'file:///' + norm).pathname.replace(/^\//, '');
      resolved[spec] = await ensureModule(depPath.replace(/\\/g, '/'));
    }
    let code = src;
    for (const spec of deps) {
      code = code.split(`from '${spec}'`).join(`from ${JSON.stringify('dsh:' + spec)}`);
    }
    code = code.replace(/import\(`\/pages\/\$\{([^}]+)\}\.js`\)/g,
      'globalThis.__dynImport($1)');
    globalThis.__dynImport = async (name) =>
      (await ensureModule(`${WEB}/pages/${name}.js`)).namespace;
    const mod = new vm.SourceTextModule(code, { context: vm.createContext(globalThis) });
    // ⚠ link 的回调必须返回 **Module 实例**（不是 namespace）——
    // 返回 namespace 会抛 "Provided module is not an instance of Module"
    await mod.link(async (spec) => resolved[spec.replace(/^dsh:/, '')]);
    await mod.evaluate();
    nsCache.set(norm, mod.namespace);
    return mod;
  })();
  rawModules.set(norm, promise);
  return promise;
}

const loadModule = async (path) => (await ensureModule(path.replace(/\\/g, '/'))).namespace;

/* ------------------------------------------------------------------- 跑 */
const report = {
  base: BASE, fatal: null, pages: {}, nav: [], featureRows: 0,
  appVersion: '', calls: 0, problems: [],
};

try {
  await loadModule(`${WEB}/app.js`);
  for (const fn of (listeners.DOMContentLoaded || [])) await fn();
  await new Promise((r) => setTimeout(r, 2000));
} catch (err) {
  report.fatal = `${err.constructor.name}: ${err.message}`;
}

const navNode = doc.getElementById('nav');
report.nav = navNode ? navNode.children.map((c) => c.textContent.trim()) : [];
const rows = doc.getElementById('feature-rows');
report.featureRows = rows ? rows.children.length : 0;
const ver = doc.getElementById('app-version');
report.appVersion = ver ? ver.textContent : '';
const view = doc.getElementById('view');
report.viewCards = view ? view.children.length : 0;
report.viewText = view ? view.textContent.slice(0, 160) : '';
report.calls = calls.length;
report.problems = pageProblems;

/* 逐个切换页面：验证每个功能页都能真的渲染出卡片 */
for (const id of ['translate', 'cheats', 'selfcheck']) {
  try {
    await loadModule(`${WEB}/app.js`).then((m) => m.mountPage(id));
    await new Promise((r) => setTimeout(r, 600));
    const host = doc.getElementById('view');
    const cards = host ? host.children.length : 0;
    const text = host ? host.textContent : '';
    report.pages[id] = {
      cards,
      failed: text.includes('页面加载失败'),
      // 卡片里应当有实质内容（不是空白页）
      chars: text.length,
    };
  } catch (err) {
    report.pages[id] = { cards: 0, failed: true, error: `${err.constructor.name}: ${err.message}` };
  }
}

/* --------------------------------------------------- 可选：真的驱动修改页 */
/** 等到 fn() 为真，或超时。比固定 sleep 稳（慢机器上不会假失败）。 */
async function waitFor(fn, timeoutMs = 15000, stepMs = 100) {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    let ok = false;
    try { ok = !!fn(); } catch (err) { ok = false; }
    if (ok) return true;
    if (Date.now() > deadline) return false;
    await new Promise((r) => setTimeout(r, stepMs));
  }
}

/** 等到 fn() 的返回值**连续 3 次不变**，再返回那个值。
 *
 * ⚠ 为什么不能只等"第一格出现"：渲染是同步的一大段 append，但只要
 * ``waitFor(数量 > 0)`` 一返回就立刻去数，就可能数到**建了一半的表格**
 * —— 本探针实测把 46 个数成了 45，于是"逐行对齐"报了假失败。
 * 断言渲染结果之前，必须先确认它不再变了。 */
async function waitStable(fn, timeoutMs = 15000, stepMs = 100) {
  const deadline = Date.now() + timeoutMs;
  let last;
  let same = 0;
  for (;;) {
    let current;
    try { current = fn(); } catch (err) { current = null; }
    if (current === last) {
      same += 1;
      if (same >= 3) return current;
    } else {
      last = current;
      same = 1;
    }
    if (Date.now() > deadline) return last;
    await new Promise((r) => setTimeout(r, stepMs));
  }
}

/** 递归收集整棵子树的节点（按谓词过滤）。 */
function collect(node, pred, out = []) {
  for (const c of node.childNodes) {
    if (!(c instanceof N)) continue;
    if (pred(c)) out.push(c);
    collect(c, pred, out);
  }
  return out;
}

if (GAME) {
  const icon = { game: GAME, steps: [], ok: false, error: null };
  try {
    await loadModule(`${WEB}/app.js`).then((m) => m.mountPage('cheats'));
    await new Promise((r) => setTimeout(r, 400));

    const view = doc.getElementById('view');
    const dirInput = doc.getElementById('ch-dir');
    const openBtn = doc.getElementById('ch-open');
    icon.steps.push(`填目录输入框=${!!dirInput} 读取按钮=${!!openBtn}`);
    dirInput.value = GAME;
    openBtn.click();

    const gotSaves = await waitFor(() => doc.getElementById('ch-load-0'));
    icon.steps.push(`存档载入按钮出现=${gotSaves}`);
    if (gotSaves) {
      const toggle = doc.getElementById('ch-icon-toggle');
      const hint = doc.getElementById('ch-icon-hint');
      icon.togglePresent = !!toggle;
      icon.toggleDisabled = !!(toggle && toggle.disabled);
      icon.toggleChecked = !!(toggle && toggle.checked);
      icon.hint = hint ? hint.textContent : '';

      doc.getElementById('ch-load-0').click();
      // ⚠ 用 class **分词**判断，不能用 `attributes.class === 'icon-cell'`：
      // "空位"格是 `icon-cell blank`，等值比较会把它整类漏掉（本探针第一版
      // 就漏了 2 个，把 43 报成了 41）。
      const isIconCell = (n) => String(n.attributes.class || '')
        .split(/\s+/).includes('icon-cell');
      const isBlank = (n) => String(n.attributes.class || '')
        .split(/\s+/).includes('blank');
      const gotItems = await waitFor(
        () => collect(view, isIconCell).length > 0);
      // 再等到表格不再增长，才敢数格子（否则会数到建了一半的表）
      await waitStable(() => collect(doc.getElementById('ch-items'),
        (n) => n.tagName === 'TR').length);
      const cells = collect(view, isIconCell);
      const blanks = cells.filter(isBlank);
      const real = cells.filter((c) => !isBlank(c) && c.style.backgroundImage);
      const rowsInTable = collect(doc.getElementById('ch-items'),
        (n) => n.tagName === 'TR').length;
      const headRows = collect(doc.getElementById('ch-items'),
        (n) => n.tagName === 'THEAD').length;
      const bodyRows = collect(doc.getElementById('ch-items'),
        (n) => n.tagName === 'TBODY').length;
      icon.heads = headRows;
      icon.bodies = bodyRows;
      icon.steps.push(`道具表出现图标格=${gotItems}`);
      icon.cells = cells.length;
      icon.realCells = real.length;
      icon.blankCells = blanks.length;
      icon.blankTitles = blanks.slice(0, 4).map((c) => c.attributes.title);
      // 每一行都该有一个图标格（表格里还有 1 行表头）
      icon.tableRows = rowsInTable;
      icon.cellsMatchRows = cells.length === rowsInTable - headRows;
      icon.sample = real.slice(0, 3).map((c) => ({
        pos: c.style.backgroundPosition,
        size: `${c.style.width}x${c.style.height}`,
        url: c.style.backgroundImage,
        title: c.attributes.title,
      }));
      // 关掉开关：应当只剩 class 变化，图标格还在（不重建表格）
      const itemsHost = doc.getElementById('ch-items');
      toggle.checked = false;
      toggle.dispatchEvent({ type: 'change' });
      icon.hiddenClassWhenOff = itemsHost.className;
      icon.cellsAfterToggle = collect(view, isIconCell).length;
      toggle.checked = true;
      toggle.dispatchEvent({ type: 'change' });
      icon.classWhenOn = itemsHost.className;
      icon.ok = gotItems;
    }
  } catch (err) {
    icon.error = `${err.constructor.name}: ${err.message}`;
  }
  report.iconFlow = icon;
}

if (AS_JSON) {
  console.log(JSON.stringify(report));
} else {
  console.log('base        :', report.base);
  console.log('app-version :', JSON.stringify(report.appVersion));
  console.log('导航项      :', report.nav.length, report.nav.join(' / '));
  console.log('功能表行    :', report.featureRows);
  console.log('默认页卡片  :', report.viewCards, JSON.stringify(report.viewText.slice(0, 80)));
  for (const [id, info] of Object.entries(report.pages)) {
    console.log(`页面 ${id.padEnd(10)}: 卡片 ${info.cards}  文案 ${info.chars} 字  失败=${info.failed}`);
  }
  console.log('网络调用    :', report.calls);
  if (report.iconFlow) {
    const f = report.iconFlow;
    console.log('图标流程    :', f.ok ? '成功' : '未完成', f.error || '');
    (f.steps || []).forEach((s) => console.log('              ', s));
    console.log('              开关：存在=%s 禁用=%s 打开=%s'
      , f.togglePresent, f.toggleDisabled, f.toggleChecked);
    console.log('              提示：%s', f.hint);
    console.log('              图标格 %d 个（真图标 %d，空位 %d）'
      , f.cells, f.realCells, f.blankCells);
    console.log('              表格 %d 张（表头行 %d），tr 合计 %d，图标格逐一对应数据行=%s'
      , f.bodies, f.heads, f.tableRows, f.cellsMatchRows);
    (f.blankTitles || []).forEach((t) => console.log('              空位 %s', t));
    (f.sample || []).forEach((s) => console.log('              样例 %s %s %s'
      , s.pos, s.size, s.title));
    console.log('              关掉后 class=%j，图标格仍 %d 个（不重建表格）'
      , f.hiddenClassWhenOff, f.cellsAfterToggle);
    console.log('              打开后 class=%j', f.classWhenOn);
  }
  if (report.fatal) console.log('!! 致命错误 :', report.fatal);
  report.problems.forEach((p) => console.log('页面告警    :', p));
}

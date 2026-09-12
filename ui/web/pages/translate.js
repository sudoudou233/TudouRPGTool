/* ---------------------------------------------------------------------------
 * 文本翻译功能页 —— 扫描 / 编辑 / 批量翻译 / 生成汉化版 / 备份还原
 *
 * @feature  translate
 * @layer    ui
 * @public   render
 * @depends  /dom.js, /api/translate/*, /api/job, /api/cancel
 * @tested   tests/integration/test_translate_page.py（静态契约）
 * @footprint docs/UI_SPEC.md
 *
 * 迁移来源：rpgmaker_translation_tool/web/index.html:86-253 的四张卡片
 * （选目录 / 扫描 / 翻译设置 / 生成汉化版）。行为对齐点：
 *   * 扫描的 4 个内容开关（注释 / 备注 / 事件名 / 动画名）
 *   * 4 个翻译引擎 + 接口自检按钮
 *   * 生成汉化版分"写副本（默认）"与"覆盖原游戏（危险）"，覆盖必须二次确认
 *   * 备份列表可还原，且还原前自动再备份
 *
 * 硬约束（docs/UI_SPEC.md §5）：
 *   * 长任务一律 waitJob + 进度条 + 取消按钮，**取消后界面立即可用**
 *   * 破坏性操作 confirmDialog，并在文案里写明"改哪些文件、备份在哪里"
 *   * 默认零破坏：默认只写副本，覆盖原游戏是高级选项
 *   * 页面不得写具体颜色值，只用 tokens.css 令牌与 components.css 的类
 *
 * 为什么用模块级 state 而不是闭包变量：``render(host)`` 每次切换页面都会被
 * 重新调用，而列表/备份这些区域要能"局部重绘"。把状态放模块级，
 * 重绘函数（reload / loadBackups）就不需要层层传递引用。
 * ------------------------------------------------------------------------- */

import {
  el, getJSON, postJSON, toast, confirmDialog, waitJob,
  fmtDuration, pct, escapeHTML,
} from '/dom.js';

/** 每页条目数（与后端 DEFAULT_PAGE_SIZE 一致） */
const PAGE_SIZE = 80;

/** 条目状态 → 中文标签 + 样式类（后端返回 pending/translated/skipped/error） */
const STATUS = {
  pending: { label: '待翻译', cls: 'pending' },
  translated: { label: '已翻译', cls: 'translated' },
  skipped: { label: '已跳过', cls: 'skipped' },
  error: { label: '出错', cls: 'error' },
};

/** 语言代码 → 下拉显示名 */
const LANGS = [
  ['auto', '自动检测'], ['ja', '日语'], ['en', '英语'], ['ko', '韩语'],
  ['zh-CN', '简体中文'], ['zh-TW', '繁体中文'],
];

/** 需要填写接口地址与模型名的引擎 */
const NEED_ENDPOINT = ['openai', 'ollama'];

const state = {
  session: null,
  providers: [],
  config: {},
  options: {
    include_comments: false,
    include_notes: false,
    include_event_names: false,
    include_animations: true,
  },
  query: { q: '', category: '', status: '', page: 1 },
  page: { entries: [], total: 0, page: 1, pages: 1 },
  jobHost: null,
};

export async function render(host) {
  state.query = { q: '', category: '', status: '', page: 1 };

  host.append(buildDirCard());
  host.append(buildScanCard());
  host.append(buildSettingsCard());
  host.append(buildBuildCard());

  state.jobHost = el('section', { class: 'card' });
  host.append(state.jobHost);

  await loadProviders();
  await loadConfig();
  await refreshSession();
}

/* ---------------------------------------------------------------------------
 * 卡片 1：游戏目录
 * ------------------------------------------------------------------------- */
function buildDirCard() {
  const dirInput = el('input', {
    type: 'text', id: 'tr-dir', placeholder: '例如 D:\\games\\我的游戏',
  });
  dirInput.value = (state.session && state.session.game_dir) || state.config.last_game_dir || '';

  const browseBtn = el('button', { class: 'btn', type: 'button', text: '浏览…' });
  browseBtn.addEventListener('click', async () => {
    browseBtn.disabled = true;
    try {
      const res = await postJSON('/api/translate/pick_folder', { initial: dirInput.value });
      if (res.cancelled || !res.dir) return;
      dirInput.value = res.dir;
      await openDir(res.dir);
    } catch (err) {
      /* 没有图形环境（远程/精简 Python）时会走到这里 —— 引导用户粘贴路径 */
      toast('无法打开系统对话框：' + err.message + '（可直接粘贴路径）', 'warn', 8000);
    } finally {
      browseBtn.disabled = false;
    }
  });

  const openBtn = el('button', { class: 'btn primary', type: 'button', text: '打开并识别' });
  openBtn.addEventListener('click', () => openDir(dirInput.value.trim()));

  return el('section', { class: 'card' }, [
    el('h2', {}, [el('span', { class: 'step', text: '1' }),
      document.createTextNode('游戏目录')]),
    el('div', {
      class: 'card-sub',
      text: '选择 RPG Maker 游戏根目录，工具会自动识别引擎并定位数据目录。默认只写副本，不动原文件。',
    }),
    el('div', { class: 'row' }, [dirInput, browseBtn, openBtn]),
    el('div', { class: 'chips', id: 'tr-engine' }),
  ]);
}

async function openDir(dir) {
  if (!dir) { toast('请先选择游戏目录', 'warn'); return; }
  try {
    const res = await postJSON('/api/translate/open', { dir });
    applySession(res.session);
    toast(res.cached_entries > 0
      ? `已载入上次的扫描结果（${res.cached_entries} 条），可直接继续`
      : '已识别引擎，请点击「扫描文本」', 'ok');
    await reload();
  } catch (err) {
    toast('打开失败：' + err.message, 'error');
  }
}

/** 把会话信息渲染到引擎胶囊区（任何会改变会话的操作后都应调用）。 */
function applySession(session) {
  state.session = session || null;
  const host = document.getElementById('tr-engine');
  if (!host) return;
  host.textContent = '';
  if (!session || !session.loaded) {
    host.append(el('span', { class: 'chip', text: '尚未识别引擎' }));
    return;
  }
  host.append(el('span', { class: 'chip ok', html: `引擎 <b>${escapeHTML(session.engine || '?')}</b>` }));
  host.append(el('span', { class: 'chip', html: `${escapeHTML(session.summary || session.label || '')}` }));
  const c = session.counts;
  if (c) {
    host.append(el('span', { class: 'chip', html: `共 <b>${c.total}</b> 条` }));
    host.append(el('span', { class: 'chip ok', html: `已译 <b>${c.translated}</b>` }));
    host.append(el('span', { class: 'chip', html: `待译 <b>${c.pending}</b>` }));
    if (c.skipped) host.append(el('span', { class: 'chip', html: `已跳过 <b>${c.skipped}</b>` }));
    if (c.error) host.append(el('span', { class: 'chip danger', html: `出错 <b>${c.error}</b>` }));
  }
}

async function refreshSession() {
  try {
    const res = await getJSON('/api/translate/state');
    applySession(res.session);
    if (res.session && res.session.loaded) await reload();
  } catch (err) {
    /* 首屏读取失败不打扰用户；后续每个操作都会各自报错 */
  }
}

/* ---------------------------------------------------------------------------
 * 卡片 2：扫描 + 文本列表
 * ------------------------------------------------------------------------- */
function buildScanCard() {
  const optsHost = el('div', { class: 'row' });
  const boxes = {};
  for (const [key, label] of [
    ['include_comments', '提取注释（108 指令）'],
    ['include_notes', '提取备注 / 描述'],
    ['include_event_names', '提取事件名'],
    ['include_animations', '提取动画名'],
  ]) {
    const box = el('input', { type: 'checkbox' });
    box.checked = !!state.options[key];
    boxes[key] = box;
    optsHost.append(el('label', { class: 'check' }, [box, document.createTextNode(label)]));
  }

  const scanBtn = el('button', { class: 'btn primary', type: 'button', text: '扫描文本' });
  scanBtn.addEventListener('click', async () => {
    const dir = (document.getElementById('tr-dir') || {}).value;
    if (!dir) { toast('请先选择游戏目录', 'warn'); return; }
    for (const key of Object.keys(boxes)) state.options[key] = boxes[key].checked;
    scanBtn.disabled = true;
    try {
      const opened = await postJSON('/api/translate/open', { dir: dir.trim() });
      applySession(opened.session);
      const res = await postJSON('/api/translate/scan', { dir: dir.trim(), options: state.options });
      const job = await runJob(res.job, '扫描文本');
      if (job.status === 'done') toast(`扫描完成：${(job.result || {}).total || 0} 条`, 'ok');
      await reload();
    } catch (err) {
      toast('扫描失败：' + err.message, 'error', 12000);
    } finally {
      scanBtn.disabled = false;
    }
  });

  const skipBtn = el('button', { class: 'btn sm', type: 'button', text: '把待翻译全部标记为跳过' });
  skipBtn.addEventListener('click', async () => {
    const scope = state.query.category ? `类别「${state.query.category}」中的` : '所有';
    const ok = await confirmDialog('全部标记为跳过？',
      `当前筛选下${scope}<b>待翻译</b>条目会被标记为「已跳过」，之后不再送去翻译。<br>` +
      '此操作可以逐条改回「待翻译」。');
    if (!ok) return;
    try {
      const res = await postJSON('/api/translate/skip_all', {
        category: state.query.category, status: 'pending',
      });
      await runJob(res.job, '标记跳过');
      toast('已标记跳过', 'ok');
      await reload();
    } catch (err) {
      toast('标记失败：' + err.message, 'error');
    }
  });

  return el('section', { class: 'card' }, [
    el('h2', {}, [el('span', { class: 'step', text: '2' }),
      document.createTextNode('扫描与文本列表')]),
    el('div', {
      class: 'card-sub',
      text: '提取游戏内全部可翻译文本。结果保存在会话文件里 —— 关掉工具再打开同一游戏可以继续（断点续传）。',
    }),
    optsHost,
    el('div', { class: 'row' }, [scanBtn, skipBtn]),
    el('div', { id: 'tr-list' }),
  ]);
}

async function reload() {
  const host = document.getElementById('tr-list');
  if (!host) return;
  const params = new URLSearchParams({
    q: state.query.q,
    category: state.query.category,
    status: state.query.status,
    page: String(state.query.page),
    size: String(PAGE_SIZE),
  });
  try {
    state.page = await getJSON('/api/translate/entries?' + params.toString());
  } catch (err) {
    host.textContent = '';
    host.append(el('div', { class: 'error-text', text: '读取列表失败：' + err.message }));
    return;
  }
  renderList(host);
  try {
    applySession((await getJSON('/api/translate/state')).session);
  } catch (err) {
    /* 计数刷新失败不影响列表使用 */
  }
}

function renderList(host) {
  host.textContent = '';

  /* ---- 过滤条 ---- */
  const qInput = el('input', {
    type: 'text', placeholder: '搜索原文 / 译文 / 备注', value: state.query.q,
  });
  const catSel = el('select', {});
  catSel.append(el('option', { value: '', text: '全部类别' }));
  const categories = (state.session && state.session.categories) || {};
  for (const name of Object.keys(categories).sort()) {
    catSel.append(el('option', { value: name, text: `${name}（${categories[name]}）` }));
  }
  catSel.value = state.query.category;

  const stSel = el('select', {});
  stSel.append(el('option', { value: '', text: '全部状态' }));
  for (const [key, spec] of Object.entries(STATUS)) {
    stSel.append(el('option', { value: key, text: spec.label }));
  }
  stSel.value = state.query.status;

  const applyQuery = () => {
    state.query.q = qInput.value.trim();
    state.query.category = catSel.value;
    state.query.status = stSel.value;
    state.query.page = 1;
    reload();
  };
  qInput.addEventListener('keydown', (ev) => { if (ev.key === 'Enter') applyQuery(); });
  catSel.addEventListener('change', applyQuery);
  stSel.addEventListener('change', applyQuery);

  host.append(el('hr', { class: 'divider' }));
  host.append(el('div', { class: 'row' }, [
    qInput, catSel, stSel,
    el('button', { class: 'btn sm', type: 'button', text: '筛选', onclick: applyQuery }),
    el('span', {
      class: 'hint',
      text: `共 ${state.page.total} 条 · 第 ${state.page.page}/${state.page.pages} 页`,
    }),
  ]));

  if (!state.page.entries.length) {
    host.append(el('div', {
      class: 'empty',
      text: (state.session && state.session.loaded)
        ? '没有符合条件的条目'
        : '还没有扫描结果 —— 先选择游戏目录并点击「扫描文本」',
    }));
    return;
  }

  /* ---- 列表 ---- */
  const tbody = el('tbody', {});
  for (const entry of state.page.entries) {
    const key = `${entry.file}|${entry.path}`;
    const input = el('input', { type: 'text', value: entry.translated || '' });
    const rowSave = (status) => saveEntry(key, input.value, status);
    input.addEventListener('keydown', (ev) => {
      if (ev.key === 'Enter') rowSave(entry.status === 'pending' ? 'translated' : entry.status);
    });

    tbody.append(el('tr', {}, [
      el('td', { class: 'nowrap' }, [statusTag(entry.status)]),
      el('td', {}, [
        el('div', { class: 'nowrap', text: entry.category || '' }),
        el('div', { class: 'hint mono', text: `${entry.file} · ${entry.path}` }),
        entry.note ? el('div', { class: 'hint', text: entry.note }) : null,
        entry.error ? el('div', { class: 'error-text', text: entry.error }) : null,
      ]),
      el('td', { text: entry.original }),
      el('td', {}, [
        el('div', { class: 'row' }, [
          input,
          el('button', {
            class: 'btn sm', type: 'button', text: '保存',
            onclick: () => rowSave(entry.status === 'pending' ? 'translated' : entry.status),
          }),
          el('button', {
            class: 'btn sm', type: 'button',
            text: entry.status === 'skipped' ? '恢复' : '跳过',
            onclick: () => rowSave(entry.status === 'skipped' ? 'pending' : 'skipped'),
          }),
        ]),
      ]),
    ]));
  }

  host.append(el('div', { class: 'table-wrap' }, [
    el('table', {}, [
      el('thead', {}, [el('tr', {}, [
        el('th', { text: '状态' }), el('th', { text: '位置' }),
        el('th', { text: '原文' }), el('th', { text: '译文' }),
      ])]),
      tbody,
    ]),
  ]));

  host.append(el('div', { class: 'pager' }, [
    el('button', {
      class: 'btn sm', type: 'button', text: '上一页',
      disabled: state.page.page <= 1,
      onclick: () => { state.query.page = state.page.page - 1; reload(); },
    }),
    el('span', { text: `第 ${state.page.page} / ${state.page.pages} 页` }),
    el('button', {
      class: 'btn sm', type: 'button', text: '下一页',
      disabled: state.page.page >= state.page.pages,
      onclick: () => { state.query.page = state.page.page + 1; reload(); },
    }),
  ]));
}

function statusTag(status) {
  const spec = STATUS[status] || { label: status || '未知', cls: 'pending' };
  return el('span', { class: 'tag ' + spec.cls, text: spec.label });
}

async function saveEntry(key, translated, status) {
  try {
    await postJSON('/api/translate/entry', { key, translated, status });
    toast('已保存', 'ok', 1500);
  } catch (err) {
    toast('保存失败：' + err.message, 'error');
  }
}

/* ---------------------------------------------------------------------------
 * 卡片 3：翻译设置
 * ------------------------------------------------------------------------- */
function buildSettingsCard() {
  const engineSel = el('select', { id: 'tr-engine-sel' });
  const keyInput = el('input', { type: 'password', id: 'tr-key', placeholder: '仅保存在本机 config.json' });
  const baseInput = el('input', { type: 'text', id: 'tr-base', placeholder: '接口地址' });
  const modelInput = el('input', { type: 'text', id: 'tr-model', placeholder: '模型名' });
  const srcSel = el('select', { id: 'tr-src' });
  const dstSel = el('select', { id: 'tr-dst' });
  const workersInput = el('input', { type: 'number', id: 'tr-workers', min: '1', max: '16' });
  const batchInput = el('input', { type: 'number', id: 'tr-batch', min: '1', max: '100' });

  for (const [code, label] of LANGS) {
    srcSel.append(el('option', { value: code, text: label }));
  }
  for (const [code, label] of LANGS) {
    if (code !== 'auto') dstSel.append(el('option', { value: code, text: label }));
  }

  const keyField = field('API Key', keyInput);
  const baseField = field('接口地址', baseInput);
  const modelField = field('模型', modelInput);

  const syncEngineFields = () => {
    const provider = state.providers.find((p) => p.id === engineSel.value);
    keyField.hidden = !(provider && provider.need_key);
    const needEndpoint = NEED_ENDPOINT.includes(engineSel.value);
    baseField.hidden = !needEndpoint;
    modelField.hidden = !needEndpoint;
  };
  engineSel.addEventListener('change', syncEngineFields);
  state.syncEngineFields = syncEngineFields;

  const saveBtn = el('button', { class: 'btn sm', type: 'button', text: '保存设置' });
  saveBtn.addEventListener('click', async () => {
    try {
      const res = await postJSON('/api/translate/config', { config: collectConfig(false) });
      state.config = res.config;
      toast('设置已保存', 'ok');
    } catch (err) {
      toast('保存失败：' + err.message, 'error');
    }
  });

  const testBtn = el('button', { class: 'btn sm', type: 'button', text: '接口自检' });
  testBtn.addEventListener('click', async () => {
    testBtn.disabled = true;
    const original = testBtn.textContent;
    testBtn.textContent = '自检中…';
    try {
      const res = await postJSON('/api/translate/test', { config: collectConfig(true) });
      const preview = (res.results || []).map((r) => `「${r}」`).join(' ');
      toast(`接口正常（${res.elapsed}s）：${preview}`, 'ok', 9000);
    } catch (err) {
      toast('接口自检失败：' + err.message, 'error', 15000);
    } finally {
      testBtn.disabled = false;
      testBtn.textContent = original;
    }
  });

  const startBtn = el('button', { class: 'btn primary', type: 'button', text: '开始翻译' });
  startBtn.addEventListener('click', () => startTranslate({ redo: false, onlyErrors: false }, startBtn));

  const retryBtn = el('button', { class: 'btn', type: 'button', text: '只重试出错条目' });
  retryBtn.addEventListener('click', () => startTranslate({ redo: false, onlyErrors: true }, retryBtn));

  const redoBtn = el('button', { class: 'btn', type: 'button', text: '全部重译' });
  redoBtn.addEventListener('click', async () => {
    const ok = await confirmDialog('全部重译？',
      '会重新翻译<b>所有</b>条目（含已翻译的），已有译文将被覆盖。<br>「已跳过」的条目不受影响。',
      '确认重译');
    if (ok) startTranslate({ redo: true, onlyErrors: false }, redoBtn);
  });

  return el('section', { class: 'card' }, [
    el('h2', {}, [el('span', { class: 'step', text: '3' }),
      document.createTextNode('翻译设置')]),
    el('div', {
      class: 'card-sub',
      text: '出网请求只包含剥离控制码后的纯文本，不含文件路径与游戏目录。',
    }),
    el('div', { class: 'grid' }, [
      field('翻译引擎', engineSel),
      keyField, baseField, modelField,
      field('源语言', srcSel),
      field('目标语言', dstSel),
      field('并发数', workersInput),
      field('每批条数', batchInput),
    ]),
    el('div', { class: 'row' }, [saveBtn, testBtn]),
    el('hr', { class: 'divider' }),
    el('div', { class: 'row' }, [startBtn, retryBtn, redoBtn]),
  ]);
}

/** 组装 {label, control} 的表单字段。 */
function field(label, control) {
  return el('div', { class: 'field' }, [el('label', { text: label }), control]);
}

/**
 * 从界面读取翻译配置。
 *
 * ``forTest=true`` 时即使 Key 为空也要发送（自检需要知道"当前没填"）；
 * 平时**只在用户真的填了东西时才发送** api_key / base_url / model ——
 * 后端对空值与掩码值会保留已存 Key，少发就等于"没改"。
 */
function collectConfig(forTest) {
  const value = (id) => {
    const node = document.getElementById(id);
    return node ? String(node.value || '').trim() : '';
  };
  const cfg = {
    engine: value('tr-engine-sel'),
    src_lang: value('tr-src'),
    dst_lang: value('tr-dst'),
    workers: Number(value('tr-workers')) || 4,
    batch_size: Number(value('tr-batch')) || 10,
  };
  const key = value('tr-key');
  const base = value('tr-base');
  const model = value('tr-model');
  if (key || forTest) cfg.api_key = key;
  if (base || forTest) cfg.base_url = base;
  if (model || forTest) cfg.model = model;
  return cfg;
}

async function loadProviders() {
  try {
    state.providers = (await getJSON('/api/translate/providers')).providers || [];
  } catch (err) {
    state.providers = [];
  }
  const sel = document.getElementById('tr-engine-sel');
  if (!sel) return;
  sel.textContent = '';
  for (const p of state.providers) {
    sel.append(el('option', { value: p.id, text: p.name }));
  }
}

async function loadConfig() {
  try {
    state.config = (await getJSON('/api/translate/config')).config || {};
  } catch (err) {
    state.config = {};
  }
  const c = state.config;
  const set = (id, value) => {
    const node = document.getElementById(id);
    if (node && value !== undefined && value !== null && value !== '') node.value = value;
  };
  set('tr-engine-sel', c.engine);
  set('tr-src', c.src_lang);
  set('tr-dst', c.dst_lang);
  set('tr-workers', c.workers);
  set('tr-batch', c.batch_size);
  /* 接口地址与模型名只回填"非密钥"信息；密钥栏留空（后端只返回掩码值） */
  set('tr-base', c.base_url);
  set('tr-model', c.model);
  if (typeof state.syncEngineFields === 'function') state.syncEngineFields();
}

async function startTranslate({ redo, onlyErrors }, button) {
  button.disabled = true;
  try {
    const res = await postJSON('/api/translate/start', {
      config: collectConfig(false), redo, only_errors: onlyErrors,
    });
    const job = await runJob(res.job, onlyErrors ? '重试出错条目' : '批量翻译');
    if (job.status === 'done' && job.result) {
      toast(`翻译结束：成功 ${job.result.done || 0} 条，失败 ${job.result.failed || 0} 条`, 'ok', 8000);
    }
    await reload();
  } catch (err) {
    toast('翻译失败：' + err.message, 'error', 15000);
  } finally {
    button.disabled = false;
  }
}

/* ---------------------------------------------------------------------------
 * 卡片 4：生成汉化版 + 备份还原
 * ------------------------------------------------------------------------- */
function buildBuildCard() {
  const modeSel = el('select', { id: 'tr-mode' });
  modeSel.append(el('option', { value: 'copy', text: '写副本（推荐，原游戏不动）' }));
  modeSel.append(el('option', { value: 'inplace', text: '覆盖原游戏（危险，会先自动备份）' }));

  const targetInput = el('input', {
    type: 'text', id: 'tr-target', placeholder: '留空则自动生成「<游戏名>_汉化」',
  });
  const fontInput = el('input', {
    type: 'text', id: 'tr-font', placeholder: '可选：中文字体文件 .ttf / .otf',
  });
  const fontBrowse = el('button', { class: 'btn sm', type: 'button', text: '浏览字体…' });
  fontBrowse.addEventListener('click', async () => {
    try {
      const res = await postJSON('/api/translate/pick_font', { initial: fontInput.value });
      if (!res.cancelled && res.path) fontInput.value = res.path;
    } catch (err) {
      toast('无法打开系统对话框：' + err.message + '（可直接粘贴路径）', 'warn', 8000);
    }
  });

  const targetField = field('输出目录', targetInput);
  const buildBtn = el('button', { class: 'btn primary', type: 'button', text: '生成汉化版' });

  const syncMode = () => {
    const inplace = modeSel.value === 'inplace';
    targetField.hidden = inplace;
    buildBtn.className = inplace ? 'btn danger' : 'btn primary';
    buildBtn.textContent = inplace ? '覆盖原游戏并生成' : '生成汉化版';
  };
  modeSel.addEventListener('change', syncMode);
  syncMode();

  buildBtn.addEventListener('click', async () => {
    const inplace = modeSel.value === 'inplace';
    const game = (state.session && state.session.game_dir) || '（未选择游戏目录）';
    const where = inplace
      ? `<b>直接覆盖原游戏</b>：<span class="code">${escapeHTML(game)}</span><br>` +
        '工具会先把将被修改的文件备份到游戏目录下的「汉化备份_*」中，随时可以还原。'
      : '复制到新目录：<span class="code">'
        + escapeHTML(targetInput.value.trim() || '自动生成 <游戏名>_汉化') + '</span><br>'
        + '原游戏目录不会被修改。';
    const ok = await confirmDialog(
      inplace ? '确认覆盖原游戏？' : '确认生成汉化版？',
      `${where}<br><br>只写入<b>已翻译</b>的条目；未翻译的内容按字节原样保留。`,
      inplace ? '确认覆盖' : '开始生成');
    if (!ok) return;

    buildBtn.disabled = true;
    try {
      const res = await postJSON('/api/translate/build', {
        mode: modeSel.value,
        target: targetInput.value.trim() || null,
        font: fontInput.value.trim() || null,
        overwrite: true,
        confirm: true,        // ← 二次确认已完成（硬约束 §4.2）
      });
      const job = await runJob(res.job, '生成汉化版');
      if (job.status === 'done') {
        showBuildResult(job.result || {});
        toast('汉化版生成完成', 'ok');
      }
      await loadBackups();
    } catch (err) {
      toast('生成失败：' + err.message, 'error', 15000);
    } finally {
      buildBtn.disabled = false;
    }
  });

  const backupBtn = el('button', { class: 'btn', type: 'button', text: '刷新备份列表' });
  backupBtn.addEventListener('click', () => loadBackups());

  /* 首次进入就列一次备份（用户可能上次已经构建过） */
  setTimeout(() => loadBackups(), 0);

  return el('section', { class: 'card' }, [
    el('h2', {}, [el('span', { class: 'step', text: '4' }),
      document.createTextNode('生成汉化版')]),
    el('div', {
      class: 'card-sub',
      text: '把译文写回游戏数据。未修改的内容按字节原样保留；覆盖类操作都会先备份并展示备份路径。',
    }),
    el('div', { class: 'grid' }, [
      field('写入方式', modeSel),
      targetField,
      field('中文字体（可选）', el('div', { class: 'row' }, [fontInput, fontBrowse])),
    ]),
    el('div', { class: 'row' }, [buildBtn, backupBtn]),
    el('div', { id: 'tr-backups' }),
  ]);
}

function showBuildResult(result) {
  const host = state.jobHost;
  if (!host) return;
  host.textContent = '';
  host.append(el('h2', {}, [el('span', { class: 'step', text: '✓' }),
    document.createTextNode('生成结果')]));

  host.append(el('div', { class: 'row' }, [
    el('span', { class: 'hint', text: '写入方式' }),
    el('span', { class: 'chip', text: result.mode === 'inplace' ? '覆盖原游戏' : '写副本' }),
    el('span', { class: 'hint', text: '写回条目' }),
    el('span', { class: 'chip ok', text: String(result.entries || 0) }),
    el('span', { class: 'hint', text: '文件' }),
    el('span', { class: 'chip', text: String(result.files || 0) }),
  ]));

  host.append(pathRow('输出目录', result.target_dir, '打开'));

  /* 硬约束 §4.2：覆盖类操作必须展示备份路径 */
  if (result.backup_dir) {
    host.append(pathRow('备份位置', result.backup_dir, '打开备份目录'));
  } else {
    host.append(el('div', {
      class: 'hint',
      text: '本次为写副本，原游戏未被修改，因此没有生成备份。',
    }));
  }

  if (result.notes && result.notes.length) {
    host.append(el('div', { class: 'hint', text: '提示：' }));
    host.append(el('ul', { class: 'muted' },
      result.notes.map((n) => el('li', { text: String(n) }))));
  }
}

function pathRow(label, path, buttonText) {
  return el('div', { class: 'row' }, [
    el('span', { class: 'hint', text: label }),
    el('span', { class: 'code', text: path || '—' }),
    el('button', {
      class: 'btn sm', type: 'button', text: buttonText,
      disabled: !path,
      onclick: () => openInExplorer(path),
    }),
  ]);
}

async function loadBackups() {
  const host = document.getElementById('tr-backups');
  if (!host) return;
  host.textContent = '';
  let res;
  try {
    res = await getJSON('/api/translate/backups');
  } catch (err) {
    /* 没扫描/没会话时后端会明确报错 —— 这不是异常情况，用 hint 不用 error */
    host.append(el('div', { class: 'hint', text: err.message }));
    return;
  }
  const list = res.backups || [];
  if (!list.length) {
    host.append(el('div', {
      class: 'empty',
      text: '还没有备份。选择「覆盖原游戏」生成汉化版时会自动创建备份。',
    }));
    return;
  }

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
  const game = (state.session && state.session.game_dir) || '（当前游戏）';
  const ok = await confirmDialog('确认还原？',
    `将用备份 <span class="code">${escapeHTML(item.name)}</span> 覆盖 `
    + `<span class="code">${escapeHTML(game)}</span> 下的游戏数据。<br><br>`
    + '当前状态会先被自动再备份一次 —— 所以「还原错了」还可以再还原回来。',
    '确认还原');
  if (!ok) return;
  try {
    const res = await postJSON('/api/translate/restore', { dir: item.dir });
    const r = res.result || {};
    toast(`还原完成：恢复 ${r.restored || 0} 个文件`
      + (r.safety_backup ? '（已为还原前状态生成备份）' : ''), 'ok', 8000);
    await loadBackups();
  } catch (err) {
    toast('还原失败：' + err.message, 'error', 15000);
  }
}

async function openInExplorer(dir) {
  if (!dir) return;
  try {
    await postJSON('/api/translate/open_dir', { dir });
  } catch (err) {
    toast('无法打开目录：' + err.message, 'warn');
  }
}

/* ---------------------------------------------------------------------------
 * 任务进度与取消
 * ------------------------------------------------------------------------- */
async function runJob(jobId, title) {
  const host = state.jobHost;
  const bar = el('i', {});
  const msg = el('span', { class: 'hint', text: '排队中…' });
  const cancelBtn = el('button', { class: 'btn sm danger', type: 'button', text: '取消' });
  const statusHost = el('div', {});
  host.textContent = '';
  host.append(el('h2', {}, [el('span', { class: 'step', text: '…' }),
    document.createTextNode(title)]));
  host.append(el('div', { class: 'row' }, [
    msg, el('span', { class: 'spacer' }), cancelBtn,
  ]));
  host.append(el('div', { class: 'progress' }, [bar]));
  host.append(statusHost);

  let settled = false;
  cancelBtn.addEventListener('click', async () => {
    cancelBtn.disabled = true;
    cancelBtn.textContent = '取消中…';
    try {
      await postJSON('/api/cancel', { id: jobId });
      toast('已请求取消', 'warn');
    } catch (err) {
      toast('取消失败：' + err.message, 'error');
    }
    /* 硬约束 §5-7：取消后界面**立即**恢复可用，不等待后台线程真正退出 */
    settled = true;
    cancelBtn.textContent = '已取消';
  });

  const finish = (job) => {
    msg.textContent = `${pct(job.progress)} · ${job.message || ''}`
      + (job.elapsed ? ` · ${fmtDuration(job.elapsed)}` : '');
  };

  try {
    const job = await waitJob(jobId, {
      onTick: (j) => {
        if (!settled) finish(j);
        bar.style.width = pct(j.progress);
      },
    });
    if (job.status === 'error') {
      statusHost.append(el('div', { class: 'error-text', text: '失败：' + (job.error || '未知错误') }));
      if (job.traceback_tail) {
        statusHost.append(el('pre', { class: 'code', text: job.traceback_tail }));
      }
    } else if (job.status === 'cancelled') {
      statusHost.append(el('div', { class: 'warn-text', text: '已取消（已完成的条目仍然保留）' }));
    } else {
      bar.style.width = '100%';
      msg.textContent = '完成';
      cancelBtn.remove();
    }
    return job;
  } catch (err) {
    statusHost.append(el('div', { class: 'error-text', text: err.message }));
    throw err;
  } finally {
    settled = true;
  }
}

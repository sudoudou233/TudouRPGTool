/* ---------------------------------------------------------------------------
 * 环境自检功能页
 *
 * @feature  selfcheck
 * @layer    ui
 * @public   render
 * @depends  /dom.js, /api/selfcheck/report
 * @tested   tests/features/selfcheck/test_manifest.py
 * @footprint docs/UI_SPEC.md
 *
 * 需求 §8-6 的演示页面：新增功能**只需要** features/<id>/ + 本文件，
 * 外壳（index.html / app.js / server.py / app.py）一个字节都不用改。
 *
 * 只使用 components.css 的共享组件类，不写任何内联配色。
 * ------------------------------------------------------------------------- */

import { el, getJSON, toast, escapeHTML } from '/dom.js';

export async function render(host) {
  let report = null;
  try {
    report = await getJSON('/api/selfcheck/report');
  } catch (err) {
    toast('读取环境信息失败：' + err.message, 'error');
  }

  if (!report) {
    host.append(el('section', { class: 'card' }, [
      el('div', { class: 'error-text', text: '无法读取环境信息。' }),
    ]));
    return;
  }

  const py = report.python || {};
  host.append(el('section', { class: 'card' }, [
    el('h2', {}, [el('span', { class: 'step', text: '1' }),
      document.createTextNode('运行环境')]),
    el('div', { class: 'card-sub', text: '排查“为什么我这里不行”时先看这里。' }),
    el('div', { class: 'chips' }, [
      el('span', { class: 'chip ok', html: `Python <b>${escapeHTML(py.version)}</b>` }),
      el('span', { class: 'chip', text: py.implementation || '' }),
      el('span', { class: 'chip', text: py.supports_3_8_syntax ? '≥ 3.8 要求满足' : '版本过低' }),
      el('span', { class: 'chip', text: py.platform || '' }),
    ]),
    el('div', { class: 'grid' }, [
      kv('工程根目录', (report.paths || {}).project_root),
      kv('运行数据目录', (report.paths || {}).data_dir),
      kv('数据目录可写', (report.paths || {}).runtime_writable ? '是' : '否'),
      kv('参考工具目录', (report.paths || {}).reference_root),
      kv('真实样本目录', (report.paths || {}).samples_root || '（未设置）'),
    ]),
  ]));

  const asm = report.assembly || {};
  host.append(el('section', { class: 'card' }, [
    el('h2', {}, [el('span', { class: 'step', text: '2' }),
      document.createTextNode('装配结果')]),
    el('div', {
      class: 'card-sub',
      text: '这些都由注册表自动发现得到 —— 新增 features/<id>/manifest.py 就会出现在这里。',
    }),
    el('div', { class: 'chips' }, [
      el('span', { class: 'chip', html: `功能 <b>${asm.feature_count || 0}</b> 个` }),
      el('span', { class: 'chip', html: `路由 <b>${asm.route_count || 0}</b> 条` }),
    ]),
    featureTable(asm.features || []),
    routeTable(asm.routes_by_feature || {}),
  ]));

  const conv = report.convergence || {};
  const allMerged = conv.engines === 'merged' && conv.formats === 'merged'
    && conv.marshal === 'merged';
  host.append(el('section', { class: 'card' }, [
    el('h2', {}, [el('span', { class: 'step', text: '3' }),
      document.createTextNode('收敛状态')]),
    el('div', {
      class: 'card-sub',
      text: '需求 §3.3 要求"同一职责只有一份实现"。这三项是运行时事实，不是文档承诺。',
    }),
    el('div', { class: 'chips' }, [
      el('span', { class: 'chip ' + (allMerged ? 'ok' : 'warn'),
        html: `全部收敛 <b>${allMerged ? '是' : '否'}</b>` }),
      el('span', { class: 'chip', html: `引擎识别 <b>${escapeHTML(conv.engines || '?')}</b>` }),
      el('span', { class: 'chip', html: `MV/MZ 编解码 <b>${escapeHTML(conv.formats || '?')}</b>` }),
      el('span', { class: 'chip', html: `Ruby Marshal <b>${escapeHTML(conv.marshal || '?')}</b>` }),
    ]),
  ]));

  const eng = report.engines || {};
  const safety = report.safety || {};
  host.append(el('section', { class: 'card' }, [
    el('h2', {}, [el('span', { class: 'step', text: '4' }),
      document.createTextNode('能力边界')]),
    el('div', { class: 'grid' }, [
      kv('支持读写', (eng.supported || []).join('、')),
      kv('仅识别', (eng.recognize_only || []).join('、')),
      kv('安全层模块', (safety.modules || []).join('、')),
      kv('备份目录前缀', safety.backup_prefix),
    ]),
  ]));
}

function kv(label, value) {
  return el('div', { class: 'field' }, [
    el('label', { text: label }),
    el('div', {}, [el('span', { class: 'code', text: value || '—' })]),
  ]);
}

function featureTable(features) {
  if (!features.length) {
    return el('div', { class: 'empty', text: '没有发现任何功能模块。' });
  }
  return el('div', { class: 'table-wrap' }, [
    el('table', {}, [
      el('thead', {}, [el('tr', {}, [
        el('th', { text: '功能 id' }), el('th', { text: '名称' }),
        el('th', { text: '版本' }), el('th', { text: '状态' }),
      ])]),
      el('tbody', {}, features.map((f) => el('tr', {}, [
        el('td', {}, [el('span', { class: 'code', text: f.id })]),
        el('td', { text: f.name }),
        el('td', { text: f.version }),
        el('td', {}, [f.ok
          ? el('span', { class: 'tag ok', text: '已加载' })
          : el('span', { class: 'tag error', text: '加载失败' })]),
      ]))),
    ]),
  ]);
}

function routeTable(byFeature) {
  const rows = Object.keys(byFeature).sort();
  if (!rows.length) return el('div');
  return el('div', { class: 'chips' }, [
    el('span', { class: 'hint', text: '各归属的路由数：' }),
    ...rows.map((key) => el('span', {
      class: 'chip', html: `${escapeHTML(key)} <b>${byFeature[key]}</b>`,
    })),
  ]);
}

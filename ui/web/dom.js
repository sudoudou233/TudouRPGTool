/* ---------------------------------------------------------------------------
 * 共享前端工具：API 调用、Toast、任务轮询、DOM 助手
 *
 * @feature  none
 * @layer    ui
 * @public   $ $$ el api toast getJSON postJSON waitJob pollJob fmtBytes
 *           fmtDuration escapeHTML show modal confirmDialog
 * @depends  (none)
 * @tested   tools/check_footprint.py
 * @footprint docs/UI_SPEC.md#js-components
 *
 * 迁移来源：rpgmaker_translation_tool/web/index.html:256-278/336-342 的
 * api() / toast() / waitJob()，但修正了三个已知缺陷（见 M0 报告 §4.3）：
 *   B-21  escapeHTML 补齐引号转义（原 safe() 只转义 & < >，注入面）
 *   B-23  waitJob 加总超时 + 统一轮询实现（原三份复制粘贴且无超时）
 *   统一错误处理：检查 r.ok，并把 {ok:false,error,code} 转成异常
 * ------------------------------------------------------------------------- */

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

/** 创建元素：el('div', {class:'card'}, [child, 'text']) */
export function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key === 'class') node.className = value;
    else if (key === 'dataset') Object.assign(node.dataset, value);
    else if (key === 'style' && typeof value === 'object') Object.assign(node.style, value);
    else if (key.startsWith('on') && typeof value === 'function') {
      node.addEventListener(key.slice(2).toLowerCase(), value);
    } else if (key === 'html') node.innerHTML = value;
    else if (key === 'text') node.textContent = value;
    else node.setAttribute(key, value === true ? '' : String(value));
  }
  const list = Array.isArray(children) ? children : [children];
  for (const child of list) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

/** HTML 转义：修正原实现只转义 & < > 的注入面（B-21）。 */
export function escapeHTML(value) {
  return String(value === null || value === undefined ? '' : value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

/** 统一 API 调用。失败抛 Error（带 .code / .status）。 */
export async function api(path, body, method) {
  const init = { method: method || (body === undefined ? 'GET' : 'POST'), headers: {} };
  if (body !== undefined) {
    init.headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(body);
  }
  const res = await fetch(path, init);
  const ctype = res.headers.get('Content-Type') || '';
  let payload;
  if (ctype.includes('json')) {
    payload = await res.json().catch(() => ({}));
  } else {
    payload = await res.text();
  }
  if (!res.ok || (payload && typeof payload === 'object' && payload.ok === false)) {
    const err = new Error((payload && payload.error) || `HTTP ${res.status}`);
    err.code = (payload && payload.code) || 'http_' + res.status;
    err.status = res.status;
    err.payload = payload;
    throw err;
  }
  return payload;
}

export const getJSON = (path) => api(path, undefined, 'GET');
export const postJSON = (path, body) => api(path, body || {}, 'POST');

/* ------------------------------------------------------------------ Toast */
export function toast(message, kind = 'info', timeout = 4200) {
  const host = $('#toast');
  if (!host) return;
  const node = el('div', { class: `toast ${kind}`, text: message });
  host.append(node);
  setTimeout(() => node.remove(), timeout);
  return node;
}

/* ------------------------------------------------------------------ 模态框 */
export function modal({ title, bodyHTML, buttons = [] }) {
  const mask = el('div', { class: 'modal-mask' });
  const foot = el('div', { class: 'foot' });
  const close = () => mask.remove();
  for (const spec of buttons) {
    foot.append(el('button', {
      class: 'btn ' + (spec.kind || ''),
      type: 'button',
      text: spec.label,
      onclick: () => { if (!spec.onClick || spec.onClick() !== false) close(); },
    }));
  }
  mask.append(el('div', { class: 'modal' }, [
    el('h3', { text: title }),
    el('div', { class: 'body', html: bodyHTML || '' }),
    foot,
  ]));
  document.body.append(mask);
  return { close, mask };
}

export function confirmDialog(title, bodyHTML, okLabel = '确认') {
  return new Promise((resolve) => {
    modal({
      title,
      bodyHTML,
      buttons: [
        { label: '取消', onClick: () => resolve(false) },
        { label: okLabel, kind: 'primary', onClick: () => resolve(true) },
      ],
    });
  });
}

/* ------------------------------------------------------------------ 任务轮询 */
/**
 * 轮询后台任务直到终态。
 * 修正 B-23：原 waitJob 无超时，任务丢失会永久循环。这里有总超时 +
 * 连续 404 容忍计数，并在超时/丢失时抛错而不是静默卡死。
 */
export async function waitJob(jobId, {
  interval = 400, timeout = 30 * 60 * 1000, onTick = null, tolerateMissing = 5,
} = {}) {
  const started = Date.now();
  let missing = 0;
  for (;;) {
    let payload;
    try {
      payload = await getJSON('/api/job?id=' + encodeURIComponent(jobId));
    } catch (err) {
      if (err.code === 'job_missing') {
        missing += 1;
        if (missing > tolerateMissing) throw new Error('任务已丢失：' + jobId);
      } else {
        throw err;
      }
    }
    if (payload && payload.job) {
      missing = 0;
      const job = payload.job;
      if (onTick) onTick(job);
      if (['done', 'error', 'cancelled'].includes(job.status)) return job;
    }
    if (Date.now() - started > timeout) {
      throw new Error(`任务 ${jobId} 超过 ${Math.round(timeout / 1000)} 秒仍未结束`);
    }
    await new Promise((r) => setTimeout(r, interval));
  }
}

/* ------------------------------------------------------------------ 格式化 */
export function fmtBytes(n) {
  if (n === null || n === undefined) return '—';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let v = Number(n), i = 0;
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i += 1; }
  return `${v.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

export function fmtDuration(seconds) {
  if (seconds === null || seconds === undefined) return '—';
  const s = Math.max(0, Math.round(Number(seconds)));
  if (s < 60) return `${s} 秒`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m} 分 ${s % 60} 秒`;
  return `${Math.floor(m / 60)} 时 ${m % 60} 分`;
}

export function pct(value) {
  const v = Number(value || 0);
  return `${Math.round(Math.max(0, Math.min(1, v)) * 100)}%`;
}

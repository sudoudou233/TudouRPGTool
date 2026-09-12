/* ---------------------------------------------------------------------------
 * 文本翻译功能页
 *
 * @feature  translate
 * @layer    ui
 * @public   render
 * @depends  /dom.js, /api/translate/*
 * @tested   tools/check_footprint.py（页面模块必须导出 render 且只使用共享组件）
 * @footprint docs/FEATURES.md#translate
 *
 * M1 状态：**接线骨架**。展示功能已注册、列出可用的翻译引擎适配器、
 * 展示 core 依赖与健康检查。扫描 / 翻译 / 生成汉化版的完整交互在 M3a 接线
 * （迁移来源 rpgmaker_translation_tool/web/index.html:86-253 的四张卡片）。
 *
 * 只使用 components.css 的共享组件类，不写任何内联配色（由
 * tools/check_footprint.py 校验）。
 * ------------------------------------------------------------------------- */

import { el, getJSON, toast } from '/dom.js';

export async function render(host) {
  let status = {};
  let providers = {};
  try {
    status = await getJSON('/api/translate/status');
  } catch (err) {
    toast('读取翻译功能状态失败：' + err.message, 'error');
  }
  try {
    providers = await getJSON('/api/translate/providers');
  } catch (err) {
    providers = { providers: [] };
  }

  host.append(el('section', { class: 'card' }, [
    el('h2', {}, [
      el('span', { class: 'step', text: '1' }),
      document.createTextNode('功能状态'),
    ]),
    el('div', { class: 'card-sub', text: 'M1 骨架阶段：功能已按契约注册，业务链路在 M3a 接线。' }),
    el('div', { class: 'chips' }, [
      el('span', { class: 'chip warn', html: `阶段 <b>${status.status || 'unknown'}</b>` }),
      el('span', { class: 'chip', text: status.detail || '' }),
    ]),
  ]));

  host.append(el('section', { class: 'card' }, [
    el('h2', {}, [
      el('span', { class: 'step', text: '2' }),
      document.createTextNode('翻译引擎适配器'),
    ]),
    el('div', { class: 'card-sub', text: '迁移自 rpgmaker_translation_tool/tool/translators.py（零第三方依赖，出网只发纯文本）。' }),
    el('div', { class: 'table-wrap' }, [
      el('table', {}, [
        el('thead', {}, [el('tr', {}, [
          el('th', { text: 'ID' }),
          el('th', { text: '名称' }),
          el('th', { text: '需要密钥' }),
          el('th', { text: '说明' }),
        ])]),
        el('tbody', {}, (providers.providers || []).map((p) => el('tr', {}, [
          el('td', {}, [el('span', { class: 'code', text: p.id })]),
          el('td', { text: p.name }),
          el('td', {}, [el('span', { class: 'tag ' + (p.need_key ? 'skipped' : 'translated'), text: p.need_key ? '需要' : '不需要' })]),
          el('td', { class: 'muted', text: p.note }),
        ]))),
      ]),
    ]),
  ]));

  host.append(el('section', { class: 'card' }, [
    el('h2', {}, [
      el('span', { class: 'step', text: '3' }),
      document.createTextNode('后续里程碑将在此接入'),
    ]),
    el('ul', { class: 'muted' }, [
      el('li', { text: 'M2b：marshal 与 formats 收敛为唯一实现（含加密 JSON 包装）' }),
      el('li', { text: 'M3a：扫描文本 → 批量翻译（进度/可中断）→ 生成汉化版 → 备份还原 → 字体注入' }),
      el('li', { text: 'M4：与其他页面统一令牌与交互范式' }),
    ]),
  ]));
}

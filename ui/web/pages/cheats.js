/* ---------------------------------------------------------------------------
 * 存档修改功能页
 *
 * @feature  cheats
 * @layer    ui
 * @public   render
 * @depends  /dom.js, /api/cheats/*
 * @tested   tools/check_footprint.py
 * @footprint docs/FEATURES.md#cheats
 *
 * M1 状态：**引擎识别链路已可用**（走 core.engines 唯一实现），
 * 读档 / 改数值 / 存档的交互在 M3b 接线（逻辑层迁移自
 * rpgmaker_cheating_tool/{engines,rpgdata,mvdata,rmarshal,lzstring}.py，
 * 界面层按 ADR-001 重写为 Web 页面）。
 * ------------------------------------------------------------------------- */

import { el, getJSON, postJSON, toast } from '/dom.js';

export async function render(host) {
  const dirInput = el('input', { type: 'text', placeholder: '例如 D:\\gamess\\某游戏\\game' });
  const resultBox = el('div');
  const detectBtn = el('button', {
    class: 'btn primary', type: 'button', text: '识别引擎并列出存档',
    onclick: () => runDetect(dirInput.value.trim(), detectBtn, resultBox),
  });

  host.append(el('section', { class: 'card' }, [
    el('h2', {}, [
      el('span', { class: 'step', text: '1' }),
      document.createTextNode('选择游戏目录'),
    ]),
    el('div', { class: 'card-sub', text: '选择包含 www / data / Data 文件夹的那一层。识别与存档发现走 core/engines.py（全工程唯一实现）。' }),
    el('div', { class: 'row' }, [dirInput, detectBtn]),
  ]));

  host.append(el('section', { class: 'card' }, [
    el('h2', {}, [
      el('span', { class: 'step', text: '2' }),
      document.createTextNode('识别结果'),
    ]),
    resultBox,
  ]));

  host.append(el('section', { class: 'card' }, [
    el('h2', {}, [
      el('span', { class: 'step', text: '3' }),
      document.createTextNode('后续里程碑将在此接入'),
    ]),
    el('ul', { class: 'muted' }, [
      el('li', { text: 'M2a：修 XP/VX 的 marshal 写回字节漂移（P0），建立可信测试基线' }),
      el('li', { text: 'M3b：读档 → 改金币/步数/道具/角色/开关变量 → 原子写回 + 自动备份 + 还原入口' }),
      el('li', { text: 'M4：统一令牌与交互范式' }),
    ]),
  ]));

  resultBox.append(el('div', { class: 'empty', text: '尚未识别。填入游戏目录后点上面的按钮。' }));
}

async function runDetect(dir, button, box) {
  box.innerHTML = '';
  if (!dir) {
    toast('请先填写游戏目录', 'warn');
    return;
  }
  button.disabled = true;
  box.append(el('div', { class: 'muted', text: '识别中…' }));
  try {
    const res = await postJSON('/api/cheats/detect', { dir });
    box.innerHTML = '';
    if (!res.ok) {
      box.append(el('div', { class: 'error-text', text: res.error || '识别失败' }));
      return;
    }
    box.append(el('div', { class: 'chips' }, [
      el('span', { class: 'chip ok', html: `引擎 <b>${res.label}</b>` }),
      el('span', { class: 'chip', html: `存档 <b>${(res.saves || []).length}</b> 个` }),
      res.match ? el('span', { class: 'chip', html: `判据 <b>${res.match}</b>` }) : null,
      res.supported ? null : el('span', { class: 'chip warn', text: '仅识别，不支持修改' }),
    ]));
    box.append(el('div', { class: 'grid', style: { marginTop: 'var(--sp-4)' } }, [
      kv('数据目录', res.data_dir),
      kv('存档目录', res.save_dir),
      kv('存档扩展名', res.save_ext),
    ]));
    if ((res.saves || []).length) {
      box.append(el('div', { class: 'divider' }));
      box.append(el('div', { class: 'table-wrap' }, [
        el('table', {}, [
          el('thead', {}, [el('tr', {}, [el('th', { text: '存档文件' })])]),
          el('tbody', {}, res.saves.map((name) => el('tr', {}, [
            el('td', {}, [el('span', { class: 'code', text: name })]),
          ]))),
        ]),
      ]));
    }
    if ((res.save_dirs || []).length > 1) {
      box.append(el('div', { class: 'warn-text', text: `注意：发现 ${res.save_dirs.length} 个含存档的目录，可能存在自动存档等第二套存档，修改时需全部处理。` }));
    }
  } catch (err) {
    box.innerHTML = '';
    box.append(el('div', { class: 'error-text', text: '识别失败：' + err.message }));
    toast('识别失败：' + err.message, 'error');
  } finally {
    button.disabled = false;
  }
}

function kv(label, value) {
  return el('div', { class: 'field' }, [
    el('label', { text: label }),
    el('div', {}, [el('span', { class: 'code', text: value || '—' })]),
  ]);
}

export { runDetect };

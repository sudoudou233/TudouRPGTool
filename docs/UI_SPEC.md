# UI 规格 —— 设计令牌、组件清单、页面清单、交互范式

> 依据《RPG Maker 全能工具 · 工程级开发工作流提示词》§6.1。
> 变更时机：UI 变更时。**本文件登记的页面清单由 `tools/check_footprint.py`（F-12）双向校验**。

---

## 1. 设计令牌（`ui/web/tokens.css`）

全站唯一配色真源。视觉基线继承 `rpgmaker_translation_tool/web/index.html:8-12`
已验证的暗色主题，**值逐字保留**以保证视觉不漂移。

| 令牌 | 值 | 用途 | 来源 |
| --- | --- | --- | --- |
| `--bg` | `#14161c` | 页面背景 | 原 `--bg` |
| `--card` | `#1d212b` | 卡片背景 | 原 `--card` |
| `--card2` | `#232836` | 次级背景（表头、按钮） | 原 `--card2` |
| `--line` | `#303648` | 边框/分隔线 | 原 `--line` |
| `--text` | `#e8eaf0` | 主文本 | 原 `--text` |
| `--muted` | `#9aa3b5` | 次要文本 | 原 `--muted` |
| `--accent` | `#4f8cff` | 主色（按钮、进度、导航激活） | 原 `--accent` |
| `--accent2` | `#6ec06e` | 成功色 | 原 `--accent2` |
| `--warn` | `#e6a23c` | 警告色 | 原 `--warn`（原实现零引用，本版补齐用途） |
| `--danger` | `#e06c75` | 危险/错误色 | 原 `--danger` |
| `--radius` | `10px` | 圆角基准 | 原 `--radius` |
| `--bg-deep` | `#14171f` | 代码块/进度槽底色 | 由硬编码提取（原 3 处） |
| `--on-accent` | `#fff` | 主色上的文字 | 由硬编码提取（原 2 处） |
| `--success-bg` | `#10240f` | 成功按钮底色 | 由硬编码提取 |
| `--input-bg` | `#2a2f3d` | 输入框底色 | 由硬编码提取（原 2 处） |
| `--overlay` | `rgba(0,0,0,.55)` | 模态遮罩 | 由硬编码提取 |
| `--tag-*-fg/bg` | 四态共 8 个 | 状态标签配色 | 原 `index.html:57-60` |
| `--sp-1` … `--sp-6` | 4/6/8/12/16/24px | 间距刻度 | 新增（原实现散落硬编码） |
| `--fs-xs` … `--fs-2xl` | 11/12/13/15/18/22px | 字号刻度 | 新增 |
| `--radius-sm/-lg/-pill` | 6/14/999px | 圆角派生 | 新增 |
| `--shadow-card/-modal` | — | 阴影 | 新增 |
| `--font-ui` | 中文优先字体栈 | 界面字体 | 原实现 |
| `--font-mono` | 等宽字体栈 | 路径/代码 | 新增 |

**硬规则**：页面模块（`ui/web/pages/*.js`）**不得**写具体颜色值，只能用令牌或
`components.css` 的类。由 `tools/check_footprint.py` 与代码评审共同保证。

---

## 2. 组件清单（`ui/web/components.css`）

| 组件 | 类名 | 说明 |
| --- | --- | --- |
| 顶栏 | `header` / `.sub` / `.spacer` | 应用标题 + 版本 + 健康胶囊 + 刷新按钮 |
| 导航 | `.nav` / `.nav-item` / `.nav-item.active` / `.nav-item.disabled` | **多页入口，由 `/api/nav` 驱动** |
| 按钮 | `.btn` + `.primary` / `.success` / `.danger` / `.sm` / `:disabled` | 四种语义 |
| 卡片 | `.card` / `.card h2` / `.step` / `.card-sub` | 内容分组，带步骤徽标 |
| 布局 | `.row` / `.grid` / `.field` / `.check` / `.divider` | 表单与栅格 |
| 表单控件 | `input[type=text/number/password]` / `select` / `textarea` | 统一底色与聚焦色 |
| 指标 | `.chips` / `.chip` + `.warn` / `.danger` / `.ok`、`.kpi` | 状态胶囊与关键指标 |
| 表格 | `.table-wrap` / `table` / `th,td` / `td.num` | 粘性表头 + 横向滚动 |
| 状态标签 | `.tag` + `.pending` / `.translated` / `.skipped` / `.error` / `.warn` / `.ok` | 条目状态 |
| 进度条 | `.progress` / `.progress > i` | 任务进度 |
| 模态框 | `.modal-mask` / `.modal` / `.modal h3` / `.body` / `.foot` | 二次确认与冲突选择 |
| Toast | `#toast` / `.toast` + `.error` / `.ok` / `.warn` | 轻提示 |
| 工具类 | `.muted` / `.error-text` / `.warn-text` / `.ok-text` / `.hint` / `.mono` / `.pager` / `.code` / `.empty` / `.nowrap` | 排版与空状态 |

### 已删除的旧样式（禁止复活）

| 原位置 | 内容 | 删除理由 |
| --- | --- | --- |
| `index.html:76-79` | `.dir-item` 系列 | 配套的 `/api/listdir` 已被原生选择器取代，全仓零引用 |
| `index.html:63` | `.progress.success` | 零引用 |
| `index.html:66` | `.ok-text` | 零引用（本版补上了用途，见组件清单） |

---

## 3. JavaScript 共享工具（`ui/web/dom.js`）

| 导出 | 说明 |
| --- | --- |
| `$` / `$$` | `querySelector` / `querySelectorAll` 简写 |
| `el(tag, attrs, children)` | 元素构造器（替代字符串拼 HTML） |
| `escapeHTML(value)` | **转义 `& < > " '` 五个字符**（修正原 `safe()` 只转义三个的注入面） |
| `api(path, body, method)` | 统一请求；解析 `{ok:false,error,code}` 并抛 `Error` |
| `getJSON` / `postJSON` | 语义化封装 |
| `toast(msg, kind, timeout)` | 轻提示 |
| `modal({...})` / `confirmDialog(...)` | 模态框与二次确认 |
| `waitJob(jobId, {timeout, onTick})` | **带总超时的**任务轮询（修正原 `waitJob` 无超时永久循环） |
| `fmtBytes` / `fmtDuration` / `pct` | 格式化 |

---

## 4. 页面清单

> **这一节由 F-12 双向校验**：这里列出的每个 `pages/*.js` 必须存在，反之亦然。

| 页面 id | 标题 | 文件 | 所属功能 | 状态 |
| --- | --- | --- | --- | --- |
| `translate` | 文本翻译 | `ui/web/pages/translate.js` | `features/translate` | **已接线**（M3a）：选目录 → 扫描 → 列表编辑 → 批量翻译 → 生成汉化版 → 备份还原 |
| `cheats` | 存档修改 | `ui/web/pages/cheats.js` | `features/cheats` | M1 引擎识别已可用（M3b 接线） |

页面模块契约：必须 `export function render(host, ctx)`（可为 async）。
`host` 是已清空的容器元素；`ctx` 含 `{nav, features}`。

### 4.1 `translate` 页面的五张卡片（M3a 定稿）

| 卡片 | 内容 | 对应端点 |
| --- | --- | --- |
| 1 游戏目录 | 路径输入 + 「浏览…」（原生对话框）+ 「打开并识别」；下方胶囊显示引擎 / 数据目录 / 计数 | `pick_folder`、`open`、`state` |
| 2 扫描与文本列表 | 4 个内容开关 + 「扫描文本」「把待翻译全部标记为跳过」；列表含搜索 / 类别 / 状态筛选、分页、行内改译文、逐条跳过与恢复 | `scan`、`skip_all`、`entries`、`entry` |
| 3 翻译设置 | 引擎 / Key / 接口地址 / 模型 / 语言 / 并发 / 批大小 + 「保存设置」「接口自检」；「开始翻译」「只重试出错条目」「全部重译」 | `providers`、`config`(GET/POST)、`test`、`start` |
| 4 生成汉化版 | 写入方式（**默认写副本**）/ 输出目录 / 可选字体 + 「生成汉化版」；生成后显示输出目录与**备份路径**；下方是备份列表（可还原） | `build`、`backups`、`restore`、`open_dir`、`pick_font` |
| 5 任务进度 | 进度条 + 百分比 + 阶段文案 + 耗时 + **取消按钮**；失败时显示 `job.error` 与 `traceback_tail` | `job`、`cancel` |

**该页面被一个静态契约测试守护**（`tests/integration/test_translate_page.py`，23 例）：
页面调用的每个端点都必须真实存在、后端每个翻译端点都必须有界面入口（双向）、
覆盖与还原必须有 `confirmDialog` 且把 `confirm: true` 传给后端、
默认写入方式必须是 `copy`、必须展示备份路径、密钥框必须是 `password` 且不回显。

### 外壳（不属任何功能，永不随功能变化）

| 文件 | 职责 |
| --- | --- |
| `ui/web/index.html` | 页面骨架：#nav / #view / #toast 三个挂载点 + 功能状态表 + 诊断面板 |
| `ui/web/app.js` | 启动引导、导航渲染、页面动态 `import()`、诊断请求 |
| `ui/web/tokens.css` | 设计令牌 |
| `ui/web/components.css` | 共享组件 |
| `ui/web/dom.js` | JS 共享工具 |

---

## 5. 交互范式（全站统一）

1. **功能入口自动出现**：启动时 `GET /api/nav` 取导航；点击导航项时
   `import(`/pages/${module}.js`)` 并调用其 `render(host)`。
   因此**新增功能 = 新增 `features/<name>/` + 新增 `ui/web/pages/<id>.js`**，
   `index.html` 与 `app.js` 不需要修改。
2. **状态反馈三件套**：
   - 轻量结果 → `toast(msg, 'ok'|'error'|'warn')`
   - 长任务 → 进度条 + 百分比 + 阶段文案（`job.message`）+ 可取消按钮
   - 错误 → 卡片内 `.error-text` 显示 `job.error`，`job.traceback_tail` 供排查
3. **破坏性操作二次确认**：覆盖原游戏、写回原存档、还原备份、删除输出目录，
   一律先 `confirmDialog()`，并在文案中写明"将修改哪些文件、备份在哪里"。
4. **危险操作视觉标记**：覆盖类按钮用 `.btn.danger`；默认选项永远是"写副本"。
5. **默认零破坏**：处理用户游戏目录时默认**只写副本**；覆盖原文件是高级选项，
   且必须显示备份路径。
6. **错误信息可读**：面向用户的错误必须是中文句子，技术细节（异常类型、
   路径）附在括号内；原始 traceback 只在诊断面板展示。
7. **进度可中断**：任何超过 2 秒的任务都必须有取消入口，且取消后界面立即
   恢复可用（不等待后台线程真正退出）。
8. **不使用内联样式表达配色**：布局性的 `style` 允许（且推荐用 `--sp-*` 令牌），
   颜色一律走类名。

---

## 6. 布局与响应式

* 内容最大宽度 `--content-max: 1180px`，居中。
* 顶栏 `position: sticky`，高度 `--header-h: 56px`。
* 表格容器 `.table-wrap` 最大高度 `60vh` 且可滚动，表头 sticky。
* `.grid` 使用 `repeat(auto-fit, minmax(240px, 1fr))`，在窄窗口自动降列。
* 模态框 `max-width: min(680px, 92vw)`，保证小窗口不溢出。
* 验收要求（§8-8）：常见窗口尺寸（1280×720 / 1440×900 / 1920×1080）下无布局错乱。

---

## 7. UI 审查清单（M4 用）

- [ ] 所有页面只使用 `components.css` 的类，无孤立样式
- [ ] 没有页面自定颜色（全部走令牌）
- [ ] 导航由 `/api/nav` 驱动，新增功能无需改外壳
- [ ] 每个长任务都有进度 + 取消
- [ ] 每个破坏性操作都有二次确认且写明备份位置
- [ ] 错误提示是中文可读文本
- [ ] 1280×720 下无横向滚动条（表格除外）

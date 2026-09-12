# AGENTS.md —— 给下一个 AI 的开工指令

> 本文件是**接手本工程的第一入口**。读完本文件 + `docs/STATE.md`，你就能开始工作。
> 最后更新：**M2b（2/3）完成时**。

---

## 0. 这个工程是什么

把两个原本独立、各自能跑的 RPG Maker 工具合并成一个**统一的游戏修改全能工具**：

| 来源（只读参照，永不修改） | 能力 |
| --- | --- |
| `D:\test1\rpgtool\rpgmaker_translation_tool` | 文本提取 / 翻译 / 生成汉化版 / 字体注入 |
| `D:\test1\rpgtool\rpgmaker_cheating_tool` | 存档与游戏数据修改（金币/道具/角色/开关变量） |

**工程根目录**：`D:\test1\Tudou_RPGTool\TudouRPGTool\`
（⚠ 注意有两层 `Tudou_RPGTool\TudouRPGTool`；外层只是容器，git 仓库在内层。
需求文档 §4.3 建议的 `rpgtool\rpgmaker_allinone` **未采用**，见 `docs/OPEN-QUESTIONS.md` Q-01。）

---

## 1. 按顺序读这些文件

| 顺序 | 文件 | 为什么读 |
| --- | --- | --- |
| 1 | `docs/STATE.md` | **当前状态快照**：已完成 / 进行中 / 已知缺陷 / 下一步 |
| 2 | `docs/ARCHITECTURE.md` | 分层、数据流、依赖方向、关键设计取舍 |
| 3 | `docs/MODULES.md` | 要改某个文件时：它负责什么、公开 API、谁调用它、改动影响面 |
| 4 | `docs/FEATURES.md` | 要新增/修改功能时：契约 + 完整步骤 |
| 5 | `docs/DECISIONS.md` | 为什么是这样（ADR），别重复推翻已定的决策 |
| 6 | `docs/UI_SPEC.md` | 改界面时：设计令牌、组件、交互范式 |
| 7 | `docs/M0-现状测绘.md` | 两个原工具的完整测绘 + **29 条已知缺陷台账** |
| 8 | `docs/迁移对照表.md` | 原功能 → 新位置 → 测试 → 验证状态（"没丢功能"的证明） |
| 9 | `docs/DEVLOG.md` | 历史足迹（追加式时间线） |
| 10 | `docs/ROADMAP.md` | 已规划未做的功能与扩展点 |

机器可读版本：`docs/footprint.json`（功能 → 文件 → 公开 API → 测试 → 命令）。

---

## 2. 硬约束（不可协商，违反即 P0/P1）

1. **零第三方依赖** —— 只允许 Python 标准库。连**测试**也不许 `import requests`
   （这正是原工具踩过的坑：`tests/test_e2e.py:15`、`tests/test_pipeline.py:15`）。
   `tests/integration/test_startup.py` 会用 AST 扫描全部源码强制这条。
2. **Python 3.8+ 兼容** —— 不得用 `list[int]`、`dict | None` 等 3.9+ 语法。
   同一测试文件里有静态检查。
3. **任何写回前必须备份，且可还原** —— 一律走 `core/safety/atomic.py`
   与 `core/safety/backup.py`，**禁止**页面上或功能里直接 `open(path, "wb")`。
   这条由 `tests/compat/test_m2a_regressions.py` 用 **AST 扫描**强制
   （查真正的写模式 `open` 调用；不能用字符串匹配 —— 文档字符串里会描述原实现）。
   违规的也是 `core/safety/builder.py` 的 `confirm_overwrite`：覆盖原游戏/已有输出
   必须显式确认，否则抛 `OverwriteNotConfirmed`。
4. **未修改的内容字节级原样保留** —— 由 roundtrip 测试强制
   （`tests/compat/test_marshal_compat.py`，300 个真实样本零漂移）。
5. **破坏性操作二次确认** —— 覆盖原游戏 / 写回原存档 / 还原备份 / 删输出目录。
6. **默认只写副本** —— 处理用户游戏目录时；覆盖原文件是高级选项且要显示备份路径。
7. **中文界面、UTF-8** —— 所有文件读写**显式指定编码**（避免 GBK 环境乱码）。
8. **不修改两个参考目录** —— 它们是回退参照，且本身仍是可运行的工具。

---

## 3. 目录约定

```text
TudouRPGTool/
├─ app.py                  # 唯一入口：装配 core/ui/features 并启动服务
├─ core/                   # 与 UI 无关的纯逻辑（不得 import ui / features）
│  ├─ engines.py           # 引擎识别 + 数据/存档目录发现（唯一实现）
│  ├─ constants.py         # 引擎常量唯一真源
│  ├─ registry.py          # 功能模块自动发现与装配（扩展核心）
│  ├─ context.py           # register(ctx) 的契约：Router / PageSpec / AppContext
│  ├─ jobs.py              # 后台任务队列（有界并发、每任务取消、TTL 回收）
│  ├─ config.py paths.py textutil.py
│  ├─ marshal/             # Ruby Marshal（doc_model + value_model，M2b 收敛为一份）
│  ├─ formats/             # mv_mz_data / rgss_data / mv_save / rgss_save / lzstring
│  └─ safety/              # atomic（原子写）/ backup（备份还原）/
│                          # builder（生成汉化版编排）/ fontutil（字体）
│                          # ⚠ 依赖方向单向：atomic ← backup ← builder → fontutil
│                          #   backup **不得** import core.formats（会形成 import 环）
├─ features/               # 一个目录 = 一个可插拔功能模块
│  ├─ translate/
│  └─ cheats/
├─ ui/                     # 界面层
│  ├─ server.py routes.py
│  └─ web/                 # index.html app.js dom.js tokens.css components.css pages/
├─ tests/                  # unit / compat / features / integration / local
├─ tools/                  # check_footprint.py gen_footprint.py
├─ docs/                   # 足迹系统全套
└─ runtime/                # 运行时数据（gitignore）：sessions/ logs/
```

**依赖方向单向**：`features` → `core`，`ui` → `core` + `features` 的公开接口。
`core` **不得** import `ui` 或 `features`（`check_footprint.py` F-09 静态强制）。

---

## 4. 常用命令

```powershell
# 工程根
cd D:\test1\Tudou_RPGTool\TudouRPGTool

# 启动（会打印自检报告，然后打开浏览器）
python app.py
python app.py --port 8765 --no-browser
python app.py --check              # 只自检并退出（退出码 0=通过）
python app.py --check --json       # 机器可读

# 测试（统一入口，退出码可信）
python tests/run_all.py            # unit + compat + features + integration
python tests/run_all.py --suite unit
python tests/run_all.py --with-local   # 追加真实样本层
python tests/run_all.py --list     # 看各层用例数

# 足迹校验（必须退出码 0）
python tools/check_footprint.py
python tools/check_footprint.py --json
python tools/gen_footprint.py      # 源码变动后刷新 footprint.json
python tools/gen_footprint.py --check   # 只比较不写盘

# 真实样本测试（样本不入库；用环境变量指向本机游戏库）
$env:TUDOU_RPGTOOL_SAMPLES = 'D:\gamess'
python tests/run_all.py --suite compat
```

### 环境变量

| 变量 | 作用 | 默认 |
| --- | --- | --- |
| `TUDOU_RPGTOOL_ROOT` | 覆盖工程根（测试隔离用） | 本文件所在目录 |
| `TUDOU_RPGTOOL_DATA` | 覆盖运行时数据目录 | `<root>/runtime` |
| `TUDOU_RPGTOOL_REFERENCE_ROOT` | 两个参考工具的父目录 | `D:\test1\rpgtool` |
| `TUDOU_RPGTOOL_SAMPLES` | 真实游戏样本根（**不入库**） | `D:\gamess`（若存在） |

---

## 5. 变更三连（不可省略）

任何一次改动都必须同时包含：**代码 + 测试 + 足迹更新**。三者缺一，评审按 `P1` 处理。

具体动作：

1. 写代码（新文件必须带 `@feature` / `@layer` / `@public` / `@depends` / `@tested` / `@footprint` 足迹头）
2. 写/改测试（`tests/<层>/...`）
3. 跑三条命令并确认退出码为 0：
   ```powershell
   python tests/run_all.py
   python tools/gen_footprint.py      # 有新文件/新功能时必须
   python tools/check_footprint.py
   ```
4. 更新 `docs/STATE.md`（状态快照）与 `docs/DEVLOG.md`（追加式时间线）
5. 架构/决策有变 → 更新 `docs/ARCHITECTURE.md` / `docs/DECISIONS.md`
6. 界面有变 → 更新 `docs/UI_SPEC.md`

---

## 6. 提交规范

* 一个里程碑一个（或几个）提交，提交信息用中文，说明"改了什么 + 为什么 + 怎么验证"。
* 提交信息里**必须**包含验证证据（执行了什么命令、结果如何）。
* 不要把 `config.json` / `sessions/` / `runtime/` / `*.bak` / 汉化备份 / 游戏样本提交进去
  （`.gitignore` 已覆盖，但请自查 `git status`）。
* 不要提交游戏数据文件、游戏文本内容、API Key。

---

## 7. 当前进度与下一步

见 `docs/STATE.md`。里程碑顺序：

`M0 现状测绘`（✅）→ `M1 骨架与足迹`（✅）→ `M2a 可信基线 + P0 修复`
→ `M2b core 收敛` → `M3a 翻译接入` → `M3b 修改接入` → `M4 UI 统一` → `M5 验收硬化`

**M2b（2/3）结束时仍存在的临时状态**（下一个 AI 必须知道）：

* `core/marshal/` 里**有两份实现**（`doc_model` 与 `value_model`）——临时状态，
  M2b 收敛为一份（方向见 **ADR-004**）。验收硬指标：两侧 roundtrip 断言同时通过。
* ~~`core/_refbridge.py`~~ **已在 M2b 删除**。它的"与旧实现等价"证据已冻结为
  `tests/unit/test_engines.py` 的 `TestFrozenRealGameBaseline`（7 个真实游戏）
  与 `TestFrozenDetectionFixtures`（13 种判据组合，两套 MV/MZ 判据都覆盖）。
* ~~`core/formats/` 尚未抽出共享的 `jsoncodec.py`~~ **已在 M2b 抽出**：
  MV/MZ 两条路径共用一份 JSON / 压缩 / 加密包装实现，
  `core/formats/__init__.py` 的 `CONVERGENCE_STATUS == "merged"`。
* `features/translate/translators.py` 与 `session.py` 是 vendored 代码，
  M3a 接线为正式模块；两个功能页仍是骨架（`status: skeleton`）。

**P0/P1 缺陷已在 M2a 全部修完**（B-01/02/03/04/05/06/07/10/11/26 + N-07/08），
每条都有回归断言在 `tests/compat/test_m2a_regressions.py`。
**改 `core/safety/builder.py` 或 `core/marshal/` 之前必须先读 `docs/STATE.md` §5** ——
那里记录了每个缺陷的位置与修法，改坏会立刻让回归测试红灯。

# 当前状态快照（STATE）

> **接手本工程第一份要读的文件。** 读完本文件你就能说清"系统有哪几个功能、各自改哪里"。
> 每个里程碑结束时更新。最后更新：**M5 之后（开始加功能）**。

---

## 1. 一句话状态

**M0 ～ M5 已全部交付**（需求 §8 的 8 项判据逐条落地，见 §2），
之后按用户反馈修掉 6 个缺陷（N-23 ～ N-28），
现在**进入"加功能"阶段**（用户明确要求：不再修 bug，往上加功能）。

已交付的两个功能（后端 + 前端都接通）：

* **文本翻译**：扫描 → 编辑 → 批量翻译 → 生成汉化版 → 备份还原（17 个端点 + 五张卡片）
* **存档修改**：读档 → 改金币/道具/角色/开关变量 → 写回存档 → 数据表编辑 → 备份还原
  （**21 个端点** + 六张卡片；含新加的图标两个端点）

另有第三个功能 `selfcheck`（环境自检，1 个端点）—— 它是需求 §8-6
"扩展性"的活演示：**新增功能不改外壳一行**。

外壳级能力（不属任何功能）：**「最近打开」下拉**（`/api/recent` 等 4 个端点）——
翻译与改档都往里记，点一下就能切换游戏。

**加功能阶段的候选清单在 `docs/ROADMAP.md` §5**（F-01 ～ F-09，每条都写了
价值/落点/验收判据）。已完成的：**F-10 游戏内图标**（§5.1）、
**F-09 最近打开的游戏**（§5.2）。

---

## 2. 里程碑进度

| 里程碑 | 状态 | 完成判据 | 实测结果 |
| --- | --- | --- | --- |
| M0 现状测绘 | ✅ 完成 | 每条功能都有"原位置 → 新位置"映射 | `docs/M0-现状测绘.md`、`docs/迁移对照表.md`（99 条映射） |
| M1 骨架与足迹 | ✅ 完成 | 空壳可启动，足迹校验通过 | `python app.py --check` 退出码 0；足迹校验 0 错误 |
| M2a 可信基线 + P0 修复 | ✅ 完成 | 测试可一键跑且退出码可信；P0 缺陷有回归断言 | 5 个 P0 + 4 个 P1 已修；合成 VX/XP 样本覆盖 B-10 活路径 |
| **M2b core 收敛** | ✅ **完成** | 三类职责各只有一份实现 | `all_merged == true`；`value_model.py` 与 `_refbridge.py` 已删除 |
| **M3a 翻译功能接入** | ✅ **完成** | 扫描→翻译→生成汉化版→还原 全链路走通 | 17 个端点 + 五张卡片 + MV/VX Ace 端到端构建写回还原 + 真实 HTTP 烟测 |
| **M3b 修改功能接入** | ✅ **完成** | 5 类存档读写改回读在界面走通 | 18 个端点 + 六张卡片 + MV/VX Ace 端到端改档写回还原 + 数据表编辑（34 个字段规则） |
| **M4 UI 统一** | ✅ **完成（机械部分）** | UI 审查通过，无孤立样式 | `tests/integration/test_ui_consistency.py`（18 例）：3 个页面共 31 个类全部来自 `components.css`、无硬编码色值、令牌引用全部已定义、响应式成因已钉住；**人工走查步骤见 `docs/UI_SPEC.md` §7.1** |
| **M5 验收硬化** | ✅ **完成** | 需求 §8 的 8 项全过 | ✅ 1 启动 / ✅ 2 翻译回归（4 引擎）/ ✅ 3 修改回归（5 格式）/ ✅ 4 无损性 / ✅ 5 安全性 / ✅ 6 扩展性 / ✅ 7 足迹 / ✅ 8 UI（机械部分，人工走查仍待做） |
| **加功能阶段** | 🔄 **进行中** | 按 `docs/ROADMAP.md` §5 清单往上加 | ✅ **F-10 游戏内图标**（见 §5.1）；✅ **F-09 最近打开的游戏**（见 §5.2）；⬜ F-01 差异报告 … |

---

## 3. 系统有哪几个功能，各自改哪里

> 这是"3 分钟内说清楚"的那一段。详细文件地图见 `docs/MODULES.md`，
> 功能注册表见 `docs/FEATURES.md`。

| 功能 id | 用户可见名 | 界面入口 | 后端入口 | 核心实现文件 |
| --- | --- | --- | --- | --- |
| `translate` | 文本翻译 | `ui/web/pages/translate.js` | `features/translate/manifest.py` → `routes.register_routes` | `core/formats/mv_mz_data.py`、`core/formats/rgss_data.py`、`core/safety/builder.py`、`core/safety/backup.py`、`features/translate/translators.py` |
| `cheats` | 存档修改 | `ui/web/pages/cheats.js` | `features/cheats/manifest.py` → `routes.register_routes` | `core/formats/mv_save.py`、`core/formats/rgss_save.py`、`features/cheats/data_fields.py`、`core/marshal/`、`core/iconutil.py`（道具图标） |
| `selfcheck` | 环境自检 | `ui/web/pages/selfcheck.js` | `features/selfcheck/manifest.py` → `register(ctx)`（单端点，不拆 routes） | `features/selfcheck/manifest.py`（只读，无 core 写回路径） |

**跨功能的公共地基**（改这些会影响所有功能，务必先读 `docs/MODULES.md`）：

| 文件 | 一句话职责 | 改动影响面 |
| --- | --- | --- |
| `core/engines.py` | 引擎识别 + 数据/存档目录发现 | 两个功能都依赖；改它会同时影响翻译扫描与存档修改 |
| `core/registry.py` + `core/context.py` | 功能发现与装配契约 | 改它影响所有功能的注册方式 |
| `core/safety/atomic.py` | **唯一的写盘手段**（原子写 + 备份 + 护栏） | 改它影响所有写回路径的数据安全 |
| `core/safety/backup.py` | 备份 / 还原 / 清单（**不依赖 formats**） | 两个功能共用（生成汉化版 / 改存档都要还原能力） |
| `core/safety/builder.py` | 生成汉化版与字体应用的编排层（暂存换名 + 失败回滚） | 改它影响"生成汉化版"整条链路 |
| `core/jobs.py` | 后台任务队列 | 改它影响所有长任务的进度/取消 |
| `ui/server.py` + `ui/web/dom.js` | HTTP 层与前端共享工具 | 改它影响所有页面 |

---

## 4. M1 实际交付了什么（可验证）

### 4.1 唯一入口

```powershell
cd D:\test1\Tudou_RPGTool\TudouRPGTool
python app.py --check      # 退出码 0
python app.py              # 启动并打开浏览器
```

`app.py --check` 的实测输出：

```text
RPG Maker 全能工具 v2.0.0-dev  (Python 3.10.9)
工程根目录：D:\test1\Tudou_RPGTool\TudouRPGTool
已加载的功能模块：文本翻译(translate)、存档修改(cheats)
  · 注册 cheats     -> registered (skeleton)
  · 注册 translate  -> registered (skeleton)
已登记路由：14 条
自检结果：通过
```

### 4.2 已完成且**真的可用**的能力（M1 就能端到端验证）

| 能力 | 说明 | 证据 |
| --- | --- | --- |
| **引擎识别（合并后唯一实现）** | 从第一天起就只有一份实现，同时保留两套 MV/MZ 判据（`*_managers.js` 与 `*_core.js`）+ `System.json` 兜底 | 7 个真实游戏上与**两个**旧实现判定 100% 一致；补上了旧翻译工具识别不出的 **VX（`.rvdata`）** |
| **存档发现** | 5 类命名规则 + 多存档目录探测（应对自动存档） | 与旧修改工具在 6 个真实游戏上结果一致（3/0/24/2/1/9 个存档） |
| **Marshal 字节级往返** | `core/marshal/doc_model` | **300 个真实 `.rvdata2` 零漂移** |
| **原子写入与备份** | `core/safety/atomic.py`（原工具全部为非原子写） | 写入失败时原文件字节不变；并发写不产生撕裂 |
| **任务队列** | 有界并发 / 每任务取消 / TTL 回收（原实现三者皆无） | 5 个取消相关用例 + 并发上限实测 |
| **功能自动发现** | 新建 `features/<name>/manifest.py` 即被注册，导航自动出现 | `/api/nav` 返回 `['translate','cheats']` |
| **Web 外壳** | 显式路由表（替代 `if/elif` 长链）+ 统一错误结构 + Host/Origin 白名单 + 路径穿越防护 | 14 条路由；`/../app.py` 被拒（400） |

### 4.3 足迹系统

| 文件 | 状态 |
| --- | --- |
| `AGENTS.md` | ✅ |
| `docs/STATE.md` | ✅（本文件） |
| `docs/ARCHITECTURE.md` | ✅ |
| `docs/MODULES.md` | ✅ |
| `docs/FEATURES.md` | ✅ |
| `docs/DECISIONS.md` | ✅ |
| `docs/DEVLOG.md` | ✅ |
| `docs/UI_SPEC.md` | ✅ |
| `docs/ROADMAP.md` | ✅ |
| `docs/footprint.json` | ✅ 39 文件 / 2 功能（由 `tools/gen_footprint.py` 从源码生成） |
| `docs/OPEN-QUESTIONS.md` | ✅ |
| `docs/M0-现状测绘.md`、`docs/迁移对照表.md` | ✅ |
| `tools/check_footprint.py` | ✅ 12 条规则，**会真的失败**（每条规则都有触发用例） |

---

## 5. 已知缺陷台账

> 完整 29 条见 `docs/M0-现状测绘.md` §4。
> **M2a 已修完所有 P0 与关键 P1**（下表 ✅ 条目均有回归断言）。

### P0（阻断级：会丢功能或损坏用户文件）—— **全部已修**

| 编号 | 位置 | 问题 | M2a 处置 |
| --- | --- | --- | --- |
| **B-01** ✅ | `core/safety/builder.py` | 覆盖已有输出目录时先 `rmtree` 再拷贝，中途失败旧输出永久丢失 | 改为**暂存目录 + 原子换名**：先拷到 `<dst>.__staging_*`，成功后把旧目录移开 → 换名 → 删旧；失败只清理暂存。回归：`test_old_output_survives_when_copy_fails` |
| **B-02** ✅ | `core/formats/{mv_mz_data,rgss_data}.py`、`core/safety/{builder,backup}.py` | 游戏数据/存档写回**非原子**（`open("wb")` 直接截断） | 全部改走 `core/safety/atomic.py`。回归：AST 扫描"禁止写模式 open" + 写入失败原文件字节不变 |
| **B-03** ✅ | `core/safety/builder.py` | 字体兜底覆盖 `gamefont.ttf` / `mplus-1m-regular.ttf`，但这两个路径不在备份清单里 → 无法还原 | `font_touched_paths()` 无条件登记这两个路径；回归：`test_fallback_overwrite_can_be_restored` 走真实 build+restore |
| **B-10** ✅ | `core/marshal/doc_model.py` | `Parser._fixnum` **重复定义**（后一处覆盖前一处）→ XP/VX 按变体解析、按标准写回，字节漂移 | 删除重复定义，只留尊重 `self.standard` 的一版。**另发现并修复第二处**：标准编码 `_fixnum_to_bytes_std` 把单字节上限写成 122，而 `0x7B` 是长格式标记 → 118..122 会错位，正确上限是 **117**。回归：`tests/compat/test_standard_mode.py` |
| **B-11** ✅ | `core/marshal/doc_model.py` | `to_py()` 有 10 个类未实现，而 `Array`/`Hash` 会递归调用 → 真实数据调用即抛 | 补齐全部 10 个类（`HashDef`/`Struct`/`Userdef`/`Usermarshal`/`UsermarshalRaw`/`ObjectNode`/`Ivar`/`Regexp`/`ClassNode`/`ModuleNode`），统一约定：内建类型直返，Ruby 独有结构返回带 `"__ruby__"` 标记的 dict |

### P1（必修）

| 编号 | 位置 | 问题 |
| --- | --- | --- |
| B-04 | `core/safety/backup.py` | 还原不完整：新增的字体文件不会被删除；还原本身不备份、非原子 |
| B-05 | `core/safety/backup.py` + 前端 | **覆盖原游戏没有二次确认对话框**（违反硬约束 §4.2） |
| B-06 | `core/safety/backup.py` | `build()` 无 try/except、无回滚；copy 模式失败留半成品 |
| B-07 | `core/formats/rgss_save.py` 相关 | 修改工具备份 `OSError` 被静默忽略后仍写档 |
| B-13 | `core/formats/rgss_data.py` | `_set_value(..., original)` 的 `original` 参数从未使用 → 不做陈旧性校验，按 path 盲写 |
| B-20 | `ui/server.py`（**已部分修复**） | M1 已加 Host/Origin 白名单；仍需评估 `/api/quit` 等敏感接口 |
| B-21 | `ui/web/dom.js`（**已修复**） | `escapeHTML` 已补齐 5 个字符转义；`el()` 构造器替代字符串拼 HTML |
| B-22 | `core/jobs.py`（**已修复**） | 已实现有界并发、每任务取消、TTL 回收、快照副本 |
| B-23 | `ui/web/dom.js`（**已修复**） | `waitJob` 已加总超时与任务丢失容忍 |
| B-26 | `core/safety/backup.py` | 模块顶层 `import winreg` → 非 Windows 上导入即失败 |

### M1 期间**新发现**的问题（不在 M0 台账中）

| 编号 | 位置 | 问题 | 状态 |
| --- | --- | --- | --- |
| **N-01** | `core/formats/mv_mz_data.py` | **402（显示选择项）的选项文本全部或部分丢失**。真实形状是 `[["是","否"], cancelType, defaultType]`（`parameters[0]` 是列表），原实现按单值处理 → 嵌套形状下**整个选择项丢失**。已修：新增 `_MULTI_VALUE_CODES` + `_choice_texts()`，两种形状都支持 | ✅ M1 已修 + 有测试 |
| **N-02** | `core/textutil.py` | `has_real_text("\\V[1]")` 原返回 True（因控制码里的 `V` 是字母）→ **纯控制码会被送去翻译**，破坏游戏变量引用。已修：先剥离控制码再判定 | ✅ M1 已修 + 有测试 |
| **N-03** | `ui/server.py` | 畸形 JSON 请求体（`{not json`）被退化成表单解析，处理器拿到垃圾键值。已修：声明 JSON 却解析失败时保留原文并标记 `_parse_error` | ✅ M1 已修 + 有测试 |
| **N-04** | `core/registry.py` | 功能发现用 `pkgutil.iter_modules` 的 `ispkg` 过滤，会**静默跳过**缺 `__init__.py` 的功能目录（最该报错的情形）。已修：直接列目录逐个判定并报错 | ✅ M1 已修 + 有测试 |
| **N-05** | `core/context.py` | 未命名路由默认用 `handler.__name__`，一堆 lambda 会得到同名 `<lambda>` → 误报"路由名重复" | ✅ M1 已修 + 有测试 |
| **N-06** | `core/jobs.py` | **终态竞态**：先写 `status="error"` 再写 `traceback`，轮询方会读到"已失败但没有 traceback"的半成品 | ✅ M1 已修：新增 `Job.finalize()` 在锁内一次性发布终态 |
| **N-07** | `core/formats/rgss_data.py` | 多值条目的写回路径（`.../parameters/0/0`）在 RGSS 侧不被支持 → 译文落不下去 | ✅ **M2a 已修**：`_navigate`/`_set_value` 重写为 `_step`/`_index`/`_rmobject_key`，支持"列表里的列表"与非前缀 ivar 键；非整数段抛明确的 `KeyError` |
| **N-08** | `core/textutil.py` | 注释声称支持符号型转义，但 `CONTROL_RE` 要求反斜杠后必须是字母 → 从不被匹配 | ✅ **M2a 已修**：补齐符号型分支并收紧字母型（`{1,2}` + 不允许 `[` 紧跟，修掉 `\G你好` 被读成 `\G你` 的问题） |

### M2a 期间**新发现**的问题

| 编号 | 位置 | 问题 | 状态 |
| --- | --- | --- | --- |
| **N-09** | `core/formats/rgss_save.py` | `read_actors` / `set_actor_attr` / `set_actor_skills` 写死 `[v for k,v in actors_node.ivars][0]`，假设容器是**对象**（`Game_Actors`）。但 stock XP/VX 存档里它是**数组** → `AttributeError: 'Array' object has no attribute 'ivars'`，整条 RGSS 存档读写不可用 | ✅ **M2a 已修**：新增 `_as_array()` 归一化两种形态（对象取 `@data`，数组直接用）。**由合成 VX/XP 样本暴露** |
| **N-10** | `core/marshal/doc_model.py` | 标准编码 `_fixnum_to_bytes_std` 把单字节上限写成 122，但 `0x7B` 是长格式标记 → **118..122 这五个值编码后被解析成垃圾并使后续流错位**（B-10 的第二处，与重复定义相互独立） | ✅ **M2a 已修**：上限改为 117（即 `0x06..0x7A`）。由合成样本的往返断言暴露（`struct.error: unpack requires a buffer of 4 bytes`） |
| **N-11** | `core/safety/__init__.py` ↔ `core/formats/__init__.py` | 拆分 safety 层时出现**循环 import**：`formats.__init__ → mv_mz_data → safety.__init__ → builder → formats.mv_mz_data` | ✅ **M2a 已修**：`core/safety/__init__.py` 改用 PEP 562 `__getattr__` 懒加载子模块（并让 `check_footprint` 的 F-05 认可这种写法） |

---

### M3a 接线期**新发现**的问题（**最危险的一类：静默丢功能**）

M2b 的 marshal 收敛完成后，把 `rgss_data.py` 切到 `value_layer`。**VX Ace 的
提取量从 6 千余条掉到 115 条，而且不报错。** 三个原因叠加，逐个修掉：

| 编号 | 位置 | 问题 | 修法 |
| --- | --- | --- | --- |
| **N-12** | `core/formats/rgss_data.py` | `RPG::Map#@events` 是 **Hash**（键为事件 id），而 vendored 代码用 `enumerate` 当列表遍历 → `RMDict.__getitem__(0)` 抛 **`KeyError: 0`**，整张地图的地图事件全丢 | 新增 `_pairs_of()` / `_pairs_of_values()`，把 Array / Hash / 值层代理 / Ivar 包装统一成 `[(key, value)]`；所有遍历点改用它 |
| **N-13** | 同上 | 字符串在值层是 **`RMStr` 代理**，`isinstance(v, str)` 不成立 → `_text_of` 返回 `None` → 文本被判为"没有内容"；`@parameters` 还是 **Ivar 包装的数组**，`len()` 为 0 → 所有 401/402 对话被丢弃 | `_text_of` 分三层剥（`Ivar` → 带 `.value` 的代理 → 原生类型）；`@parameters` 取值后先 `_unwrap` |
| **N-14** | `core/marshal/doc_model.py` | **`SymLink`（符号表引用）没被解析** → `class_name` 退化成 `"symbol#6"` → 所有 `class_name == "RPG::EventCommand"` 判断失效、`_rmobject_key` 找不到 `@code`/`@parameters` | `_sym_name` 回查 `node._parser.symbols`；新增有界的模块级解析器登记表 `_PARSERS`（深层 SymLink 拿不到 `_parser`）；`loads` 改走 `load_streams`（只有它回填 `_parser`） |
| **N-15** | `core/formats/mv_mz_data.py` | MV/MZ 事件条目的路径**多拼了一层 `/list/`**（`1/list/list/1/parameters/0`）→ 扫描、统计、界面**全都正常**，但 `apply_to_files` 按路径写回时定位失败 → **事件对话与选择项全部写不进汉化版，且不报错**（表现："生成成功、数据库名词翻译了、剧情还是原文"）。同一函数里还有第二处：`_set_by_path` 只归一化中间段，末段仍是字符串 → `list[str]` 抛 `TypeError` 被上层吞掉 | ① 删除多余的一层 `list`（`path_prefix` 已含 `list`）；② `_set_by_path` 按父容器类型归一化末段键（`list` → `int`）。回归：`tests/features/translate/test_scan_regressions.py::TestN15MVEventPathShape`（4 例，含"路径必须定位到原文"与端到端写回），以及 `test_routes.py` 的 MV 构建用例 |

**为什么这几条最值得记**：N-12 ～ N-17 **全都不报错**，只表现为"译文变少了"、
"生成成功但游戏里没变"、"保存成功但数值没变"。如果只做接线不做**写回后的核对**，
它们会一路潜伏到用户投诉。**教训：接线阶段必须验证"写进去了"，
而不只是"扫描出来了"和"任务成功了"。**

**已加防护**：`tests/features/translate/test_scan_regressions.py`
* N-12/13/14 各自的单元断言（含"两遍构造"的符号表夹具）
* N-15 的路径形状断言 + **端到端写回**断言
* **真实样本量级断言**（`TestRealGameScanVolume`）：四个真实游戏的提取量下界，
  以及"VX Ace 必须包含对话而不只是界面术语" —— 提取量骤降会被测试抓到

**端到端写回防护**（M3a 新增）：`tests/features/translate/test_routes.py::TestBuildAndRestore`
在 MV 与 VX Ace 上**各跑一遍**完整链路，并断言：
构建后数据文件里**真的是译文**（而不是只看"任务成功"）、
`copy` 模式**原游戏目录字节不变**、覆盖必须 `confirm=true`、
`inplace` **一定生成备份**、还原后**原文真的回来了**。

### M3b 接线期**新发现**的问题（同一家族：接口说成功、文件没变）

| 编号 | 位置 | 问题 | 修法 |
| --- | --- | --- | --- |
| **N-16** | `core/formats/mv_mz_data.py`、`core/formats/rgss_data.py` | 写回层用 ``bool(translated)`` 判断"有没有值"，于是把字段改成 **``0`` / ``false``** 被当成"没有值"而**丢弃**。表现："把道具数量改成 0 没反应"、"关掉一个开关之后还在"。两条写回路径都中招 | 判据从"值真不真"改成"**字段在不在**且不是 None"（`_has_field` / `_entry_has`）。回归：`tests/features/cheats/test_writeback_regressions.py::TestN16ZeroAndFalseWrites`（含"翻译链路的 pending 仍然跳过"的反向断言） |
| **N-17** | `features/cheats/data_fields.py` | 陈旧性校验读的是 ``expect``，而界面与路由传的是 ``original`` → 校验**永远通过**，等于不存在。"防线看起来在、实际不生效"比没有防线更危险（评审时会以为已经防住了） | 新增 `expected_value()` 同时接受两个名字；写回层也做同样的 `expect` 校验。回归：`TestN17StaleCheckFieldName`（6 例） |
| **B-02 残留** | `core/formats/mv_save.py`、`core/formats/rgss_save.py` | M2a 只把"游戏数据/备份"改成了原子写，两个**存档**模块的 `save()` 还是 `open(path,'wb')` 直接截断 —— 而改存档恰恰是最容易毁玩家数据的操作（写到一半中断 = 存档报废） | 两条 `save()` 改走 `core.safety.atomic.atomic_write_bytes`；回归用"让 `os.replace` 失败"验证**原文件字节不变**（MV 与 RGSS 各一条） |
| **句柄泄漏** | 同上 | `open(path,'rb').read()` 链式调用不关句柄 —— Windows 上会让后续的替换/删除失败 | 改 `with` 语句；AST 断言禁止该写法复活 |

**已加防护**：
* `tests/features/cheats/test_routes.py`（109 例）：18 个端点双向契约、
  改内存/写盘两段式、写回必须确认、备份可还原、数据表编辑与陈旧性校验，
  **MV 与 VX Ace 各跑一遍**
* `tests/features/cheats/test_writeback_regressions.py`（20 例）：N-16 / N-17 / B-02 存档侧
* `tests/integration/test_cheats_page.py`（20 例）：页面静态契约

### M5 验收期**新发现**的问题（同一家族：不报错，但给出看起来合理的错误答案）

| 编号 | 位置 | 问题 | 修法 |
| --- | --- | --- | --- |
| **N-18** | `core/formats/rgss_data.py` | 数据文件扩展名白名单只有 `.rvdata2` / `.rxdata`，**漏了 VX 的 `.rvdata`** → 整个 VX 游戏扫出 0 条；第二处：`marshal.loads` 用默认（变体）编码，而 VX 是标准编码 | 新增 `RGSS_DATA_EXTS`；新增 `load_data_file(path, standard)` **两种编码都试**；`extract` / `apply_to_files` 接 `info["standard"]`。回归：`test_real_sample_regressions.py::TestN18VXDataFiles` |
| **N-19** | `core/formats/rgss_save.py` | 改造版 VX Ace 的存档是**两条流**（第 1 条是启动器元数据，第 2 条才是游戏状态），而 `read_party`/`read_actors`/`read_var` 硬编码 `streams[0]` → 真实存档读出来是"金币 0、没有角色、没有道具" | 新增 `state_index()`（找有 `party` 的流）+ `_target_streams()`（写操作跳过无状态的流，否则在 `None` 上取 ivar 会抛）。回归：`TestN19MultiStreamSave`（含真实样本用例） |
| **N-20** | `features/cheats/data_fields.py` | `load_data_file` 返回**值层代理**，而 `_to_plain` 按 doc_model 节点判定类型 → 每个分支都不成立 → 整文件读成 `None`（界面"一个可编辑字段都没有"） | 先 `value_layer.unwrap_to_node`。回归：`TestN20ProxyUnwrap` |
| **N-21** | `core/engines.py`、`ui/routes.py` | "收敛是否完成"有**两个来源**：`/api/health` 里 `engines` 是硬编码 `"merged"`，而自检页读 `core.engines.CONVERGENCE_STATUS`（**该常量不存在**）→ 自检页显示 `unknown`，与健康检查**互相矛盾**，两边都"成功返回" | 在 `core/engines.py` 补 `CONVERGENCE_STATUS`，两处都读它，`all_merged` 由三项现算。回归：`test_convergence_agrees_with_health` + `test_ui_routes_does_not_hardcode_convergence` |
| **N-22** | `启动.bat` | 双击启动优先 `py -3`（本机是 **3.14.5**），而文档/测试/`app.py --check` 用的是 PATH 上的 `python`（3.10.9）→ **用户路径与验证路径跑的不是同一个解释器** | `where python` 提前，`py -3` 兜底。回归：`test_bat_prefers_path_python_over_py_launcher` |

**这一家族的共同形态**：不报错，只给出**看起来合理**的错误答案。
N-16（0/False 被当"没有值"）、N-17（字段名不一致→校验空转）、
N-21（常量缺失→报告矛盾）、N-22（入口与开发环境不一致）都是这一类。
**防止办法是让断言比对"两个来源"，而不是各自断言"我这边对"。**

### **N-23（用户报告）**：前端白屏 —— app.js 的块注释被自己提前闭合

| 项 | 内容 |
| --- | --- |
| 现象 | 双击 `启动.bat` 后浏览器**永远停在「加载中…」**，没有可交互内容；无弹窗、无报错页 |
| 根因 | `ui/web/app.js` 的块注释里写了通配路径 `features/*` 与 `/manifest.py`，其中的**星号紧跟斜杠在注释内部提前闭合了注释** → 后面的中文散文变成代码 → `SyntaxError: Unexpected identifier '自动发现'` → ES 模块**一行都不执行** |
| 为何 880 个测试没抓到 | 它们**全是文本断言**（"有 export render"、"类名都在 components.css 里"、"端点存在"）。**没有任何一条真的解析或执行过这些 js** —— 文本对 ≠ 语法对 |
| 修法 | ① 注释改成 `features 下的 manifest.py`；② 新增 `tests/integration/test_web_syntax.py`（11 例）：`node --check` 静态语法 + `tools/web_probe.mjs`（Node 最小 DOM shim）**真实执行** `index.html` + `app.js`，逐个切换三个页面并报告卡片数与是否出现"页面加载失败" |
| 守卫有效性 | **把 bug 放回去验证过**：注入后 11 条断言全红，症状与用户描述一致（导航 0 项、功能表 0 行、三个页面均报 `SyntaxError: Unexpected identifier '自动发现'`）；还原后全绿 |
| 教训 | **"验证"必须覆盖被执行的东西。** Python 侧做到了（真 AST、真 roundtrip、真起服务打 HTTP），前端只停在文本层 —— 于是唯一一个"根本不执行"的失败模式恰好落在没人看的角落 |

### **N-24（用户报告）**：生成的汉化版副本里只有 `www`，没有 `Game.exe`

| 项 | 内容 |
| --- | --- |
| 现象 | 用户报告：「生成的汉化版副本只有 /www 的内容啊，外层的 game.exe 之类的没有一起生成副本吗？」——副本里没有运行时，**根本启动不了** |
| 根因 | `core/engines._mvmz_info` 把 `info["game_dir"]` **直接设成了 JSON 资源根**（老版 NW.js 布局下是 `<游戏根>/www`），因为它要用同一个值去拼 `data_dir`。而"生成汉化版（写副本）"复制的是 `info["game_dir"]` → 副本 = `www` 的内容。**两个概念被塞进了一个字段** |
| 为何测试没抓到 | 全部既有夹具都是"新版布局"（`js/`、`data/` 直接在游戏根），于是 `game_dir == js_root` 恒成立 —— 这个前提**从未被表示过，也就从未被检验**。这是"夹具比现实更整齐"导致的盲区 |
| 修法 | ① 拆字段：`game_dir` = **游戏根**（含 `Game.exe` 的那一层，等于用户选的那层），新增 `js_root` = JSON 资源根；`data_dir`/`save_dir`/字体/存档发现全部走 `js_root`。② 新增 `engines.game_root_for()`：用户**直接选中 `www`** 时也上溯到游戏根（仅在父目录确实有 `*.exe`/`package.json`/`nw.dll` 时才上溯，避免误判普通同名目录）。③ 新增 `engines.game_root()` / `js_root()` 便捷访问器。④ `builder` 的 copy 结果回传 `source_dir`/`copied_files` 并在 notes 里写明"已复制游戏目录：…（共 N 个文件）"；游戏根下没有 `Game.exe` 时额外给提示 |
| 守卫有效性 | **把旧行为放回去验证过**：注入 `_mvmz_info(engine, js_root, js_root)` 后，`test_copy_scope.py` 报出与用户描述**逐字一致**的失败：`'Game.exe' not found in ['data', 'js', 'save']`；还原后 16 例全过 |
| 真实样本实测 | 在 `boli3/RJ01052631` 的**副本**上跑：扫描 45,666 条 → 写副本 → 副本根含 `Game.exe`/`nw.dll`/`www/data`，共复制 1,535 个文件；原游戏文件数 1535 → 1535（未改动） |
| 教训 | **夹具比现实更整齐，就会漏掉现实里的分支。** 之前 880+ 测试全绿，是因为没有一个夹具构造出"`game_dir != js_root`"这个真实且常见的形态 |

### **N-25（用户报告）**：对话没被翻译到 —— 地图事件路径缺 `list` 层（54.86% 丢失）

| 项 | 内容 |
| --- | --- |
| 现象 | 用户在做 MV 游戏（老版 www 布局）：会话里 **45,037 条全部标记已翻译**，但生成的汉化版里**对话还是日文** |
| 排查 | ① 读会话：数据完好（39,934 条对话都有译文）→ ② 查游戏目录：`data/*.json` 未改动、没有汉化版 → ③ 抽 path 去真实数据上定位：`Actors/Items/CommonEvents` 全 OK，`Map001.json` 的 `events/2/pages/0/1/parameters/0` 抛 `KeyError: 1` → ④ **全量测**：**24,709 / 45,037 = 54.86% 定位失败**，全是地图事件对话 |
| 根因 | `mv_mz_data.extract` 给**地图事件**拼路径时漏了 `list` 层（`events/%d/pages/%d`），而 `_walk_event_list` 内部拼的是 `"%s/%d/parameters/%d"`（下标是**指令在 list 里的位置**）。写回时 `_set_by_path` 在 dict 上取键 `"1"` 失败 → `KeyError` 被吞 → 整张地图的对话静默丢失。**与 N-15 完全同形态**；更阴险的是 `CommonEvents` 那条路径是**对的**，只有地图漏了 —— 上一轮修 N-15 时我改了两条相似调用点中的一条 |
| 修法 | ① `extract` 的地图路径前缀补 `/list`。② **新增 `tools/fix_session_paths.py`**：就地修已扫过的会话（用户已翻完 45,037 条，重扫会丢进度）；按正则补 `list` 并按新 key（`file|path`）重新归位；幂等、默认干跑、`--apply` 才写盘且先备份。③ **N-26**：跨盘输出（游戏在 D:、输出留成 `C:\Temp`）原先抛英文栈 `path is on mount 'C:', start on mount 'D:'` —— 跨盘其实可支持（暂存目录在目标盘旁，两次 `os.replace` 仍在同盘内），于是跳过相对路径检查、`copy_tree` 跨盘改走 `copyfile` + 保留时间戳 |
| 守卫有效性 | **把缺 `list` 的写法放回去**：测试立刻报 `'pages/0/1/' unexpectedly found in 'events/1/pages/0/1/parameters/0'`；还原后全过 |
| 用户会话实测 | 就地修复后：**可定位 45,037 / 45,037 = 100.00%**（修复前 45.14%）；端到端写副本：写回 45,037 条 / 164 个文件、复制 8,229 个文件、副本含 `Game.exe`、抽查三条地图对话均已是中文、原游戏时间戳未变 |

**N-25 现在由一条"全量"断言守住**：`test_no_entries_lost_across_the_whole_game`
与 `test_every_extracted_path_resolves_to_its_original` ——
"提取到的**每一条**路径都必须能在同一份数据里定位到原文"。
这条断言与"哪个文件、哪种事件、哪一层结构"无关，因此不会再有"漏改一处"的盲区。

### **N-27（用户报告）**：存档搜不到 —— 规则太窄，而且说不清原因

| 项 | 内容 |
| --- | --- |
| 现象 | 「存档修改板块搜索不到存档所在文件夹，是不是路径限制得太死了」 |
| 排查 | ① 统计整个样本库"像存档但认不出来"的名字：`filegameEnd.rpgsave`（通关存档，4 处）这类插件命名**一个都不认**；`config.*`/`global.*`/`shared.*` 是**正确的排除**（设置项不是进度）。② 用用户那个游戏实测：`www/save` 里只有 `config.rpgsave`（112 字节设置文件）—— **该游戏确实还没存过档**，但界面没告诉他这件事 |
| 修法 | ① MV/MZ 命名规则放宽为 `^file(?:\d+\|[A-Za-z_][\w-]*)\.(rpgsave\|rmmzsave)$`；② `find_save_dirs` 深度 `2 → 3`（够到 `save/auto`）；③ `save_dirs` 增加"常见但暂时为空"的存档目录名；④ 新增 `engines.list_other_save_files()` 与 `GET /api/cheats/find_saves`（兜底按扩展名全盘搜）；⑤saves 接口回传 `search` / `other_files` / `hint`；⑥ 页面空状态改为"说明原因 + 列出搜过的目录（可打开）+ 列出非存档文件及原因 + 手填路径 + 一键全盘搜" |
| 守卫 | `tests/features/cheats/test_save_discovery.py`（22 例）：命名变体、搜索范围、设置文件排除与解释、兜底搜索、提示文案 |
| 顺带修 | `www/save` 与 `www/Save` 在 Windows 上是同一目录 → 去重必须用 `os.path.normcase`（否则界面上出现两条一样的记录；`config.rpgsave` 也因此被列两遍） |
| 基线更正 | 冻结基线 `V5.9` 的存档数 `2 → 3`：该目录实际有 `file0`/`file19`/**`filegameEnd`** 三个槽位，旧规则漏了通关存档 —— **基线把"漏数"冻结成了正确值**。冻结基线在这里发挥了作用：它逼我确认"是规则改错了，还是基线本来就错"，而不是随手改数字 |

**教训**：「找不到」这类反馈里，用户要的往往不是"放宽规则"，而是"**告诉我为什么找不到**"。
这次两者都做了，但真正让用户能自助的是后者 ——
放宽规则只让样本库里一个游戏多认出一个文件；说清楚则让所有"找不到"的情况都能被用户自己判断。

### **N-28（用户报告）**：道具列表不如参考工具全 —— 只列了"已持有"

| 项 | 内容 |
| --- | --- |
| 现象 | 「修改工具里面读取出来的道具内容没有 rpgmaker_cheating_tool 全啊，只读出了人物身上自带有的道具」 |
| 对照 | 参考工具 `main.py:294-305` 的 `_refresh_inv` **遍历整张数据表**并显示 `counts.get(oid, 0)` —— 没持有的显示 0，这样用户才能**添加自己还没有的道具**。我们只列 `party['_items']` 里已有的键 → 未持有的一律看不见，**功能比参考工具窄** |
| 量化 | 用户那个游戏（`D:\test1\wdss2`）：数据表 **35 件**，身上只有 **2 件** → 界面上只有 2 行 |
| 修法 | ① `CheatsService.catalog()` 返回整张表 + 持有数（`{id, name, count, owned}`，按 id 升序）；`party_view()` 同时给 `items`（仅持有）与 `catalog`（整表）。② 数据表末尾的**占位条目**（有 id 没名字，真实游戏常见）在未持有时不列出 —— 否则用户以为能加一件叫 `#35` 的道具。③ 存档里有、数据表里没有的 id（MOD/换过表）标 `orphan` 保留显示，否则"背包里的东西在界面上看不见"。④ 页面默认显示整表，加**搜索**与**「只看已持有」**筛子 + 计数，加"持有/未持有"状态列 |
| 守卫 | `tests/features/cheats/test_item_catalog.py`（20 例，MV 与 VX Ace 各一遍）：整表是否列全、未持有 count 为 0、三个桶都有整表、"仅持有"是子集、**给未持有的道具并保存后真的进背包**、数量归零后条目仍在、按 id 排序、占位条目不列出、孤儿条目可见 |
| 实测 | 修复后该游戏列出 35 件道具（含未持有的 `药水`/`魔法药水`…）、4 把武器、4 件防具；前端 cheats 页文案 441 字 → **46,621 字** |

**教训**：这次是**"迁移时把功能做窄了"**，而且窄得不显眼 ——
列表能显示、能改数值、测试全绿，只是**少了"表里其它条目"**。
对照参考工具时，只看它"读取了什么"（`read_party`）不够，
还要看它**界面上呈现的是什么**（`_refresh_inv` 遍历的是 `self.gd.items`
而不是 `counts`）。**行为等价性要按"用户能看到/能做到什么"核对，
而不是按"调用了哪些函数"。**

---

## 5.1 M5 之后：新功能（不是修 bug，按用户要求往上加）

### **F-10（用户要求）**：道具/武器/防具前面显示**游戏内图标**

| 项 | 内容 |
| --- | --- |
| 需求原话 | 「在修改工具的页面添加一个小开关，功能是将列表中可修改的物品/装甲之类的东西前添加一个对应的游戏内图标，因为有些物品基本是文本乱码、编号数字、或者干脆没名字，如果在前方加入一个小图标，那么找到相对应的物体会更简单」 |
| 来源 | **两个参考工具都没有这个能力**（`docs/迁移对照表.md` 无对应项）—— 属于纯新增 |
| 落点 | 新增 `core/iconutil.py`（图集定位/解密/切片几何）→ `features/cheats/routes.py`（`icon_of` / `icon_meta` / `icon_sheet` + 两个端点）→ `ui/web/pages/cheats.js`（`buildIconSwitch` / `iconCell` / `nameCell`）+ `components.css` 的 `.switch` / `.icon-cell` |
| 关键事实 | 数据表里本来就有 `iconIndex`（RGSS 是 `@icon_index`）= "IconSet 里第几格"。所以**不需要任何图像处理**：后端给整张图 + `cell`/`columns`，界面用 CSS `background-position` 裁单格 |
| 几何 | 用真实样本量出来：MV/MZ `512x640` → **32px / 16 列 / 20 行**；VX Ace `384x1032`、`384x1272`、`384x1248`、`384x1440` → **24px / 16 列**。都固定 16 列，行数由高度定 |
| 加密 | MV 的 `.rpgmvp` 与 MZ 的 `.png_` 是**同一套**加壳：偏移 0..15 恒为 `RPGMV…` 伪头，偏移 16..31 = 真实 PNG 前 16 字节异或 `System.json` 的 `encryptionKey`，偏移 32.. 原样。**已用真实文件验证**：`IconSet.rpgmvp` 偏移 16..31 是 `021f4689 0310a5a5 …`，异或 key `8b4f08ce…` 后正好是 `89504e47 0d0a1a0a 0000000d 49484452`（PNG 签名 + IHDR） |
| 守卫 | `tests/unit/test_iconutil.py`（40 例，含**真实游戏字节锚点**）、`tests/features/cheats/test_item_icons.py`（19 例）、`tests/integration/test_web_syntax.py::TestWebProbeIconFlow`（7 例，**驱动真实界面**并断言每个图标的 CSS 坐标）、`tests/integration/test_cheats_page.py::TestIconToggle`（10 例，静态契约） |
| 实测 | 用户那个游戏（`D:\test1\wdss2`，图集是加密的 `.rpgmvp`）：页面上渲染出 **43 个图标格**（41 个真图标 + 2 个虚线空位），`icon 176 → -0px -352px`、`icon 20 → -128px -32px`，与"第 12 行第 1 列 / 第 2 行第 5 列"一致 |

**这次特意避开的两个坑**（都属于"看着正常、其实错了"）：

1. **换游戏后图集缓存没失效** → 会用新游戏的 `iconIndex` 去裁旧游戏的图集，
   画出来是**另一件道具的图标**，界面上完全看不出异常。
   修法：`open_game()` 里显式 `self._icon_cache = None`；守卫
   `test_item_icons.TestIconCacheInvalidation`（MV 32px → VX Ace 24px）。
2. **`iconIndex == 0` 被当成有效第 0 格** → 也会画出别的道具。
   修法：`0` 画虚线空位；守卫同时钉住 `icon_of` 里 `0` 与 `None` 的语义差别
   （`0` = 作者写了"不显示图标"，`None` = 这个表根本没有图标信息）。

**真实边界（如实降级，不猜）**：

* `D:\gamess\demon\DD_V07c_Windows`（MZ 破解版，带第三方汉化注入器
  `TrsData.bin`）的 `IconSet.png_` 用本机 **7 个真实游戏的 key 全试过都解不开**
  → 界面显示「图标图集已加密，解不开：用 System.json 里的 encryptionKey
  解不开（该图集可能被第三方汉化/破解工具改过）」并**把开关置灰**，
  其余功能完全不受影响。这条有断言（`test_real_broken_sample_raises_…`）。
* `D:\gamess\boli\B7794\博麗霊夢は洗脳されてしまいました`（VX Ace）的
  `Graphics/System` 是**空的**（被汉化工具剥掉了）→ 提示「找不到图标图集」，
  同样只是置灰开关。

### **F-09（用户选定）**：最近打开的游戏

| 项 | 内容 |
| --- | --- |
| 需求 | 从 `docs/ROADMAP.md` §5.1 的候选里选定；原描述"反复切换游戏时省事" |
| 落点 | 新增 `core/recent.py`（MRU 存储）→ `core/context.AppContext.recent`（懒构造）→ `ui/routes.py` 四个端点 → `ui/web/app.js` 的下拉 + `index.html` 的 `#recent` 挂载点 |
| 记录时机 | 两个功能的 `open_game` 各调一次 `core.recent.note_game(ctx, ...)`；翻译侧放在**缓存命中之前**，于是"复用已存会话"也会刷新它在列表里的位置 |
| 顺序判据 | **列表位置**而不是时间戳 —— 同一秒内连开两个游戏完全可能（自动扫描），按时间戳排会"顺序随机"。`record()` = 先删同项再插到最前，`when` 只做展示 |
| 页面契约 | 页面模块可**可选**导出 `openGame(path)`；外壳通过自定义事件 `recent-changed` 刷新下拉（页面不主动改外壳，符合需求 §8-6） |
| 失效目录 | **保留**并标 `exists=False`（可能只是暂时移走），界面显示为不可点；删除只由「清理失效项」显式触发 |
| 守卫 | `tests/unit/test_recent.py`（51 例，其中 11 例专喂坏数据：垃圾 JSON / 结构不对 / 同名目录占位 / 盘写不进去 / 残缺项 / 重复项）、`test_web_syntax.py::TestShellRecentDropdown`（7 例静态契约）+ `TestWebProbeIconFlow` 的 2 例端到端（通过界面打开游戏 → 下拉必须跟着更新） |
| 实测 | 活服务器上：`/api/cheats/open` wdss2 → 列表出现 `('wdss2','cheats','mv')`；再 `/api/translate/open` ToT → `[('ToT 1.16.2.2 CN1.0','translate','vxace'), ('wdss2','cheats','mv')]`；页面探针里下拉渲染出 2 条 + 操作行 |

**踩到并修掉的两个坑**：

1. **测试污染用户数据**：`recent.json` 的内容会直接显示在用户导航栏里，
   而 app 级测试用默认 runtime 目录 → 跑一次测试就往用户列表里塞临时游戏。
   修法：`test_web_syntax.isolate_runtime()` 把 `TUDOU_RPGTOOL_DATA` 指到临时目录
   （**在构造 App 之前**，因为 `App.__init__` 就会构造 `RecentGames`）。
2. **探针时序不稳**：原来 `mountPage` 后固定 `sleep(400)`，实测 8 次里有 1 次
   扑空（页面挂载要 await 一次动态 import），表现是"这一次跑通了、下一次没跑通"。
   修法：改成 `waitFor(元素出现)`，并把页面 `#toast` 的文字收进报告 ——
   失败时能直接看到原因，而不是只知道"没出现"。修后连跑 8 次全绿。

### **N-30（用户报告）**：TOT 的武器/防具"图标读取不对" —— 其实是列表里一半是空槽位

| 项 | 内容 |
| --- | --- |
| 现象 | 「这个图标读取的不是很对，比如 tot 的武器防具类的图标……对于 tot 有很多新绘图标，是不是加密太多导致无法查看到」 |
| **结论** | **不是加密问题**。用户那个 TOT 的图集是明文 PNG（只是隔行编码），而且游戏脚本自己写的取图标方式与我们**逐字一致**：`Window_Base:373-374` 是 `Cache.system("Iconset")` + `Rect.new(icon_index % 16 * 24, icon_index / 16 * 24, 24, 24)`（该游戏有 5 份脚本副本，全部如此）。我们选中 `Graphics/System/IconSet.png`（384×1032 = 688 格），与引擎一致；所有 `icon_index` 最大 636，**没有一个越界** |
| 排错过程 | ① 先量图集（6 个真实游戏：MV 32px / VX Ace 24px，都 16 列）；② 反查游戏脚本的取图标代码，确认与我们一致；③ 把图集裁成对照图**肉眼看**：索引 144 = 斧头（对上 `Hand Ax`）、145 = 拳套（对上 `Cestus`）、尾部 888–909 是明显的新绘图标（靴子/篝火/宝石/玫瑰）；④ 再量 catalog 到底给界面列了什么 |
| **真因** | catalog 把数据表里的**空槽位**全列出来了。N-28 写的判定是 `if not name and not count: continue`，而 `name` 来自 `_name_of()` —— 那个函数**从不返回空串**（取不到就回退 `#id`），所以这个条件**永远不成立**，"跳过占位条目"一条都没跳 |
| 量化 | `ToT 1.16.2.2 CN1.0`：武器 200 槽 → **122 个是空的**、防具 200 → 111 空、道具 400 → 275 空。界面上超过一半是 `#61`/`#62`… 配空白虚线框，看起来就是"图标读不出来" |
| 修法 | ① 新增 `_raw_name()` 专管"到底有没有名字"（与 `_name_of` 分工：后者管"界面显示什么"）；② 跳过判据改成 **没名字 ∧ 没图标 ∧ 没持有** —— 有图标也是线索，不能连它一起杀；③ 持有中的空槽位仍列出（背包里的东西不能看不见）；④ 跳过的数量通过 `catalog_stats[kind].hidden` 回传，**界面上写出来**（不许静默隐藏） |
| 顺带修的不对称 | MV 侧 `GameDataMV._load_names` 原来只按"有名字"入库，于是"有图标但没名字"的道具在界面上**彻底消失**；RGSS 侧本来就是无条件入库。现已对齐（有名字 **或** 有图标即入库） |
| 守卫 | `tests/features/cheats/test_item_catalog.py`（28 例，MV + VX Ace 各一遍）。**注回 bug 后 12 条断言变红**，确认不是空转 |
| 实测 | ToT：武器 200→**78 行**（75 有图标 / 3 无图标 / 残留占位 0），防具 200→**89 行**，道具 400→**125 行**；wdss2：道具 35→34 行（`#35` 空槽被隐藏，"啊啊啊啊"保留） |

**教训（这是本工程第二次栽在同一件事上）**：那条断言**名字、文档都写对了，
但从来没执行过** —— 夹具里根本没有空槽位，所以 `for` 循环体一次都没进。
上一课（AGENTS.md §7）写的是"夹具要覆盖现实里的分支"，这次的具体形态是
**"遍历型断言必须先在夹具里断言'病灶存在'"**：`test_item_catalog` 现在会先
`assertIn(oid, store)` 确认夹具真有那个空槽位，再去断言它被跳过 ——
否则夹具一改，断言就悄悄退化成恒真。

---

## 5.3 发布准备（用户要求"可以直接发 GitHub"）

| 项 | 做法 | 证据 |
| --- | --- | --- |
| 许可证 | 新增 `LICENSE`（**MIT**）。原先没有 —— 没有许可证的仓库默认"保留所有权利"，别人实际上不能合法使用/分发 | `test_readme_is_publishable` 断言 README 声明了 MIT **且** `LICENSE` 真实存在 |
| README | 重写为面向使用者的版本（中文为主 + 英文简介；目录、三个功能、真实 CLI 参数、安全约定、FAQ、隐私、开发者入口、文档索引、来源致谢、免责声明、许可证） | 5 条发布断言；官方一句 `python app.py --help` 对账 |
| **`.gitattributes`** | 补 `*.bat text eol=crlf`。原来只有 `* text=auto`，git 会把 `启动.bat` 规范化成 LF，别人 clone 下来可能**双击跑不起来** —— 这是唯一的入口脚本 | 全新 clone 里实测：`启动.bat` 43 个 CRLF、**0 个裸 LF**、纯 ASCII |
| **密钥防泄漏** | 新增 `tools/check_secrets.py` + 27 例测试；`.gitignore` 补 `config.local.json` / `*.key` / `*.pem` / `.env*` / `secrets.json` / `credentials.json`；新增不含密钥的 `config.example.json` | 见下 |
| 仓库体检 | 跟踪文件 123 个 / 1.73 MB；`config.json`、`runtime/`、样本、`*.bak` **都未被跟踪**；全历史扫描无密钥 | `python tools/check_secrets.py` 退出码 0 |
| 全新 clone 验证 | clone 到临时目录后**真的跑一遍**：`--check` 退出码 0（53 路由）→ 全量测试 0 失败 → 两边文件数一致 | 抓"本地有、从没 `git add`"这类翻车 |

### 密钥防泄漏：为什么必须扫**历史**

`.gitignore` 只挡"以后不再提交"。key 一旦进过**一次**提交，就永久留在 git 对象里，
`git push` 会把整个历史推上去 —— **本地 `git status` 干干净净，远端却有**。
所以 `check_secrets.py` 的判据是"所有提交里的所有 blob"，并且额外把本机
`config.json` 里的**真实值**拿去历史里精确匹配（报告只出打码形式）。

**实测**：本仓库全历史扫描**未发现任何密钥**，本机那个真 key 从未进过任何提交。

**过程中被自己的工具抓到的两件事**（都是"门禁会不会被无视"的问题）：

1. **假阳性**：工作区模式会把本机 `config.json` 报出来 —— 它已被 gitignore、
   根本不会被推送。报它只会训练用户无视这个工具，所以判据改成
   "**会被提交的文件**"（`ls-files` + `--others --exclude-standard`）。
2. **自绊**：测试夹具里的假 key 写成字面量时，扫描器把**自己的测试文件**
   报成泄漏（我甚至在"解释为什么不能写字面量"的注释里又写了一遍）。
   改成运行时拼接，并加 `TestSelfScan` 钉住这一点。

**性能**：第一版每个 blob 起一次 `git cat-file`，同样仓库要 **23.7 秒** ——
慢到没法进门禁，而"跑不起来的安全检查"等于没有检查。改成一次进程流式读后 **1.2 秒**。

⚠ **已知未处理的一项（等用户决定）**：仓库里仍有**本机绝对路径**
（`D:\test1\...` 40 处 / 9 文件，`D:\gamess\...` 50 处 / 16 文件，
`C:\Users\<用户名>` 2 处）。它们不是密钥，但会暴露机器目录布局。
这些路径是"实测证据"的一部分（见 §5.1/§5.2 的台账），删掉会削弱可复查性，
所以没有擅自处理。

### 真实样本扫描基线（M3a 实测，供后续对照）

| 游戏 | 引擎 | 条目数 | 对话 | 耗时 |
| --- | --- | --- | --- | --- |
| `boli\B7794\博麗霊夢は洗脳されてしまいました` | vxace | 16,547 | 15,545 | 1.5s |
| `JIANTATA\1-6\PC-1\ToT 1.16.2.2 CN1.0` | vxace | 48,103 | 45,731 | 11.8s |
| `痴女の触手 官中版\痴女の触手 官中版` | mv | 2,332 | 1,155 | 0.8s |
| `demon\DD_V07c_Windows\DD_V07c_Windows` | mz | 57,177 | 55,767 | 0.8s |

（另：原翻译工具的 `test_pipeline.py` 在同一个 VX Ace 样本上报 6,511 条，
那是它**只统计了部分文件**的结果；本工程覆盖更全，因此数值更高。）

---

## 6. 当前测试状态

```powershell
python tests/run_all.py                      # 1022 例，0 失败 0 错误
python tests/run_all.py --quiet              # 退出码 0
python tools/check_footprint.py --quiet      # 退出码 0（45 文件 / 3 功能）
python app.py --check                        # 退出码 0（49 条路由）
启动.bat                                     # 双击启动（等价于 python run.py）

# 前端冒烟（需 Node；没装则测试自动 skip）：
node --experimental-vm-modules tools/web_probe.mjs http://127.0.0.1:8765 ui/web

# 前端冒烟 + **真的驱动修改页**（填目录 → 点读取 → 点载入 → 数图标格）
node --experimental-vm-modules tools/web_probe.mjs http://127.0.0.1:8765 ui/web --game 'D:\test1\wdss2'
```

| 测试层 | 用例数 | 说明 |
| --- | --- | --- |
| `unit/` | 412 | 纯单元，零外部依赖（含 `test_sysdialog.py` 的 23 例、`test_iconutil.py` 的 40 例） |
| `compat/` | 98 | 原两个工具断言的可迁移版本 + **缺陷回归**（B-02/B-03/B-10/N-07…）+ **合成 VX/XP 样本** |
| `features/` | 376 | 三个功能模块的自有测试（translate 132 + cheats 227 + selfcheck 17） |
| `integration/` | 136 | 端到端链路 + 零第三方依赖扫描 + 3.8 语法扫描 + 页面静态契约 + **UI 统一性** + **启动入口（16）** + **验收回归（17）** + **前端真跑起来（18，含 7 例驱动界面数图标坐标）** |
| `local/` | 0（待补） | 真实样本层，靠 `TUDOU_RPGTOOL_SAMPLES` 指定；样本不入库 |

**F-10（游戏内图标）新增的测试重点**：

* `tests/unit/test_iconutil.py`（40 例）：解密算法用**真实游戏的 32 字节 + key**
  钉死（`021f4689…` 异或 `8b4f08ce…` 必须得到 `89504e47 0d0a1a0a…`）；
  另有一个**真实"解不开"样本**（破解版）断言必须抛错而不是返回乱码
* `tests/features/cheats/test_item_icons.py`（19 例）：MV/VX Ace 两套夹具，
  含 `0` 与 `None` 的语义区分、孤儿条目不编图标、**换游戏后缓存必须失效**
* `tests/integration/test_web_syntax.py::TestWebProbeIconFlow`（7 例）：
  真的点界面，断言每个图标的 CSS 坐标是 `(-160,0)` / `(-128,-32)` / `(-32,-32)`


**M3b 新增的测试重点**：

* `tests/features/cheats/test_routes.py`（109 例）：**改档全链路** ——
  打开游戏 → 选存档 → 改金币/道具/角色/开关变量 → 保存 → 重新解析文件核对 →
  还原回原字节；MV 与 VX Ace 两套夹具各跑一遍（VX Ace 侧还断言
  "数字字段写回后仍是 Fixnum，不是字符串"）
* `tests/features/cheats/test_writeback_regressions.py`（20 例）：N-16 / N-17 / B-02
* `tests/integration/test_cheats_page.py`（20 例）：页面静态契约（三处写操作
  都必须有二次确认、必须两段式交互、必须展示备份路径、多套存档目录必须提醒）

**真实样本覆盖**（设 `TUDOU_RPGTOOL_SAMPLES` 后）：

* **300 个真实 `.rvdata2` 字节级往返零漂移**（`test_marshal_compat.py`）
* 7 个真实游戏上与两个旧引擎识别实现判定 100% 一致

**⚠ 未设置环境变量时**，`test_marshal_compat.py::TestMarshalRoundtripRealSamples`
会 skip 而非失败。

**合成样本覆盖**（`tests/compat/test_standard_mode.py`，任何机器都能跑）：
本机没有 VX（`.rvdata`）与纯 XP（`.rxdata`）游戏，因此用代码生成最小存档，
覆盖 `standard=True`（XP/VX 的活路径）。**这套合成样本一加上就抓出了 N-09 与 N-10**，
证明"没有样本 = 没有证据"。

---

## 7. 下一步（M3a 剩余 → M3b）

按需求 §10 的 M3a 判据：**扫描 → 翻译 → 生成汉化版 → 还原 全链路在界面走通**。

### 7.1 功能接线（M3a 已完成 ✅）

落点：`features/translate/routes.py`（新建，17 个端点）+ `features/translate/manifest.py`（改为薄壳）
+ `ui/web/pages/translate.js`（五张卡片）。

| # | 任务 | 状态 | 证据 |
| --- | --- | --- | --- |
| 1 | 扫描：4 个开关（注释/备注/事件名/动画名）→ 后台任务 + 进度 | ✅ | `TestOpenAndScan`（MV 与 VX Ace 各跑一遍） |
| 2 | 文本列表：搜索 / 类别 / 状态 / 分页 / 行内编辑 / 批量跳过 | ✅ | `TestEntryPaging`（含"分页不重不漏"断言）+ 页面静态契约 |
| 3 | 4 个引擎适配器接线 + 设置持久化 + 接口自检 | ✅ | `TestConfigEndpoints` + `test_providers_ids_match_build_translator` |
| 4 | 批量翻译：进度 + 可中断 + 断点续传 | ✅ | 走 `ctx.jobs` + `_CancelBridge`；`TestJobEndpoints` |
| 5 | 生成汉化版：复制到新目录 / 覆盖原游戏（二次确认 + 备份路径） | ✅ | `TestBuildAndRestore`（MV 与 VX Ace 各跑一遍）+ 页面断言"必须 confirmDialog 且传 confirm:true" |
| 6 | 备份列表 + 还原入口 | ✅ | 同上：`list_backups` / `restore_backup` 端到端 |
| 7 | 字体应用（`font` 参数透传给 `builder.build` + 原生选字体） | ✅ | `apply_font` 已有 M2a 回归；`pick_font` 端点 + 页面"浏览字体…" |
| 8 | 隐私断言：请求体不含 file/path/游戏目录 | ✅ | `TestPrivacy::test_translate_batch_receives_only_texts` + 页面上有隐私说明 |

**M3a 接线期暴露的两个额外缺陷**（都不是"接线写错了"，而是被接线暴露出来的真缺陷）：

* **N-15**：MV/MZ 事件条目路径多拼一层 `/list/` → 事件对话与选择项
  **写不进汉化版且不报错**（详见 §5 的 M3a 小节）
* **F-09 违规**：`features/translate/routes.py` 曾反向 import `ui.native_pick`
  → 对话框能力下沉到 `core/sysdialog.py`（分层是硬约束，见 `docs/MODULES.md`）

### 7.2 下一步：M5 收尾

M4 的机械部分与 M5 的 8 项均已落地（见 §2）。剩下的是**收尾与通读**：

| # | 任务 | 判据 |
| --- | --- | --- |
| 1 | 通读 `README.md`，确认照着做能跑通 | 至少实际执行一遍"双击启动 → 两个功能各做一次操作" |
| 2 | `docs/UI_SPEC.md` §7.1 的人工走查 | 三档窗口各看一遍，把结论写回该表 |
| 3 | `docs/迁移对照表.md` 的 ⬜/⚠️ 条目逐条收口 | B-16/B-17 已在 M3b 补断言；B-19（队伍成员只读）已标注等价 |
| 4 | 需求 §9 的"已知变体"清单 | 加密 JSON 包装、非标准 marshal、多流存档、额外字段 —— 已全部处理并各有回归 |

### 7.3 必须遵守的既有约束（M2a ～ M5 建立）

* **写回一律走 `core/safety/atomic.py`** —— 由 `test_m2a_regressions.py` 与
  `test_writeback_regressions.py` 的 AST 扫描强制（禁止写模式 `open`，覆盖
  存档/数据/备份/清单四条路径）
* **覆盖必须 `confirm_overwrite=True` / `confirm=true`** —— 否则拒绝写，
  且**文件字节不变**（有断言）
* **破坏性操作二次确认** —— `ui/web/dom.js` 的 `confirmDialog()`，并在文案里
  写明改哪些文件、备份在哪里
* **默认零破坏** —— `translate` 默认写副本；`cheats` 默认只改内存
* **长任务必须可中断** —— 用 `ctx.jobs.submit(fn)`，任务内查
  `job.token.is_cancelled()`；不给界面留点了停不下来的按钮
* **进度回调签名** `progress_cb(done, total, message=None)`
* **功能不得 import `ui`** —— 需要界面能力时把实现放进 `core`（M3a 的 F-09 教训；
  M5 之后 F-10 又踩到一次，`Response` 因此搬进 `core/context.py`，见 ADR-014）
* **写回判据看"字段在不在"，不看"值真不真"** —— `0` / `False` 是合法值（N-16 教训）
* **两侧字段名必须对齐** —— 校验读的字段名与界面传的不一致 = 校验不存在（N-17 教训）
* **判断"是不是加密/特殊格式"看内容，不看扩展名** —— 真实游戏里扩展名不可信
  （N-24 的 `game_dir`、F-10 的 `.png` 里装着加壳数据，都是同一类教训）

* **写回一律走 `core/safety/atomic.py`** —— 由 `tests/compat/test_m2a_regressions.py`
  的 AST 扫描强制（禁止写模式 `open`）
* **覆盖必须 `confirm_overwrite=True`** —— 否则抛 `OverwriteNotConfirmed`
* **破坏性操作二次确认** —— `ui/web/dom.js` 的 `confirmDialog()`
* **默认只写副本** —— `mode=copy` 是默认，界面默认选中它
* **长任务必须可中断** —— 用 `ctx.jobs.submit(fn)`，任务内查
  `job.token.is_cancelled()`；不给界面留点了停不下来的按钮
* **进度回调签名** `progress_cb(done, total, message=None)`
* **功能不得 import `ui`** —— 需要界面能力时把实现放进 `core`（M3a 的 F-09 教训）

### 7.4 端到端回归（需求 §8-2 的判据）

MV / MZ / VX Ace / XP **各至少 1 个样本**走完：

```text
【翻译】扫描 → 翻译（用离线假翻译器跑通，不依赖真引擎）→ 生成汉化版 → 写回原游戏 → 还原
【修改】读档 → 改数值 → 写回存档 → 还原
```

现状：

| 引擎 | 翻译链路 | 修改链路 | 备注 |
| --- | --- | --- | --- |
| MV | ✅ 合成样本（进 CI）+ ✅ 真实样本扫描 | ✅ 合成样本（进 CI） | MV/MZ 的 JSON 结构一致，差异只在标记文件与压缩 |
| VX Ace | ✅ 合成样本（进 CI）+ ✅ 真实样本扫描 | ✅ **真实样本**（`test_acceptance.py` 用真实存档跑完改档→保存→还原） | 真实样本是 **2 流存档**（N-19 的现场） |
| MZ | ✅ 合成样本（进 CI）+ ✅ 真实样本扫描 | ✅ 合成样本（进 CI） | 真实 MZ 样本只有扫描覆盖 |
| XP / VX | ✅ 合成样本（`standard=True`，进 CI） | ✅ 合成样本（进 CI） | 本机没有真实 XP/VX 游戏（M0 已登记为空白） |

用 `TUDOU_RPGTOOL_SAMPLES` 指向真实样本；**样本不入库**（ADR-005）。

## 8. 当前已知的临时状态（M4/M5 会消掉，别当成设计）

| 临时状态 | 消除时机 | 验收判据 |
| --- | --- | --- |
| `features/translate/translators.py`、`session.py` 是 vendored 代码（保留了原实现的结构与注释） | M5 视情况整理 | 行为由 `test_routes.py` / `test_scan_regressions.py` 覆盖；整理时必须保持 4 个适配器与去重翻译语义不变 |
| 1280×720 等窗口的**观感**尚未人工确认 | M5 收尾 | `docs/UI_SPEC.md` §7.1 的走查步骤做完；成因已由 `test_ui_consistency.py` 钉住 |
| Python 3.8 兼容性只有**静态语法扫描**（本机只有 3.10.9） | 无法消除 | `tests/integration/test_startup.py` 的 3.8 语法扫描 + 手工避免 3.9+ 语法；`run.py` 会拒绝 < 3.8 |
| `ctx.translate_service` / `ctx.cheats_service` 是为测试/调试页暴露的服务实例 | 保留（已文档化） | 生产代码不得依赖它们；两个 `register_routes` 的 docstring 已声明 |
| 前端只在浏览器里可验证（无前端测试框架，因零第三方依赖） | 保留 | 以页面静态契约（43 例）+ UI 统一性（18 例）替代；新增页面照写一份 |
| MZ / XP 的端到端里 MZ 用合成数据（真实 MZ 样本只有扫描覆盖） | 无法完全消除 | MV/MZ 的 JSON 结构一致，差异只在标记文件与压缩方式，两者都已覆盖 |

**M2b 已完成的部分（全部）**：

* ✅ **formats 收敛**：新增 `core/formats/jsoncodec.py`，MV/MZ 两条路径共用一份
  JSON / 压缩 / 加密包装实现；`core/formats/__init__.py` 的
  `CONVERGENCE_STATUS` 已置 `"merged"`；由
  `tests/unit/test_jsoncodec.py::TestConvergence` 静态断言守护
  （禁止再出现第二份 `base64.b64decode` / 密钥派生 / `zlib` 调用）
* ✅ **`_refbridge.py` 已删除**：等价性证据冻结为
  `TestFrozenRealGameBaseline`（7 个真实游戏）与
  `TestFrozenDetectionFixtures`（13 种判据组合，两套 MV/MZ 判据都覆盖）；
  `/api/health` 改为报告 `convergence` 状态
* ✅ **测试去重**：`test_misc.py` 已删除，用例各归其位

**M2a 已清掉的临时状态**（留档）：

* ~~`core/safety/backup.py` 是 vendored 的 `build.py`（399 行，五个职责挤一起）~~
  → 已拆为 `atomic` / `backup` / `builder` / `fontutil` 四个模块（ADR-011）
* ~~`tools/_m1_fix_future_imports.py`、`_m1_fix_test_root.py`、`_m1_sync_tested.py`、
  `_m1_patch_features.py`~~ → 已删除，`footprint.json` 已刷新（40 → 37 文件）

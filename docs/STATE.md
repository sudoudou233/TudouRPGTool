# 当前状态快照（STATE）

> **接手本工程第一份要读的文件。** 读完本文件你就能说清"系统有哪几个功能、各自改哪里"。
> 每个里程碑结束时更新。最后更新：**M3b 完成时**。

---

## 1. 一句话状态

**M3a 与 M3b 都已完成**：两个功能的后端与前端都接通了 ——

* **文本翻译**：扫描 → 编辑 → 批量翻译 → 生成汉化版 → 备份还原（17 个端点 + 五张卡片）
* **存档修改**：读档 → 改金币/道具/角色/开关变量 → 写回存档 → 数据表编辑 → 备份还原
  （18 个端点 + 六张卡片）

接线期间累计挖出并修掉 **6 个"静默不生效"缺陷**（N-12 ～ N-17）与 3 个安全隐患
（分层违规、B-02 的存档侧残留、句柄泄漏）。其中 N-16/N-17 尤其阴险：
**接口返回 `ok`，但文件其实没变**。
**下一步：M4 UI 统一（跨页视觉审查）→ M5 验收硬化（需求 §8 的 8 项 + README + 启动器）。**

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
| M4 UI 统一 | ⬜ 未开始 | UI 审查通过，无孤立样式 | 两个页面已共用令牌与组件；跨页审查待做 |
| M5 验收硬化 | ⬜ 未开始 | 需求 §8 的 8 项全过 | — |

---

## 3. 系统有哪几个功能，各自改哪里

> 这是"3 分钟内说清楚"的那一段。详细文件地图见 `docs/MODULES.md`，
> 功能注册表见 `docs/FEATURES.md`。

| 功能 id | 用户可见名 | 界面入口 | 后端入口 | 核心实现文件 |
| --- | --- | --- | --- | --- |
| `translate` | 文本翻译 | `ui/web/pages/translate.js` | `features/translate/manifest.py` → `routes.register_routes` | `core/formats/mv_mz_data.py`、`core/formats/rgss_data.py`、`core/safety/builder.py`、`core/safety/backup.py`、`features/translate/translators.py` |
| `cheats` | 存档修改 | `ui/web/pages/cheats.js` | `features/cheats/manifest.py` → `routes.register_routes` | `core/formats/mv_save.py`、`core/formats/rgss_save.py`、`features/cheats/data_fields.py`、`core/marshal/` |

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
python tests/run_all.py                      # 791 例，0 失败 0 错误
python tests/run_all.py --quiet              # 退出码 0
python tools/check_footprint.py --quiet      # 退出码 0（41 文件 / 2 功能）
python app.py --check                        # 退出码 0（45 条路由）
```

| 测试层 | 用例数 | 说明 |
| --- | --- | --- |
| `unit/` | ~320 | 纯单元，零外部依赖（含 `test_sysdialog.py` 的 23 例） |
| `compat/` | ~100 | 原两个工具断言的可迁移版本 + **缺陷回归**（B-02/B-03/B-10/N-07…）+ **合成 VX/XP 样本** |
| `features/` | ~250 | 两个功能模块的自有测试（translate ~116 + cheats ~135） |
| `integration/` | ~73 | 启动服务后的端到端链路 + 零第三方依赖扫描 + Python 3.8 语法扫描 + **两个页面的静态契约 43 例** |
| `local/` | 0（待补） | 真实样本层，靠 `TUDOU_RPGTOOL_SAMPLES` 指定；样本不入库 |

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

### 7.2 下一步：M4 UI 统一，然后 M5 验收硬化

**M4（跨页视觉与交互统一）** —— 两个页面已经共用 `tokens.css` 与
`components.css`，剩下的是一次审查：

| # | 任务 | 判据 |
| --- | --- | --- |
| 1 | 走一遍 `docs/UI_SPEC.md` §7 的 7 条审查清单 | 全部打勾 |
| 2 | 1280×720 / 1440×900 / 1920×1080 三档窗口实际看一眼 | 无布局错乱、无横向滚动（表格除外） |
| 3 | 两页的"任务进度 / 空状态 / 错误提示"措辞与形态对齐 | 同类情况同一表现 |
| 4 | 把审查结果写回 `docs/UI_SPEC.md` §7 | 清单变成"已过"并注明日期 |

**M5（验收硬化）** —— 需求 §8 的 8 项 + 交付物：

| # | 任务 | 备注 |
| --- | --- | --- |
| 1 | 需求 §8 的 8 项逐条核对并留证据 | 见需求文档；每条对应到具体命令与输出 |
| 2 | `README.md`（面向使用者：怎么启动、两个功能怎么用、出了事怎么还原） | **尚未创建** |
| 3 | 启动器（`启动.bat` 之类的双击入口） | **尚未创建**；要处理"Python 不在 PATH"的提示 |
| 4 | MZ / XP 的真实样本端到端（现在只有合成样本） | 用 `TUDOU_RPGTOOL_SAMPLES` |
| 5 | `docs/迁移对照表.md` 的 ⬜/⚠️ 条目逐条收口 | B-16/B-17 已在 M3b 补齐测试 |

### 7.3 必须遵守的既有约束（M2a/M2b/M3a/M3b 建立）

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
* **功能不得 import `ui`** —— 需要界面能力时把实现放进 `core`（M3a 的 F-09 教训）
* **写回判据看"字段在不在"，不看"值真不真"** —— `0` / `False` 是合法值（N-16 教训）
* **两侧字段名必须对齐** —— 校验读的字段名与界面传的不一致 = 校验不存在（N-17 教训）

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
| MV | ✅ 合成样本（进 CI）+ ✅ 真实样本扫描 | ✅ 合成样本（进 CI） | 真实样本的**构建**待 M5 |
| VX Ace | ✅ 合成样本（进 CI）+ ✅ 真实样本扫描 | ✅ 合成样本（进 CI） | 真实样本的**构建**待 M5 |
| MZ | ⬜ 只有真实样本**扫描** | ⬜ 无夹具 | 待 M5 |
| XP / VX | ⬜ `standard=True` 的往返已覆盖（合成） | ⬜ 无夹具 | 待 M5 |

用 `TUDOU_RPGTOOL_SAMPLES` 指向真实样本；**样本不入库**（ADR-005）。

## 8. 当前已知的临时状态（M4/M5 会消掉，别当成设计）

| 临时状态 | 消除时机 | 验收判据 |
| --- | --- | --- |
| `features/translate/translators.py`、`session.py` 是 vendored 代码（保留了原实现的结构与注释） | M5 视情况整理 | 行为由 `test_routes.py` / `test_scan_regressions.py` 覆盖；整理时必须保持 4 个适配器与去重翻译语义不变 |
| `README.md` 与双击启动器**尚未创建** | M5 | 交付物清单要求（需求 §9/§10） |
| 页面尚未做跨页视觉统一审查 | M4 | `docs/UI_SPEC.md` §7 的 7 条清单全过 |
| `ctx.translate_service` / `ctx.cheats_service` 是为测试/调试页暴露的服务实例 | 保留（已文档化） | 生产代码不得依赖它们；两个 `register_routes` 的 docstring 已声明 |
| MZ / XP 的端到端只在合成样本或只读链路上覆盖 | M5 | 用 `TUDOU_RPGTOOL_SAMPLES` 的真实样本各跑一遍（§7.4 表） |
| 前端只在浏览器里可验证（无前端测试框架，因零第三方依赖） | 保留 | 以 `test_translate_page.py` / `test_cheats_page.py` 的**静态契约**替代；新增页面照写一份 |

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

# 当前状态快照（STATE）

> **接手本工程第一份要读的文件。** 读完本文件你就能说清"系统有哪几个功能、各自改哪里"。
> 每个里程碑结束时更新。最后更新：**M1 完成**。

---

## 1. 一句话状态

**M2b core 收敛已完成**：需求 §3.3 的三类重复实现**各只剩一份** ——
引擎识别、MV/MZ 编解码（`jsoncodec.py`）、Ruby Marshal（`doc_model` 二进制层 +
`value_layer` 门面，旧 `value_model` 已删）。`_refbridge.py` 已删除，
`/api/health` 的 `convergence.all_merged == true`。
**下一步：M3a 翻译功能接入。**

---

## 2. 里程碑进度

| 里程碑 | 状态 | 完成判据 | 实测结果 |
| --- | --- | --- | --- |
| M0 现状测绘 | ✅ 完成 | 每条功能都有"原位置 → 新位置"映射 | `docs/M0-现状测绘.md`、`docs/迁移对照表.md`（99 条映射） |
| M1 骨架与足迹 | ✅ 完成 | 空壳可启动，足迹校验通过 | `python app.py --check` 退出码 0；足迹校验 0 错误 |
| M2a 可信基线 + P0 修复 | ✅ 完成 | 测试可一键跑且退出码可信；P0 缺陷有回归断言 | 5 个 P0 + 4 个 P1 已修；合成 VX/XP 样本覆盖 B-10 活路径 |
| **M2b core 收敛** | ✅ **完成** | 三类职责各只有一份实现 | `all_merged == true`；`value_model.py` 与 `_refbridge.py` 已删除；475 例测试全绿 |
| M3a 翻译功能接入 | ⬜ 未开始 | 扫描→翻译→生成汉化版→还原 全链路走通 | — |
| M3b 修改功能接入 | ⬜ 未开始 | 5 类存档读写改回读在界面走通 | — |
| M4 UI 统一 | ⬜ 未开始 | UI 审查通过，无孤立样式 | — |
| M5 验收硬化 | ⬜ 未开始 | 需求 §8 的 8 项全过 | — |

---

## 3. 系统有哪几个功能，各自改哪里

> 这是"3 分钟内说清楚"的那一段。详细文件地图见 `docs/MODULES.md`，
> 功能注册表见 `docs/FEATURES.md`。

| 功能 id | 用户可见名 | 界面入口 | 后端入口 | 核心实现文件 |
| --- | --- | --- | --- | --- |
| `translate` | 文本翻译 | `ui/web/pages/translate.js` | `features/translate/manifest.py` → `register(ctx)` | `core/formats/mv_mz_data.py`、`core/formats/rgss_data.py`、`core/safety/builder.py`、`core/safety/backup.py`、`features/translate/translators.py` |
| `cheats` | 存档修改 | `ui/web/pages/cheats.js` | `features/cheats/manifest.py` → `register(ctx)` | `core/engines.py`、`core/formats/mv_save.py`、`core/formats/rgss_save.py`、`core/marshal/` |

**跨功能的公共地基**（改这些会影响所有功能，务必先读 `docs/MODULES.md`）：

| 文件 | 一句话职责 | 改动影响面 |
| --- | --- | --- |
| `core/engines.py` | 引擎识别 + 数据/存档目录发现 | 两个功能都依赖；改它会同时影响翻译扫描与存档修改 |
| `core/registry.py` + `core/context.py` | 功能发现与装配契约 | 改它影响所有功能的注册方式 |
| `core/safety/atomic.py` | **唯一的写盘手段**（原子写 + 备份 + 护栏） | 改它影响所有写回路径的数据安全 |
| `core/safety/backup.py` | 备份 / 还原 / 清单（**不依赖 formats**） | 改它影响所有写回的还原能力 |
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
| `docs/footprint.json` | ✅ 40 文件 / 2 功能（由 `tools/gen_footprint.py` 从源码生成） |
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

## 6. 当前测试状态

```powershell
python tests/run_all.py                      # 444 例，0 失败 0 错误（含真实样本）
python tests/run_all.py --quiet              # 退出码 0
python tools/check_footprint.py --quiet      # 退出码 0（37 文件 / 2 功能）
python app.py --check                        # 退出码 0
```

| 测试层 | 用例数 | 说明 |
| --- | --- | --- |
| `unit/` | ~300 | 纯单元，零外部依赖 |
| `compat/` | ~96 | 原两个工具断言的可迁移版本 + **M2a 缺陷回归** + **合成 VX/XP 样本** |
| `features/` | ~30 | 两个功能模块的自有测试 |
| `integration/` | ~30 | 启动服务后的端到端链路 + 零第三方依赖扫描 + Python 3.8 语法扫描 |
| `local/` | 0（待补） | 真实样本层，靠 `TUDOU_RPGTOOL_SAMPLES` 指定；样本不入库 |

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

## 7. 下一步（M3a 翻译功能接入）任务清单

M2b 已把 core 收敛完毕，M3a 不再有先收敛再接线的顾虑。按需求 §10 的 M3a 判据：
**扫描 → 翻译 → 生成汉化版 → 还原 全链路在界面走通**。

### 7.1 功能接线（后端）

| # | 任务 | 落点 |
| --- | --- | --- |
| 1 | 扫描：4 个开关（注释/备注/事件名/动画名）→ 后台任务 + 进度 | eatures/translate/routes.py（新建）+ eatures/translate/session.py |
| 2 | 文本列表：搜索 / 类别筛选 / 状态筛选 / 分页 / 行内编辑 / 跳过 | 同上 + ui/web/pages/translate.js |
| 3 | 4 个引擎适配器接线 + 设置持久化 + 接口自检 | eatures/translate/translators.py + core/config.py |
| 4 | 批量翻译：进度 + ETA + 可中断 + 重试出错内容 + 断点续传 | eatures/translate/（任务内用 job.set_progress / job.token） |
| 5 | 生成汉化版：复制到新目录 / 覆盖原游戏（**必须二次确认 + 展示备份路径**） | core/safety/builder.py 的 uild(..., confirm_overwrite=True) |
| 6 | 备份列表 + 还原入口（UI 可点） | core/safety/backup.py 的 list_backups / 
estore_backup |
| 7 | 字体应用两条路径 + 失败回退提示 | core/safety/builder.py 的 pply_font |
| 8 | 隐私断言：请求体不含 file/path/游戏目录 | 新增测试 |

### 7.2 必须遵守的既有约束（M2a/M2b 建立）

* **写回一律走 core/safety/atomic.py** —— 由 	est_m2a_regressions.py 的
  AST 扫描强制（禁止写模式 open）
* **覆盖必须 confirm_overwrite=True** —— 否则抛 OverwriteNotConfirmed
* **破坏性操作二次确认** —— ui/web/dom.js 的 confirmDialog()
* **默认只写副本** —— mode=copy 是默认，不传则界面默认选中它
* **长任务必须可中断** —— 用 ctx.jobs.submit(fn)，任务内查
  job.token.is_cancelled()；不给界面留点了停不下来的按钮
* **进度回调签名** progress_cb(done, total, message=None)

### 7.3 端到端回归（§8-2 的判据）

MV / MZ / VX Ace / XP **各至少 1 个样本**走完：

`
扫描 → 翻译（用离线假翻译器跑通，不依赖真引擎）→ 生成汉化版 → 写回原游戏 → 还原
`

用 TUDOU_RPGTOOL_SAMPLES 指向真实样本；**样本不入库**（ADR-005）。

## 8. 当前已知的临时状态（M3 会消掉，别当成设计）

| 临时状态 | 消除时机 | 验收判据 |
| --- | --- | --- |
| `features/translate/translators.py`、`session.py` 是 vendored 代码，尚未按 `manifest.py` 契约组织 | M3a | 接线为正式模块并接入 UI |
| 两个功能页都是**骨架**（`status: skeleton`） | M3a / M3b | 两条回归链路在界面走通 |

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

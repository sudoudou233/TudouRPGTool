# 开发足迹（DEVLOG）

> **追加式时间线**：每次提交追加一条，记录日期、改了什么、为什么、怎么验证、遗留什么。
> 永不删除历史条目。

---

## 2026-09-12 ｜ M2a 可信基线与 P0 修复

### 改了什么

**修完 5 个 P0 + 4 个关键 P1，全部配回归断言**（先写断言看它失败，再修到通过）：

| 编号 | 文件 | 修法 |
| --- | --- | --- |
| B-01 ✅ | `core/safety/builder.py`（新） | 覆盖输出改为**暂存目录 + 原子换名**；失败只清理暂存，旧输出完好 |
| B-02 ✅ | `mv_mz_data.py` / `rgss_data.py` / `builder.py` / `backup.py` | 所有写回改走 `core/safety/atomic.py`（临时文件 + fsync + `os.replace`） |
| B-03 ✅ | `builder.py` | `font_touched_paths()` 无条件登记字体兜底会覆盖的两个默认字体文件 |
| B-04 ✅ | `core/safety/backup.py`（重写） | 清单区分 `files`（恢复）与 `created`（删除）；还原前先为当前状态生成安全备份 |
| B-05 ✅ | `builder.py` | 新增 `confirm_overwrite` 参数；copy 与 inplace 都必须显式确认 |
| B-06 ✅ | `builder.py` | inplace 失败**自动从备份回滚**，回滚结果挂在 `BuildFailed.rollback` |
| B-07 ✅ | `backup.py` | 备份拷贝失败抛 `AtomicWriteError`，不再静默吞 `OSError` 后继续写档 |
| B-10 ✅ | `core/marshal/doc_model.py` | 删除重复的 `Parser._fixnum`；**另修标准编码单字节上限 122 → 117**（N-10） |
| B-11 ✅ | `core/marshal/doc_model.py` | 补齐 10 个缺失的 `to_py()`，统一 `"__ruby__"` 标记约定 |
| B-26 ✅ | `builder.py` | `winreg` 改为函数内 import；非 Windows 返回 `{'installed': False, reason}` |
| N-07 ✅ | `core/formats/rgss_data.py` | `_navigate`/`_set_value` 重写为 `_step`/`_index`/`_rmobject_key` |
| N-08 ✅ | `core/textutil.py` | 补齐符号型转义分支；收紧字母型（修掉 `\G你好` 被读成 `\G你`） |

**安全层拆分**（ADR-011）：原 vendored `build.py`（399 行、五个职责）拆为
`atomic` / `backup` / `builder` / `fontutil`，依赖方向单向
（`backup` **不 import `core.formats`**，切断 import 环；
`core/safety/__init__.py` 用 PEP 562 `__getattr__` 懒加载）。

**新增合成 VX/XP 样本**（ADR-013）：`tests/compat/test_standard_mode.py`（约 330 行）。
本机没有 VX/纯 XP 游戏，而 `standard=True` 正是 B-10 的活路径 —— 改用代码合成最小
`.rvdata` / `.rxdata`，覆盖两套整数编码的全部边界值 + `contents` 布局 + 完整读写改回读。

**清理**：删除 `tools/` 下 4 个 M1 一次性脚本；`footprint.json` 40 → 37 文件。

### 为什么

需求 §10 的 M2a 判据：**测试可一键跑且退出码可信；P0 缺陷有回归断言**。
M1 已把测试基线做可信（统一入口、退出码、零第三方依赖），但 5 个 P0 缺陷
（含"会丢用户文件"的 B-01 与"写回非原子"的 B-02）必须先修，
否则 M2b 的收敛会把它们固化进唯一实现。

### 怎么验证

```powershell
python tests/run_all.py                      # 458 例，0 失败 0 错误
$env:TUDOU_RPGTOOL_SAMPLES='D:\gamess'
python tests/run_all.py                      # 含 300 个真实 .rvdata2 零漂移
python tools/check_footprint.py --quiet      # 退出码 0（37 文件 / 2 功能）
python app.py --check                        # 退出码 0
```

关键新增断言（`tests/compat/test_m2a_regressions.py`，31 例）：

* `test_old_output_survives_when_copy_fails` —— monkeypatch `copy_tree` 抛 `OSError`，
  断言旧输出的文件**字节完好**（B-01）
* `test_mv_mz_save_data_file_is_atomic` —— 让 `os.replace` 失败，断言原文件**字节不变**（B-02）
* `test_rgss_writeback_is_atomic` 等 4 条 —— AST 扫描"禁止写模式 `open`"（B-02；
  不能用字符串匹配：文档字符串里会描述原实现，M2a 实测踩到）
* `test_fallback_overwrite_can_be_restored` —— 走真实 build+restore，
  断言被字体兜底覆盖的默认字体**能还原**（B-03）
* `test_restore_removes_files_created_by_build` / `test_restore_is_backed_up_itself`（B-04）
* `test_overwrite_without_confirmation_is_rejected` / `test_inplace_without_confirmation_is_rejected`（B-05）
* `test_whole_project_has_no_top_level_winreg` —— 全仓扫描（B-26）
* `TestB10FixnumStandard` —— 20 个边界值 × 两套编码的往返字节一致（B-10）
* `test_no_duplicate_fixnum_definition` —— 断言 `Parser` 里只有一个 `_fixnum`（防复发）

### M2a 期间**新发现**的缺陷（不在 M0/M1 台账中）

| 编号 | 位置 | 问题 | 怎么发现的 |
| --- | --- | --- | --- |
| **N-09** | `core/formats/rgss_save.py` | `read_actors`/`set_actor_attr`/`set_actor_skills` 写死 `[v for k,v in actors_node.ivars][0]`，假设容器是对象；**stock XP/VX 存档里它是数组** → `AttributeError`，**整条 RGSS 存档读写不可用** | 新加的合成 VX/XP 样本 |
| **N-10** | `core/marshal/doc_model.py` | 标准编码 `_fixnum_to_bytes_std` 单字节上限写成 122，但 `0x7B` 是长格式标记 → **118..122 五个值编码后被解成垃圾并使后续流错位** | 同上的边界值往返（`struct.error: unpack requires a buffer of 4 bytes`） |
| **N-11** | `core/safety/__init__.py` ↔ `core/formats/__init__.py` | 拆分 safety 层时的**循环 import** | 拆完立刻撞上（import 即失败） |

**N-09/N-10 的意义**：这两个都是 P0 级、且**此前完全没有任何测试能发现**的缺陷 ——
因为它们只活在 `standard=True` 这条本机没有样本的路径上。
这直接验证了 ADR-013 的判断：**"没有样本"等价于"没有证据"**。

### 遗留

* 真机 VX / XP 样本仍空白（合成样本覆盖不到汉化/破解变体），见 `docs/ROADMAP.md` §3
* `core/marshal/` 仍是两份实现（M2b）
* `core/_refbridge.py` 仍 14 项待收敛（M2b）
* 建议 M2b 引入审查者（需求 §2）

---

## 2026-09-12 ｜ M0 现状测绘（提交 `fb0809d`，后续迁入本仓库）

### 改了什么

| 文件 | 内容 |
| --- | --- |
| `docs/M0-现状测绘.md`（401 行） | 两个参考工具的完整测绘（实读全部源码 3,013 + 678 + 2,113 行） |
| `docs/迁移对照表.md`（173 行） | 99 条映射：功能 → 原位置(文件:行号) → 测试 → 新位置 → 验证状态 |
| `docs/OPEN-QUESTIONS.md`（164 行） | 需求 §12 全部开放问题的结论 + 理由 + 替代代价 |
| `.gitignore` | 保护 `config.json` / `sessions/` / `*.bak` / 汉化备份 / 样本 / Python 缓存 |

### 为什么

需求 §13 要求"第一步不要写代码：先只读参考两个原工具目录，产出 M0 现状测绘"。

### 怎么验证

| 命令 | 结果 |
| --- | --- |
| 翻译工具 5 个测试逐个执行 | `test_translators` / `test_translate_job` / `test_marshal`(ALL_OK) / `test_e2e`(ALL E2E OK，译文字串落地 8 条) 通过；`test_pipeline` 超 120s 未结束（真 Google 翻译） |
| 修改工具 7 个测试逐个执行 | `test_roundtrip`(240 ok, 0 failed) / `test_all_saves`(24 档 failures: 0) / `test_mvmz` / `test_gui` / `test_gui_multi` 通过；`test_edit` 零断言；`test_cross_js` 失败（缺工程外 `verify_save.js`） |
| 阻断第三方模块后导入生产模块 | 翻译工具 11 模块 + `main`、修改工具 6 模块**全部 OK**；同环境跑测试则 `test_e2e`/`test_pipeline` 在 `import requests` 处 ImportError |
| UI 启动 | Web `/api/health` → `{'ok':true,'version':'1.2.0'}`；tkinter `App(root)` → 7 个分页构造成功 |
| 参考目录未被修改 | 全程只读 |

### 关键发现（写进 `docs/STATE.md` §5 台账）

1. `tests/test_e2e.py:15` 与 `tests/test_pipeline.py:15` 使用第三方库 **`requests`** →
   违反硬约束 §4.1（本机恰好装了 `requests 2.25.1` 所以从未暴露）
2. `rmarshal.py:491-496` 的 `Parser._fixnum` 被 `:508-510` 重复定义覆盖 →
   XP/VX 回写字节漂移，而**本机无 VX 样本**
3. 重复实现实测为**四类**，比需求 §3.3 多一类：`PARAMS` 常量两处重复且都零引用
4. 翻译工具**不识别 VX**（`.rvdata` 落到"未识别"），而修改工具支持

### 遗留

* 需求 §12 的 Q-01（工程落盘位置）待人类裁决 → 已裁决为
  `D:\test1\Tudou_RPGTool\TudouRPGTool\`（见 `docs/OPEN-QUESTIONS.md`）

---

## 2026-09-12 ｜ M1 骨架与足迹

### 改了什么

**新增 `core/`（纯逻辑层，13 个模块 + 3 个子包）**

| 文件 | 说明 |
| --- | --- |
| `core/constants.py` | 引擎常量唯一真源（消除原 `PARAMS` 两处重复） |
| `core/engines.py` | **合并后的引擎识别**：两套 MV/MZ 判据 + System.json 兜底 + 数据/存档双目录 |
| `core/paths.py` | 路径唯一真源，函数式 + 环境变量覆盖（原为模块级常量，B-25） |
| `core/config.py` | 配置读写 + 原子写 + `redacted()` 密钥掩码 |
| `core/registry.py` | 功能自动发现与装配（`manifest.py` 契约） |
| `core/context.py` | `Router` / `PageSpec` / `AppContext` —— register 契约 |
| `core/jobs.py` | 有界并发 + 每任务取消 + TTL 回收 + 原子终态（修正 B-22、N-06） |
| `core/textutil.py` | 控制码切分与还原（修 `has_real_text` 纯控制码误判，N-02） |
| `core/marshal/` | `doc_model`（v8 增量保真）+ `value_model`（编码感知）—— **M2b 收敛** |
| `core/formats/` | `mv_mz_data` / `rgss_data` / `mv_save` / `rgss_save` / `lzstring` |
| `core/safety/` | `atomic`（新写，唯一写盘手段）+ `backup`（vendored）+ `fontutil` |
| `core/_refbridge.py` | **临时**桥接层（12 项登记，仅用于回归对照） |

**新增 `features/`（2 个功能模块）**

`features/translate/`（`manifest.py` + vendored `translators.py` / `session.py`）、
`features/cheats/`（`manifest.py`）

**新增 `ui/`（Web 外壳）**

`ui/server.py`（显式路由表 + Host/Origin 白名单 + 防穿越）、`ui/routes.py`（10 条核心路由）、
`ui/web/{index.html,app.js,dom.js,tokens.css,components.css,pages/{translate,cheats}.js}`

**新增 `app.py`**：唯一入口，装配 + 自检 + 生命周期 + 旧实例回收

**新增 `tests/`（5 层，420 例）**：`unit/`、`compat/`、`features/`、`integration/`、`local/` +
`run_all.py`（统一入口，退出码可信）

**新增 `tools/`**：`check_footprint.py`（12 条规则）、`gen_footprint.py`、3 个一次性脚本

**新增 `docs/` 足迹全套**：`STATE.md`、`ARCHITECTURE.md`、`MODULES.md`、`FEATURES.md`、
`DECISIONS.md`（10 条 ADR）、`UI_SPEC.md`、`ROADMAP.md`、`footprint.json`；
`AGENTS.md`

### 为什么

需求 §10 的 M1 完成判据：**空壳可启动，足迹校验通过**。

### 怎么验证

```powershell
python app.py --check                     # 退出码 0
python tools/check_footprint.py --quiet   # 退出码 0（40 文件、2 功能、0 错误）
python tests/run_all.py --quiet           # 退出码 0
$env:TUDOU_RPGTOOL_SAMPLES='D:\gamess'
python tests/run_all.py                   # 420 例，0 失败 0 错误
```

| 证据 | 结果 |
| --- | --- |
| 引擎识别 vs **两个**旧实现（7 个真实游戏） | **100% 一致** |
| 存档发现 vs 旧修改工具（6 个真实游戏） | 数量完全一致（3/0/24/2/1/9） |
| Marsha 字节级往返（**300 个真实 `.rvdata2`**） | **0 失败** |
| 测试总数 | 420 例，0 失败 0 错误 |
| 路由 | 14 条（10 核心 + 4 功能） |
| 前端静态资源 | `/`、`app.js`、`dom.js`、`tokens.css`、`components.css`、两个页面全 200 |
| 安全 | `/../app.py` → 400；外部 Host → 403；外部 Origin → 403 |

### M1 期间发现并修复的**新缺陷**（不在 M0 台账中）

| 编号 | 位置 | 问题 | 修法 |
| --- | --- | --- | --- |
| **N-01** | `core/formats/mv_mz_data.py` | **402 选择项全部或部分丢失**：真实形状是 `[["是","否"], cancelType, defaultType]`，原实现按单值处理 → 嵌套形状下整个选择项丢失 | 新增 `_MULTI_VALUE_CODES` + `_choice_texts()`，扁平与嵌套两种形状都支持 |
| **N-02** | `core/textutil.py` | `has_real_text("\\V[1]")` 返回 True（控制码里的 `V` 是字母）→ **纯控制码被送去翻译**，破坏变量引用 | 先剥离控制码再判定 |
| **N-03** | `ui/server.py` | 畸形 JSON body 被退化成表单解析，处理器拿到垃圾键值 | 声明 JSON 却解析失败时保留原文 + 标 `_parse_error` |
| **N-04** | `core/registry.py` | `pkgutil` 的 `ispkg` 过滤会**静默跳过**缺 `__init__.py` 的功能目录 | 改 `os.listdir` 逐个判定并报错 |
| **N-05** | `core/context.py` | 未命名路由默认名是 `handler.__name__`，多个 lambda 得到同名 `<lambda>` → 误报"路由名重复" | 仅在显式命名或默认名唯一时登记名字 |
| **N-06** | `core/jobs.py` | **终态竞态**：先发布 `status` 再写 `traceback`，轮询方读到半成品 | 新增 `Job.finalize()` 锁内一次性发布（ADR-008） |

### M1 期间发现但**未修**（转 M2a）

| 编号 | 位置 | 问题 |
| --- | --- | --- |
| **N-07** | `core/formats/rgss_data.py` | 多值条目的写回路径在 RGSS 侧不被支持：`_navigate` 走 `int(seg)` 抛 `ValueError` 被静默跳过 → 译文落不下去（已加防御性注释，不会写坏文件） |
| **N-08** | `core/textutil.py` | 注释声称支持 `\{ \} \^ \| \. \! \> \< \$`，但正则要求反斜杠后必须是字母 → 从不匹配（测试已固化当前行为，修好时会失败以提醒） |

### 遗留（`docs/STATE.md` §8 有完整表）

* `core/marshal/` 与 `core/formats/` 仍是"待收敛"状态（`CONVERGENCE_STATUS = "pending"`）
* `core/_refbridge.py` 的 `pending == 12`
* 两个功能页都是骨架（`status: skeleton`）
* `tools/_m1_*.py` 三个一次性脚本待删
* **Python 3.8 兼容性只有静态检查，未在真实 3.8 上跑过**
* **VX（`.rvdata`）无真实样本**（而它正是 B-10 的活路径）

---

## 迁移对照表

> 需求 §6.4 要求 `docs/DEVLOG.md` 中有"迁移对照表"。完整版见
> **`docs/迁移对照表.md`**（99 条：翻译工具 55 条 + 修改工具 37 条 + 测试资产 7 条），
> 每条含「原位置(文件:行号) → 对应测试 → 新位置 → 是否已验证」。

### 摘要（按子系统）

| 原子系统 | 新位置 | 状态 |
| --- | --- | --- |
| 翻译工具 数据层（MV/MZ + RGSS 提取与写回） | `core/formats/mv_mz_data.py`、`core/formats/rgss_data.py` | 已搬入，M2a/M3a 收敛与接线 |
| 翻译工具 引擎识别 | `core/engines.py` | ✅ **已验证**（与两个旧实现 100% 一致） |
| 翻译工具 Ruby Marshal（值模型） | `core/marshal/value_model.py` | ✅ 已搬入，往返测试通过 |
| 翻译工具 翻译引擎层 | `features/translate/translators.py` | 已搬入，M3a 接线 |
| 翻译工具 生成汉化版/备份/字体 | `core/safety/backup.py`、`core/safety/fontutil.py` | 已搬入，**5 个 P0/P1 待修** |
| 翻译工具 Web 服务 | `ui/server.py`、`ui/routes.py` | ✅ **已重写**（显式路由表 + 安全加固） |
| 翻译工具 前端 | `ui/web/*` | ✅ 令牌与组件已抽取；页面为骨架 |
| 修改工具 引擎识别 + 存档发现 | `core/engines.py` | ✅ **已验证**（合并为唯一实现） |
| 修改工具 Ruby Marshal（文档模型） | `core/marshal/doc_model.py` | ✅ **已验证**（300 真实样本零漂移） |
| 修改工具 MV/MZ 存档读写 | `core/formats/mv_save.py` | ✅ 合成样本读写改回读通过 |
| 修改工具 RGSS 存档读写 | `core/formats/rgss_save.py` | 已搬入，待真实样本回归 |
| 修改工具 LZString | `core/formats/lzstring.py` | ✅ 往返测试通过 |
| 修改工具 tkinter GUI | `ui/web/pages/cheats.js` | 引擎识别链路可用；M3b 接线其余 |

### 未能迁移的（须显式记录）

| 项 | 原因 | 处置 |
| --- | --- | --- |
| `tool/textutil.py:translate_segments()` | 原仓零调用（死代码） | 不迁移（ADR-010） |
| `/api/listdir` + `.dir-item` CSS | 原仓零引用 | 不迁移（ADR-010） |
| `--warn` / `.progress.success` / `.ok-text` | 零引用 | 前两者不迁移；`.ok-text` 补上用途（ADR-010） |
| 修改工具 7 个 `test_*.py` 的原始形态 | 硬编码本机路径 / 零断言 / 退出码恒 0 / 需 GUI 或 node | 断言逻辑已移植到 `tests/compat/*` 与 `tests/features/*`（见 `docs/迁移对照表.md` §B.3） |

### 参考目录状态（回退参照）

| 目录 | 状态 |
| --- | --- |
| `D:\test1\rpgtool\rpgmaker_translation_tool` | **未修改**，仍可独立运行（`启动翻译工具.bat`） |
| `D:\test1\rpgtool\rpgmaker_cheating_tool` | **未修改**，仍可独立运行（`启动修改器.bat`） |

# 当前状态快照（STATE）

> **接手本工程第一份要读的文件。** 读完本文件你就能说清"系统有哪几个功能、各自改哪里"。
> 每个里程碑结束时更新。最后更新：**M1 完成**。

---

## 1. 一句话状态

**M1 骨架与足迹已完成**：唯一入口可启动、两个功能模块按契约自动发现并注册、
足迹系统全套产出且校验通过（退出码 0）、420 个测试全绿。
**下一步：M2a 可信测试基线 + P0 缺陷修复。**

---

## 2. 里程碑进度

| 里程碑 | 状态 | 完成判据 | 实测结果 |
| --- | --- | --- | --- |
| M0 现状测绘 | ✅ 完成 | 每条功能都有"原位置 → 新位置"映射 | `docs/M0-现状测绘.md`、`docs/迁移对照表.md`（99 条映射） |
| **M1 骨架与足迹** | ✅ **完成** | 空壳可启动，足迹校验通过 | `python app.py --check` 退出码 0；`python tools/check_footprint.py` 退出码 0（40 文件、2 功能、0 错误） |
| M2a 可信基线 + P0 修复 | ⬜ 未开始 | 测试可一键跑且退出码可信；5 个 P0 缺陷有回归断言 | — |
| M2b core 收敛 | ⬜ 未开始 | 重复实现清零；两份 marshal 断言同时通过 | — |
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
| `translate` | 文本翻译 | `ui/web/pages/translate.js` | `features/translate/manifest.py` → `register(ctx)` | `core/formats/mv_mz_data.py`、`core/formats/rgss_data.py`、`core/safety/backup.py`、`features/translate/translators.py` |
| `cheats` | 存档修改 | `ui/web/pages/cheats.js` | `features/cheats/manifest.py` → `register(ctx)` | `core/engines.py`、`core/formats/mv_save.py`、`core/formats/rgss_save.py`、`core/marshal/` |

**跨功能的公共地基**（改这些会影响所有功能，务必先读 `docs/MODULES.md`）：

| 文件 | 一句话职责 | 改动影响面 |
| --- | --- | --- |
| `core/engines.py` | 引擎识别 + 数据/存档目录发现 | 两个功能都依赖；改它会同时影响翻译扫描与存档修改 |
| `core/registry.py` + `core/context.py` | 功能发现与装配契约 | 改它影响所有功能的注册方式 |
| `core/safety/atomic.py` | **唯一的写盘手段**（原子写 + 备份） | 改它影响所有写回路径的数据安全 |
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

## 5. 已知缺陷台账（M2a 的主要输入）

> 完整 29 条见 `docs/M0-现状测绘.md` §4。这里只列**必须最先处理**的。

### P0（阻断级：会丢功能或损坏用户文件）

| 编号 | 位置 | 问题 | 计划 |
| --- | --- | --- | --- |
| **B-01** | `core/safety/backup.py`（原 `build.py:366`） | 生成汉化版时目标目录已存在会先 `shutil.rmtree` 再拷贝；中间失败旧输出不可恢复 | M2a：改为"先拷到临时目录再原子换名" |
| **B-02** | `core/formats/rgss_data.py`、`core/formats/mv_mz_data.py` | 游戏数据写回**非原子**（`open("wb")` 直接截断） | M2a：全部改走 `core/safety/atomic.py` |
| **B-03** | `core/safety/backup.py`（原 `build.py:155-161`） | 字体兜底会**覆盖** `gamefont.ttf` / `mplus-1m-regular.ttf`，而这两个路径不在备份清单里 → **无法还原** | M2a：加入 touched 清单 |
| **B-10** | `core/marshal/doc_model.py` | `Parser._fixnum` **重复定义**（后一处覆盖前一处）→ `standard=True`（XP/VX 活路径）**按变体解析、按标准写回**，字节漂移 | M2a：先修再做 M2b 收敛 |
| **B-11** | `core/marshal/doc_model.py` | `to_py()` 有 10 个类未实现，而 `Array`/`Hash` 会递归调用 → 对真实数据调用即抛 | M2b：补齐或改由门面层承担 |

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
| **N-07** | `core/formats/rgss_data.py` | 多值条目的写回路径（`.../parameters/0/0`）在 RGSS 侧不被支持：`_navigate` 会走 `int(seg)` 抛 `ValueError` 被静默跳过 → 译文落不下去 | ⬜ **M2a 处置**（已加防御性注释，不会写坏文件） |
| **N-08** | `core/textutil.py` | 注释声称支持 `\{ \} \^ \| \. \! \> \< \$`，但 `CONTROL_RE` 要求反斜杠后必须是字母 → 这些符号型转义**从不被匹配** | ⬜ **M2a 处置**（已有固化了当前行为的测试，修好时该测试会失败以提醒更新） |

---

## 6. 当前测试状态

```powershell
python tests/run_all.py                      # 420 例，0 失败 0 错误（含真实样本）
python tests/run_all.py --quiet              # 退出码 0
python tools/check_footprint.py --quiet      # 退出码 0
python app.py --check                        # 退出码 0
```

| 测试层 | 用例数 | 说明 |
| --- | --- | --- |
| `unit/` | ~300 | 纯单元，零外部依赖 |
| `compat/` | ~48 | 原两个工具断言的可迁移版本（含 **300 个真实 `.rvdata2` 零漂移**） |
| `features/` | ~30 | 两个功能模块的自有测试 |
| `integration/` | ~30 | 启动服务后的端到端链路 + 零第三方依赖扫描 + Python 3.8 语法扫描 |
| `local/` | 0（待补） | 真实样本层，靠 `TUDOU_RPGTOOL_SAMPLES` 指定；样本不入库 |

**注意**：`tests/compat/test_marshal_compat.py::TestMarshalRoundtripRealSamples`
在未设置 `TUDOU_RPGTOOL_SAMPLES` 时会 skip（不是失败）。要拿到"300 文件零漂移"
的完整证据，必须设该环境变量。

---

## 7. 下一步（M2a）任务清单

按优先级：

1. **修 5 个 P0**：B-01、B-02、B-03、B-10、B-11。每个都要配"能复现缺陷"的回归断言
   （先写断言看到它失败，再修到通过）。
2. **处置 N-07、N-08**：多值条目写回路径 + 控制码正则注释不符。
3. **决定 VX（`.rvdata`）覆盖方式**：本机**没有 VX 游戏样本**，而 VX 正是 B-10 的
   活路径。要么合成 VX 样本（用 `marshal` 造最小 `.rvdata`），要么在
   `docs/ROADMAP.md` 登记为"已知未验证边界"。
4. **把 P0/P1 修复逐条写入 `docs/DECISIONS.md`**（修 / 保留并登记 / 明确不做，三选一，不许沉默）。
5. **清理临时脚本**：`tools/_m1_*.py`（3 个）在 M2a 结束后删除，同时从
   `docs/footprint.json` 移除。
6. **考虑引入审查者**（需求 §2）：M2b 与 M4 是最值得互审的两个节点，
   审查记录写入 `docs/reviews/REVIEW-YYYYMMDD-<主题>.md`。

---

## 8. 当前已知的临时状态（M2b/M3 会消掉，别当成设计）

| 临时状态 | 消除时机 | 验收判据 |
| --- | --- | --- |
| `core/marshal/` 有**两份实现**（`doc_model` + `value_model`） | M2b | 两侧 roundtrip 断言同时通过；重复实现清零 |
| `core/_refbridge.py` 桥接层（12 项登记） | M2b 后整文件删除 | `reference_status()['pending'] == 0` |
| `core/formats/` 未抽出共享 `jsoncodec.py`（MV/MZ 游戏数据与存档各写一套 JSON/压缩约定） | M2b | 一个实现两条路径共用 |
| `features/translate/translators.py`、`session.py` 是 vendored 代码 | M3a | 接线为正式模块并接入 UI |
| 两个功能页都是**骨架**（`status: skeleton`） | M3a / M3b | 两条回归链路在界面走通 |
| `tools/_m1_fix_future_imports.py`、`_m1_fix_test_root.py`、`_m1_sync_tested.py` | M2a | 删除并从 footprint.json 移除 |
| `tests/unit/test_misc.py` 里的 `TestConfig`/`TestConstants` 与 `test_config.py` 重复导出 | M2a | 去重（当前无害：每个用例只执行一次） |

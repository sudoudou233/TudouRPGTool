# 开发足迹（DEVLOG）

> **追加式时间线**：每次提交追加一条，记录日期、改了什么、为什么、怎么验证、遗留什么。
> 永不删除历史条目。

---

## 2026-09-13 ｜ M3a 完成：翻译页面接线（五张卡片），全链路在界面走通

### 改了什么

| 文件 | 变更 |
| --- | --- |
| `ui/web/pages/translate.js` | 从 M1 骨架（82 行、3 张展示卡）重写为**真实功能页**（~700 行、5 张卡片）：① 游戏目录（粘贴路径 + 原生「浏览…」+ 打开并识别，胶囊显示引擎/数据目录/条目计数）② 扫描与文本列表（4 个内容开关、搜索/类别/状态筛选、分页、行内改译文、逐条跳过与恢复、批量跳过）③ 翻译设置（引擎/Key/地址/模型/语言/并发/批大小 + 保存 + 接口自检 + 开始翻译/只重试出错/全部重译）④ 生成汉化版（写入方式默认写副本、输出目录、可选字体、生成后展示输出目录与**备份路径**、备份列表可还原）⑤ 任务进度（进度条 + 百分比 + 阶段文案 + 耗时 + **取消**，失败显示 `job.error` 与 `traceback_tail`） |
| `tests/integration/test_translate_page.py`（新，23 例） | **页面静态契约**测试：页面 ↔ 后端**双向**一致、破坏性操作必须有二次确认、默认零破坏、密钥不回显、无硬编码颜色、无调试残留 |
| `docs/UI_SPEC.md` | §4 页面清单更新为"已接线"，新增 §4.1 五张卡片的定稿（含每张卡对应的端点） |
| `docs/STATE.md` | M3a 标记完成；§7 改为"M3a 已完成 + M3b 待做"的形态，并给出 M3b 的落地建议 |

### 为什么这样写

**1) 前端没有测试框架，但前端最容易错的地方恰好是静态可查的。**

本工程零第三方依赖（连测试也不许引 `requests`），所以不引 npm / playwright。
但"点了没反应"这类问题的根因几乎都是静态的：

| 症状 | 静态可查的根因 | 本文件的断言 |
| --- | --- | --- |
| 点按钮没反应 / 404 toast | 页面调了后端**不存在**的端点 | `test_every_called_endpoint_exists` |
| 后端写了接口但界面上找不到入口 | **死接口**（实现了却没人用） | `test_every_feature_endpoint_is_used_or_excused`（反向核对） |
| 违反硬约束 §4.2 | 覆盖/还原漏了二次确认 | `test_overwrite_requires_confirm_dialog` 等 |
| 用户以为"翻完了"其实没翻 | 漏 `await runJob(...)`：界面立刻显示完成，任务还在跑 | `test_every_long_task_call_is_awaited` |
| `escapeHTML is not a function` | `import` 了 `dom.js` 里不存在的符号 —— **浏览器只在点到那一行时才报** | `test_imported_symbols_all_exist_in_dom_js` |
| 视觉漂移 | 页面里写死颜色值 | `test_no_inline_colour_values` |

**2) 后端路由表是"真装配"取来的，不维护第二份清单。**

测试通过真实的 `Registry` + `ui_routes.register_core_routes(ctx)` 装配后取
`router.routes()`，因此它断言的是**运行时事实**：如果有人改了端点路径而没改页面，
这条测试立刻红。

**3) "默认零破坏"在代码层面钉住，而不是靠文案。**

`test_default_mode_is_copy` 直接断言下拉里第一个 `<option>` 的 `value` 是 `copy`
—— 因为默认选中的就是第一项。想改成默认覆盖，必须先改这条测试，
从而强制作者面对"这是破坏性默认值"这件事。

### 怎么验证

```powershell
python tests/run_all.py                      # 635 例，0 失败 0 错误
python tools/check_footprint.py --quiet      # 39 文件 / 2 功能，退出码 0
python app.py --check                        # 退出码 0
node --check ui/web/pages/translate.js       # JS 语法（本机有 node 时）
$env:TUDOU_RPGTOOL_SAMPLES='D:\gamess'
python tests/run_all.py                      # 635 例全过
```

另外做了一次**真实 HTTP 烟测**（临时脚本，跑完即删）：真起一次服务，按页面的
期望形状核对 `/api/health`（`convergence.all_merged == true`）、`/api/nav`、
17 个翻译端点里可安全调用的那些、以及 5 个静态资源。
结果 19 项全过；其中**反向验证了"无会话时必须是明确报错而不是 500"**：
`backups` / `restore` / `build` / `skip_all` / `start` 在没有会话时都返回
`{ok: false, error: ...}`，页面据此用 `hint` 而非 `error` 展示。

### 踩坑记录

1. **烟测脚本自己的断言写错了两次**，而实现是对的：
   * 无会话时 `/api/translate/entries` **不返回** `pages` 字段（只有
     `page`/`size`/`total`）—— 断言写成了"必须有 `pages`"；
   * `/api/translate/skip_all` 无会话时的报错文案是"请先选择游戏目录并扫描文本"，
     而断言在找"扫描"二字。
   **教训：断言失败时先确认"是实现错了还是断言错了"** —— 这次是断言错了。
2. 页面里 `collectConfig` 需要区分"保存设置"与"接口自检"两种语义：
   保存时**不能**把空的 `api_key` 发上去（后端会保留已存 Key，但显式发空串
   语义就变成"我要清空"），而自检时必须发（否则后端用旧配置自检，用户会困惑）。
   用一个 `forTest` 参数区分，并把原因写进注释。

### 遗留

* M3b（`cheats` 的 5 类存档读写改回读）未开始，落地建议见 `docs/STATE.md` §7.2
* M4 统一界面：跨页视觉审查（`docs/UI_SPEC.md` §7 的 7 条）尚未做
* MZ / XP 的端到端构建仍只有合成样本；真实样本待 M5

---

## 2026-09-13 ｜ M3a 后端接线完成：翻译功能 17 个端点接入（含 N-15 与一处分层违规）

### 改了什么

| 文件 | 变更 |
| --- | --- |
| `features/translate/routes.py`（新，~570 行） | **翻译功能的后端接线**：17 个端点 —— `state` / `open` / `pick_folder` / `pick_font` / `scan` / `entries` / `entry` / `skip_all` / `start` / `providers` / `test` / `config`(GET+POST) / `build` / `backups` / `restore` / `open_dir`。含 `TranslateService`（会话持有者）、`_CancelBridge`（`CancelToken.is_cancelled()` → `is_set()`）、`sync_game_info()`（构建前校正 `session.info`） |
| `features/translate/manifest.py` | 从骨架改为**薄壳**：构造服务 + 委托 `register_routes` + 声明页面；`health()` 增加"4 个适配器都能构造"检查；`core_deps` 补 `builder` / `fontutil` |
| `core/sysdialog.py`（新，~200 行） | 原生对话框能力，从 `ui/native_pick.py` **下沉到 core**（见下"分层违规"）；`shell_candidates()` / `build_script()` 抽成**纯函数**以便在 CI 里断言 B-27 的修复 |
| `core/formats/mv_mz_data.py` | **N-15**：`_walk_event_list` 删掉多余的一层 `list`；`_set_by_path` 按父容器类型归一化末段键 |
| `core/safety/builder.py` | `_iter_entries()`：兼容 `Session.entries` 是 **keyed-dict**（键为 `"file|path"`、值为条目）这一真实形态；原先只做 `.values()` 会把条目当字段映射用 → `entry.get("status")` 静默取空 → **一条译文都写不进去** |
| `core/context.py`（未改） | `ctx.translate_service` 由 `register_routes` 挂在 ctx 上，供测试与调试页取用（已在 docstring 声明为非公共 API） |
| `tests/features/translate/test_routes.py`（新，88 例） | 17 个端点的**双向**契约核对 + 会话隔离夹具 + MV / VX Ace 两套合成夹具 + 端到端构建→写回→还原 |
| `tests/unit/test_sysdialog.py`（新，23 例） | B-27 修复点的可 CI 断言部分 |
| `tests/features/translate/test_scan_regressions.py` | 新增 `TestN15MVEventPathShape`（4 例） |
| `tests/unit/test_app.py`、`tests/unit/test_server.py` | 骨架端点 `/api/translate/status` 的断言换成真实业务端点；server 侧新增 3 个**真 HTTP** 用例 |

### 为什么（本轮两个"必须记"的发现）

#### 1) **N-15**：MV/MZ 的事件对话**写不进汉化版，而且不报错**

M2b 重构 `mv_mz_data._walk_event_list` 时，路径多拼了一层 `/list/`：

```text
实际产出：1/list/list/1/parameters/0     ← 多了一个 list
正确形状：1/list/1/parameters/0          ← path_prefix 已经含 "list"
```

`apply_to_files` 按路径定位失败 → **所有 401 对话与 402 选择项都写不进去**。
危害在于**每一层都是"成功"的**：扫描条数正常、界面显示正常、统计正常、
任务状态 `done`、构建返回 `entries: 2` —— 只有打开游戏才会发现剧情还是原文。

同一函数还有第二处：`_set_by_path` 只归一化**中间段**，末段原样返回字符串，
于是 `list[str]` 抛 `TypeError`，被上层 `except` 吞掉又是一种静默丢条目。

**怎么发现的**：M3a 写"构建后把文件读回来核对译文"的端到端用例时暴露的 ——
如果只断言"任务成功"，这个缺陷会一路进到用户手里。

#### 2) 一处**分层违规**：`features` 反向 import `ui`

第一次把对话框抽成 `ui/native_pick.py`，`features/translate/routes.py` 里
`from ui import native_pick` —— `python tools/check_footprint.py` 立刻报错：

```text
[ERROR][F-09] ... core/features 分层违规
```

这条不是"检查器太严"，而是**架构真的错了**：分层规定 `features → core`、
`ui → core + features`。**"弹一个系统对话框"与业务和界面都无关**
（和剪贴板同级），正确位置是 `core/sysdialog.py`；`ui/` 里只应有 HTTP 门面。

顺带一个收益：放进 `core` 后把 `shell_candidates()` 与 `build_script()` 抽成
纯函数，于是 **B-27（写死 PowerShell 绝对路径）的修复本身可以被 CI 断言**,
而不是只能靠"在一台机器上手点一次"。

### 怎么验证

```powershell
python tests/run_all.py                      # 585 例，0 失败 0 错误
python tools/check_footprint.py --quiet      # 39 文件 / 2 功能，退出码 0
python app.py --check                        # 退出码 0
$env:TUDOU_RPGTOOL_SAMPLES='D:\gamess'
python tests/run_all.py --suite compat       # 300 个 .rvdata2 零漂移 + 扫描量级断言
```

**关键证据**（不是"跑通了"，而是"内容真的变了"）：

| 断言 | 结果 |
| --- | --- |
| MV 构建后 `data/CommonEvents.json` 的 401 参数 | `"你好，旅行者。"` → `"旅行者"`（**N-15 的判据**） |
| MV 构建后 402 参数 | `["是","否"]` → `["旅行者","旅行者"]` |
| VX Ace 构建后 `Data/CommonEvents.rvdata2` 的 401 参数（重新解析字节流） | `"旅行者"` |
| `copy` 模式后原游戏目录指纹 | **字节不变** |
| 未确认覆盖已有输出 | 任务 `error: OverwriteNotConfirmed` |
| `inplace` 构建 | 一定生成 `backup_dir`，且 `list_backups` 能看到它（`has_manifest: true`） |
| 还原后 | 原文 `"你好，旅行者。"` 真的回来了，且还原前自动再备份一次 |

### 写测试时踩到的坑（值得记）

1. **后台任务必须先 `jobs.wait` 再断言**。`skip_all` 用例最初漏了这一步，
   于是断言与任务执行竞争 —— 同样的代码有时 0、有时 3，**间歇性红**。
   这类"偶发失败"最容易被误判成业务缺陷，已在用例注释里写明原因。
2. **`route.feature` 只有在 Registry 装配路径下才有值**。直接调
   `manifest.register(ctx)` 得到的是 `None` —— 想测"路由归属"就必须走
   `Registry.register_all(ctx)`，然后按 feature 过滤（注册表会装配所有功能）。
3. **handler 取用要包 `staticmethod`**。把普通函数赋成类属性后经 `self.handler`
   取会触发描述符协议变成 bound method，于是 `handler(Request)` 会多传一个
   `self`（M1 已经踩过一次，这次在探针脚本里又踩了一次）。
4. Windows 上 `TemporaryDirectory.cleanup` 会与刚写完会话文件的后台线程撞车
   （`OSError: [WinError 145] 目录不是空的`）→ 夹具用
   `ignore_cleanup_errors=True`（3.10+，3.8/3.9 自动退回）。

### 遗留

* **前端未接**：`ui/web/pages/translate.js` 仍是 M1 骨架，17 个端点只有
  `test_server.py` 的 3 个真 HTTP 用例覆盖"HTTP 层能通"（M4 统一界面时接入）
* MZ / XP 的端到端构建目前只有合成样本覆盖；真实样本待 M5 补齐
* M3b（`cheats` 的 5 类存档读写改回读）未开始

---

## 2026-09-12 ｜ M3a 开工：扫描链路跑通，并修掉三个"静默丢功能"缺陷（N-12/13/14）

### 改了什么

| 文件 | 变更 |
| --- | --- |
| `core/marshal/doc_model.py` | **N-14**：`_sym_name` 解析 `SymLink`（符号表引用）—— 回查 `node._parser.symbols`，新增有界的模块级解析器登记表 `_PARSERS`；`Parser` 遇到 SYMLINK 时登记解析器；新增节点访问辅助 `ivar()` / `ivar_names()` |
| `core/marshal/value_layer.py` | `loads` 改走 `doc_model.load_streams`（**只有它回填 `_parser`**，SymLink 才有符号表可查）；`_sym_name` 同样解析 SymLink |
| `core/formats/rgss_data.py` | **N-12**：新增 `_pairs_of()` / `_pairs_of_values()`，把 Array / Hash / 值层代理 / Ivar 包装统一成 `[(key, value)]`，所有遍历点改用它；**N-13**：`_text_of` 分三层剥代理，`@parameters` 取值后先 `_unwrap` |
| `tests/features/translate/test_scan_regressions.py`（新，41 例） | N-12/13/14 的单元断言 + **真实样本量级断言** |

### 为什么（这是本轮最值得记的一件事）

M2b 把 `rgss_data.py` 从 `value_model` 切到 `value_layer` 之后，
**VX Ace 的提取量从 6 千余条掉到 115 条，而且不报错。**
三个原因叠加，每一个都单独足以造成"静默丢功能"：

| 编号 | 根因 | 表现 |
| --- | --- | --- |
| **N-12** | `RPG::Map#@events` 是 **Hash**，vendored 代码用 `enumerate` 当列表遍历 | `RMDict.__getitem__(0)` 抛 `KeyError: 0`，整张地图的地图事件全丢 |
| **N-13** | 字符串在值层是 `RMStr` **代理**，`isinstance(v, str)` 不成立；`@parameters` 还是 Ivar 包装的数组，`len()` 为 0 | `_text_of` 返回 `None` → 所有 401/402 对话被判为"没有内容" |
| **N-14** | **`SymLink`（符号表引用）没被解析** | `class_name` 退化成 `"symbol#6"` → `class_name == "RPG::EventCommand"` 永远为假 |

修复效果（真实样本实测）：

```
VX Ace  boli\B7794     115 → 16,547 条（对话 15,545）
VX Ace  JIANTATA\ToT    350 → 48,103 条（对话 45,731）
```

**为什么必须记下来**：三处都不报错，只表现为"译文变少了"。
如果 M3a 只做接线、不做量级核对，这个问题会一直潜伏到用户发现。
所以新增的测试里除了单元断言，还有一条 `TestRealGameScanVolume`：
**四个真实游戏的提取量下界 + "VX Ace 必须包含对话而不只是界面术语"**
—— 让"数量级崩塌"变成测试能抓到的事。

### 怎么验证

```powershell
python tests/run_all.py                      # 492 例，0 失败 0 错误
$env:TUDOU_RPGTOOL_SAMPLES='D:\gamess'
python tests/run_all.py                      # 含扫描量级断言 + 300 个 .rvdata2 零漂移
python tools/check_footprint.py --quiet      # 37 文件，退出码 0
python app.py --check                        # 退出码 0
```

真实样本扫描基线（已写入 `docs/STATE.md` §5 供后续对照）：

| 游戏 | 引擎 | 条目 | 对话 | 耗时 |
| --- | --- | --- | --- | --- |
| `boli\B7794` | vxace | 16,547 | 15,545 | 1.5s |
| `JIANTATA\ToT 1.16.2.2` | vxace | 48,103 | 45,731 | 11.8s |
| `痴女の触手 官中版` | mv | 2,332 | 1,155 | 0.8s |
| `DD_V07c_Windows` | mz | 57,177 | 55,767 | 0.8s |

### 夹具踩坑（写测试时的三次返工，值得记）

`tests/features/translate/test_scan_regressions.py` 需要构造带 **SymLink** 的
节点树，为此返工三次：

1. `doc_model` 的序列化器**不做符号去重**（每个 Symbol 节点都写全名），
   所以"数一遍主夹具"得到的下标不可靠 → 改为用一张只含所需符号的小表探下标
2. 探符号表必须用 `doc_model.load_streams`（回填 `_parser`），
   `doc_model.loads` 不会 → 拿不到符号表
3. `D.Symbol(b"X")` 两个相等的对象**不会**被序列化成 `SymLink`，
   必须显式构造 `D.SymLink(index)`

这三条都写进了测试注释，避免下一个人重复踩。

### 遗留

* M3a 剩余：翻译（4 个引擎适配器接线 + 批量任务）、生成汉化版、还原、UI 页面接线
* 计划见 `docs/STATE.md` §7；M2a/M2b 建立的约束（原子写、`confirm_overwrite`、
  长任务可中断）在接线时必须遵守

---

## 2026-09-12 ｜ M2b（3/3 之三）：marshal 收敛完成 —— 旧值模型删除，需求 §3.3 三类重复全部归零

### 改了什么

| 文件 | 变更 |
| --- | --- |
| `core/marshal/value_layer.py` | 补 **ivar 编码传递**：从 ``Ivar`` 的 ``@encoding = :Windows_31J`` 解析出编码并带到内层字符串代理（`.enc`）。这是写回 cp932 数据不损坏的前提 |
| `core/marshal/doc_model.py` | 新增节点访问辅助 `ivar(node, name)` / `ivar_names(node)`（``ivars`` 是列表不是 dict，按名字取字段需要它） |
| `core/formats/rgss_data.py` | 由 `value_model` 切到 `value_layer`；判据统一为**鸭子类型**（`_is_object_proxy` / `_is_array_proxy` / `_is_ivar_proxy` / `_is_string_proxy`）；`_set_value` 改为**跟随原编码**写回 |
| `core/safety/builder.py` | `inject_font_script` 由 `value_model` 切到 `value_layer` + 节点层精确构造 |
| `core/marshal/value_model.py` | **删除** |
| `core/marshal/__init__.py` | `CONVERGENCE_STATUS`：`"pending"` → **`"merged"`** |
| `tests/compat/test_marshal_compat.py` | `TestValueModelRoundtrip` → `TestValueLayerRoundtrip`；新增 **`TestMarshalConvergence`**（6 例静态断言） |
| `tests/compat/test_m2a_regressions.py` | N-07 夹具改用**节点树**（更贴近真实：真实存档本来就是解析出的节点树）；新增两条**端到端**测试（真 `apply_to_files` + 原子写 + 重读校验） |

### 为什么

需求 §3.3 的验收硬指标："合并后上述三类职责各只有一份实现"。
M2b 前两步已收敛 formats 与删除脚手架，本步完成最后一项。

### 关键设计：为什么值层不重新解析

`value_layer` 的代理**直接持有并改写 `doc_model` 的 Node**：
改代理 = 改 Node，因此 `doc_model.dumps` 里未触碰的子树仍吐原始字节，
字节保真与"值层便利"同时成立，且**全工程只有一个解析器**。
若走"值 ↔ 节点来回转换"的路线，字节保真会丢失 —— 这是本步最核心的取舍。

### 本步的两个真实难点

1. **编码传递**：`doc_model` 是纯字节的（这正是它字节保真的原因），
   字符串编码藏在 `Ivar` 包装里。若不把它带到 `RMStr.enc`，
   `_set_value` 就会一律按 UTF-8 写回 —— XP 的 cp932 文本会被重新编码，
   字节数变化，游戏读到的字符串长度可能不对。
   修法：`wrap()` 遇到 `Ivar` 时解析 `@encoding` 并传给内层代理。
2. **鸭子类型判据**：`wrap()` 把 `Array`/`ObjectNode`/`String` 分别包成
   `RMArray`/`RMObject`/`RMStr` **代理**，`isinstance(x, marshal.RMObject)`
   这类旧判据不再成立。统一改为按能力判断（有 `class_name`+`ivars` 即对象，
   类名 `RMArray` 即数组，字符串代理明确排除在"可下标"之外 ——
   否则给字符串取整数下标会取到字符，把 402 选择项写错位置）。

### 怎么验证

```powershell
python tests/run_all.py                      # 475 例，0 失败 0 错误
$env:TUDOU_RPGTOOL_SAMPLES='D:\gamess'
python tests/run_all.py                      # 300 个真实 .rvdata2 零漂移
python tools/check_footprint.py --quiet      # 37 文件，退出码 0
python app.py --check                        # 退出码 0
```

`/api/health` 实测：

```json
{"engines":"merged","formats":"merged","marshal":"merged","all_merged":true}
```

需求 §3.3 三类重复的实现文件核对：`core/engines.py`、`core/formats/jsoncodec.py`、
`core/marshal/{doc_model,value_layer}.py` 各就各位；
`core/marshal/value_model.py` 与 `core/_refbridge.py` 均已删除。

### 防退化断言（`TestMarshalConvergence`）

* `CONVERGENCE_STATUS == "merged"`
* `value_model.py` 不得复活
* 不得有模块 import `value_model`
* `core/marshal/` 下只允许 `doc_model.py` + `value_layer.py` + `__init__.py`，
  且门面里不得出现 `class Parser` / `_parse_fixnum` / `struct.unpack(` / `buf[self.pos]`
* 两个真实调用方都必须 import `value_layer`
* `/api/health` 的 `all_merged` 必须为 true

### 遗留

* M2b 完成。**下一步 M3a**：翻译功能接入（扫描 → 翻译 → 生成汉化版 → 还原），
  计划见 `docs/STATE.md` §7
* 已知未验证边界不变：真机 VX/XP 样本仍空白；Python 3.8 仅静态检查

---

## 2026-09-12 ｜ M2b（3/3 之二）：值层门面 `value_layer.py` 落地（marshal 收敛的实施第一步）

### 改了什么

| 文件 | 内容 |
| --- | --- |
| `core/marshal/value_layer.py`（新，约 640 行） | 在**文档模型**之上提供"像 Python 对象一样读写"的值层视图 |
| `tests/unit/test_marshal_value.py`（新，36 例） | 覆盖标量、对象代理、**改动落到 Node**、字节稳定性、Hash/Array、unwrap |

### 为什么这样合（ADR-004 的关键设计）

`core/marshal/` 有两份独立实现：`doc_model`（Node 树 + `Node.raw` 增量字节保真）
与 `value_model`（`RM*` 类 + 直接读写 Python 值）。ADR-004 定的方向是
"文档模型为二进制层主体、值模型降为门面"。

**但"把值模型搬到文档模型上跑两遍编解码"是错的** —— 那会丢掉字节保真。
本实现的机制是让值层对象**直接持有并改写 Node**：

* 读：`wrap(node)` 把 Node 包成 `RMObject` / `RMStr` / `RMIvar` 等代理
* 写：代理上的修改经 `_IvarMap` / 列表视图**立刻落到 Node**
* 存：`doc_model.dumps(root)` —— 因为改的就是 Node，未触碰的子树仍吐原始字节

于是"值层的便利"与"文档模型的字节保真"同时成立，且**只有一份解析器**。
这正是需求 §3.3 想要的收敛结果。

### 唯一的真难点：ivar 键的两种约定

* 文档模型的 `ObjectNode.ivars` 是 **`(Symbol 节点, 值节点)` 的列表**，名字带 `@`
* 旧值模型与所有调用方（`core/formats/rgss_data.py`）用**普通 dict**，
  键是 `str`，且**允许省略 `@`**（`rgss_data` 两种都写）

`_IvarMap` 因此做成"双向容忍"的映射视图：读时先试原样再试加/去 `@`；
写时复用已存在的键名（避免产生 `level` 与 `@level` 两个键），
不存在则按该对象现有习惯决定是否加 `@`。Hash 键用同一套规则（`_key_candidates`）。

### 怎么验证

```powershell
python tests/run_all.py                      # 466 例，0 失败 0 错误
$env:TUDOU_RPGTOOL_SAMPLES='D:\gamess'
python tests/run_all.py                      # 300 个真实 .rvdata2 零漂移
python tools/check_footprint.py --quiet      # 38 文件，退出码 0
python app.py --check                        # 退出码 0
```

关键断言：**未改动的往返字节一致**（`test_untouched_roundtrip_is_byte_exact`）、
**只改一个字段时其它子树仍吐原始字节**（`test_untouched_subtree_keeps_raw_bytes`）、
**用不带 `@` 的键写不会新建重复键**（`test_set_without_at_prefix_reuses_existing_key`）。

### 实现期间踩到的三个坑（已写进测试注释）

1. `Bignum(sign, digits)` 的 `sign` 是 `b'+'`/`b'-'`，`digits` 是 16 位数字组
   —— 不是原始字节
2. 代理之间比较要**递归展开**：`dict(self.items()) == other` 会拿
   `RMArray`/`RMDict` 与 `[1,2]`/`{1:2}` 比，必然不等。为此加了 `to_plain()`
   （明确标注"只用于比较/展示，不要用它写回"）
3. Hash 的符号键有的带 `@` 有的不带，键匹配必须与 `_IvarMap` 用同一套容忍规则

### 遗留（M2b 最后一步）

`value_layer` 目前**尚未被任何生产代码使用** —— 下一步才是切换：

1. `core/formats/rgss_data.py` 由 `from ..marshal import value_model` 改为
   用 `value_layer`（接口已按它的用法设计：`RMObject.ivars[...]`、
   `RMIvar.value`、`RMStr.enc`、`loads`/`dumps`）
2. `core/safety/builder.py` 的字体脚本注入改用 `value_layer` 构造节点
3. 删除 `core/marshal/value_model.py`，`CONVERGENCE_STATUS` 置 `"merged"`
4. 加静态断言：`core/marshal/` 下只剩一份二进制实现

---

## 2026-09-12 ｜ M2b（3/3 之一）：删除 `core/_refbridge.py`，`/api/health` 改报收敛状态

### 改了什么

| 文件 | 变更 |
| --- | --- |
| `core/_refbridge.py` | **删除**（M1 引入的临时脚手架，14 项登记） |
| `tests/unit/test_refbridge.py` | **删除**（13 例，测的是桥接层自身） |
| `tests/unit/test_engines.py` | 移除 `TestReferenceParity`；`@public` 更新 |
| `ui/routes.py` | 移除 refbridge 引用；新增 `convergence_status()`；`/api/health` 的 `reference` 段 → **`convergence` 段** |
| `ui/web/app.js` | 顶栏 chip 由"待收敛参考实现 N"改为"**收敛 x/3**"（`ok` 色表示全部收敛） |
| `tests/integration/test_startup.py` | 健康检查键列表更新；新增 `test_health_reports_convergence_progress` |
| `features/translate/manifest.py`、`core/safety/__init__.py` | `@depends` 更新 |
| `AGENTS.md`、`docs/MODULES.md`、`docs/ROADMAP.md`、`docs/STATE.md` | 同步 |

### 为什么

需求 §3.3 要求三类重复实现各只剩一份。桥接层的存在本身会让"到底还有几份实现"
变得含糊 —— 它是 M1/M2a 期间为了拿"新实现 vs 旧实现一致性"证据而引入的脚手架，
收敛完成后必须消失。

### 关键做法：先冻结证据，再删脚手架

直接删桥接层会**连带删掉唯一的等价性证据**（`TestReferenceParity` 依赖它）。
所以先用独立夹具把结论固化下来（上一个提交 `b3a0ff1`），本提交才动刀。
夹具不依赖参考工具，任何机器可跑。

### 顺带改进：把"收敛进度"变成可观测事实

原先 `/api/health` 报的是 `reference.pending`（桥接层还剩几项）——
那是**过程指标**。现在改为 `convergence` 段：

```json
{"engines": "merged", "formats": "merged", "marshal": "pending", "all_merged": false}
```

这是需求 §3.3 的**交付指标**本身，而且顶栏直接显示"收敛 x/3"。
好处：验收者不必读文档就能看到收敛是否完成；文档与运行时会不一致的情况也少了。
新增 `test_health_reports_convergence_progress` 钉住它。

### 怎么验证

```powershell
python tests/run_all.py                      # 430 例，0 失败 0 错误
$env:TUDOU_RPGTOOL_SAMPLES='D:\gamess'
python tests/run_all.py                      # 300 个真实 .rvdata2 零漂移 + 冻结基线通过
python tools/check_footprint.py --quiet      # 37 文件，退出码 0
python app.py --check                        # 退出码 0
```

实测 `/api/health` 的收敛段：`engines=merged, formats=merged, marshal=pending`。

### 遗留

* `core/marshal/` 仍是两份实现 —— **M2b 只剩这一项**，计划见 `docs/STATE.md` §7.1

---

## 2026-09-12 ｜ M2b（2/3）：测试去重 + 把"与旧实现等价"的证据冻结为独立夹具

### 改了什么

| 项 | 内容 |
| --- | --- |
| 删除 `tests/unit/test_misc.py` | 它把 5 个模块的用例混在一起，而 `test_config.py` 只是**再导出**一次 → 同一批用例执行两遍（unit 层计数虚高到 371） |
| `tests/unit/test_config.py` | 收纳 `TestConfig` + `TestConstants`（并补了 batch_size 钳制、`redacted` 五种密钥名、`default_config_path`、`DATA_EXTS` 覆盖等用例） |
| `tests/unit/test_engines.py` | 新增 `TestFrozenRealGameBaseline`（4 例）与 `TestFrozenDetectionFixtures`（4 例） |
| `core/textutil.py` | 修正 docstring 里指向已删除 `test_misc.py` 的引用 |

### 为什么

两件事，都是 M2b 剩余工作的前置条件：

1. **去重**：`docs/STATE.md` §7.3 登记的"计数翻倍"问题。真实用例数比显示值少 49，
   会让"测试覆盖是否足够"的判断失去准头。
2. **冻结证据**（关键）：`core/_refbridge.py` 是为"新实现 vs 旧实现"对照而存在的
   临时脚手架，M2b 要删掉它。但**直接删会连带删掉唯一的一份等价性证据**
   （`TestReferenceParity` 依赖 refbridge）。所以先把结论固化成不依赖参考工具的夹具。

### 冻结了什么

| 夹具 | 内容 |
| --- | --- |
| `FROZEN_REAL_GAME_BASELINE`（7 条） | 7 个真实游戏的**引擎判定 + 存档数量**，采集时同时比对本工程与**两个**旧实现，三者全部一致（含"未识别"一例） |
| `FROZEN_DETECTION_FIXTURES`（13 条） | 每种标记文件组合 → 期望引擎。**同时覆盖两套 MV/MZ 判据**（`*_core.js` 属修改工具、`*_managers.js` 属翻译工具）、www 布局、System.json 兜底、RGSS 三档、2000/2003、未识别 |

另加一条"能力提升"断言：旧翻译工具识别不出 VX（`.rvdata`），本实现必须支持 ——
这是合并带来的实际收益，值得单独钉住。

夹具的注释里写明了**采集时间与采集方式**，并说明"若判定变化，本表会失败，
那时必须回答是有意改进还是回归"。这样它就不是一份会慢慢腐烂的快照。

### 怎么验证

```powershell
python tests/run_all.py                      # 444 例，0 失败 0 错误
$env:TUDOU_RPGTOOL_SAMPLES='D:\gamess'
python tests/run_all.py                      # 冻结基线 4 例通过（真实样本）+ 300 个 .rvdata2 零漂移
python tools/check_footprint.py --quiet      # 38 文件，退出码 0
python app.py --check                        # 退出码 0
```

### 遗留

* `core/_refbridge.py` 与其 13 例测试仍存在 —— 但**删除路径已写成机械步骤**
  （6 步，见 `docs/STATE.md` §7.2），下一轮直接执行
* `core/marshal/` 仍是两份实现（3/3 部分），计划见 §7.1

---

## 2026-09-12 ｜ M2b（1/3）：抽出 `core/formats/jsoncodec.py`，MV/MZ 编解码收敛为一份

### 改了什么

| 文件 | 内容 |
| --- | --- |
| `core/formats/jsoncodec.py`（新，约 300 行） | MV/MZ 共享编解码层：文本/JSON 两种风格、BOM 容忍、JsonEx 元数据键唯一真源、加密包装的密钥派生与异或流、LZString/zlib 压缩与**按内容**判别 |
| `core/formats/mv_mz_data.py` | 包装四函数改为**转发** jsoncodec；`_save_data_file` 用 `dumps_pretty` + 原子写 |
| `core/formats/mv_save.py` | `_load`/`_dump` 改用 `decompress_save`/`compress_save`；`META_KEYS` 变别名；`_clean_ints` 转发 `int_map_from`；`_load_json` 转发 `read_json_file`；`PARAMS` 改从 `core/constants.py` 导入（消除第二处重复）；**按内容**判定 engine |
| `core/formats/__init__.py` | `CONVERGENCE_STATUS`：`pending` → `"merged"` |
| `tests/unit/test_jsoncodec.py`（新，35 例） | 编解码全覆盖 + `TestConvergence` 静态断言收敛结果 |

### 为什么

需求 §3.3 第三类重复的验收硬指标："合并后上述三类职责各只有一份实现"。
收敛前，MV/MZ 两条路径各写了一套 JSON / 压缩 / 编码约定（`utf-8-sig`、
JsonEx 元数据键、加密包装、LZString/zlib）。

### 怎么验证

```powershell
python tests/run_all.py                      # 493 例，0 失败 0 错误
$env:TUDOU_RPGTOOL_SAMPLES='D:\gamess'
python tests/run_all.py                      # 300 个真实 .rvdata2 零漂移
python tools/check_footprint.py --quiet      # 38 文件，退出码 0
python app.py --check                        # 退出码 0
```

`TestConvergence` 的四条静态断言（防止后来者再写一遍）：

* 两个模块都必须使用 `jsoncodec`
* `mv_mz_data` 不得再出现 `base64.b64decode` 或 `205 ^`（第二份包装实现）
* `META_KEYS` 只能有一处定义
* `zlib` / `lzstring` 调用不得散落在 `mv_mz_data` / `mv_save`

### 设计取舍

* **两种 JSON 风格都保留**：游戏数据要可读（缩进 2，便于用户与后续 AI 排查），
  存档要紧凑（会被压缩，且与引擎写法一致）。收敛的是"约定"而不是"格式"。
* **压缩按内容判别而非扩展名**：真实游戏里存在扩展名与内容不一致的情况
  （改包 / 工具生成 / 汉化版重打包）。`is_zlib_stream` 看首字节 `0x78`。
  顺带修正 `SaveFileMV.__init__`：engine 现在也按内容判定，与 `_load` 一致。
* **坏 JSON 抛错而非返回 None**：调用方需要区分"文件不存在"与"文件损坏"。

### 遗留（M2b 剩余 2/3）

* `core/marshal/` 仍是两份实现 → 下一轮按 ADR-004 收敛（接口面与已知陷阱已写入
  `docs/STATE.md` §7.1）
* `core/_refbridge.py` 仍是 14 项登记 → 需先把 `test_engines.py::TestReferenceParity`
  的对照结论固化为内联期望值，再删除桥接层（`docs/STATE.md` §7.2）

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

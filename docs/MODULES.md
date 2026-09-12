# 模块地图（MODULES）

> 用途：**要改某个文件之前先读这里** —— 它负责什么、公开 API 是什么、
> 谁在调用它、改动会影响什么。
> 自动化版本：`tools/gen_footprint.py` 会从各文件 docstring 的 `@public`
> 生成 `docs/footprint.json` 的 `files` 段；**本文件负责"谁调用/影响面"这类
> 无法自动推导的信息**，两者互补。变更时机：新增/移动模块时。

---

## 0. 快速索引

| 你收到的需求 | 先看这些文件 |
| --- | --- |
| 支持的引擎种类要增加 | `core/constants.py` → `core/engines.py` → `core/formats/*` |
| 某类游戏识别不出来 | `core/engines.py`（判据表在 §core/engines.py） |
| 存档读不出来 / 读出来是乱码 | `core/formats/mv_save.py` 或 `rgss_save.py` → `core/marshal/` |
| 译文写回后游戏崩了 | `core/formats/mv_mz_data.py` 或 `rgss_data.py` 的 `apply_to_files` |
| 写盘要更安全 | `core/safety/atomic.py`（唯一写盘手段） |
| 备份/还原行为不对 | `core/safety/backup.py` |
| 想加一个新功能 | `docs/FEATURES.md#契约` → `core/registry.py` / `core/context.py` |
| 长任务卡住 / 不能取消 | `core/jobs.py` |
| 界面样式不统一 | `ui/web/tokens.css` + `components.css` + `docs/UI_SPEC.md` |
| 新增一个页面 | `features/<name>/manifest.py` 里加 `pages` 一条 + 新建 `ui/web/pages/<id>.js` |
| 足迹校验报错 | `tools/check_footprint.py`（12 条规则见文件头 RULES） |

---

## 1. `core/` —— 纯逻辑层（不得 import ui / features）

### core/constants.py

| 项 | 内容 |
| --- | --- |
| 职责 | 引擎标识、存档命名规则、属性名等**常量的唯一真源** |
| 公开 API | `ENGINES`、`ENGINE_ORDER`、`DATA_EXTS`、`SAVE_PATTERNS`、`SAVE_EXTS`、`PARAMS`、`PARAM_LABELS`、`SUPPORTED_ENGINES`、`RECOGNIZE_ONLY_ENGINES`、`engine_label()`、`is_supported()` |
| 谁调用 | `core/engines.py`、`features/cheats/manifest.py`、`tests/*` |
| 改动影响 | **全工程**。改 `SAVE_PATTERNS` 会同时影响两个功能的存档发现 |
| 消除的重复 | 原 `rpgdata.py:180` 与 `mvdata.py:100` 各有一份逐字相同的 `PARAMS`（且都零引用） |

### core/engines.py

| 项 | 内容 |
| --- | --- |
| 职责 | 引擎识别 + 数据目录/存档目录发现（**合并后的唯一实现**） |
| 公开 API | `detect_engine()`（未识别返回 None）、`detect()`（永远返回带 `error` 的 info）、`describe()`、`list_saves()`、`find_save_dirs()`、`data_dir()`、`save_dir()` |
| 判据优先级 | ① MV/MZ：`js/rmmz_managers.js` → `www/js/rmmz_managers.js` → `js/rmmz_core.js` → `www/js/rmmz_core.js` → `rpg_managers.js` 系列 → `rpg_core.js` 系列<br>② System.json 兜底（读 `equipTypes`/`itemCategories`/`locale` 判 MZ）<br>③ RGSS：`Data/*.rvdata2`→vxace、`*.rvdata`→vx、`*.rxdata`→xp<br>④ `RPG_RT.ini`/`*.ldb` → 2k3（只识别） |
| 返回结构 | `{engine, label, data_dir, save_dir, ext, standard, layout, supported, match, game_dir, error}` |
| 谁调用 | `features/cheats/manifest.py`（`/api/cheats/detect`）、`features/translate/session.py`、`core/_refbridge.py`（对照测试） |
| 改动影响 | 两个功能都依赖。改判据请同步 `tests/unit/test_engines.py::TestReferenceParity`（与两个旧实现比对） |
| 比原实现多出的能力 | 识别 **VX（`.rvdata`）** —— 原翻译工具 `tool/engines.py:62-71` 不识别 VX，会落到"未识别" |

### core/registry.py

| 项 | 内容 |
| --- | --- |
| 职责 | 扫 `features/*/`，加载 `manifest.py`，校验必备字段，调用 `register(ctx)` |
| 公开 API | `Registry`、`FeatureModule`、`FootprintMeta`、`discover()`、`get_registry()`、`reset_registry()`、`MANIFEST_FILENAME`、`REQUIRED_FIELDS` |
| 谁调用 | `app.py:App.build()`、`ui/routes.py`、`tests/unit/test_registry.py` |
| 改动影响 | **所有功能的注册方式**。改契约要同步 `docs/FEATURES.md` 与两个 manifest |
| 关键取舍 | 不做"放文件即生效"的 import 魔法：直接用 `os.listdir` 判定并给出可读错误。缺 `__init__.py`、缺 `MANIFEST` 字段、id 重复都会报错而不是静默跳过 |

### core/context.py

| 项 | 内容 |
| --- | --- |
| 职责 | `register(ctx)` 的契约对象：路由表、页面声明、只读路径 |
| 公开 API | `Router`、`Route`、`PageSpec`、`AppContext` |
| 谁调用 | `app.py`、`ui/routes.py`、所有 `features/*/manifest.py` |
| 改动影响 | 改 `Route._compile` 会影响所有路由匹配；改 `AppContext.route/page` 影响所有功能的注册代码 |
| 特性 | 路径占位段（`/api/x/{id}`）、装饰器与直接调用双形态、**路由自动归属登记它的功能 id**（`test_registry.py` 用它断言功能没越界登记路由） |

### core/jobs.py

| 项 | 内容 |
| --- | --- |
| 职责 | 后台任务队列：有界并发、每任务取消、TTL 回收、快照输出 |
| 公开 API | `JobManager`、`Job`、`CancelToken`、`Cancelled`、`TRACEBACK` |
| 谁调用 | `app.py`、`ui/routes.py`（`/api/job`、`/api/jobs`、`/api/cancel`） |
| 改动影响 | 影响所有长任务（扫描/翻译/生成汉化版）的进度与取消 |
| 修正的原缺陷 | B-22：无并发上限 / 任务永不回收 / 只有全局取消 / `/api/job` 返回可变 dict |
| 关键实现 | `Job.finalize()` 在锁内**一次性发布终态**（避免"已失败但 traceback 还是 None"的竞态，M1 实测发现 N-06） |

### core/config.py

| 项 | 内容 |
| --- | --- |
| 职责 | 全局设置读写（含 API Key），原子写，掩码输出 |
| 公开 API | `AppConfig`、`DEFAULTS`、`SECRET_KEYS`、`read_config()`、`write_config()`、`redacted()`、`load_config()`、`save_config()`、`default_config_path()` |
| 谁调用 | `app.py`、`ui/routes.py`（`/api/config`，M3a 接入） |
| 改动影响 | 键名沿用原工具，保证旧 `config.json` 可直接迁移 |
| 新增能力 | `redacted()` —— 日志/接口返回时掩码密钥（原工具 `/api/config` 原样返回完整 Key） |

### core/paths.py

| 项 | 内容 |
| --- | --- |
| 职责 | 路径解析唯一真源（工程根、运行时目录、参考工具、样本根） |
| 公开 API | `project_root()`、`core_dir()`、`features_dir()`、`ui_dir()`、`web_dir()`、`tests_dir()`、`tools_dir()`、`docs_dir()`、`data_dir()`、`sessions_dir()`、`logs_dir()`、`ensure_dir()`、`reference_root()`、`reference_roots()`、`reference_tool()`、`reference_available()`、`samples_root()`、`ENV_*` 常量 |
| 谁调用 | 几乎所有模块 |
| 改动影响 | 全工程。**函数式 + 环境变量覆盖**（原实现是模块级常量，导致无法多实例、测试无法隔离 —— B-25） |

### core/textutil.py

| 项 | 内容 |
| --- | --- |
| 职责 | RPG Maker 文本的控制码切分与还原 |
| 公开 API | `CONTROL_RE`、`split_text()`、`has_real_text()`、`collect_segments()`、`rebuild()` |
| 谁调用 | `core/formats/mv_mz_data.py`、`core/formats/rgss_data.py`、`features/translate/translators.py` |
| 改动影响 | 影响**所有文本提取与翻译重组**。改正则要同步 `tests/unit/test_textutil.py` |
| ⚠ 已知问题 | N-08：注释声称支持 `\{ \} \^ \| \. \! \> \< \$`，但正则要求反斜杠后必须是字母 → 这些符号型转义从不被匹配（M2a 处置）。测试里有一条**固化当前行为**的用例，修好时会失败以提醒更新 |

### core/marshal/（⚠ 临时含两份实现）

| 文件 | 职责 | 公开 API | 谁调用 |
| --- | --- | --- | --- |
| `doc_model.py` | **文档模型**：22 个 Node 类，`Node.raw` + `dirty` 增量字节保真，支持多流与 XP/VX 标准模式 | `Node`、`Parser`、`loads`、`dumps`、`load_streams`、`mark_dirty`、`VERSION` | `core/formats/rgss_save.py`、`tests/compat/test_marshal_compat.py` |
| `value_model.py` | **值模型**：13 个 `RM*` 类，编码感知，可直接从 Python 值构造并 dump | `loads`、`dumps`、`RMStr`、`RMIvar`、`RMObject`、`RMDict`、`RMSymbol`、`RMStruct`、`RMUserDefined`、`RMUserMarshal`、`RMRegexp`、`RMData`、`RMClass`、`RMModule`、`RMFloat` | `core/formats/rgss_data.py`、`core/safety/backup.py` |
| `__init__.py` | 收敛状态标记 | `CONVERGENCE_STATUS`（当前 `"pending"`） | `tools/check_footprint.py` |

**改动影响**：这两份实现**都必须通过 300 个真实样本的字节级往返测试**
（`tests/compat/test_marshal_compat.py`）。修改任何一份之后必须重跑 compat 层。
**M2b 目标**：以 `doc_model` 为二进制层主体、`value_model` 降为对象门面，收敛为一份。

### core/formats/

| 文件 | 职责 | 公开 API | 谁调用 |
| --- | --- | --- | --- |
| `mv_mz_data.py` | MV/MZ **游戏数据**（`data/*.json`）提取与写回，含加密 JSON 包装 | `extract()`、`apply_to_files()`、`TEXT_CODES`、`WRAPPER_KEYS`、`_load_data_file()`、`_save_data_file()`、`_MULTI_VALUE_CODES`、`_choice_texts()` | `features/translate/session.py`、`core/safety/backup.py`、`core/formats/rgss_data.py`（复用 `TEXT_CODES`） |
| `rgss_data.py` | VX Ace/XP **游戏数据**（`Data/*.rvdata2|rxdata`）提取与写回 | `extract()`、`apply_to_files()` | `features/translate/session.py`、`core/safety/backup.py` |
| `mv_save.py` | MV/MZ **存档**（LZString / zlib 双格式自动判别） | `GameDataMV`、`SaveFileMV`、`META_KEYS` | `features/cheats/manifest.py`（M3b 接线） |
| `rgss_save.py` | RGSS **存档**（hash / contents 双布局，多流同步） | `GameData`、`SaveFile`、`sync_dirty()`、`find_top_hash()` | 同上 |
| `lzstring.py` | MV 存档所用的 LZString 编解码 | `compress`、`decompress`、`compress_to_base64`、`decompress_from_base64` | `core/formats/mv_save.py` |
| `__init__.py` | 收敛状态标记 | `CONVERGENCE_STATUS`（当前 `"pending"`） | — |

**改动影响**：这三个职责（数据提取 / 数据写回 / 存档读写）直接决定"功能是否等价"。
改 `TEXT_CODES` 会同时改变 MV/MZ 与 RGSS 两条提取路径（它们共用这张表 —— 这是**有意**的，
防止两处规则漂移）。

**M2b 目标**：抽出 `jsoncodec.py`（JSON + LZString + zlib + 加密包装），
让游戏数据与存档两条路径共用一份编解码实现。

### core/safety/（M2a 拆为四个模块，依赖方向单向）

| 文件 | 职责 | 公开 API | 谁调用 |
| --- | --- | --- | --- |
| `atomic.py` | **唯一的写盘手段**：原子写 + 备份文件 + 目标护栏 | `atomic_write_bytes()`、`atomic_write_text()`、`sibling_backup()`、`assert_safe_target()`、`next_free_dir()`、`unique_temp_path()`、`AtomicWriteError`、`SafeTargetError` | 所有需要写文件的模块 |
| `backup.py` | 备份 / 还原 / 清单（**不 import `core.formats`** —— 这是切断 import 环的关键） | `backup_files()`、`restore_backup()`、`list_backups()`、`safety_backup()`、`write_manifest()`、`read_manifest()`、`record_created()`、`BACKUP_PREFIX`、`MANIFEST_NAME` | `builder.py`、M3a/M3b 接线 |
| `builder.py` | **生成汉化版的编排层**：暂存换名（B-01）、字体应用（B-03）、失败回滚（B-06）、覆盖确认（B-05） | `build()`、`apply_font()`、`copy_tree()`、`default_target_dir()`、`resolve_target_dir()`、`font_touched_paths()`、`patch_core_js()`、`inject_font_script()`、`install_user_font()`、`OverwriteNotConfirmed`、`BuildFailed`、`FONT_FALLBACK_NAMES` | `features/translate/manifest.py`（M3a 接线） |
| `fontutil.py` | 字体族名解析（ttf/otf/ttc） | `extract_family()`、`safe_filename()` | `builder.py` |

**依赖方向（务必保持）**：

```
atomic  ←  backup  ←  builder  →  fontutil
                       ↓
                 core.formats
```

`backup.py` **不得** import `core.formats`：一旦引入就会形成
`formats.__init__ → mv_mz_data → safety.__init__ → builder → formats` 的环（ADR-011）。
`core/safety/__init__.py` 用 PEP 562 `__getattr__` 懒加载子模块来打破该环。

**⚠ 改 `builder.py` 之前必须先读** `docs/STATE.md` §5 的 P0 清单 ——
这个文件承载了 5 个已修的数据安全缺陷，每一条都有回归断言
（`tests/compat/test_m2a_regressions.py`），改坏会立刻红灯。

---

## 2. `features/` —— 可插拔功能模块

| 文件 | 职责 | 公开 API | 谁调用 |
| --- | --- | --- | --- |
| `features/__init__.py` | 包标记 + 契约说明 | `LAYER`、`REQUIRED_FILE` | — |
| `features/translate/manifest.py` | 翻译功能的自我描述与注册 | `MANIFEST`、`register()`、`health()` | `core/registry.py` |
| `features/translate/translators.py` | 4 个翻译引擎适配器 + 批量翻译执行器（vendored） | `build_translator`、`translate_entries`、`TranslateError`、`TruncatedError`、`GoogleTranslator`、`OpenAICompatibleTranslator`、`DeepLTranslator`、`_http` | M3a 接线 |
| `features/translate/session.py` | 翻译会话与进度持久化（vendored） | `Session`、`ScanOptions`、`DEFAULT_OPTIONS` | M3a 接线 |
| `features/cheats/manifest.py` | 修改功能的自我描述与注册 | `MANIFEST`、`register()`、`health()` | `core/registry.py` |
| `features/cheats/__init__.py` | 包标记 | `manifest` | — |

**功能注册的路由**（M1 现状）：

| 路由 | 功能 | 状态 |
| --- | --- | --- |
| `GET /api/translate/status` | translate | 骨架占位 |
| `GET /api/translate/providers` | translate | **可用**（列出 4 个适配器） |
| `GET /api/cheats/status` | cheats | 骨架占位 |
| `POST /api/cheats/detect` | cheats | **可用**（引擎识别 + 存档发现，走 `core/engines.py`） |

---

## 3. `ui/` —— 界面层

| 文件 | 职责 | 公开 API | 谁调用 |
| --- | --- | --- | --- |
| `ui/server.py` | HTTP 服务：`Router` 分发、静态资源（防穿越）、Host/Origin 白名单、统一响应 | `Request`、`Response`、`JsonApiServer`、`safe_int()`、`safe_bool()`、`make_server()`、`start()`、`free_port()`、`ALLOWED_HOSTS` | `app.py` |
| `ui/routes.py` | 不属于任何功能的核心路由 | `register_core_routes()` | `app.py` |
| `ui/web/index.html` | 页面骨架（#nav / #view / #toast + 功能状态表 + 诊断面板） | — | 浏览器 |
| `ui/web/app.js` | 启动引导、导航渲染、页面动态 import、诊断 | `boot`、`renderNav`、`renderFeatureTable`、`mountPage` | `index.html` |
| `ui/web/dom.js` | 前端共享工具 | `$`、`$$`、`el`、`escapeHTML`、`api`、`getJSON`、`postJSON`、`toast`、`modal`、`confirmDialog`、`waitJob`、`fmtBytes`、`fmtDuration`、`pct` | 所有页面模块 |
| `ui/web/tokens.css` | 设计令牌（唯一配色真源） | — | 所有 CSS |
| `ui/web/components.css` | 共享组件库 | — | 所有页面 |
| `ui/web/pages/translate.js` | 翻译功能页 | `render(host, ctx)` | `app.js` 动态 import |
| `ui/web/pages/cheats.js` | 修改功能页 | `render(host, ctx)` | 同上 |

**核心路由表**（`ui/routes.py` 登记，不属任何功能）：

| 路由 | 作用 |
| --- | --- |
| `GET /api/health` | 整体健康检查（应用/注册表/任务/UI/参考实现可用性） |
| `GET /api/features` | 已加载功能清单 + 每个功能的健康检查 |
| `GET /api/nav` | 前端导航数据 |
| `GET /api/pages` | 所有功能声明的页面 |
| `GET /api/routes` | 路由表（调试与足迹核对） |
| `GET /api/job?id=` | 任务快照 |
| `GET /api/jobs` | 最近任务列表 |
| `POST /api/cancel` | 取消指定任务（无 id 则全部） |
| `GET /api/paths` | 工程路径（方便定位） |
| `GET /api/time` | 服务端时间 |

---

## 4. `tools/` —— 开发期脚本

| 文件 | 职责 | 公开 API | 说明 |
| --- | --- | --- | --- |
| `check_footprint.py` | 足迹校验器（**12 条规则**，失败非零退出） | `Checker`、`Finding`、`RULES`、`parse_meta()`、`expected_layer()`、`module_name_for()`、`main()` | 评审者一键验证足迹真实性的入口 |
| `gen_footprint.py` | 从源码 docstring 生成 `docs/footprint.json` | `build_footprint()`、`TEST_COMMANDS`、`LAYERS`、`main()` | 源码变动后必须重跑 |
| `_m1_fix_future_imports.py` | **一次性**：vendored 文件加足迹头（合并进 docstring） | `PLAN`、`merge_header()`、`main()` | M2a 后删除 |
| `_m1_fix_test_root.py` | **一次性**：测试文件改锚点查找工程根 | `PATTERN`、`REPLACEMENT`、`main()` | M2a 后删除 |
| `_m1_sync_tested.py` | **一次性**：对齐 `@tested` 与真实测试文件 | `MAPPING`、`main()` | M2a 后删除 |

### `check_footprint.py` 的 12 条规则

| 规则 | 检查内容 |
| --- | --- |
| F-01 | 未登记的新源文件（必须出现在 `footprint.json` 的 `files`） |
| F-02 | 模块 docstring 必须含 `@feature` 与 `@layer` |
| F-03 | `@layer` 必须与目录推断的分层一致（且与 JSON 记录一致） |
| F-04 | JSON 登记了但文件已不存在 |
| F-05 | JSON 声明的 `public` 符号必须真实存在于模块中 |
| F-06 | `features/<name>/` 必须有 `manifest.py`（含必备字段）+ `tests/features/<name>/` 测试 |
| F-07 | 每个功能必须声明页面，且 `ui/web/pages/<id>.js` 存在并导出 `render` |
| F-08 | `@tested` 指向的路径必须存在（`(一次性脚本` 可豁免） |
| F-09 | `core` 不得 import `ui` 或 `features` |
| F-11 | JSON 登记的功能 id 必须与 `features/` 目录一致（双向） |
| F-12 | `ui/web/pages/*.js` 必须在 `docs/UI_SPEC.md` 登记（双向） |

---

## 5. `core/_refbridge.py` —— 临时桥接层（**M2b 后整文件删除**）

| 项 | 内容 |
| --- | --- |
| 职责 | 按登记表加载参考实现（只用于**回归对照**；生产路径不依赖它） |
| 公开 API | `REFERENCES`（12 项）、`ReferenceUnavailable`、`load_reference()`、`reference_status()`、`pending_references()` |
| 为什么存在 | M2a/M2b 期间需要"新实现 vs 旧实现"的一致性证据（如引擎识别在 7 个真实游戏上 100% 一致、marshal 300 文件零漂移） |
| 安全设计 | `load_reference()` 拒绝未登记的名字 → 无法随手 import 绕过登记表 |
| 当前 `pending` | 12 项（`/api/health` 的 `reference.pending` 会显示） |
| 消除时机 | M2b 收敛完成后，`pending == 0`，删除本文件 |

---

## 6. 文件 → 谁调用它（反向索引）

| 被子系统 | 影响的功能 |
| --- | --- |
| `core/constants.py`、`core/paths.py`、`core/engines.py`、`core/registry.py`、`core/context.py` | **全部**（改这些 = 全局变更，必须跑全量测试） |
| `core/safety/atomic.py` | 全部写回路径（数据安全） |
| `core/jobs.py`、`ui/server.py`、`ui/web/dom.js` | 全部长任务与页面 |
| `core/formats/mv_mz_data.py`、`rgss_data.py`、`core/textutil.py` | 仅 `translate` |
| `core/formats/mv_save.py`、`rgss_save.py`、`core/marshal/` | 仅 `cheats`（`marshal` 也被 `translate` 的 RGSS 数据路径使用） |
| `core/safety/backup.py`、`fontutil.py` | 仅 `translate` |

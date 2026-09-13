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
| 改存档后没生效（界面说成功） | 先查写回层的"有没有值"判据：**`translated=0`/`False` 不能被当成"没有值"**（N-16） |
| 改了数据表却提示"值不一致" | `features/cheats/data_fields.py` 的 `verify_original`（陈旧性校验）；重读一次数据即可 |
| 译文写回后游戏崩了 | `core/formats/mv_mz_data.py` 或 `rgss_data.py` 的 `apply_to_files` |
| 写盘要更安全 | `core/safety/atomic.py`（唯一写盘手段） |
| 备份/还原行为不对 | `core/safety/backup.py` |
| 想加一个新功能 | `docs/FEATURES.md#契约` → `core/registry.py` / `core/context.py` |
| 长任务卡住 / 不能取消 | `core/jobs.py` |
| 翻译功能的接口要改 | `features/translate/routes.py`（接口清单在 `test_routes.py::EXPECTED`） |
| "生成汉化版"没写进译文 | 先查 `mv_mz_data._set_by_path` / `rgss_data._navigate` 的**路径约定**（N-15、N-07 都出在这里） |
| 选游戏/选字体的对话框弹不出来 | `core/sysdialog.py`（B-27） |
| 道具/武器/防具前面要显示游戏内图标 | `core/iconutil.py`（图集定位+解密+切片几何）→ `features/cheats/routes.py` 的 `icon_of`/`icon_meta`/`icon_sheet` → `ui/web/pages/cheats.js` 的 `iconCell` |
| 图标画出来了但位置不对 / 画的是别的道具 | 先查 `cell` 与 `columns`：MV/MZ **32px**、VX Ace **24px**，都是 16 列（`core/constants.py` 的 `ICON_CELLS`）；再查换游戏后 `_icon_cache` 有没有失效（N-29） |
| 图标全是空格子 / 开关是灰的 | `icon_info` 的 `reason` 就是答案：没图集 / 解不开 / 尺寸不认识，三种都如实说明 |
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

### core/sysdialog.py

| 项 | 内容 |
| --- | --- |
| 职责 | 原生系统对话框（选文件夹 / 选字体文件）：tkinter 优先，PowerShell 回退 |
| 公开 API | `pick_folder()`、`pick_font()`、`available()`、`DialogUnavailable`、`shell_candidates()`、`build_script()`、`FONT_FILTER` |
| 谁调用 | `features/translate/routes.py`（`pick_folder` / `pick_font` 两个端点） |
| 改动影响 | 只影响"选路径"的交互；不参与任何写盘路径 |
| 迁移来源 | 原翻译工具**内联在** `tool/server.py:65-87`，且写死了 PowerShell 绝对路径（**B-27**） |

**为什么放在 `core` 而不是 `ui`**：M3a 首次把它抽成 `ui/native_pick.py`，
足迹校验 **F-09** 立刻报错 —— `features/translate/routes.py` 反向 import 了
`ui`，违反"`features → core`、`ui → features`"的单向依赖。**弹系统对话框是
与业务和界面都无关的系统能力**（和剪贴板同级），因此正确位置是 `core`；
`ui/` 里只有 HTTP 门面。

**可测性设计**：`shell_candidates()` 与 `build_script()` 是纯函数（不弹窗、
不起进程），所以"B-27 的修复"本身可以被 CI 完整断言；真正弹窗的 `pick()`
只在有图形环境的机器上执行。降级契约（两者都不可用 → `DialogUnavailable`）
由 `tests/unit/test_sysdialog.py` 钉死。

### core/iconutil.py

| 项 | 内容 |
| --- | --- |
| 职责 | 游戏内图标图集（IconSet）的**定位 / 解密 / 切片几何**；不做任何图像解码或编码 |
| 公开 API | `find_sheet()`、`encryption_key()`、`decrypt_image()`、`png_size()`、`geometry()`、`load()`、`MV_HEADER`、`PNG_HEADER` |
| 谁调用 | `features/cheats/routes.py` 的 `CheatsService.icon_meta()` / `icon_sheet()` |
| 改动影响 | 只影响"道具列表前面的小图标"；不参与写盘、不参与存档读写 |
| 测试 | `tests/unit/test_iconutil.py`（40 例）、`tests/features/cheats/test_item_icons.py`（19 例）、`tests/integration/test_web_syntax.py::TestWebProbeIconFlow`（7 例，驱动真实界面） |
| 来源 | **两个参考工具都没有这个能力**（新功能，无迁移对应项） |

**为什么不需要任何图像处理**：数据表里本来就有 `iconIndex`（RGSS 是
`@icon_index`）—— 它就是"IconSet 图集里的第几格"。所以本模块只负责
**给出整张图 + 每格边长 + 每行几格**，由浏览器用 CSS `background-position`
裁出单格。零依赖、零编码，也不用把图集拆成一堆小文件。

**加密格式**（用真实样本实测确认，见 `docs/STATE.md` §5 N-29）：
MV 的 `.rpgmvp` 与 MZ 的 `.png_` 是同一套加壳 —— 偏移 0..15 恒为
`52 50 47 4D 56 …` 伪头，偏移 16..31 是真实 PNG 前 16 字节逐字节异或
`System.json` 里的 `encryptionKey`，偏移 32.. 原样。

**设计上的两个刻意选择**：

1. **按内容而不是按扩展名判断是否加密**。真实游戏里存在被汉化/破解工具
   改名或重新打包的资源，扩展名不可信（与 `mv_save.SaveFileMV` 的
   "内容优先于参数"同一原则）。
2. **解不开就如实报错，绝不返回半成品**。解不开时 `load()` 的
   `available=False` 且 `reason` 是给用户看的中文原因；界面据此把开关
   置灰并说明。实测 `D:\gamess\demon\DD_V07c_Windows` 的 `IconSet.png_`
   被第三方汉化注入器改过，本机 7 个真实游戏的 key 全试过都解不开 ——
   这种游戏必须优雅降级，而不是画出 320 个错位的图。

⚠ **切换游戏时必须清 `CheatsService._icon_cache`**（`open_game` 里显式清空）。
不清就会出现"新游戏的道具名配旧游戏的图集"，画出来是**另一件道具的图标**，
看着还挺正常 —— 与 N-12～N-28 是同一类缺陷，有专门断言守着
（`test_item_icons.TestIconCacheInvalidation`）。

### core/marshal/（⚠ 临时含两份实现）

| 文件 | 职责 | 公开 API | 谁调用 |
| --- | --- | --- | --- |
| `doc_model.py` | **二进制层**：Node 树（22 个类），`Node.raw` + `dirty` 增量字节保真，支持多流与 XP/VX 标准模式。**全工程唯一的解析器与序列化器** | `Node`、`Parser`、`loads`、`dumps`、`load_streams`、`mark_dirty`、`VERSION`、`ivar()`、`ivar_names()` | `core/formats/rgss_save.py`、`core/marshal/value_layer.py`、测试 |
| `value_layer.py` | **值层门面**：在 Node 之上提供"像 Python 对象一样读写"的代理。**改代理 = 改 Node**，因此字节保真天然成立，且不需要第二份解析器 | `RMObject`、`RMIvar`、`RMStr`、`RMSymbol`、`RMArray`、`RMDict`、`RMStruct`、`RMUserDefined`、`RMUserMarshal`、`RMRegexp`、`RMData`、`RMClass`、`RMModule`、`RMFloat`、`wrap`、`unwrap`、`unwrap_to_node`、`loads`、`load_streams`、`dumps`、`is_ruby_object`、`to_plain` | `core/formats/rgss_data.py`、`core/safety/builder.py` |
| `__init__.py` | 收敛状态标记 | `CONVERGENCE_STATUS`（**已为 `"merged"`**） | `tools/check_footprint.py`、`ui/routes.py` |

**改动影响**：全工程**只有一个 marshal 解析器**（`doc_model`），值层只是它的视图。
因此改 `doc_model` 会影响所有 marshal 路径（RGSS 游戏数据 + RGSS 存档 +
字体脚本注入），改后必须重跑 compat 层（300 个真实样本零漂移）。

**收敛纪律**（由 `tests/compat/test_marshal_compat.py::TestMarshalConvergence`
静态断言守护）：

* `value_layer` **不得**出现 `class Parser` / `_parse_fixnum` / 编码逻辑
  —— 那等于又造一份实现
* `value_model.py` 不得复活、也不得被任何模块 import
* `core/marshal/` 下只允许 `doc_model.py` + `value_layer.py` + `__init__.py`

### core/formats/

| 文件 | 职责 | 公开 API | 谁调用 |
| --- | --- | --- | --- |
| `jsoncodec.py` | **MV/MZ 共享编解码层**（M2b 收敛点）：文本/JSON 两种风格、BOM 容忍、JsonEx 元数据键唯一真源、加密包装的密钥派生与异或流、LZString/zlib 压缩与按内容判别 | `read_text()`、`read_json_file()`、`dumps_pretty()`、`dumps_compact()`、`write_text_file()`、`write_bytes_file()`、`META_KEYS`、`is_meta_key()`、`strip_meta_keys()`、`int_map_from()`、`WRAPPER_KEYS`、`is_wrapped()`、`split_wrapper()`、`join_wrapper()`、`derive_wrapper_key()`、`crypt_wrapper_bytes()`、`decrypt_wrapper_payload()`、`encrypt_wrapper_payload()`、`is_zlib_stream()`、`decompress_save()`、`compress_save()`、`save_engine()` | `mv_mz_data.py`、`mv_save.py`、M3a/M3b 接线 |
| `mv_mz_data.py` | MV/MZ **游戏数据**（`data/*.json`）提取与写回，含加密 JSON 包装 | `extract()`、`apply_to_files()`、`TEXT_CODES`、`WRAPPER_KEYS`、`_MULTI_VALUE_CODES`、`_choice_texts()`、`_load_data_file()`、`_save_data_file()` | `features/translate/session.py`、`core/safety/builder.py`、`core/formats/rgss_data.py`（复用 `TEXT_CODES`） |
| `rgss_data.py` | VX Ace/XP **游戏数据**（`Data/*.rvdata2|rxdata`）提取与写回 | `extract()`、`apply_to_files()` | `features/translate/session.py`、`core/safety/builder.py` |
| `mv_save.py` | MV/MZ **存档**（LZString / zlib 双格式按内容判别） | `GameDataMV`、`SaveFileMV`、`META_KEYS` | `features/cheats/manifest.py`（M3b 接线） |
| `rgss_save.py` | RGSS **存档**（hash / contents 双布局，多流同步） | `GameData`、`SaveFile`、`sync_dirty()`、`find_top_hash()` | 同上 |
| `lzstring.py` | MV 存档所用的 LZString 编解码 | `compress`、`decompress`、`compress_to_base64`、`decompress_from_base64` | `core/formats/jsoncodec.py` |
| `__init__.py` | 收敛状态标记 | `CONVERGENCE_STATUS`（**已为 `"merged"`**） | `tools/check_footprint.py` |

**改动影响**：这三个职责（数据提取 / 数据写回 / 存档读写）直接决定"功能是否等价"。
改 `TEXT_CODES` 会同时改变 MV/MZ 与 RGSS 两条提取路径（它们共用这张表 —— 这是**有意**的，
防止两处规则漂移）。

**⚠ 收敛后的纪律**：JSON 风格、BOM 处理、JsonEx 元数据键、加密包装、
压缩判别**都只能在 `jsoncodec.py` 里实现一次**。
`tests/unit/test_jsoncodec.py::TestConvergence` 会静态断言这一点：
在 `mv_mz_data.py` 里再出现 `base64.b64decode` / 密钥派生 / `zlib` 调用即红灯。

### core/safety/（M2a 拆为四个模块，依赖方向单向）

| 文件 | 职责 | 公开 API | 谁调用 |
| --- | --- | --- | --- |
| `atomic.py` | **唯一的写盘手段**：原子写 + 备份文件 + 目标护栏 | `atomic_write_bytes()`、`atomic_write_text()`、`sibling_backup()`、`assert_safe_target()`、`next_free_dir()`、`unique_temp_path()`、`AtomicWriteError`、`SafeTargetError` | 所有需要写文件的模块 |
| `backup.py` | 备份 / 还原 / 清单（**不 import `core.formats`** —— 这是切断 import 环的关键） | `backup_files()`、`restore_backup()`、`list_backups()`、`safety_backup()`、`write_manifest()`、`read_manifest()`、`record_created()`、`BACKUP_PREFIX`、`MANIFEST_NAME` | `builder.py`、M3a/M3b 接线 |
| `builder.py` | **生成汉化版的编排层**：暂存换名（B-01）、字体应用（B-03）、失败回滚（B-06）、覆盖确认（B-05） | `build()`、`apply_font()`、`copy_tree()`、`default_target_dir()`、`resolve_target_dir()`、`font_touched_paths()`、`patch_core_js()`、`inject_font_script()`、`install_user_font()`、`OverwriteNotConfirmed`、`BuildFailed`、`FONT_FALLBACK_NAMES` | `features/translate/routes.py`（M3a 接线） |
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
| `features/translate/manifest.py` | 翻译功能的自我描述与注册（**薄壳**：构造服务 + 委托路由 + 页面） | `MANIFEST`、`register()`、`health()` | `core/registry.py` |
| `features/translate/routes.py` | **翻译功能的后端接线**（M3a）：扫描 / 编辑 / 翻译 / 生成汉化版 / 备份还原，17 个端点 | `TranslateService`、`register_routes()`、`PROVIDERS`、`session_id_for()`、`session_path_for()`、`MAX_PAGE_SIZE`、`DEFAULT_PAGE_SIZE` | `features/translate/manifest.py` |
| `features/translate/translators.py` | 4 个翻译引擎适配器 + 批量翻译执行器（vendored） | `build_translator`、`translate_entries`、`TranslateError`、`TruncatedError`、`GoogleTranslator`、`OpenAICompatibleTranslator`、`DeepLTranslator`、`_http` | `features/translate/routes.py` |
| `features/translate/session.py` | 翻译会话与进度持久化（vendored） | `Session`、`ScanOptions`、`DEFAULT_OPTIONS` | `features/translate/routes.py` |
| `features/cheats/manifest.py` | 修改功能的自我描述与注册（**薄壳**） | `MANIFEST`、`register()`、`health()` | `core/registry.py` |
| `features/cheats/routes.py` | **修改功能的后端接线**（M3b）：读档 / 改档 / 写回 / 数据表编辑 / 备份还原，18 个端点 | `CheatsService`、`register_routes()`、`BackupPolicy`、`ACTOR_ATTRS`、`EDIT_KINDS`、`PAID_FOR` | `features/cheats/manifest.py` |
| `features/cheats/data_fields.py` | **可编辑字段的唯一规则表**（MV/MZ 与 RGSS 各一份）+ 扫描 / 陈旧性校验 / 写回编排 | `MV_FIELD_RULES`、`RGSS_FIELD_RULES`、`rules_for_file()`、`scan_data()`、`build_entries()`、`set_in_data()`、`verify_original()`、`expected_value()`、`KIND_OF` | `features/cheats/routes.py` |
| `features/cheats/__init__.py` | 包标记 | `manifest` | — |

**功能注册的路由**（M3a + M3b 现状）：

| 路由 | 功能 | 状态 |
| --- | --- | --- |
| `GET /api/translate/state` | translate | **可用**（会话状态 / 计数 / 类别分布 / 上次构建结果） |
| `POST /api/translate/open` | translate | **可用**（校验目录 + 建会话，复用断点续传） |
| `POST /api/translate/pick_folder`、`pick_font` | translate | **可用**（原生对话框；取消返回 `cancelled: true`） |
| `POST /api/translate/scan` | translate | **可用**（后台任务） |
| `GET /api/translate/entries` | translate | **可用**（分页 + 关键词 + 类别 + 状态过滤） |
| `POST /api/translate/entry` | translate | **可用**（改单条译文 / 状态，即时落盘） |
| `POST /api/translate/skip_all` | translate | **可用**（后台任务，可限定类别） |
| `POST /api/translate/start` | translate | **可用**（后台任务 + 进度/取消；空 Key 不覆盖已存 Key） |
| `GET /api/translate/providers` | translate | **可用**（列出 4 个适配器） |
| `POST /api/translate/test` | translate | **可用**（接口自检，出网一次；失败按返回值上报） |
| `GET`/`POST /api/translate/config` | translate | **可用**（读**掩码**返回 / 写盘） |
| `POST /api/translate/build` | translate | **可用**（后台任务；覆盖必须 `confirm=true`） |
| `GET /api/translate/backups` | translate | **可用**（列出备份及其清单） |
| `POST /api/translate/restore` | translate | **可用**（还原前自动再备份一次） |
| `POST /api/translate/open_dir` | translate | **可用**（在文件管理器中打开目录） |
| `GET /api/cheats/status` | cheats | **可用**（功能状态 + 已打开上下文 + 可编辑属性清单） |
| `POST /api/cheats/detect` | cheats | **可用**（无状态识别：引擎判据 + 数据/存档目录） |
| `POST /api/cheats/open` | cheats | **可用**（识别并加载名字表，记住上下文） |
| `POST /api/cheats/pick_folder` | cheats | **可用**（原生文件夹对话框） |
| `GET /api/cheats/saves` | cheats | **可用**（存档列表 + 备份列表 + 当前存档） |
| `POST /api/cheats/load` | cheats | **可用**（打开存档；路径必须在本游戏存档目录内） |
| `GET /api/cheats/party`、`actors`、`vars` | cheats | **可用**（读队伍/角色/开关变量，带可读名字） |
| `POST /api/cheats/party`、`actor`、`var` | cheats | **可用**（改**内存**，不落盘） |
| `POST /api/cheats/save` | cheats | **可用**（写回存档；必须先备份，覆盖必须 `confirm=true`） |
| `GET`/`POST /api/cheats/data` | cheats | **可用**（列可编辑字段 / 写回数据表，含陈旧性校验） |
| `GET /api/cheats/backups`、`POST /api/cheats/restore` | cheats | **可用**（备份列表 / 还原，还原前再备份） |
| `POST /api/cheats/open_dir` | cheats | **可用**（在文件管理器中打开目录） |

**接口契约由测试双向核对**：
`tests/features/translate/test_routes.py::TestRouteRegistration.EXPECTED` 与
`tests/features/cheats/test_routes.py::TestRouteRegistration.EXPECTED`
（少一个或多一个都红灯），页面侧由
`tests/integration/test_translate_page.py` / `test_cheats_page.py` 核对。

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

## 5. 收敛状态（需求 §3.3 的三类重复实现）

> 由 `/api/health` 的 `convergence` 段实时报告；这里说明各自的收敛方式与守护测试。

| 职责 | 真源 | 状态 | 守护测试 |
| --- | --- | --- | --- |
| 引擎识别 + 目录/存档发现 | `core/engines.py` | ✅ **merged**（从 M1 第一天起就只有一份，未经历"两份再合并"） | `tests/unit/test_engines.py`：`TestFrozenDetectionFixtures`（13 种判据组合，两套 MV/MZ 判据都覆盖）+ `TestFrozenRealGameBaseline`（7 个真实游戏，需 `TUDOU_RPGTOOL_SAMPLES`） |
| MV/MZ 编解码（JSON / 压缩 / 加密包装 / JsonEx 元数据） | `core/formats/jsoncodec.py` | ✅ **merged**（M2b 抽出，`CONVERGENCE_STATUS == "merged"`） | `tests/unit/test_jsoncodec.py::TestConvergence`（静态断言禁止第二份 `base64.b64decode` / 密钥派生 / `zlib` 调用） |
| Ruby Marshal | `core/marshal/doc_model.py`（二进制层）+ `core/marshal/value_layer.py`（值层门面） | ✅ **merged**（M2b；`CONVERGENCE_STATUS == "merged"`，旧 `value_model.py` 已删） | `tests/compat/test_marshal_compat.py`（300 真实样本零漂移 + `TestMarshalConvergence` 静态断言）+ `tests/compat/test_standard_mode.py`（合成 VX/XP）+ `tests/unit/test_marshal_value.py`（值层语义 36 例） |

**`core/_refbridge.py` 已删除**（M2b）：它曾是 M1/M2a 的临时脚手架，
用于在收敛期间加载旧实现做对照。删除前先把等价性证据**冻结为不依赖参考工具的夹具**
（上表前两行的守护测试），因此删除没有丢证据。
`/api/health` 的 `reference` 段随之被 `convergence` 段取代 ——
让"收敛是否完成"成为可观测事实，而不是只写在文档里。

**保留**：`core/paths.py` 的 `reference_root()` / `reference_tools()` /
`reference_available()` —— 它们与桥接层无关，是"参考目录在哪"的可配置项。

---

## 6. 文件 → 谁调用它（反向索引）

| 被子系统 | 影响的功能 |
| --- | --- |
| `core/constants.py`、`core/paths.py`、`core/engines.py`、`core/registry.py`、`core/context.py` | **全部**（改这些 = 全局变更，必须跑全量测试） |
| `core/safety/atomic.py` | 全部写回路径（数据安全） |
| `core/jobs.py`、`ui/server.py`、`ui/web/dom.js` | 全部长任务与页面 |
| `core/formats/jsoncodec.py` | MV/MZ 两条路径（游戏数据 + 存档） |
| `core/formats/mv_mz_data.py`、`rgss_data.py`、`core/textutil.py` | 仅 `translate` |
| `core/formats/mv_save.py`、`rgss_save.py`、`core/marshal/` | 主要 `cheats`（`marshal` 也被 `translate` 的 RGSS 数据路径使用） |
| `core/safety/backup.py` | `translate`（生成汉化版/还原）与 `cheats`（写回存档/数据表前的备份）**共用** |
| `core/safety/builder.py`、`fontutil.py` | 仅 `translate` |
| `core/sysdialog.py` | 两个功能的"选路径"端点（`pick_folder` / `pick_font`） |
| `features/translate/routes.py` | 仅 `translate` |
| `features/cheats/routes.py`、`data_fields.py` | 仅 `cheats` |

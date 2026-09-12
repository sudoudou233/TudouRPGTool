# 架构说明（ARCHITECTURE）

> 变更时机：架构变更时。本文解释**分层、数据流、依赖方向、关键设计取舍**。
> 文件级细节见 `docs/MODULES.md`；功能接入方式见 `docs/FEATURES.md`。

---

## 1. 分层总览

```text
                    ┌─────────────────────────────┐
                    │  app.py（唯一入口）          │
                    │  装配 + 自检 + 生命周期       │
                    └──────────────┬──────────────┘
                                   │
          ┌────────────────────────┼────────────────────────┐
          ▼                        ▼                        ▼
   ┌─────────────┐         ┌─────────────┐          ┌──────────────┐
   │  ui/        │         │ features/   │          │ core/        │
   │  界面层      │────────▶│ 可插拔功能   │─────────▶│ 纯逻辑层      │
   │  server     │  调用    │ translate   │  依赖     │ engines      │
   │  routes     │         │ cheats      │          │ marshal      │
   │  web/*      │         │ <future>    │          │ formats      │
   └─────────────┘         └─────────────┘          │ safety       │
          │                        │                 │ registry     │
          │                        │                 │ jobs/config  │
          └────────────────────────┴────────────────▶└──────────────┘
                        两条边都只能指向 core
```

**依赖方向单向**：`features` → `core`；`ui` → `core` + `features` 暴露的接口。
`core` **不得** import `ui` 或 `features` —— 由 `tools/check_footprint.py` 的
**F-09** 静态强制（AST 扫描，发现即报错）。

为什么这条方向重要：core 是"能在没有界面、没有浏览器的情况下被单元测试"的部分。
原两个工具把 HTTP 路由、GUI 回调、业务逻辑混在 `server.py:476-549` 与
`main.py:204-484` 里，导致**同一职责出现两份实现**（需求 §3.3 的三类重复正是这么来的）。

---

## 2. 启动与装配数据流

```text
python app.py
  │
  ├─ 1. paths.project_root()          定位工程根（可用环境变量覆盖）
  ├─ 2. AppConfig.load()              读 config.json（缺失/损坏回落默认值）
  ├─ 3. JobManager(4 workers)         有界并发任务池
  ├─ 4. registry.get_registry()       ── 自动发现 ──────────────────────────┐
  │      └─ 扫 features/*/manifest.py，import 后读 MANIFEST dict             │
  ├─ 5. AppContext(router, config, jobs)                                    │
  ├─ 6. ui_routes.register_core_routes(ctx)   登记 /api/health 等 10 条核心路由
  ├─ 7. registry.register_all(ctx)    ── 装配 ─────────────────────────────┤
  │      └─ 对每个功能调用其 register(ctx)：                                │
  │           ctx.get/post(...)   → 登记路由（自动归属 feature id）          │
  │           ctx.page({...})     → 声明前端页面                            │
  ├─ 8. app.check()                   自检：功能目录/健康检查/前端资源/核心路由
  └─ 9. JsonApiServer.start()         绑定 127.0.0.1，可选打开浏览器
```

### 请求数据流

```text
浏览器 fetch
  │
  ▼
ui/server.py :: Handler._dispatch()
  ├─ Host/Origin 白名单校验（防 DNS rebinding / 本地网页越权）
  ├─ 解析 query + JSON body → Request 对象（arg() 统一先 body 后 query）
  ├─ 特殊：/api/quit 直接响应并异步 shutdown
  ▼
ui/server.py :: JsonApiServer.handle(request)
  ├─ Router.resolve(method, path) → (route, path_params)
  ├─ 未命中且非 /api/*  → serve_static()（含 realpath 防穿越）
  ├─ 未命中 API 路由     → 404 {"ok":false,"code":"not_found"}
  └─ 命中 → route.handler(request)
         ├─ 返回 dict/list → 自动 JSON 序列化
         ├─ 抛异常         → 500 {"ok":false,"code":"handler_exception",...}
         └─ 返回 Response  → 原样使用（状态码/类型可控）
```

长任务（扫描、翻译、生成汉化版）走**任务队列**，不阻塞请求：

```text
POST /api/...      → jobs.submit(fn) → 立刻返回 {job: "job3"}
浏览器轮询          → GET /api/job?id=job3 → 快照 {status, progress, message, ...}
任务内部            → job.set_progress(done, total, msg) / job.token.is_cancelled()
   取消            → POST /api/cancel {id} → 仅取消该任务（不是全局事件）
```

---

## 3. 模块依赖图（关键节点）

```text
core/constants.py ◀──── core/engines.py ◀──── features/*（引擎识别）
       ▲
       │
core/paths.py ◀── core/config.py
              ◀── core/registry.py ◀── app.py
              ◀── core/safety/atomic.py

core/marshal/doc_model.py  ◀── core/formats/rgss_save.py   （RGSS 存档）
core/marshal/value_model.py ◀── core/formats/rgss_data.py  （RGSS 游戏数据）
                                core/safety/backup.py      （字体脚本注入）

core/formats/lzstring.py   ◀── core/formats/mv_save.py     （MV 存档）
core/textutil.py           ◀── core/formats/mv_mz_data.py  （控制码判定）
                           ◀── core/formats/rgss_data.py

core/context.py（Router/PageSpec/AppContext） ◀── core/registry.py
                                             ◀── ui/routes.py
                                             ◀── features/*/manifest.py

core/jobs.py ◀── app.py ◀── ui/routes.py（/api/job、/api/cancel）
```

---

## 4. 关键设计取舍

### 4.1 为什么用本地 Web UI 而不是 tkinter

见 `docs/DECISIONS.md` **ADR-001**。要点：翻译工具已有成熟的 Web 前端与设计令牌；
tkinter 侧价值全在逻辑层（1839 行），GUI 层本身是胶水（494 行）；
且 tkinter 实测**零样式能力**（原修改工具没有一行 `ttk.Style()`），
在"零第三方依赖"约束下无法满足需求 §4.4 的视觉要求。

### 4.2 为什么功能模块用 `manifest.py` 而不是 `module.json`

见 **ADR-002**。要点：零依赖 + Python 原生（可声明函数引用如健康检查）；
可被 `check_footprint.py` 直接 import 后断言。

### 4.3 为什么 `core/engines.py` 从第一天就只有一份实现

需求 §3.3 指出两侧各有一份引擎识别、**判据与返回结构都不同**。
如果 M1 先把两份都搬进来"以后再合并"，就会立即产生双实现与两条事实标准。
因此 M1 直接写**合并后的新文件**：两套 MV/MZ 判据都保留（任一命中即识别），
`System.json` 兜底保留，返回结构统一为同时含 `data_dir` 与 `save_dir`。
验证方式：与**两个**旧实现在 7 个真实游戏上比对判定结果（100% 一致）。

### 4.4 为什么 `core/marshal/` 暂时有两份实现

`doc_model`（文档模型，增量字节保真）与 `value_model`（值模型，编码感知）各有独有能力，
合并必须先修两个 P0 缺陷（B-10 的 `_fixnum` 重复定义、B-11 的 `to_py` 缺失）。
M1 的完成判据是"空壳可启动 + 足迹校验通过"，带病收敛会把缺陷固化，
因此按里程碑拆到 M2a（修）→ M2b（并）。**这是计划内的临时状态，不是设计。**

### 4.5 为什么写盘必须走 `core/safety/atomic.py`

原两个工具**所有**游戏文件写入都是非原子的（`open(path,"wb")` 直接截断），
写一半被中断就留下半写文件、游戏损坏（M0 台账 B-02/B-08）。
本工程把"临时文件 + fsync + `os.replace`"收敛为唯一写盘手段，
并在同一模块提供 `assert_safe_target()`（拒绝磁盘根/家目录/游戏目录内）
与 `sibling_backup()`（**失败即抛错**，不像原实现那样静默吞掉 `OSError`）。

### 4.6 为什么错误响应统一成 `{ok, error, code}`

原实现业务错误一律 HTTP 200 + `{"error": str}`，前端只能字符串匹配，
且无法区分"参数错"与"服务崩"。本工程统一结构 + 恰当状态码
（400 参数错 / 403 越权 / 404 未找到 / 500 处理器异常），
并保留 `code` 供程序判断（如 `job_missing`、`target_exists`）。

### 4.7 为什么 `JobManager` 要有界并发 + TTL + 每任务取消

原 `Jobs` 三个问题：每任务一线程无上限（可无限起线程）、任务永不回收
（id 用 `len+1`，字典无界增长）、只有全局 `cancel_event` 导致扫描与构建**不可取消**
（违反需求 §4.4"可中断"）。本实现逐条修正，并让 `/api/job` 返回**快照副本**
（原实现直接返回可变 dict）。

---

## 5. 扩展点：新增一个功能要动哪里

目标体验（需求 §5.1）：**新建一个 `features/` 目录并注册，界面自动出现该功能的入口。**

```text
features/<新功能>/
├─ __init__.py
├─ manifest.py          # 必须：MANIFEST dict + register(ctx)
├─ <实现文件>.py         # 业务逻辑（可复用 core 能力）
└─ (前端页面在 ui/web/pages/<page-id>.js)

tests/features/<新功能>/
└─ test_manifest.py     # 必须：功能自有测试（F-06 校验其存在）
```

**不需要修改**：`app.py`、`ui/server.py`、`ui/web/index.html`、`ui/web/app.js`。
导航由 `/api/nav` 驱动，页面由动态 `import()` 加载。

完整步骤与样板见 `docs/FEATURES.md#契约`。

---

## 6. 数据安全设计（硬约束 §4.2 的落点）

| 约束 | 落点 | 强制方式 |
| --- | --- | --- |
| 写回前必须备份 | `core/safety/atomic.atomic_write_bytes(backup=True)`、`core/safety/backup.backup_files()` | 代码评审 + 测试 |
| 备份可还原且 UI 可见 | `core/safety/backup.restore_backup/list_backups` + `/api/backups`、`/api/restore` | M3a 接入 UI |
| 未修改内容字节级保留 | marshal 的 `Node.raw`/`dirty` 增量保真 | `tests/compat/test_marshal_compat.py`（300 真实样本零漂移） |
| 破坏性操作二次确认 | `ui/web/dom.js` 的 `confirmDialog()` | M4 UI 审查清单 |
| 默认只写副本 | `build(mode="copy")` 为默认；inplace 为高级选项 | M3a 接线时落实 |
| 异常中断不留半写文件 | 原子写 | `tests/unit/test_atomic.py`（写入失败时原文件字节不变） |

---

## 7. 平台与兼容性约束

| 约束 | 现状 | 落点 |
| --- | --- | --- |
| 零第三方依赖 | ✅ 生产与测试全部 stdlib-only | `tests/integration/test_startup.py::TestCleanEnvironment` 用 AST 扫描全部源码 |
| Python 3.8+ | ⚠️ 静态检查通过，未在真实 3.8 上跑过 | 同上（扫描 `list[int]` / `X | Y` 语法） |
| Windows 优先但不绑死 | ⚠️ `core/safety/backup.py` 仍有顶层 `import winreg`（B-26） | M2a 改为惰性导入 + 非 Windows 分支 |
| 离线可用 | ✅ 除翻译功能外无网络访问 | 唯一出网点：`features/translate/translators.py:_http` |
| 不上传游戏文件 | ✅ 只发送剥离控制码后的纯文本片段 | M3a 补一条"请求体不含 file/path/游戏目录"的断言 |

---

## 8. 与需求文档的对应关系

| 需求章节 | 落点 |
| --- | --- |
| §4.1 技术与运行 | §7 上表；`tests/integration/test_startup.py` |
| §4.2 数据安全 | §6 上表；`core/safety/` |
| §4.3 工作区纪律 | 参考目录只读；工程根见 `AGENTS.md` §0 |
| §4.4 视觉与体验 | `docs/UI_SPEC.md` |
| §5 目标架构 | 本文 §1-§3 |
| §5.1 功能模块契约 | 本文 §5；`docs/FEATURES.md#契约` |
| §5.2 允许的架构选择 | `docs/DECISIONS.md` ADR-001 ~ ADR-007 |
| §6 工作足迹系统 | `docs/` 全套 + `tools/check_footprint.py`（12 条规则） |

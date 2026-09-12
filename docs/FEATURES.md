# 功能注册表（FEATURES）

> **功能 → 入口 → 依赖文件 → 测试 → 验证命令 → 扩展步骤。**
> 变更时机：每新增/修改功能。机器可读版本：`docs/footprint.json` 的 `features` 段。
> 由 `tools/check_footprint.py` 的 **F-06 / F-07 / F-11 / F-12** 校验本表与代码一致。

---

## 1. 已注册功能

### translate —— 文本翻译

| 项 | 内容 |
| --- | --- |
| 功能 id | `translate` |
| 用户可见名称 | 文本翻译 |
| 图标 | 文 |
| 版本 | 0.3.0 |
| 状态 | **后端已完成（M3a）**；前端页面待 M4 接入 |
| 界面入口 | 导航项「文本翻译」→ `ui/web/pages/translate.js`（仍是 M1 骨架） |
| 后端入口 | `features/translate/manifest.py` → `register(ctx)` → `routes.register_routes()` |
| manifest | `features/translate/manifest.py` |
| API 前缀 | `/api/translate` |
| 声明的页面 | `{id: translate, title: 文本翻译, module: translate, order: 10}` |
| 断言测试 | `tests/features/translate/test_manifest.py`、`test_routes.py`、`test_scan_regressions.py` |
| 验证命令 | `python tests/run_all.py --suite features` |

**已注册的 API 路由**（17 条；清单由
`test_routes.py::TestRouteRegistration.EXPECTED` **双向**核对）

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| GET | `/api/translate/state` | 会话状态 / 计数 / 类别分布 / 上次构建结果 |
| POST | `/api/translate/open` | 校验目录 + 建会话（复用断点续传；换目录自动新建） |
| POST | `/api/translate/pick_folder` | 原生文件夹选择（取消返回 `cancelled: true`） |
| POST | `/api/translate/pick_font` | 原生字体文件选择 |
| POST | `/api/translate/scan` | 扫描文本（**后台任务**，4 个内容开关） |
| GET | `/api/translate/entries` | 文本列表（分页 + 关键词 + 类别 + 状态） |
| POST | `/api/translate/entry` | 改单条译文 / 状态（即时落盘，可断点续传） |
| POST | `/api/translate/skip_all` | 批量标记跳过（**后台任务**，可限定类别） |
| POST | `/api/translate/start` | 批量翻译（**后台任务**；进度/取消/重试/只重出错项） |
| GET | `/api/translate/providers` | 列出 4 个翻译引擎适配器 |
| POST | `/api/translate/test` | 接口自检（出网一次；失败按返回值上报，不 500） |
| GET | `/api/translate/config` | 读全局设置（**API Key 已掩码**） |
| POST | `/api/translate/config` | 写全局设置 |
| POST | `/api/translate/build` | 生成汉化版（**后台任务**；覆盖必须 `confirm=true`） |
| GET | `/api/translate/backups` | 列出备份（含清单，UI 展示备份路径用） |
| POST | `/api/translate/restore` | 从备份还原（还原前自动再备份一次） |
| POST | `/api/translate/open_dir` | 在文件管理器中打开目录 |

**接口层的三条不变量**（都有断言，改动时必须保持）：

1. **长任务一定走 `ctx.jobs`** —— 扫描 / 批量跳过 / 批量翻译 / 生成汉化版
   都返回 `{ok, job}`，前端靠 `/api/job` 轮询进度并可取消
2. **空 `api_key` / 掩码 `api_key` 不覆盖已存 Key** —— 前端回显的是掩码值，
   照原样写回会把好 Key 清掉（要清空须显式 `clear_api_key: true`）
3. **覆盖必须显式确认** —— 前端必须先弹二次确认再把 `confirm=true` 传下来，
   否则 `builder.build` 抛 `OverwriteNotConfirmed`

**依赖的 core 能力**（manifest 的 `core_deps`）

`core.engines`、`core.textutil`、`core.formats.mv_mz_data`、`core.formats.rgss_data`、
`core.marshal.doc_model`、`core.safety.backup`、`core.safety.atomic`、
`core.safety.builder`、`core.safety.fontutil`

**实现文件**

| 文件 | 角色 |
| --- | --- |
| `features/translate/manifest.py` | 自描述与注册（**薄壳**：构造服务 + 声明页面） |
| `features/translate/routes.py` | **后端接线**：17 个端点 + `TranslateService`（M3a） |
| `features/translate/translators.py` | 4 个引擎适配器 + `translate_entries()` 批量执行（vendored） |
| `features/translate/session.py` | 会话与进度持久化（vendored） |
| `core/formats/mv_mz_data.py` | MV/MZ 游戏数据提取与写回 |
| `core/formats/rgss_data.py` | VX Ace/XP 游戏数据提取与写回 |
| `core/safety/builder.py` | 生成汉化版编排（暂存换名 / 回滚 / 字体 / 覆盖确认） |
| `core/safety/backup.py` | 备份 / 还原 / 清单 |
| `core/safety/fontutil.py` | 字体族名解析 |
| `core/sysdialog.py` | 原生文件夹 / 字体对话框 |
| `core/textutil.py` | 控制码保护 |
| `ui/web/pages/translate.js` | 前端页面（M4 接入） |

**功能覆盖范围**（不得缩水，逐条对照 `docs/迁移对照表.md` §A）

* 引擎：MV / MZ / VX Ace / XP 的提取 + 翻译 + 写回；2000/2003 仅识别
* 数据：System / Actors / Classes / Skills / Items / Weapons / Armors /
  Enemies / States / Troops / Animations / Tilesets / CommonEvents /
  MapInfos / MapNNN（含事件指令文本）
* 加密 JSON 包装（`{"uid","bid","data"}`）解密与再加密
* 4 个翻译引擎、接口自检、批量翻译（进度 + ETA + 可中断 + 重试）
* 生成汉化版（复制到新目录 / 覆盖原游戏）、备份与还原、`汉化备份_*`
* 字体应用（MV/MZ 改写 core.js；VX Ace/XP 装用户字体库 + 注入脚本）
* 控制码保护（`\V[n]` `\N[n]` `\C[n]` `\I[n]` 与换行原样保留）
* 隐私边界：出网只发剥离控制码后的纯文本

---

### cheats —— 存档修改

| 项 | 内容 |
| --- | --- |
| 功能 id | `cheats` |
| 用户可见名称 | 存档修改 |
| 图标 | 改 |
| 版本 | 0.1.0 |
| 状态 | **M1 骨架 + 引擎识别链路已可用**（读档/改值/存档在 M3b 接线） |
| 界面入口 | 导航项「存档修改」→ `ui/web/pages/cheats.js` |
| 后端入口 | `features/cheats/manifest.py` → `register(ctx)` |
| API 前缀 | `/api/cheats` |
| 声明的页面 | `{id: cheats, title: 存档修改, module: cheats, order: 20}` |
| 断言测试 | `tests/features/cheats/test_manifest.py` |
| 验证命令 | `python tests/run_all.py --suite features` |

**已注册的 API 路由**

| 方法 | 路径 | 状态 | 作用 |
| --- | --- | --- | --- |
| GET | `/api/cheats/status` | 骨架占位 | 返回功能状态 |
| POST | `/api/cheats/detect` | **可用** | 识别引擎、列出存档、探测多套存档目录 |

**依赖的 core 能力**

`core.engines`、`core.constants`、`core.formats.mv_save`、`core.formats.rgss_save`、
`core.formats.lzstring`、`core.marshal.doc_model`、`core.safety.atomic`

**实现文件**

| 文件 | 角色 |
| --- | --- |
| `features/cheats/manifest.py` | 自描述与注册 |
| `core/engines.py` | 引擎识别 + 存档发现（与 translate 共用） |
| `core/formats/mv_save.py` | MV/MZ 存档读写（LZString / zlib） |
| `core/formats/rgss_save.py` | RGSS 存档读写（hash / contents 双布局、多流同步） |
| `core/marshal/doc_model.py` | Ruby Marshal 字节级保真 |
| `core/safety/atomic.py` | 原子写回 + 自动备份 |
| `ui/web/pages/cheats.js` | 前端页面 |

**功能覆盖范围**

* 引擎：MV / MZ / VX Ace / VX / XP（2000/2003 仅识别）
* 存档格式：`file*.rpgsave`（LZString）、`file*.rmmzsave`（zlib）、
  `Save*.rvdata2`、`Save*.rvdata`、`Save*.rxdata`
* 可改：金币、步数、道具/武器/防具数量（含添加背包中原本不存在的物品）、
  角色等级/经验/HP/MP/TP/8 项属性加成/技能列表、开关、变量
* 队伍成员（`party_ids`）：**原工具仅只读展示，无写回路径** —— 本工程保持等价，
  如需新增请走「新增能力」流程
* 安全：保存前自动备份、只改指定数值、其余字节级原样保留、原子写

---

## 2. 功能模块契约（新增功能必须遵守）

### 2.1 目录结构

```text
features/<name>/
├─ __init__.py              # 包标记（必须，否则无法 import）
├─ manifest.py              # 必须：MANIFEST dict + register(ctx)
└─ <实现文件>.py             # 业务逻辑

tests/features/<name>/
└─ test_manifest.py         # 必须：功能自有测试（F-06 会校验存在）

ui/web/pages/<page-id>.js   # 前端页面（必须 export render）
```

### 2.2 `MANIFEST` 字段

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `id` | ✅ | 功能唯一标识（也是 `features/<name>/` 目录名） |
| `name` | ✅ | 中文显示名 |
| `icon` | ✅ | 一个字符的图标 |
| `version` | ✅ | 语义化版本 |
| `description` | ✅ | 一句话说明 |
| `order` | — | 导航排序（默认 100） |
| `core_deps` | — | 依赖的 core 模块列表（健康检查会逐个 import 验证） |
| `api_prefix` | — | API 命名空间前缀（**登记的路由必须落在该前缀下**） |
| `pages` | — | 页面声明列表 `{id, title, module, icon, order}` |
| `health` | — | 健康检查函数（返回 dict 或布尔） |
| `enabled` | — | 是否启用（默认 True） |

### 2.3 `register(ctx)` 契约

**只能**通过 `ctx` 暴露的三个接口操作，**不得**直接修改 app 或 server 内部：

```python
def register(ctx):
    @ctx.get("/api/<prefix>/xxx", name="<前缀>_xxx")   # 或 ctx.post
    def handler(request):
        return {"ok": True, ...}          # dict 会被自动 JSON 序列化

    ctx.post("/api/<prefix>/yyy", name="<前缀>_yyy")(handler2)

    ctx.page({"id": "<page-id>", "title": "标题", "module": "<page-id>"})
    return "registered"
```

* 路由会**自动归属**到登记它的功能 id（`test_registry.py` 会断言功能没越界登记路由）。
* 处理器签名统一为 `handler(request)`；`request.data` 是 JSON body，`request.params` 是 query，
  用 `request.arg("x")` 可一次查两处。
* 长任务用 `ctx.jobs.submit(fn)`；`fn(job)` 内用 `job.set_progress()` 与
  `job.token.is_cancelled()`。

### 2.4 前端页面契约

```javascript
import { el, getJSON, postJSON, toast } from '/dom.js';

export async function render(host, ctx) {
  host.append(el('section', { class: 'card' }, [ /* 只用 components.css 的类 */ ]));
}
```

* `host` 是已清空的容器元素；`ctx` 含 `{nav, features}`。
* **只能用 `components.css` 的类与 `tokens.css` 的令牌**，不得写具体颜色值。
* 长任务用 `waitJob()` 轮询并提供取消按钮。

---

## 3. 新增一个功能的完整步骤

以「修改队伍人数上限」为例（需求 §2.3-4 的扩展性实证场景）：

1. **建目录与包标记**
   ```powershell
   mkdir features\party
   ```
   新建 `features/party/__init__.py`（内容：`from . import manifest`）

2. **写 manifest**（`features/party/manifest.py`）
   ```python
   MANIFEST = {
       "id": "party",
       "name": "队伍设置",
       "icon": "队",
       "version": "0.1.0",
       "description": "调整队伍人数上限与成员。",
       "order": 30,
       "core_deps": ("core.formats.mv_save", "core.formats.rgss_save",
                     "core.safety.atomic"),
       "api_prefix": "/api/party",
       "pages": ({"id": "party", "title": "队伍设置", "module": "party",
                  "icon": "队", "order": 30},),
   }

   def register(ctx):
       @ctx.get("/api/party/status", name="party_status")
       def status(request=None):
           return {"ok": True, "status": "ready"}
       ctx.page(MANIFEST["pages"][0])
       return "registered"

   def health():
       return {"status": "ok", "detail": "就绪"}

   MANIFEST["health"] = health
   ```

3. **写前端页面**（`ui/web/pages/party.js`）：必须 `export function render(host, ctx)`，
   只使用共享组件类。

4. **写功能自有测试**（`tests/features/party/test_manifest.py`）：至少断言
   已注册、必备字段齐全、页面文件存在、健康检查通过。

5. **更新足迹**
   * `docs/UI_SPEC.md` §4 页面清单加一行（**否则 F-12 报错**）
   * 本文件 §1 加一节
   * `docs/STATE.md` §3 功能表加一行

6. **刷新并校验**
   ```powershell
   python tools/gen_footprint.py
   python tools/check_footprint.py     # 必须退出码 0
   python tests/run_all.py             # 必须全部通过
   ```

7. **启动确认**：`python app.py` → 导航自动出现「队伍设置」，点击后页面正常渲染。
   **不需要修改** `app.py` / `ui/server.py` / `index.html` / `app.js`。

> 如果以上步骤里出现"必须改核心代码才能让新功能生效"，说明扩展点设计失败，
> 按 `P1` 处理：把缺口写进 `docs/reviews/OPEN-QUESTIONS.md` 并修扩展点。

---

## 4. 修改一个已有功能的步骤

1. 读 `docs/MODULES.md` 找到该功能的实现文件与影响面。
2. 读 `docs/STATE.md` §5 确认要改的文件**没有未修的 P0/P1 缺陷**（尤其是
   `core/safety/backup.py`、`core/marshal/`、`core/formats/*`）。
3. 改代码 → 改/加测试 → 跑 `tests/run_all.py` → 跑 `tools/check_footprint.py`。
4. 更新本文件的「功能覆盖范围」与该功能的 `docs/迁移对照表.md` 条目。
5. 追加 `docs/DEVLOG.md` 一条。

---

## 5. 功能等价性核对表（M5 验收用）

> 对着 `docs/迁移对照表.md` 逐条核对。**不许"应该还在"。**

| 来源 | 条目数 | 已验证 | 待迁移 |
| --- | --- | --- | --- |
| 翻译工具（附录 A） | 55 | 局部（M0 已在原工具实跑） | 大部分 |
| 修改工具（附录 B） | 37 | 局部（M0 已在原工具实跑） | 大部分 |
| 测试资产迁移（附录 B.3） | 7 | — | 全部 |

M5 时本表所有行必须为"✅"，或对未完成项有明确的人类裁决记录。

---

## 6. 未做与不做（需求 §9）

| 项 | 处置 |
| --- | --- |
| RPG Maker 2000/2003 修改 | **不做**，仅识别（`supported=False`） |
| 2000/2003 文本翻译（LDB 格式） | **不做**，仅提示不支持 |
| 作弊与汉化之外的引擎逆向 | **不做** |
| 接入付费或私有服务 | **不做**；翻译只支持用户自备密钥的公开接口 |
| 队伍成员写回 | **原工具就没有** —— 保持等价；如需新增走「新增功能」流程 |

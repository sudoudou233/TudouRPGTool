# 决策记录（ADR）

> 每条决策包含：编号、日期、背景、决策、备选方案、后果。
> 变更时机：每次重要决策。**不要重复推翻已记录的决策**；要改就新增一条并说明为何推翻。

---

## ADR-001 ｜ UI 外壳选型：本地 Web UI

* **日期**：2026-09-12（M0 决策，M1 落地）
* **状态**：已采纳
* **对应需求**：§5.2、§4.4、§12-1

### 背景

两个原工具形态不同：翻译工具是本地 HTTP 服务 + 浏览器界面（`tool/server.py` 571 行 +
`web/index.html` 678 行，含成套暗色设计令牌）；修改工具是 tkinter 桌面 GUI
（`main.py` 494 行，GUI 与业务逻辑混在一个类里）。

### 决策

**以本地 Web UI 为主壳**：Python 标准库 `http.server` 提供 API 与静态资源，
前端是单页应用（无构建、无 CDN、无 npm）。tkinter 版修改器的**逻辑层迁移**、
**界面层重写**为 Web 页面。

### 备选方案与代价

| 方案 | 代价 |
| --- | --- |
| 纯 tkinter 重写 | 需把扫描/翻译/生成汉化版/字体/备份还原全部重做成 tk 控件；零第三方依赖下**没有可用的现代 UI 库**；实测原修改工具**没有一行 `ttk.Style()`**，纯系统默认外观，无法满足"美观、风格统一" |
| 换 Flask/FastAPI | 违反硬约束 §4.1 零第三方依赖，**直接否决** |
| 混合（Web 主 + tk 弹框） | **已采用**：沿用原工具做法，用 tkinter 弹原生文件/字体选择器（`tool/server.py:65-87`），不构成额外决策 |

### 后果

* 正面：复用翻译工具已验证的前端资产与 21 条 API 范式；长任务的进度/取消有成熟范式；
  样式可用 CSS 令牌集中管理。
* 负面：依赖浏览器；原生对话框仍需 tkinter 兜底（Windows 优先可接受）。
* 落点：`ui/server.py`、`ui/web/*`、`docs/UI_SPEC.md`。

---

## ADR-002 ｜ 功能注册表用 `manifest.py` 而非 `module.json`

* **日期**：2026-09-12
* **状态**：已采纳
* **对应需求**：§5.1、§12-4

### 背景

需求 §5.1 允许 `module.json` 或 `manifest.py` 二选一，并要求"新增功能 = 插一块"。

### 决策

用 **`manifest.py`**（Python 数据结构）+ **显式 import 的自动发现**
（`core/registry.py` 扫 `features/*/`）。

### 理由

1. 零依赖 + Python 原生：可直接声明函数引用（`MANIFEST["health"] = health`），
   JSON 只能写字符串再二次解析。
2. 可测试性：`tools/check_footprint.py` 能直接 import 后断言（如"声明的页面文件必须存在"）。
3. 无 import 副作用风险：manifest 只放数据 + `register(ctx)` 签名。

### 明确取舍：不做隐式魔法

不用 `pkgutil.iter_modules` 的 `ispkg` 过滤（它会**静默跳过**缺 `__init__.py` 的功能目录，
而那正是最该报错的情形）。改为 `os.listdir` 逐个判定并给出可读错误：
缺 `manifest.py`、缺 `__init__.py`、缺 `MANIFEST` 字段、功能 id 重复都会报错。
启动时显式打印"已加载的功能模块：translate、cheats"。

前端"入口自动出现"：后端 `/api/nav` 返回导航，前端据此渲染；
前端侧只有**一处**登记（页面文件 + manifest 的 `pages` 声明），
符合需求 §5.1"做不到自动发现时至少只在固定一两处登记"。

### 后果

落点：`core/registry.py`、`core/context.py`、`features/*/manifest.py`、
`docs/FEATURES.md#契约`。

---

## ADR-003 ｜ `core/engines.py` 从第一天就只有一份实现

* **日期**：2026-09-12
* **状态**：已采纳
* **对应需求**：§3.3 重复实现表第一行

### 背景

两侧各有一份引擎识别，**判据与返回结构都不同**：

| 来源 | 入口 | MV/MZ 判据 | 兜底 | 存档发现 |
| --- | --- | --- | --- | --- |
| `tool/engines.py:33` | `detect()` | `*_managers.js` | 读 System.json | 无 |
| `engines.py:37` | `detect_engine()` | `*_core.js` | 无 | `SAVE_PATTERNS` + save_dir |

### 决策

**不搬两份再合并**，M1 直接写合并后的新文件：两套判据全部保留（任一命中即识别）、
`System.json` 兜底保留、返回结构统一为同时含 `data_dir` 与 `save_dir`。

### 理由

如果 M1 先把两份都搬进来"以后再合并"，会立即产生双实现与两条事实标准，
且 M1 的足迹/测试会同时绑到两套结构上，M2 的收敛成本反而更高。
引擎识别是**小文件**（原两份共 219 行），一次写好成本很低。

### 验证

与**两个**旧实现在 7 个真实游戏（MZ / MV×2 / VX Ace×2 / XP 型 / 未识别）上比对判定结果
→ **100% 一致**；存档发现与旧修改工具在 6 个真实游戏上数量一致（3/0/24/2/1/9）。
测试：`tests/unit/test_engines.py::TestReferenceParity`。

### 后果

* 顺带修掉一个原缺陷：**翻译工具识别不出 VX（`.rvdata`）**（M0 台账 B-16），
  新实现支持 VX 并区分 `standard=True` / `layout='contents'`。
* `core/_refbridge.py` 保留对旧实现的引用，**仅用于回归对照**。

---

## ADR-004 ｜ Ruby Marshal 合并方向：文档模型为主体，值模型降为门面

* **日期**：2026-09-12（决策）→ M2b 执行
* **状态**：**已决策，未执行**
* **对应需求**：§3.3 重复实现表第二行、"验收硬指标"

### 背景

两份实现互有长短（详见 `docs/M0-现状测绘.md` §3.2）：

* `doc_model`（原 `rmarshal.py`，699 行）：`Node.raw` + `dirty` **增量字节保真**、
  多流 `load_streams`、`standard` 模式（XP/VX）、`0x45 'E'`、浮点尾启发式、可写 bignum
* `value_model`（原 `tool/marshal.py`，693 行）：值层便利 API（可直接构造并 dump）、
  编码感知（`RMStr.enc` + utf-8→cp932→latin-1 降级）、`0x65 'e'` / `0x43 'C'` /
  `0x4D 'M'` / `0x64 'd'` 四个 type code、`RMDict.default_value`

### 决策

以 **`doc_model` 为二进制层主体**，`value_model` **降为对象门面**
（提供 `loads_py` / `dumps_py` 之类的值层入口）。

### 理由

`doc_model` 的独有能力都位于"**不可用值模型等价重建**"的位置：字节保真是机制保证；
而 `value_model` 的字节保真只靠"读写同序遍历"的自述约定，遇到未知 token（`:418`）
或浮点尾就失效。二进制层必须选机制更硬的那一份。

### 必须从值模型移植的片段

1. `0x65 'e'`、`0x43 'C'`、`0x4D 'M'`、`0x64 'd'` 四个 type code 的**读写对称**实现
   —— 否则这些文件在 `doc_model` 下直接抛错。
2. 字节级编码视图：把 `RMStr.enc` 与三级降级解码作为**旁挂字段**加到
   `doc_model` 的 String/Symbol 节点上，**序列化仍走原字节**。
   （同时修正 `gbk/gb2312 → cp932` 的误映射，M0 台账 B-28。）
3. 对象门面 API：`loads_py` / `dumps_py`，并在其中用 `Parser.objects` + `Link.index`
   解析 `@` 链接 —— 这是保住 `core/formats/rgss_data.py` 与
   `core/safety/backup.py` 那几处调用方的关键。
4. **不得**把 bignum 降为裸 int（否则重演值模型 `:454` 的 `Fixnum too large` 崩溃）。

### 必须先修（否则把缺陷固化）

* **B-10**：`Parser._fixnum` 重复定义（`:491-496` 被 `:508-510` 覆盖）→
  `standard=True` 时按变体解析、按标准写回，XP/VX 字节漂移。
* **B-11**：`to_py()` 有 10 个类未实现，而 `Array`/`Hash` 会递归调用 → 真实数据调用即抛。

### 验收硬指标（需求 §3.3）

合并后 Ruby Marshal **只有一份实现**，且两侧原有断言全部通过：
`tests/compat/test_marshal_compat.py::TestMarshalRoundtripRealSamples`
（M1 实测：**300 个真实 `.rvdata2` 零漂移**）+ 合成样本用例。

---

## ADR-005 ｜ 真实样本测试三层分离，零游戏内容入库

* **日期**：2026-09-12
* **状态**：已采纳
* **对应需求**：§12-5

### 背景

原两个工具的测试**硬编码本机游戏路径**（`D:\gamess\...`），换机即无法运行；
且 `test_pipeline.py` 还会真调用 Google 翻译。真实样本有版权与体积问题。

### 决策

分三层：

| 层 | 内容 | 位置 | 入库 |
| --- | --- | --- | --- |
| L1 合成层 | 用代码当场构造最小样本（marshal 字节流、合成 MV/MZ 工程、合成存档） | `tests/unit/`、`tests/compat/` | ✅ |
| L2 真实层 | 环境变量 `TUDOU_RPGTOOL_SAMPLES` 指向的真实游戏，**只读** | `tests/compat/`（无变量则 skip） | 仅代码 |
| L3 兼容层 | 两个原工具 roundtrip 断言的合并版本，双跑同一批文件 | `tests/compat/` | 仅代码 |

### 规避版权与体积的具体做法

1. **零游戏内容入库**：仓库不出现任何游戏文本、`.rvdata2`、游戏 `.json`。
   L1 的样本由代码生成，内容为测试用假文本。
2. 样本清单只记**元数据**（路径 + 大小 + sha256），不记内容。
3. API Key 走环境变量或 `config.json`（已 gitignore）；日志输出前掩码
   （`core/config.redacted()`）。
4. `.gitignore` 覆盖 `config.json` / `runtime/` / `sessions/` / `*.bak` /
   `*汉化备份_*/` / `tests/local/samples/`。
5. **测试不得污染游戏目录**：所有写回测试必须在 `tempfile.mkdtemp()` 的副本上做
   （原 `test_all_saves.py:25` 直接写在游戏目录里，**不迁移这种做法**）。

### 后果

* 正面：任何机器上 `python tests/run_all.py` 都能跑通（无样本时相关用例 skip 而非失败）。
* 负面：要拿到"完整证据"必须设环境变量；`docs/STATE.md` 里已显式说明。

---

## ADR-006 ｜ `footprint.json` 由源码生成，人类文档与代码的一致性由反向检查兜底

* **日期**：2026-09-12
* **状态**：已采纳
* **对应需求**：§6.1 `footprint.json`、§6.2 可校验

### 背景

需求要求 `footprint.json` 与 `docs/FEATURES.md` 同步。若两者都靠手写，
一定会漂移；若让脚本去解析 markdown，又很脆弱。

### 决策

* `footprint.json` **完全由** `tools/gen_footprint.py` 从源码 docstring 的
  `@feature/@layer/@public/@depends/@tested` + `features/*/manifest.py` **生成**，
  因此**永远与源码一致**。
* 人类可读的 `docs/MODULES.md`（文件 → 职责 → API → **谁调用 → 影响面**）与
  `docs/FEATURES.md`（功能注册表）**只写一次**，负责自动推导不出来的信息。
* 两者的一致性由 `tools/check_footprint.py` 的**反向检查**兜底：
  F-08（`@tested` 路径存在）、F-11（功能双向登记）、F-12（页面清单双向一致）、
  F-05（声明的 public 符号真实存在）。

### 后果

* `python tools/gen_footprint.py --check` 可在 CI/评审时判定 JSON 是否过期。
* 新增源文件后忘记登记 → F-01 报错（非零退出），不会静默腐烂。

---

## ADR-007 ｜ `core/safety/atomic.py` 是全工程唯一写盘手段

* **日期**：2026-09-12
* **状态**：已采纳
* **对应需求**：§4.2 数据安全（最高优先级）

### 背景

原两个工具**所有**游戏文件写入都是非原子的：

| 位置 | 行为 |
| --- | --- |
| `tool/vxace.py:280-283` | `open(full,"wb")` 直接截断重写 |
| `tool/mv_mz.py:73-77` | 同上 |
| `tool/build.py:112-113` | `_patch_core_js` 直接截断重写 |
| `rpgmaker_cheating_tool/main.py:480` | 存档写回直接覆盖 |
| 原全仓唯一原子写 | `tool/session.py:117-120`（`.tmp` + `os.replace`） |

写一半被中断 → 半写文件 → 游戏损坏。

### 决策

提供 `core/safety/atomic.py` 作为**唯一**写盘手段：
临时文件（同目录）+ `fsync` + `os.replace`；并在同模块提供
`assert_safe_target()`（拒绝磁盘根/家目录/游戏目录内）与
`sibling_backup()`（**失败即抛错**，不像原实现那样静默吞掉 `OSError`）。

功能模块与页面**禁止**直接 `open(path, "wb")` 写游戏文件。

### 已实测的行为保证

`tests/unit/test_atomic.py`：

* 写入失败（含编码失败）时**原文件字节不变**，且不残留临时文件
* 并发写不同文件全部成功且内容完整；连续覆盖写每次都是完整内容
* 临时文件必在同目录（跨卷会让 `os.replace` 失去原子性）

### 已知平台限制（已实测并登记）

**同一进程内多线程并发替换同一路径**在 Windows 上会因 `os.replace` 与其它线程持有的
句柄竞争而抛 `PermissionError`（WinError 5）。因此本工程约定：
**同一文件的写入由 `core/jobs.JobManager` 的有界工作池串行化**（每个任务只写自己的目标文件）。

---

## ADR-008 ｜ `JobManager` 终态一次性发布（修正实测竞态）

* **日期**：2026-09-12（M1 实测发现，同日修复）
* **状态**：已采纳

### 背景

M1 写测试时发现：若先写 `self.status = "error"` 再写 `self.traceback`，
轮询方（`/api/job`、`JobManager.wait`）只要在这两行之间读到 status，
就会拿到"已失败但没有 traceback"的**半成品状态**。测试因此间歇性失败，
前端也会显示不完整信息。

### 决策

新增 `Job.finalize(status, message, error, traceback_text)`，
在**同一把锁**内一次性写完所有终态字段，**最后才发布 `status`**（作为可见性栅栏）。
且快照 `snapshot()` 增加 `traceback_tail`（末尾 8 行），
避免把整条栈刷进界面，同时让用户能看到失败原因。

### 后果

`tests/unit/test_jobs.py` 增加对应断言；`/api/job` 的 `traceback_tail` 供前端展示。

---

## ADR-009 ｜ 后端错误响应统一为 `{ok, error, code}` + 恰当 HTTP 状态码

* **日期**：2026-09-12
* **状态**：已采纳

### 背景

原实现业务错误一律 **HTTP 200 + `{"error": str}`**（`tool/server.py:443-449`，
全项目只有一处结构化错误码 `target_exists`）。前端只能字符串匹配，
且无法区分"参数错"与"服务崩"。

### 决策

统一为 `{"ok": false, "error": "<中文可读>", "code": "<机器可读>"}` +
恰当状态码：400 参数错 / 403 越权（Host-Origin）/ 404 未找到 / 500 处理器异常。
成功响应保持"直接返回业务 dict"（不套 `{ok:true, data:...}` 外壳），
以降低前端改动量。

### 后果

`ui/web/dom.js` 的 `api()` 会解析该结构并抛出带 `.code` / `.status` 的 `Error`，
页面可以用 `err.code` 做分支（如 `job_missing`）。

---

---

## ADR-010 ｜ 死代码与未使用 API 一律不迁移，并显式登记

* **日期**：2026-09-12
* **状态**：已采纳
* **对应需求**：§2.4"任何一方不得删除或改写既有功能"

### 背景

实测发现原工具有若干零引用代码。需求禁止"删除既有功能"，
但这些并非功能，而是废弃遗留。

### 决策

**不迁移**，并在足迹中显式登记（保证"不是悄悄消失"）：

| 位置 | 内容 | 证据 |
| --- | --- | --- |
| `tool/textutil.py:43` | `translate_segments()` | 全仓零调用 |
| `tool/server.py:385` | `/api/listdir` | 前端从未调用（已被原生选择器取代） |
| `index.html:76-79` | `.dir-item` 整套 CSS | 配套上面那条，零引用 |
| `index.html:11` | `--warn` 令牌 | 只声明未引用 → **本版补上用途**（`.tag.warn` / `.chip.warn`） |
| `index.html:63` | `.progress.success` | 零引用 |
| `index.html:66` | `.ok-text` | 零引用 → **本版补上用途** |
| `rpgdata.py:180` / `mvdata.py:100` | `PARAMS` 常量（两份逐字相同） | 两处均零引用 → 收敛为 `core/constants.PARAMS` **唯一一份** |

### 后果

`docs/M0-现状测绘.md` §3.5 与 `docs/迁移对照表.md` §D 记录全部处置；
`docs/UI_SPEC.md` §2 列出"已删除的旧样式（禁止复活）"。

---

## ADR-011 ｜ 安全层拆成四个模块，`core/safety/__init__.py` 用 PEP 562 懒加载

* **日期**：2026-09-12（M2a）
* **状态**：已采纳

### 背景

`core/safety/backup.py` 原先是 vendored 的 `translation_tool/tool/build.py`（399 行），
里面挤了五件事：备份/还原/清单、生成汉化版编排、字体注入、目标目录命名、平台相关
（`winreg`）。M2a 要修 B-01（暂存换名）、B-03（字体兜底可还原）、B-04（还原完整性）、
B-06（失败回滚）、B-07（备份失败不静默）、B-26（顶层 `winreg`）—— 在一个 399 行的
混合文件里改动风险过高。

### 决策

拆成四个模块，**依赖方向单向**：

```
atomic   （原子写 + 备份文件 + 目标护栏）          无内部依赖
   ▲
backup   （备份 / 还原 / 清单）                   只依赖 atomic，**不 import core.formats**
   ▲
builder  （生成汉化版 + 字体应用编排）             依赖 backup/atomic/fontutil + core.formats
fontutil （字体族名解析）                          无内部依赖
```

拆分时立刻撞上**循环 import**：

```
core.formats.__init__ → mv_mz_data → core.safety.atomic
                                     → core.safety.__init__ → builder
                                     → core.formats.mv_mz_data   ✗
```

### 解法

`core/safety/__init__.py` 改用 **PEP 562 `__getattr__` 懒加载**：

```python
_SUBMODULES = ("atomic", "fontutil", "backup", "builder")

def __getattr__(name):
    if name in _SUBMODULES:
        module = importlib.import_module("." + name, __name__)
        globals()[name] = module
        return module
    raise AttributeError(...)
```

于是 `from core.safety.atomic import X` 只触发 `atomic` 子模块，环被切断；
`core.safety.builder` 这类访问才按需 import。

`tools/check_footprint.py` 的 **F-05** 相应放宽：模块定义了 `__getattr__` 且名字出现在
`__all__` / `_SUBMODULES` 里时，视为"真实可用"（否则会把合规的懒加载误报为幽灵符号）。

### 备选方案与代价

| 方案 | 代价 |
| --- | --- |
| 把 formats 的 import 挪到函数内部 | 每次写回都重新 import；且"用得到才 import"的隐式依赖更难审查 |
| 让 `backup.py` 继续持有 formats 依赖 | 职责继续混杂，B-01/B-06 的改动面仍然铺开 |
| 拆分但不懒加载，靠人工保证 import 顺序 | 脆弱：任何一次 `from core.formats import X` 都会重新引入环 |

### 后果

* 每个模块可以单独测试（`test_atomic.py` / `test_build_backup.py` / `test_m2a_regressions.py`）。
* `backup.py` 不再依赖任何 formats 模块，因此可以被存档修改功能复用。
* 新增一条纪律：**`core/safety/backup.py` 不得 import `core.formats`**
  （改坏了会立刻表现为 import 环，测试跑不起来）。

---

## ADR-012 ｜ 生成汉化版用"暂存目录 + 原子换名"，覆盖需显式确认

* **日期**：2026-09-12（M2a）
* **状态**：已采纳
* **对应缺陷**：B-01、B-05、B-06

### 背景

原实现（`build.py:363-367`）：

```python
if os.path.exists(dst) and os.listdir(dst):
    if not overwrite:
        raise ValueError("目标目录已存在: %s" % dst)
    shutil.rmtree(dst)          # ← 旧输出在这里就没了
_copy_tree(game_dir, dst, progress_cb)
```

拷贝中途失败（磁盘满 / 权限 / 用户中断）→ **用户上一次生成的汉化版永久丢失**。
另外前端"覆盖原游戏"没有任何确认对话框（B-05），`build()` 全程无 try/except（B-06）。

### 决策

1. **copy 模式改为三段式**：
   * 拷贝到同父目录下的暂存目录 `<dst>.__staging_<时间戳>`
   * 成功后：旧目录 `os.replace(dst, <dst>.__old_<时间戳>)` → `os.replace(staging, dst)` → 删旧
   * 任一步失败：只 `rmtree(staging)`，**旧输出原封不动**
   * 换名本身失败时，把旧目录放回原位（保证用户至少还有原来的输出）
2. **覆盖需显式确认**：新增 `confirm_overwrite=True` 参数。
   `overwrite=True` 而未确认 → 抛 `OverwriteNotConfirmed`；
   **inplace 模式同样要求该参数**（覆盖的是用户原游戏）。
3. **inplace 失败自动回滚**：写回阶段任何异常都会用刚做的备份
   `restore_backup(safety=False)` 自动还原，并把回滚结果挂在
   `BuildFailed.rollback` 上一起抛出。

### 为什么"暂存 + 换名"而不是"先备份旧输出再删"

旧输出可能很大（整个游戏目录），再备份一份等于磁盘占用翻倍。
同目录内的 `os.replace` 是原子操作，且不需要额外空间复制旧树
（只做目录项重命名）。旧目录的删除放在最后，失败也只是留下一个 `.__old_*` 目录。

### 后果

* 回归：`tests/compat/test_m2a_regressions.py::TestB01CopyFailureKeepsOldOutput`
  （monkeypatch `copy_tree` 抛 `OSError`，断言旧输出字节完好）；
  以及 `test_overwrite_without_confirmation_is_rejected` /
  `test_inplace_without_confirmation_is_rejected`。
* `copy_tree` 默认**跳过备份目录**（`汉化备份_*`），避免把用户的备份复制进输出。
* M3a 接 UI 时必须把 `confirm_overwrite` 接到二次确认对话框上
  （`docs/UI_SPEC.md` 交互范式第 3 条）。

---

## ADR-013 ｜ 合成 VX/XP 样本作为 `standard=True` 活路径的长期覆盖

* **日期**：2026-09-12（M2a）
* **状态**：已采纳
* **对应需求**：§9 风险与边界

### 背景

本机游戏库覆盖 MV / MZ / VX Ace，**没有 VX（`.rvdata`）与纯 XP（`.rxdata`）游戏**。
而 `standard=True`（XP/VX 的标准 Ruby Marshal 整数编码）恰恰是 P0 缺陷 B-10 的活路径。
M0 已把这个缺口登记为"已知未验证边界"，M2a 必须给出结论。

### 决策

**用代码合成最小样本**，而不是"登记为边界"：

* `tests/compat/test_standard_mode.py` 用 `doc_model` 构造最小 `.rvdata` / `.rxdata`
  （`contents` 布局：`[header, [system, switches, variables, self_switches, actors,
  party, troop, map, player]]`）
* 覆盖：整数编解码两套模式的全部边界值、多流、`contents` 布局、
  `GameData`/`SaveFile` 的完整读写改回读、改后再存的字节稳定性
* 反向断言 VX Ace 仍走变体编码，不被牵连

### 效果（这是本决策最有力的证据）

合成样本**一加上就抓出两个此前完全没被发现的真实缺陷**：

* **N-09**：`rgss_save.read_actors`/`set_actor_attr`/`set_actor_skills` 写死
  `[v for k,v in actors_node.ivars][0]`，假设容器是对象；stock XP/VX 存档里它是
  数组 → `AttributeError`，**整条 RGSS 存档读写不可用**
* **N-10**：标准编码单字节上限写成 122，而 `0x7B` 是长格式标记 →
  **118..122 五个值往返后被解成垃圾并让后续流错位**

结论：**"没有样本"等价于"没有证据"**。合成本的成本很低（约 300 行），
收益是两个 P0 级缺陷。真机样本仍然更有价值（能覆盖非标准变体），
两者是互补而非替代：真机样本走 `TUDOU_RPGTOOL_SAMPLES`（不入库），
合成样本入库存档（任何机器可跑）。

### 遗留

真机 VX / XP 样本仍是空白。`docs/ROADMAP.md` §3 保留该条目，
建议在有条件时补一台真机样本（尤其是**汉化/破解变体**，合成样本覆盖不到）。

---

## ADR-014 ｜ `Response` 从 `ui/server.py` 搬到 `core/context.py`

* **日期**：2026-09-13（M5 之后，加功能阶段）
* **状态**：已采纳
* **相关**：需求 §5.1（单向依赖）、`tools/check_footprint.py` **F-09**、
  `docs/MODULES.md#coreiconutil`

### 背景

"道具前面显示游戏内图标"这个功能需要 `GET /api/cheats/icon_set` 返回
**二进制**（一张 PNG，必要时解密后的）。而 `Response` 这个包装类当时定义在
`ui/server.py` —— 也就是说 `features/cheats/routes.py` 要返回二进制，
就必须 `import ui.server`。

**这与 `core/sysdialog.py` 那次是同一个坑**（见 `docs/MODULES.md#coresysdialog`）：
M3a 曾把系统对话框放在 `ui/native_pick.py`，`features/translate` 反向 import
`ui`，被 F-09 当场拦下。当时的结论是"弹对话框是与业务和界面都无关的系统能力，
正确位置是 `core`"。这次同样的问题换了张脸回来。

### 决策

把 `Response` 移进 `core/context.py` —— 和 `Router` / `PageSpec` / `AppContext`
放在一起，因为它**不是 HTTP 的东西，而是"处理器返回值"的契约**。
`ui/server.py` 以同名再导出（`__all__` 里声明），历史
`from ui.server import Response` 不受影响；真正把 `Response` 写上网的**仍然
只有 `ui/server.py`**。

### 备选方案与否决理由

| 方案 | 否决理由 |
| --- | --- |
| 在 `features` 里 `from ui.server import Response`（局部 import） | 依赖方向反了；F-09 只强制 `core` 不 import `ui`，但 `features → ui` 同样违背分层意图，且给后人留下"这样也行"的榜样 |
| 让处理器返回 `{"__raw_bytes__": ...}` 之类的约定 | 把传输层细节塞进业务返回值，比搬一个类难懂得多 |
| 新开一个 `core/http.py` | 为一个类开一个模块；`context.py` 已经是"handler 写什么、返回什么"的家 |

### 影响

* `ui/server.py` 少一个类定义，多两行再导出；`normalize()` / `error_response()`
  / `serve_static()` 全部照旧。
* 全仓 16 处 `from ui.server import ...` 只用到 `Request` / `free_port` /
  `server` 模块本身，无一处受影响（`test_server.py` 全覆盖）。
* 二进制响应的能力现在对**任何** feature 可用，不再需要绕过分层。


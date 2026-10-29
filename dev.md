# 开发者手册（poe-workflow）

> **版本**: 0.1.0 | **更新日期**: 2026-10-30
> 本文基于仓库真实源码（`workflow_model.py` / `workflow_engine.py` / `protocols.py` / `ui/*`）撰写，非仅 README 概述。涉及 UI 簇的说明以 `poe_workflow/ui/` 实际文件为准。

---

## 1. 项目概述

`poe-workflow` 是从 poe-mapmaker 抽出的**独立工作流编排引擎**，按「路线 B：独立并行引擎，不修改 `state_machine.py`」落地。当前状态：

- **Phase 1（纯 Python 内核）**：`workflow_model.py`（数据/校验/JSON 互转） + `workflow_engine.py`（执行内核），无 PyQt5 依赖。
- **Phase 2a（UI 簇迁入）**：`ui/` 子包（弹窗 / 列表视图 / 画布视图 / 模块库 / 编辑器 / 主题 / 文案）整体迁入；`workflows/` 与 `tests/` 一并迁入。poe-mapmaker 现为薄壳，仅 `ui/main_window.open_workflow_dialog()` 通过 `from poe_workflow.ui.dialog_workflow import WorkflowDialog` 拉起弹窗。

### 1.1 技术栈

| 层级 | 技术 | 说明 |
|------|------|------|
| 内核 | 纯 Python（标准库：`dataclasses`/`json`/`re`/`threading`/`time`） | 零业务依赖，可单测 |
| 宿主契约 | `typing.Protocol`（`@runtime_checkable`） | 鸭子类型，宿主无需继承 |
| UI | PyQt5 + 自绘 QGraphicsView 画布 | `ui/` 子包，仅 UI 层依赖 PyQt5 |
| 主题 | QSS 字符串 + 画布配色字典 | 浅色 `light` / 深色 `dark` |
| 测试 | pytest + offscreen Qt | 引擎层用注入式伪对象；UI 层用宿主临时配置副本 |

### 1.2 能力清单

- 14 个原子原语（§3）
- 控制结构：循环（`count` / `until` 条件 / 网格）、分支、子工作流（嵌套、一等公民，§5）
- 8 个条件源 + 组合条件 `all`(AND)/`any`(OR)（§4）
- 4 种错误策略：`retry`(默认) / `abort` / `skip` / `jump`（§6）
- 可中断：`abort()` 贯穿所有层级（含循环体、等待）；`start()`/`abort()` 基于 `threading`，`run_sync()` 供 pytest 免 Qt 验证（§7）

---

## 2. 系统架构

### 2.1 引擎 ↔ 宿主边界（构造注入）

引擎**不反向 import 任何宿主模块**，所有外部能力在构造时通过参数注入（`WorkflowEngine.__init__`）：

```python
from poe_workflow import WorkflowEngine, workflow_from_dict

engine = WorkflowEngine(
    coord=host_coord,        # CoordService：锚点/仓库页/通货坐标解析
    inp=host_input,          # InputService：鼠标/键盘/剪贴板模拟
    parser=host_parser,      # AffixService（可选）：稀有度/词缀评估
    cm=host_cfg,             # ConfigService（可选）：配置读取
    scheme_loader=host_loader, # SchemeLoader（可选）：模块方案 name->WorkflowDef
)
engine.load_def(workflow_from_dict(data))
reason = engine.run_sync()   # "done" / "aborted" / "error"
```

契约见 `poe_workflow/protocols.py`，宿主只需结构化实现对应方法（鸭子类型），**无需继承**这些 Protocol。

```
┌──────────────────┐        构造注入        ┌─────────────────────────┐
│  宿主（poe-mapmaker）│ ───────────────────▶ │   WorkflowEngine         │
│  Coord/Input/Cfg/ │                        │  workflow_engine.py      │
│  Affix/SchemeLoader│ ◀──── 鸭子类型调用 ──── │  仅通过 Protocol 调用宿主 │
└──────────────────┘                        └─────────────────────────┘
```

### 2.2 数据模型分层

- `workflow_model.py`：`ActionStep`（单步 dataclass）+ `WorkflowDef`（顶层容器）。纯数据、纯校验，无副作用，便于单测。
- `workflow_engine.py`：消费 `WorkflowDef`，递归执行；运行期上下文存于 `self._ctx`（dict）。
- UI 层（`ui/tab_workflow.py` / `ui/workflow_canvas_model.py`）持有**同一份步骤 dict 列表**作为单一事实源，列表视图与画布视图双向联动。

### 2.3 UI 簇架构（Phase 2a）

```
WorkflowDialog(QDialog)                         # dialog_workflow.py
├── ModulePalette                              # 左：原语 + 子工作流面板（itemActivated 信号）
├── QStackedWidget
│   ├── WorkflowTab                            # 中-0：步骤卡片列表 + 参数编辑器
│   └── WorkflowCanvasTab                      # 中-1：WorkflowCanvasView 画布
└── 右侧抽屉（RightDrawer）
    └── WorkflowEditorPanel                    # 选中步骤的参数编辑抽屉
```

`WorkflowDialog` 复用与 `MainWindow` 同名的 `set_right_drawer_widget` / `set_right_drawer_visible` 两个 API，`WorkflowTab.showEvent` 通过 `hasattr(self.window(), ...)` 守卫调用，因此 `WorkflowTab` / `WorkflowEditorPanel` **零改动**即可在弹窗内工作（见 `dialog_workflow.py:14-18`, `tab_workflow.py:1742-1748`）。

---

## 3. 原语（14 个）

集合定义在 `workflow_model.PRIMITIVES`。运行期分派表见 `workflow_engine._dispatch`（`:477`）。每个原语对应一个 `_p_<name>` 方法。

> 说明：`click_anchor` / `wait_ms` 标注为「兼容旧文件」保留；新编排优先用 `move_to_anchor` + 每步 `delay_ms`（见 `workflow_model.py:28` 注释）。`read_clipboard` 的 `rule` 字段复用 `RULE_PRESETS`（§4.2）。

| 原语 | `params` 关键字段 | 行为（`_p_*` 实现） |
|------|-------------------|---------------------|
| `click_anchor` | `anchor`（必填） | 取锚点绝对坐标 → 校验未校准(0,0)阻断 → `inp.click(x,y)` |
| `move_to_anchor` | `anchor`（必填） | 取坐标 → 校验 → `inp.move_mouse(x,y)`（**不点击**） |
| `move_offset` | `anchor`, `dx=0`, `dy=0` | 锚点坐标 + (dx,dy) 像素偏移 → `inp.move_mouse` |
| `press_key` | `key` | `key` 含 `mouse_` 走 `inp.press_mouse`，否则 `inp.press_key`（支持 `ctrl+c` / `mouse_right` / `ctrl+mouse_left` 等 token） |
| `read_clipboard` | `mode="read"`\|`"match"`, `store_as="clipboard"`, `rule?` | `read`：整段存 `ctx[store_as]`；`match`：按 `rule` 抽取（bool→true/false，number→数字，text→文本）存命名变量；始终缓存原文到 `ctx["clipboard"]` |
| `copy` | `store_as="clipboard"`, `expect_prefix?` | `inp.press_key("ctrl+c")` → 等 50ms → 读剪贴板 → 写入 `ctx[store_as]`；`expect_prefix` 非空且内容不以该前缀开头则抛错交 `on_error` |
| `wait_ms` | `ms`（必填） | `self._abort.wait(ms/1000)`（可被 abort 提前唤醒） |
| `recall_cell` | 无 | 把光标移回网格循环当前格 `ctx["__grid_cell"]`；非网格上下文报错交 `on_error` |
| `log` | `message` | `logger.info("[工作流] %s", message)`（主窗口日志栏） |
| `abort` | `reason?` | 置 `_abort` 事件并抛异常，运行返回 `aborted`（不走 `on_error`） |
| `use_currency` | `currency`（必填）, `target?`, `x?`, `y?` | 把 `currency` 用上目标格：目标优先 `target` 锚点名 > `x,y` > 当前网格格 `__grid_cell` > 光标位置（`get_mouse_pos`）；含切页容错循环（读 `StashMapping.currency_stash`）+ 取用前/后验证 |
| `record_session` | 无 | `inp.record_action()`（会话限速器登记一次动作） |
| `pause` | `note?` | 软暂停，阻塞至 `resume()` 或 `abort()` 唤醒（会话超限/人工介入场景） |
| `store_to_stash` | `stash_key`（必填，StashMapping 键名）, `target?`, `x?`, `y?`, `verify=True` | 按 `StashMapping.<stash_key>` 取页签索引 → 点页签 → 移回目标格 → `ctrl+shift+mouse_left` 存入；`verify` 时调用 `inp.clipboard_stash_verify`（可选能力，缺失则跳过） |

### 3.1 坐标铁律（B-001）

`_guard_uncalibrated`（`workflow_engine.py:88`）：锚点未校准时 `get_absolute_position` 返回 `(0,0)` 哨兵，引擎**阻断**点击/移动并 `abort()`，绝不静默误点屏幕左上角。

### 3.2 剪贴板空读熔断（G6）

`_register_clipboard_read`（`workflow_engine.py:207`）：连续读空达阈值（`Runtime.clipboard_empty_limit`，默认 5，最小 1）抛 `RuntimeError` 熔断，交 `on_error` 处理。阈值经 `self._cm.get("Runtime","clipboard_empty_limit","5")` 读取。

---

## 4. 条件源（8 个）与操作符

条件源集合 `CONDITION_SOURCES = {clipboard, ctx, ctx_diff, counter, rarity, affix, session, config}`（`workflow_model.py:36`）。求值逻辑在 `workflow_engine._eval_condition`（`:500`）。

| 源 `source` | 取数方式 | 典型 `value` 比较 | 备注 |
|-------------|----------|-------------------|------|
| `clipboard` | 复用 `ctx["clipboard"]`（无则实时读一次）；可带 `rule` 抽取 | 文本/抽取值 vs `value` | 与 `read_clipboard` 共用 `RULE_PRESETS` |
| `ctx` | `self._ctx.get(key)` | 任意 | 运行期写入的命名变量（如 `before`/`after`/`__loop_index`/`__grid_col`） |
| `ctx_diff` | 比较 `ctx[key_a]` 与 `ctx[key_b]` | 两上下文变量对比 | 需 `key_a` 与 `key_b` |
| `counter` | 循环索引 `loop_index`（整型） | 整型比较 | ⚠️ **分支不支持**：`branch` 内 `counter` 恒为 0，校验层直接拒收（见 §4.3） |
| `rarity` | 从 `ctx["clipboard"]` 调 `parser.detect_rarity` → `normal/magic/rare/unique/unknown` | 稀有度字符串 | 无 `parser` 时返 `"unknown"` |
| `affix` | `parser.evaluate_map(...)` 的字段 | `key` 如 `final_decision`/`params_pass`/`whitelist_pass`/`blacklist_hit` | 黑白名单取自 `cm.get_affix_entries` |
| `session` | `inp.check_session_limit()` → `(ok, reason)` | `key=ok` 比 `False` 等 | 可选能力，缺失时返回 `(True,"")` |
| `config` | `cm.get(section, key, "")` 的字符串值 | 字符串比较 | 读 `[section] key`，如 `Strategy.enable_corruption`；无 `cm` 时返回 `False` |

### 4.1 操作符 `op`

`CONDITION_OPS = {contains, equals, nequals, gt, lt, ge, le}`（`workflow_model.py:38`）。比较在 `_cmp`（`:599`）：`gt/lt/ge/le` 走整型；`contains` 走子串；`equals/nequals` 默认字符串、整型可选（`coerce_int`，`counter` 源启用）。

### 4.2 组合条件

`all`（全部满足 AND）/ `any`（任一满足 OR），可递归嵌套，与单源条件互斥。校验见 `workflow_model._validate_condition`（`:518`）。

### 4.3 校验护栏（重要）

- `branch` 条件 `source=counter` 会被 `validate_workflow` 直接拒收（分支内循环索引恒 0，条件静默失效），提示改用 `source=ctx` + `__grid_col`/`__loop_index`。
- `source=ctx` 需 `key`；`ctx_diff` 需 `key_a`+`key_b`；`config` 需 `section`+`key`；`clipboard` 带 `rule` 时 `rule` 必须可解析（`resolve_rule` 非空）。

### 4.4 `rule` 解析（共享规则注册表）

`RULE_PRESETS`（`workflow_model.py:60`）内置：`unidentified`/`corrupted`/`item_quantity`/`map_tier`/`influence_originator`/`fortress_alhezhim`/`influence_breach`。`resolve_rule(rule)` 接受预设键或自定义 `{pattern, kind, capture_group?}`（kind ∈ `bool`/`number`/`text`）。`FEATURE_LIBRARY` / `THRESHOLD_PRESETS` 为 UI 条件编辑器的数据来源。

---

## 5. 控制结构

### 5.1 循环 `loop`

字段（`ActionStep`）：`count` / `condition` / `grid` **三选一**（校验：`_validate_step` 要求恰好其一）。

- **`count`**：固定次数，`i` 从 0 计数，`i>=count` 退出（引擎 `_run_loop:781`）。
- **`condition`（until）**：**前置判定**——每次进入循环体前先判定，**为真则退出**（「反复执行直到条件为真」）；若一开始即真，体一次不跑。`__loop_index` 写入 `ctx`。
- **`grid`（网格循环）**：`{anchor, dx, dy, cols, rows, cell_dx, cell_dy}`（`_run_grid_loop:829`）。每格绝对坐标 = 原点锚点 + (dx,dy) + 行列步进；每格写入 `ctx["__grid_cell"]`/`__grid_row`/`__grid_col`/`__loop_index`，光标先移到该格再跑 `body`。

**安全护栏**：`loop_timeout_ms`（默认 600000=10 分钟，0/None 禁用）wall-clock 超时；`_max_loop_iterations = GRID_MAX_CELLS = 10000` 迭代上限；网格 `cols×rows` 超上限在校验层（`validate_workflow`）与引擎层（`_run_grid_loop`）双处拒收/中止，防止「看似跑完实则中途截断」（G8）。

### 5.2 分支 `branch`

`condition` + `then_steps` + `else_steps`。`_run_branch:891`：判定 `condition`（默认 True 走 then），执行对应子列表。两区**连续编号**（then 从 1 起，else 接 then 数量之后），`assign_step_ids` 保证不跨区撞名（`workflow_model._assign_ids_recursive`）——撞名会导致方案无法导出/运行、画布节点无法选中。

### 5.3 子工作流 `subworkflow`

`kind="subworkflow"` + `jump_target`（模块方案名，不含 `.json`）。`_run_subworkflow:755`：**正常路径**内联执行（非错误恢复），经 `scheme_loader` 调入 `workflows/<name>.json` 步骤，受 `_max_depth` 嵌套护栏约束，可嵌套。与 `on_error=jump` 的区别：后者是「出错后的恢复动作」（§6）。

---

## 6. 错误策略

每步 `on_error`（`ActionStep.on_error`，默认 `"retry"`）∈ `ERROR_POLICIES = {retry, abort, skip, jump}`（`workflow_model.py:41`）。执行与决策在 `_run_action:655`：

- **`retry`（默认）**：尝试 `1 + retry_count` 次（`retry_count` 默认 1，`retry_delay_ms` 默认 500ms），重试间隔 `self._abort.wait(...)` 可被中断；用尽仍失败 → 置 `_abort`、返回 `"error"`。
- **`abort`**：失败即置 `_abort` 返回 `"error"`。
- **`skip`**：失败则跳过该步，返回 `"ok"`（继续后续）。
- **`jump`**：失败时用 `_do_jump`（`:702`）把 `jump_target` 作为恢复动作运行一次——先按步骤 `id` 在本树查找，否则按**模块方案名**（`workflows/<name>.json`）经 `scheme_loader` 调入执行；跳转本身失败才上报 `on_error` 并中止。`jump_target` 为步骤 id 或模块名（§5.3 同字段）。

> ⚠️ 主动 `abort()` 原语**不走** `on_error`：它已置 `_abort` 事件，运行直接返回 `aborted`（`_p_abort:267`）。

---

## 7. 可中断线程模型

`WorkflowEngine` 以 `threading.Event`（`self._abort`）作为中止开关：

- **`run_sync()`**（`:910`）：`prepare()` → `_execute()` → `on_finished(reason)`。供 pytest 免 Qt 验证，返回 `"done"`/`"aborted"`/`"error"`。
- **`start()`**（`:917`）：置 `prepare()`，起 **daemon `Thread`** 跑 `_run_thread`；运行期异常兜底经 `on_error` 透出后再 `on_finished("error")`。
- **`abort()`**：`self._abort.set()`。所有 `wait_ms` / 切页等待 / 重试间隔均用 `self._abort.wait(...)`，可被提前唤醒——故 `abort` 贯穿循环体、等待、网格遍历各层级。
- **`resume()`**：解除 `_p_pause` 软暂停阻塞（UI 继续按钮 / 测试调用）。
- **`is_running()`** / `context` 属性：状态查询与运行期 `ctx` 只读访问。

护栏常量：`_max_loop_iterations=10000`、`_max_depth=16`（默认，可配）、`_loop_timeout_ms=600000`（可配，0/None 禁用）。

### 7.1 回调钩子（UI 接入点）

`self.on_status(sid, st)` / `self.on_finished(reason)` / `self.on_error(msg)` / `self.on_pause(note)`。UI 层（`ui/tab_workflow.py` `_EngineBridge`）挂接这些回调驱动状态栏与运行控制按钮。

---

## 8. 宿主契约（protocols.py）

引擎以鸭子类型调用以下接口，**宿主只需结构化实现，无需继承**。所有 Protocol 均 `@runtime_checkable`。

### 8.1 `CoordService`

| 方法 | 签名 | 职责 |
|------|------|------|
| `get_absolute_position` | `(name: str) -> Tuple[int,int]` | 锚点名 → 屏幕绝对坐标；未校准返回 `(0,0)` 哨兵 |
| `stash_tab_position` | `(tab_index: int) -> Tuple[int,int]` | 仓库页签索引 → 页签点击坐标 |
| `stash_currency_position` | `(currency_name: str) -> Tuple[int,int]` | 通货名 → 通货在仓库中的坐标 |

### 8.2 `InputService`

| 方法 | 签名 | 职责 |
|------|------|------|
| `click` | `(x, y, button="left")` | 鼠标点击 |
| `move_mouse` | `(x, y)` | 移动光标 |
| `press_mouse` | `(key: str)` | 鼠标键/滚轮 token（`mouse_left`/`ctrl+mouse_right`…） |
| `press_key` | `(key: str)` | 键盘键或组合（`ctrl+c`） |
| `read_clipboard` | `() -> Optional[str]` | 读剪贴板 |
| `clear_clipboard` | `() -> None` | 清空剪贴板 |
| `record_action` | `() -> None` | 会话限速器登记一次动作 |
| `normal_delay` | `() -> None` | 通货应用后常规物理延迟 |
| `get_mouse_pos` | `() -> Tuple[int,int]` | **可选**：当前光标位置（悬停评估取目标格） |
| `check_session_limit` | `() -> Tuple[bool,str]` | **可选**：会话限速状态 `(ok, reason)` |
| `clipboard_stash_verify` | `() -> bool` | **可选**：存仓后校验光标处已清空 |

> 引擎以 `getattr(self._inp, "xxx", None)` 容错调用可选能力，缺失时静默跳过（保持引擎可测）。

### 8.3 `ConfigService`

| 方法 | 签名 | 职责 |
|------|------|------|
| `get` | `(section, key, default="") -> str` | 读 `[section] key` 的字符串值（configparser 风格） |
| `get_affix_entries` | `(section: str) -> List[str]` | 返回某词缀区块（如 `AffixBlackList`）全部条目 |

### 8.4 `AffixService`

| 方法 | 签名 | 职责 |
|------|------|------|
| `detect_rarity` | `(text: str) -> str` | 解析稀有度（`normal/magic/rare/unique/unknown`） |
| `evaluate_map` | `(text, blacklist, whitelist) -> Dict[str,Any]` | 评估地图词缀，返回含 `final_decision`/`params_pass`/`whitelist_pass`/`blacklist_hit` 等字段的字典 |

### 8.5 `SchemeLoader`

| 方法 | 签名 | 职责 |
|------|------|------|
| `__call__` | `(name: str) -> WorkflowDef` | 模块方案名 → `WorkflowDef`（`on_error=jump` 与子工作流调用 `workflows/<name>.json`） |

---

> TODO（待确认）：`ui/tab_workflow.py` 的 `WorkflowTab._on_run`（约 2443 行处 `def _scheme_loader(name):`）的模块文件解析路径，本文按 `dialog_workflow._WORKFLOWS_DIR`（`poe_workflow/workflows/`）与 `ModulePalette._scan_subworkflows` 的扫描口径推断为 `workflows/<name>.json`。该闭包本体未逐行通读，若实际解析路径（如带额外前缀或走宿主配置）与此不同，需以 `_on_run` 源码为准修正 §5.3 / §6 / `ops.md §3` 的描述。

## 9. 测试布局

目录 `poe_workflow/tests/`，含 **35 个 `test_workflow_*.py`**（README 记为约 505 用例）+ `conftest.py`。

- **引擎层**：以注入式伪对象（`SimpleNamespace` / 自写 mock）驱动，无真实游戏窗口即可全量回归。
- **UI 层**：`conftest.py` 强制 `QT_QPA_PLATFORM=offscreen`（在任何 `QApplication` 构造前 `setdefault`），并复用宿主 `poe_config.txt` 的**临时副本**构造 `ConfigManager`——**绝不写真实配置**。
- **夹具**（`conftest.py`）：
  - `config_manager(tmp_path)`：裸 `ConfigManager`，基于临时配置副本。
  - `stack(tmp_path)`：函数级完整依赖链 `ConfigManager→CoordinateEngine→InputSimulator→AffixParser→StateMachine`，与 `main.py` 装配顺序一致。
  - `ui_stack(tmp_path_factory)`：模块级依赖链（MainWindow 构造成本高，同模块复用）。
- **隔离守卫**：`conftest` 给 `ConfigManager._atomic_save` 打补丁，任何对真实 `poe_config.txt` 的写盘都会被拦截并抛 `RuntimeError`（防测试污染用户真实配置）。
- **路径依赖**：`conftest` 默认把 `E:\AIProgram\poe-mapmaker` 加入 `sys.path`（可用 `POE_MAPMAKER_ROOT` 环境变量覆盖），因为测试会 `import modules.*` / `ui.tab_system` 等宿主模块作为夹具。后续可改为本仓内置 mock 以彻底解耦。

> [WARN] 运行本仓测试需保证 poe-mapmaker 仓库根在 `PYTHONPATH`（或设 `POE_MAPMAKER_ROOT`）；否则 UI/集成类用例的 import 会失败。

---

## 10. 如何扩展

### 10.1 新增一个原语

1. `workflow_model.py`：把键加入 `PRIMITIVES` 集合。
2. `workflow_engine.py`：新增 `_p_<name>(self, params)` 方法实现动作；在 `_dispatch` 字典（`:478`）登记 `name: self._p_<name>`。
3. `workflow_engine._guard_uncalibrated` 适用时复用（涉及锚点坐标的动作）。
4. `ui/tab_workflow.py`：在 `_default_params(prim)`（`:402`）给出默认 `params`；如需出现在新建下拉，加入 `text_resources.WF_PRIMITIVE_DROPDOWN`。
5. `ui/text_resources.py`：在 `WF_PRIMITIVE_LABELS` 增加中文显示名（数据层键永不中文化）；如需分组展示，更新 `ui/workflow_palette.py` 的 `PRIMITIVE_GROUPS`。
6. `workflow_model._validate_step`：若有必填 `params` 字段，补校验分支（参考 `click_anchor`/`use_currency`/`store_to_stash`）。

### 10.2 新增一个条件源

1. `workflow_model.py`：把键加入 `CONDITION_SOURCES`。
2. `workflow_engine._eval_condition`（`:500`）：在 `if src == "..."` 链中增加分支，从 `self._ctx` / 宿主服务取数并调 `self._cmp(...)`。
3. `workflow_model._validate_condition`（`:518`）：补充该校验所需的必填字段（如 `config` 需 `section`+`key`）。
4. 若 UI 条件编辑器需暴露该源，更新 `ui/tab_workflow.py` 的 `_build_condition_editor` 与 `text_resources` 文案。

### 10.3 扩展宿主契约

新增宿主能力时，优先作为 `InputService` 的**可选方法**（`getattr` 容错）或新增独立 Protocol；保持引擎「缺失即跳过 / 缺失即降级」的容错哲学（参考 G6 剪贴板、`get_mouse_pos` 悬停评估降级）。

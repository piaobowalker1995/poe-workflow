# poe-workflow

独立的工作流编排引擎，**从 [poe-mapmaker](https://github.com/piaobowalker1995/poe-mapmaker) 抽取**（Phase 1：纯 Python 内核）。

## 背景

poe-mapmaker 的「工作流编排」功能（路线 B：独立并行引擎，不修改 `state_machine.py`）
包含数据模型 + 执行引擎 + 大量 UI。为降低主仓耦合、便于复用与独立测试，按用户决策
分两阶段抽取：

- **Phase 1（本仓库当前状态）**：抽取纯 Python 内核——数据模型
  (`workflow_model.py`) 与执行引擎 (`workflow_engine.py`)，**无 PyQt5 依赖**；
  poe-mapmaker 的 UI 仍留主仓，以库方式 `from poe_workflow import ...` 调用。
  注意13（文档要求）在主仓仍未完全解除，因为 UI 仍在主仓。
- **Phase 2（待实施）**：将 UI 簇（tab_workflow 等 ~5800 行）+ 共享依赖
  (theme / text_resources / _constants) + 测试整体迁入本仓库；poe-mapmaker 仅保留
  `open_workflow_dialog` 薄壳。届时本仓库需补齐自身满足注意13 的
  dev / user / ops / INDEX 文档。
- **Phase 2a（本仓库当前状态）**：已将工作流 UI 簇整体迁入 `poe_workflow/ui/`
  子包，并复刻了被 UI 使用的共享宿主模块（`theme` 画布子集 / `text_resources` 工作流
  专属文案 / `_constants` 用到的常量 / `hotkey_capture_widget`）。`workflows/` 目录
  （6 个示例方案 JSON）与 `tests/`（35 个 `test_workflow_*.py`，505 用例）一并迁入。
  poe-mapmaker 现为薄壳：仅 `ui/main_window.open_workflow_dialog()` 通过
  `from poe_workflow.ui.dialog_workflow import WorkflowDialog` 拉起弹窗。
  注意13 在主仓已解除（UI 不在主仓），但本仓库自身的 dev/user/ops/INDEX 文档仍待补齐。

## 安装

```bash
pip install -e .          # 可编辑安装（开发）
# 或
pip install .
```

## 架构

```
poe_workflow/
├── workflow_model.py   # 纯数据 + 校验 + JSON 互转（零内部依赖，便于单测）
├── workflow_engine.py  # 执行内核：原语 / 控制结构 / 条件 / 错误策略 / 可中断
├── protocols.py       # 宿主服务契约（CoordService / InputService / ConfigService /
│                      #   AffixService / SchemeLoader）——引擎以鸭子类型调用，无需继承
├── ui/                # Phase 2a 迁入的 PyQt5 UI 簇（弹窗 / 列表 / 画布 / 模块库 / 编辑器）
│   ├── dialog_workflow.py       # WorkflowDialog：模块库 + 列表/画布双视图 + 步骤编辑器抽屉
│   ├── tab_workflow.py          # WorkflowTab：列表视图 + 编辑器
│   ├── tab_workflow_canvas.py   # WorkflowCanvasTab：画布视图
│   ├── workflow_canvas.py       # WorkflowCanvasView：QGraphicsView 只读画布
│   ├── workflow_canvas_model.py # CanvasModel：画布非 Qt 适配层（数据模型）
│   ├── workflow_palette.py      # ModulePalette：原语模块库面板
│   ├── theme.py / text_resources.py / _constants.py / hotkey_capture_widget.py
│   │                           # 复刻自宿主的共享件（仅供本子包 UI 使用）
│   └── __init__.py
├── workflows/         # 示例方案 JSON（decision_map_* / example_click_read /
│                      #   preset_map_eval / new_workflow / preset_mapmaker_full）
├── tests/             # 35 个 test_workflow_*.py（505 用例，offscreen 可全量回归）
└── __init__.py        # 统一导出
```

引擎通过**构造注入**依赖宿主能力，不反向引用任何宿主模块：

```python
from poe_workflow import WorkflowEngine, workflow_from_dict

engine = WorkflowEngine(coord=host_coord, inp=host_input, cm=host_cfg, parser=host_parser)
engine.load_def(workflow_from_dict(data))
reason = engine.run_sync()   # "done" / "aborted" / "error"
```

宿主需实现 `poe_workflow.protocols` 中描述的接口（结构化即可，无需继承）。

## 能力范围（Phase 1 内核）

- **原子原语**：`click_anchor` / `move_to_anchor` / `move_offset` / `press_key` /
  `read_clipboard` / `copy` / `wait_ms` / `recall_cell` / `log` / `abort` /
  `use_currency` / `record_session` / `pause` / `store_to_stash`
- **控制结构**：`loop`（count / until 条件 / 网格循环）、`branch`（条件分支）、
  嵌套与 `subworkflow`（一等公民）
- **条件源**：`clipboard` / `ctx` / `ctx_diff` / `counter` / `rarity` / `affix` /
  `session` / `config`
- **错误策略**：`retry`（默认）/ `abort` / `skip` / `jump`（可指向步骤 id 或模块方案）
- **可中断**：`abort()` 贯穿所有层级（含循环体、等待）；`start()` / `abort()` 基于
  threading；`run_sync()` 供 pytest 免 Qt 验证

## 测试

```bash
pip install -e ".[ui]"     # 含 PyQt5 的 UI 层（仅运行 UI/画布测试需要）
pytest poe_workflow/tests/  # 35 个 test_workflow_*.py，505 用例
# 引擎层单测无需 GUI：PYTEST_QT / PyQt5 仍被 import，但逻辑以注入式伪对象驱动
```

- 引擎层以注入式伪对象驱动，无需真实游戏窗口即可全量回归；
- UI 层测试在 `poe_workflow/tests/conftest.py` 下强制 `QT_QPA_PLATFORM=offscreen`，
  并复用宿主 `poe_config.txt` 的临时副本来构造 `ConfigManager`（绝不写真实配置）；
- 测试直接 `import modules.*` / `ui.tab_system` 等宿主模块作为夹具——因此运行本仓测试时
  需将 poe-mapmaker 仓库根加入 `PYTHONPATH`（后续可改为本仓内置 mock 夹具以彻底解耦）。

## License

与 poe-mapmaker 一致。

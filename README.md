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

引擎层以注入式伪对象驱动，无需 GUI 即可全量回归（见 poe-mapmaker 的
`tests/test_workflow_engine_*.py`，Phase 2 迁移至本仓库）。

## License

与 poe-mapmaker 一致。

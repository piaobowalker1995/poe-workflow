# POE Workflow 文档索引

> **文档根目录**: `E:\AIProgram\poe-workflow`
> **版本**: 0.1.0 | **更新日期**: 2026-10-30
> 本仓库为从 [poe-mapmaker](https://github.com/piaobowalker1995/poe-mapmaker) 抽取的**独立工作流编排引擎**（Phase 1 纯 Python 内核 + Phase 2a PyQt5 UI 簇）。本文档满足主仓「注意13」的 dev / user / ops / INDEX 四件套要求。

## 1. 仓库一句话定位

把《流放之路》地图制作的「移动 / 点击 / 读剪贴板 / 复制 / 通货应用 / 存仓」等操作编排成**可重复执行、可循环、可条件分支、可中断**的方案，宿主（poe-mapmaker）通过构造注入复用其能力，自身零耦合。

## 2. 模块地图

```
poe_workflow/
├── __init__.py            # 统一导出（WorkflowEngine / workflow_from_dict / 各 Protocol 与常量）
├── workflow_model.py      # 数据模型：ActionStep / WorkflowDef、PRIMITIVES、CONDITION_*、
│                          #   ERROR_POLICIES、RULE_PRESETS、校验、JSON<->模型互转、id 重编号
├── workflow_engine.py     # 执行内核：14 原语实现、控制结构（loop/branch/subworkflow）、
│                          #   8 条件源、错误策略、可中断线程模型、run_sync/start/abort/resume
├── protocols.py           # 宿主服务契约（鸭子类型，无需继承）：CoordService / InputService /
│                          #   ConfigService / AffixService / SchemeLoader
├── ui/                    # Phase 2a 迁入的 PyQt5 UI 簇（弹窗 / 列表 / 画布 / 模块库 / 编辑器）
│   ├── dialog_workflow.py       # WorkflowDialog：模块库 + 列表/画布双视图 + 步骤编辑器抽屉
│   ├── tab_workflow.py          # WorkflowTab：列表视图 + 编辑器 + 加载/保存/运行；WorkflowEditorPanel
│   ├── tab_workflow_canvas.py   # WorkflowCanvasTab：画布视图（可编辑、拖拽重排/删除/落模块）
│   ├── workflow_canvas.py       # WorkflowCanvasView（QGraphicsView）+ 图元（Step/SubWorkflow/Container/Edge）
│   ├── workflow_canvas_model.py # CanvasModel：画布非 Qt 适配层（单一事实源，变更监听）
│   ├── workflow_palette.py      # ModulePalette：原语模块库 + 子工作流（点击/拖拽插入）
│   ├── theme.py                 # 浅色/深色 QSS + 画布配色（get_qss / get_canvas_colors）
│   ├── text_resources.py       # 中文文案单一事实源（WF_PRIMITIVE_LABELS 等，禁止硬编码中文）
│   ├── _constants.py           # 配置段名常量（SEC_*）、背包网格、延时物理下限
│   └── hotkey_capture_widget.py # 共用「单击输入框即捕获快捷键」部件
├── workflows/             # 6 个示例方案 JSON（见 §3）
└── tests/                # 35 个 test_workflow_*.py + conftest.py（offscreen 全量回归）
```

### 2.1 各模块一句话说明

| 模块 | 路径 | 一句话说明 |
|------|------|-----------|
| 数据模型 | `poe_workflow/workflow_model.py` | 纯数据 + 校验 + JSON 互转，零 Qt 依赖，便于单测 |
| 执行内核 | `poe_workflow/workflow_engine.py` | 原语 / 控制结构 / 条件 / 错误策略 / 可中断；构造注入宿主能力 |
| 宿主契约 | `poe_workflow/protocols.py` | 引擎调用的 5 个鸭子接口；宿主结构化实现即可，无需继承 |
| 编排弹窗 | `poe_workflow/ui/dialog_workflow.py` | 独立弹窗入口，三段式布局（模块库 \| 视图栈 \| 编辑器抽屉） |
| 列表视图 | `poe_workflow/ui/tab_workflow.py` | 步骤卡片列表 + 参数编辑器 + 文件加载/保存/运行控制 |
| 画布视图 | `poe_workflow/ui/tab_workflow_canvas.py` | 流程图画布，支持拖动重排、删除、模块库拖入、子工作流展开 |
| 画布控件 | `poe_workflow/ui/workflow_canvas.py` | QGraphicsView 实现，节点/连线绘制 + 网格对齐参考线 |
| 画布模型 | `poe_workflow/ui/workflow_canvas_model.py` | 非 Qt 的数据适配层，与列表视图共享同一根列表引用 |
| 模块库 | `poe_workflow/ui/workflow_palette.py` | 左侧原语 + 子工作流面板，发射 `itemActivated` 信号 |
| 主题 | `poe_workflow/ui/theme.py` | 浅色/深色两套 QSS 与画布配色，禁用硬编码颜色 |
| 文案 | `poe_workflow/ui/text_resources.py` | 所有中文显示文本集中管理 |
| 常量 | `poe_workflow/ui/_constants.py` | 配置段名、背包网格尺寸、延时物理下限常量 |
| 热键捕获 | `poe_workflow/ui/hotkey_capture_widget.py` | 复用型「单击即捕获」输入框部件 |
| 示例方案 | `poe_workflow/workflows/` | 6 个可直接加载运行的 JSON 示例 |
| 测试 | `poe_workflow/tests/` | conftest 强制 offscreen Qt，复用宿主临时配置副本做夹具 |

## 3. 内建示例方案（workflows/）

| 文件名 | name 字段 | 用途 |
|--------|-----------|------|
| `preset_mapmaker_full.json` | 预置·制图流程（全量复刻） | 网格遍历背包 + 鉴定/点金/腐化 + 分类存仓的完整体验示例 |
| `preset_map_eval.json` | 预置·地图评估（对比评估模块） | 悬停复制 → 三档评估（优秀/合格/废图）→ 按腐化开关分流存仓 |
| `decision_map_full.json` | 稀有地图重铸决策（示例） | 重铸决策 + 会话限速（`source=session`）分支示例 |
| `decision_map_verify.json` | 通货应用验证-重试（示例） | `use_currency` 取用前/后 `copy` 比对 + `on_error=retry` 示例 |
| `example_click_read.json` | 示例：点通货仓锚点并读剪贴板 | 最小可跑示例（点击锚点 + 读剪贴板 + 等待） |
| `new_workflow.json` | 新方案 | 空模板（首步 `move_to_anchor`），「新建」按钮基于此克隆 |

## 4. 文档导航

| 角色 | 子文件 | 路径 | 摘要 |
|------|--------|------|------|
| 开发者 | dev.md | `E:\AIProgram\poe-workflow\dev.md` | 架构边界（引擎↔宿主构造注入）、14 原语参数形态、8 条件源、控制结构、错误策略、可中断线程模型、宿主契约接口、测试布局、扩展指引 |
| 使用者 | user.md | `E:\AIProgram\poe-workflow\user.md` | 功能简介、从 poe-mapmaker 打开入口、编辑器（列表+画布双视图/步骤抽屉/模块库）、加载/保存/运行、地图评估预置概念 |
| 运维者 | ops.md | `E:\AIProgram\poe-workflow\ops.md` | 安装（`pip install -e ".[ui]"`）、运行测试（offscreen Qt）、新增方案 JSON、故障排查、与主仓版本耦合 |

## 5. 交叉引用表

| 主题 | 主要位置 | 关联位置 |
|------|----------|----------|
| 引擎↔宿主边界 | dev.md §2 | protocols.py 全文件 |
| 原语参数形态 | dev.md §3 | workflow_model.py `PRIMITIVES` / `ActionStep` |
| 条件源语义 | dev.md §4 | workflow_engine.py `_eval_condition` |
| 可中断模型 | dev.md §6 | workflow_engine.py `run_sync`/`start`/`abort`/`resume` |
| 编辑器用法 | user.md §3 | ui/tab_workflow.py / ui/dialog_workflow.py |
| 测试隔离 | ops.md §3 | tests/conftest.py（临时配置副本 + offscreen） |

## 6. 章节索引

| 子文件 | ## 级章节标题 |
|--------|-------------|
| dev.md | 1. 项目概述 / 2. 系统架构 / 3. 原语（14 个） / 4. 条件源（8 个）与操作符 / 5. 控制结构 / 6. 错误策略 / 7. 可中断线程模型 / 8. 宿主契约（protocols） / 9. 测试布局 / 10. 如何扩展 |
| user.md | 1. 功能简介 / 2. 如何打开 / 3. 编辑器总览 / 4. 加载/保存/运行 / 5. 地图评估预置概念 / 6. 常见问题 |
| ops.md | 1. 安装 / 2. 运行测试 / 3. 新增工作流方案 / 4. 故障排查 / 5. 与主仓（poe-mapmaker）的版本耦合 |

> **维护规则**: 子文件修改后须同步更新本文件的摘要行与版本号；本文仅保留导航功能。

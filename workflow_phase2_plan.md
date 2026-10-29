# 工作流抽取 Phase 2 规划（workflow_phase2_plan.md）

> 背景：poe-mapmaker 的「工作流编排」功能（路线 B：独立并行引擎，不改动 `state_machine.py`）
> 按用户决策分两阶段抽取到独立公开仓 **poe-workflow**。本文记录已完成项与后续子阶段规划。

## 已完成

### Phase 1 — 纯 Python 内核（已合入 poe-workflow）
- `workflow_model.py`：数据模型 + 校验 + JSON 互转，**零内部依赖**，便于单测。
- `workflow_engine.py`：执行内核——14 原语 / 8 条件源 / 4 错误策略（retry/abort/skip/jump）/
  loop·branch·subworkflow / 可中断（threading + `run_sync`）。
- `protocols.py`：宿主服务契约（CoordService / InputService / ConfigService / AffixService /
  SchemeLoader），引擎以鸭子类型调用，无需继承。
- 主仓以 `from poe_workflow import ...` 调用内核。

### Phase 2a — UI 簇 + 测试 + 数据迁出（已合入）
- UI 簇 6 文件（`dialog_workflow` / `tab_workflow` / `tab_workflow_canvas` / `workflow_canvas` /
  `workflow_canvas_model` / `workflow_palette`）+ 复刻共享件（`theme` 画布子集 / `text_resources`
  工作流文案块 / `_constants` / `hotkey_capture_widget`）迁入 `poe_workflow/ui/`。
- `workflows/` 6 个示例方案 JSON 迁入。
- 35 个 `test_workflow_*.py`（**505 用例**）迁入 `poe_workflow/tests/`。
- 主仓仅 `ui/main_window.open_workflow_dialog()` 以薄壳拉起 `WorkflowDialog`。
- 主仓 CI 加 poe-workflow 安装步骤（commit `cbaceb9`），CI-main 转绿（run #171 success）。
- poe-workflow 补 dev/user/ops/INDEX 文档（Task #170）。
- **poe-workflow 测试与宿主解耦**（Task #171）：`tests/_stubs/` 提供 `modules`/`ui` 桩，
  `unset POE_MAPMAKER_ROOT` 且不在 poe-mapmaker 目录下仍 **505 passed**。
- **poe-mapmaker 合规治理**（Task #172 / #173）：
  - P-注意19：`scripts/check_docstrings.py`（AST 覆盖率检查）+ CI 非阻断报告步骤；已补种
    核心模块公开 API 文档字符串（modules+ui 缺失率 47.8% → 42.6%）。
  - G-注意26：代码层 emoji 清理（tab_flowchart / text_resources / main_window /
    input_simulator）；文档层 dev.md / ops.md / poe_ai_rules.md emoji 清理。
  - G-注意13：工作流引擎在 dev/user/ops/INDEX 全量登记。
  - G-注意8：V3030 全量发现 §2 → §3 迁移。

## 待办（Phase 2b / 2c）

### Phase 2b — 收尾迁移与共享件统一
- **目标**：扫描主仓是否仍残留工作流相关引用（旧 `ui/tab_workflow.py` 薄桩、import 兼容层等）；
  明确主仓与子仓各持一份 `theme`/`text_resources` 副本的权威来源策略，避免漂移。
- **范围**：主仓残留扫描 + 共享件去重策略（主仓改引用子仓 / 或子仓继续复刻并约定同步）。
- **风险**：两份副本易漂移；主仓薄壳若误删会导致功能丢失。
- **排期**：待定（依赖用户确认共享件策略）。

### Phase 2c — 测试解耦固化 + CI 自包含 + 文档治理
- **poe-workflow 补 CI**（Task #169，已写 `.github/workflows/ci.yml`，依赖 #171 验证通过）：
  windows-latest + PyQt5 + offscreen + pytest，目标 505 passed 门禁。
- **主仓 P-19 硬门禁**：待 docstring 覆盖率达标后，将 ci.yml 非阻断步骤升级为
  `python scripts/check_docstrings.py --strict`。
- **文档治理**：G-注意14 `[WARN]` 版本史冲突（v3.0.16/17/24/27）待用户确认权威版本后消去；
  poe-workflow 文档 TODO（`WorkflowTab._on_run` 的 `_scheme_loader` 方案路径）待核清。
- **风险**：CI 环境与本地 venv 差异（PyQt5 on 3.13 wheel 可用性）；`tests/_stubs/modules/
  affix_parser.py` 为宿主副本，宿主变更时需同步。
- **排期**：#169 紧随 #171 完成；其余并入 v3.0.30 审计修复批次。

## 已知遗留 / 待用户决策
- **G-注意14**：dev.md §E 的 v3.0.16/17（日期冲突）、v3.0.27（重复+日期冲突）、v3.0.24（日期推断）
  共 6 处 `[WARN]` 需用户确认权威版本。
- **poe-workflow/ui 复刻件 emoji**：`poe_workflow/ui/text_resources.py` 等复刻件可能仍含 emoji
  （G-26 本次范围外，建议后续统一清理）。
- **stub `affix_parser` 一致性**：`tests/_stubs/modules/affix_parser.py` 为宿主 `modules/
  affix_parser.py` 的副本，宿主改动时需同步该桩。

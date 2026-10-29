# 运维手册（poe-workflow）

> **版本**: 0.1.0 | **更新日期**: 2026-10-30
> 面向运维/部署：安装、运行测试、新增方案、故障排查、与 poe-mapmaker 的版本耦合。开发细节见 `dev.md`，使用说明见 `user.md`。

---

## 1. 安装

仓库根目录 `E:\AIProgram\poe-workflow`。

```bash
# 仅内核（无 UI，纯 Python，无 PyQt5 依赖）
pip install -e .

# 含 PyQt5 的 UI 层（弹窗/列表/画布/模块库需要；运行 UI 与画布测试需要）
pip install -e ".[ui]"
```

- `.[ui]` 额外安装 `PyQt5`（及画布/编辑器测试所需）。
- `poe_workflow/__init__.py` 标记 `__version__ = "0.1.0"`，统一导出 `WorkflowEngine` / `workflow_from_dict` / 各 Protocol 与常量。
- 不想装 editable 可用 `pip install .`（生产冻结场景）。

> [WARN] 仅装内核（`pip install -e .`）时**无法**导入 `poe_workflow.ui.*`；若你的宿主（poe-mapmaker）依赖 `WorkflowDialog`，必须装 `.[ui]`。

---

## 2. 运行测试

测试目录 `poe_workflow/tests/`：35 个 `test_workflow_*.py` + `conftest.py`（README 记为约 505 用例）。

```bash
# 强制 offscreen Qt（无显示环境也能构造控件），跑全部
QT_QPA_PLATFORM=offscreen pytest poe_workflow/tests/
```

- `conftest.py` 在任何 `QApplication` 构造前 `os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")`，无显式设置时也会回落 offscreen。
- **引擎层单测无需 GUI**：用注入式伪对象（`SimpleNamespace` / mock）驱动 `WorkflowEngine`，不依赖真实窗口。
- **UI 层测试**：依赖 `conftest` 的 `stack` / `ui_stack` 夹具，复用宿主 `poe_config.txt` 的**临时副本**构造 `ConfigManager`，并对 `ConfigManager._atomic_save` 打补丁——**任何对真实配置文件的写盘都会被拦截并抛 RuntimeError**（测试隔离守卫）。
- **路径依赖**：`conftest` 默认把 `E:\AIProgram\poe-mapmaker` 加入 `sys.path`（可用环境变量 `POE_MAPMAKER_ROOT` 覆盖），因为用例会 `import modules.*` / `ui.tab_system` 等宿主模块。运行本仓测试前需保证该路径存在，或将 `POE_MAPMAKER_ROOT` 指向你的 poe-mapmaker 仓库根。

> [FAIL] 若未设 `QT_QPA_PLATFORM=offscreen` 且环境无显示器（CI/服务器），UI 用例会因无法初始化 Qt 平台插件而失败。务必显式带该环境变量。
>
> [FAIL] 若 `PYTHONPATH`/`POE_MAPMAKER_ROOT` 未指向有效 poe-mapmaker 仓库，集成/UI 类用例 import 失败。后续计划改为本仓内置 mock 夹具以彻底解耦。

### 2.1 只跑引擎层（最快回归）

```bash
QT_QPA_PLATFORM=offscreen pytest poe_workflow/tests/ -k "engine or phase or model or primitive"
```

（按文件名/用例名过滤；具体可用 `pytest --collect-only` 查看。）

---

## 3. 新增工作流方案

把新方案 JSON 放到 `poe_workflow/workflows/`：

1. **文件名**即模块引用键（不含 `.json`）：同时是 `jump_target`、子工作流引用、模块库显示名的数据层键。命名避免空格/中文路径问题（显示名可在文件内 `name` 字段中文化）。
2. **结构**（`workflow_from_dict` 解析）：
   ```json
   {
     "name": "我的方案（显示名，可中文）",
     "version": 1,
     "schema_version": "1.0",
     "steps": [ { "id": "1", "kind": "action", "primitive": "move_to_anchor",
                  "params": {"anchor": "inv_first_cell_base_point"} } ]
   }
   ```
   - 数组元素顺序即顶层执行顺序；嵌套用 `body` / `then_steps` / `else_steps`。
   - 不写 `schema_version` 默认 `"1.0"`，缺失字段带合理默认值（`_step_from_dict`）。
3. **校验**：加载时 `validate_workflow` 会校验重复 step id、原语/条件源合法性、必填 `params`、`loop` 三选一、网格维度上限（`GRID_MAX_CELLS=10000`）、`branch` 不支持 `counter` 源等。早失败优于运行时静默失效。
4. **生效**：弹窗模块库「子工作流」区会自动扫描 `workflows/` 下的 `.json`（经 `ModulePalette._scan_subworkflows` / `WorkflowTab._scan_schemes`），无需重启即可在编排中引用为新模块。

> [OK] 新增方案后，若要在其他方案里「跳转/子工作流」引用它，把 `jump_target`（或子工作流步骤的 `jump_target`）设为该文件名（不含 `.json`）即可。

---

## 4. 故障排查

| 问题 | 现象 | 处理 |
|------|------|------|
| 缺 PyQt5 | `import poe_workflow.ui` 报 `ModuleNotFoundError: PyQt5` | 装 `pip install -e ".[ui]"` |
| Qt 无显示器 | UI 用例 / 弹窗构造报「could not connect to display」或平台插件错误 | 带 `QT_QPA_PLATFORM=offscreen` 运行 |
| 测试写真实配置 | 测试报 `[测试隔离守卫] 拦截到对真实配置文件 ... 的写盘` | 正常防护；说明某用例未走临时副本，需修调用方，不要禁用守卫 |
| 锚点未校准 | 运行立即 `aborted`，日志「坐标阻断：锚点 X 未校准」 | 在宿主校准页完成对应锚点指认（坐标铁律 `dev.md §3.1`） |
| 剪贴板连续读空 | 步骤熔断、日志「剪贴板连续 N 次读空」 | 游戏窗口是否前台、Ctrl+C 是否生效；必要时调 `Runtime.clipboard_empty_limit` |
| 循环疑似跑一半停 | 网格 `cols×rows` 超 10000 被静默截断（已在校验层拒收） | 收窄维度；校验层会提前报错而非静默截断 |
| 分支条件不生效 | `branch` 用了 `source=counter` | 校验层会拒收；改用 `source=ctx` + `__grid_col`/`__loop_index` |
| 引用模块找不到 | `jump`/子工作流失败，日志「既非步骤 id 也非可解析模块」 | 确认 `jump_target` 是合法步骤 id 或 `workflows/<name>.json` 文件名；`scheme_loader` 已注入 |

### 4.1 日志

- 引擎日志走标准 `logging`，`log` 原语写入主窗口日志栏（`logger.info("[工作流] %s", message)`）。
- 追踪引擎内部可临时调高 `poe_workflow` logger 级别。

---

## 5. 与 poe-mapmaker 的版本耦合

- **本仓定位**：从 poe-mapmaker 抽取的**独立引擎 + UI 簇**。poe-mapmaker 现为薄壳，仅 `ui/main_window.open_workflow_dialog()` 通过 `from poe_workflow.ui.dialog_workflow import WorkflowDialog` 拉起弹窗（`README` 的 Phase 2a 描述）。
- **接口边界**：两仓通过 `poe_workflow.protocols` 的 5 个鸭子类型契约解耦；poe-mapmaker 实现 `CoordService` / `InputService` / `ConfigService` / `AffixService` / `SchemeLoader` 并注入 `WorkflowEngine`。
- **版本一致性**：本仓 `__version__ = "0.1.0"`，尚处抽取初期。宿主调用方（poe-mapmaker）若升级本仓，需确认：
  1. `WorkflowEngine` 构造参数（`coord/inp/parser/cm/scheme_loader`）与 Protocol 方法签名未变；
  2. 新增原语/条件源若主机未实现对应宿主方法，引擎以容错（可选能力缺失跳过 / 降级）处理，但**新原语的语义**需宿主配合（如新 `use_currency` 参数）。
- **发版建议**：本仓与 poe-mapmaker 同步打 tag；改动 `protocols.py` 或 `workflow_model` 的 `ActionStep`/`WorkflowDef` 字段属**破坏性变更**，须 bump `schema_version` 并在两仓同步验证。

> [WARN] 本仓测试仍 `import modules.*`（宿主）作为夹具，因此**本仓测试通过 ≠ 宿主可独立**。改动宿主坐标/输入契约时，须回到 poe-mapmaker 端回归工作流相关用例。

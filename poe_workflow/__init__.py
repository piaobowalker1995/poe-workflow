"""poe-workflow: 独立工作流编排引擎（从 poe-mapmaker 抽取，Phase 1）。

纯 Python 内核（数据模型 + 执行引擎），**无 PyQt5 依赖**。宿主通过
构造注入坐标 / 输入 / 配置 / 词缀解析 / 方案加载等能力，契约见
``poe_workflow.protocols``。

典型用法::

    from poe_workflow import WorkflowEngine, workflow_from_dict

    engine = WorkflowEngine(coord=host_coord, inp=host_input, cm=host_cfg)
    engine.load_def(workflow_from_dict(data))
    reason = engine.run_sync()  # "done" / "aborted" / "error"
"""
from .workflow_model import (
    WorkflowDef, ActionStep, WorkflowLoadError,
    validate_workflow, workflow_from_dict, load_workflow_file,
    PRIMITIVES, CONDITION_SOURCES, CONDITION_OPS, ERROR_POLICIES,
    RULE_PRESETS, THRESHOLD_PRESETS, FEATURE_LIBRARY,
    GRID_MAX_CELLS, GRID_MAX_DIM, GRID_MAX_OFFSET, RULE_KINDS,
    resolve_rule, threshold_group, build_or_pattern,
    migrate_delay_ms, remap_jump_targets, collect_step_ids,
    build_id_remap, assign_step_ids,
)
from .workflow_engine import WorkflowEngine
from .protocols import (
    CoordService, InputService, ConfigService, AffixService, SchemeLoader,
)

__all__ = [
    "WorkflowDef", "ActionStep", "WorkflowLoadError",
    "validate_workflow", "workflow_from_dict", "load_workflow_file",
    "PRIMITIVES", "CONDITION_SOURCES", "CONDITION_OPS", "ERROR_POLICIES",
    "RULE_PRESETS", "THRESHOLD_PRESETS", "FEATURE_LIBRARY",
    "GRID_MAX_CELLS", "GRID_MAX_DIM", "GRID_MAX_OFFSET", "RULE_KINDS",
    "resolve_rule", "threshold_group", "build_or_pattern",
    "migrate_delay_ms", "remap_jump_targets", "collect_step_ids",
    "build_id_remap", "assign_step_ids",
    "WorkflowEngine",
    "CoordService", "InputService", "ConfigService", "AffixService", "SchemeLoader",
]

__version__ = "0.1.0"

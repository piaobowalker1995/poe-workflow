# -*- coding: utf-8 -*-
"""GUI 升级 阶段1：模块库面板 + CanvasModel 接入工作流编排（offscreen 冒烟）。

验证：面板列出 14 原语 + 子工作流；点击插入生成合法步骤；validate_workflow 通过。
依赖 tests/conftest.py 的 qapp（pytest-qt, offscreen）+ config_manager 夹具。

注（2026-10-18）：工作流功能已剥离为独立弹窗 WorkflowDialog，模块库面板随之
上移到弹窗左侧常驻栏（不再放在编辑器抽屉内），故此处按弹窗结构断言。
注（2026-10-23）：新增 store_to_stash（存入仓库）原语 → 13 → 14。
"""
import pytest
from PyQt5.QtWidgets import QApplication

from poe_workflow.ui.dialog_workflow import WorkflowDialog
from poe_workflow.ui.tab_workflow import WorkflowTab
from poe_workflow.ui.workflow_palette import ModulePalette

PRIM_COUNT = 14


def test_palette_lists_all_primitives(qapp, config_manager):
    dlg = WorkflowDialog(config_manager)
    palette = dlg._palette
    assert isinstance(palette, ModulePalette)
    prims = [b for b in palette._buttons
             if b.property("palette_type") == "primitive"]
    assert len(prims) == PRIM_COUNT, f"应有 {PRIM_COUNT} 个原语，实际 {len(prims)}"
    # 子工作流条目至少列出一项（仓库 workflows/ 下存在预设）
    subs = [b for b in palette._buttons
            if b.property("palette_type") == "subworkflow"]
    assert subs, "模块库应至少列出一个子工作流"


def test_palette_activate_inserts_valid_primitive(qapp, config_manager):
    tab = WorkflowTab(config_manager)
    tab._on_new()  # 清成单个合法步骤，避免载入既有方案干扰计数
    before = len(tab._steps_dicts)
    tab._on_palette_activated({"type": "primitive", "payload": "move_to_anchor"})
    assert len(tab._steps_dicts) == before + 1
    errs = tab._canvas_model.validate()
    assert errs == [], errs


def test_palette_activate_inserts_valid_subworkflow(qapp, config_manager):
    tab = WorkflowTab(config_manager)
    tab._on_new()
    before = len(tab._steps_dicts)
    tab._on_palette_activated({"type": "subworkflow", "payload": "preset_mapmaker_full"})
    assert len(tab._steps_dicts) == before + 1
    errs = tab._canvas_model.validate()
    assert errs == [], errs
    # P4-A：一等公民——插入的应是 kind=subworkflow（正常路径调用），非 on_error=jump
    inserted = tab._steps_dicts[-1]
    assert inserted.get("kind") == "subworkflow"
    assert inserted.get("on_error") == "retry"
    assert inserted.get("jump_target") == "preset_mapmaker_full"

# -*- coding: utf-8 -*-
"""StepCard 编辑器直接单测补课（波1-B 批次 B3）。

此前 StepCard 内部零直接测试，是「延迟字段错位」等延迟 bug 逃过 485 全绿的根源。
本文件用 tests/conftest.py 的 qapp + config_manager 夹具，对 StepCard 关键编辑器
方法做直接单测：延迟控件直写顶层 delay_ms、_set_param 写入 params、跳转目标编辑器
回写 step dict、StepCard 按层级序号推导 id 等。运行前「跳转目标非法」校验逻辑在
tests/test_workflow_delay_and_jump.py 的 test_run_blocked_on_unresolvable_jump_target
已覆盖（属 WorkflowTab._on_run 入口）。
依赖 tests/conftest.py 的 qapp（pytest-qt, offscreen）+ config_manager 夹具。
"""
from PyQt5.QtWidgets import QSpinBox, QComboBox

from poe_workflow.ui.tab_workflow import StepCard, WorkflowTab, _new_step_dict


def _card(qapp, config_manager, over=None):
    """构造一个最小可用的 StepCard（默认动作步），返回 (card, step_dict)。"""
    tab = WorkflowTab(config_manager)
    d = _new_step_dict(tab)
    if over:
        d.update(over)
    return StepCard(d, [d], tab, "1"), d


def _row_and_spin(row):
    """返回 (row, spinbox)：调用方必须持有 row，否则 C++ 控件被 GC 后无法设值。"""
    sb = row.findChild(QSpinBox)
    assert sb is not None, "延迟行应包含 QSpinBox"
    return row, sb


def test_delay_row_spinbox_writes_top_level_delay_ms(qapp, config_manager):
    """「步骤延迟」spinbox 必须直写顶层 delay_ms，不再误写 params。"""
    card, d = _card(qapp, config_manager, {"delay_ms": 0})
    row, sb = _row_and_spin(card._build_delay_row())
    sb.setValue(300)
    assert d["delay_ms"] == 300
    assert "delay_ms" not in d.get("params", {}), "delay_ms 不得再写入 params"


def test_set_delay_method_writes_top_level(qapp, config_manager):
    card, d = _card(qapp, config_manager)
    card._set_delay(123)
    assert d["delay_ms"] == 123


def test_set_param_writes_into_params(qapp, config_manager):
    card, d = _card(qapp, config_manager)
    card._set_param("anchor", "瓦尔宝珠")
    assert d["params"]["anchor"] == "瓦尔宝珠"


def test_subworkflow_card_builds(qapp, config_manager):
    """P4-A：kind=subworkflow 卡片应能完整构建（_build_subworkflow 分支），不崩。"""
    card, d = _card(qapp, config_manager,
                    {"kind": "subworkflow", "jump_target": "preset_mapmaker_full"})
    assert d["kind"] == "subworkflow"
    # 再次触发内部编辑器重建（_build_subworkflow → 模块/跳转目标编辑器），不应抛异常
    card._build_inner()


def test_set_param_creates_params_when_missing(qapp, config_manager):
    tab = WorkflowTab(config_manager)
    d = {"id": "1", "kind": "action", "primitive": "log", "params": {}}
    card = StepCard(d, [d], tab, "1")
    card._set_param("message", "hi")
    assert d["params"]["message"] == "hi"


def test_build_action_preserves_existing_anchor_param(qapp, config_manager):
    tab = WorkflowTab(config_manager)
    d = {"id": "1", "kind": "action", "primitive": "move_to_anchor",
         "params": {"anchor": "inv_first_cell_base_point"}}
    card = StepCard(d, [d], tab, "1")
    card._build_inner()
    # 重建动作区不应清掉已有的 anchor（参数编辑器只读 getter/setter，不重写 params）
    assert d["params"].get("anchor") == "inv_first_cell_base_point"


def test_jump_target_editor_writes_back_dict(qapp, config_manager):
    """跳转目标下拉选择后，值应写回 step dict 的 jump_target。

    注意：可编辑 QComboBox 在「已是当前文本」时 setCurrentText 不会触发
    currentTextChanged（setCurrentIndex 在已是首项时同样为 no-op）。因此必须
    注入两个步骤，使组合框含「步骤: 1 / 步骤: 2」，再选文本不同于初始当前项
    的「步骤: 2」，才能确保信号真正触发、值为空时被写回。
    """
    tab = WorkflowTab(config_manager)
    # 注入两个步骤，保证跳转目标组合框有可区分的多项
    tab._steps_dicts = [{"id": "1"}, {"id": "2"}]
    d = _new_step_dict(tab)
    d.update({"on_error": "jump", "jump_target": ""})
    card = StepCard(d, tab._steps_dicts, tab, "1")
    w = card._build_jump_target_editor()
    combo = w.findChild(QComboBox)
    assert combo is not None and combo.count() > 1
    # 选一个文本不同于当前项（首项「步骤: 1」）的目标，确保信号触发
    chosen = None
    for i in range(combo.count()):
        if combo.itemData(i) and combo.itemText(i) != combo.currentText():
            chosen = i
            break
    assert chosen is not None, "应存在文本不同于当前项的跳转目标项"
    target = combo.itemData(chosen)
    target_text = combo.itemText(chosen)
    combo.setCurrentText(target_text)
    assert d["jump_target"] == target


def test_step_card_assigns_index_path_id(qapp, config_manager):
    """StepCard 应按构造时传入的层级序号推导覆盖 step id（含子步 2.1 形式）。"""
    tab = WorkflowTab(config_manager)
    parent = _new_step_dict(tab)
    card = StepCard(parent, [parent], tab, "1")
    assert parent["id"] == "1"
    child = _new_step_dict(tab)
    StepCard(child, [child], tab, "2.1")
    assert child["id"] == "2.1"

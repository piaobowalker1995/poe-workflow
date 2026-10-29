# -*- coding: utf-8 -*-
"""工作流编排独立弹窗 WorkflowDialog 测试（offscreen 冒烟）。

覆盖用户 2026-10-18 定案的剥离结构：
- 弹窗内三段布局：模块库 | 列表/画布视图栈 | 编辑器抽屉
- 弹窗实现与 MainWindow 同名的 set_right_drawer_widget / set_right_drawer_visible
  （WorkflowTab.showEvent 依赖它们做面板注入，故抽屉必须可用）
- 列表/画布共享同一份数据 + 视图切换
- 主窗口左侧导航已不再注册「工作流 / 工作流画布」页签
"""
import pytest
from PyQt5.QtWidgets import QApplication

from poe_workflow.ui.dialog_workflow import WorkflowDialog
from poe_workflow.ui.tab_workflow import WorkflowTab
from poe_workflow.ui.tab_workflow_canvas import WorkflowCanvasTab
from poe_workflow.ui.workflow_palette import ModulePalette


@pytest.fixture(scope="module")
def window(ui_stack, qapp):
    """offscreen 下构造一次 MainWindow（与 test_ui_smoke 同款装配）。"""
    from ui.main_window import MainWindow
    w = MainWindow(ui_stack.cm, ui_stack.inp, ui_stack.coord,
                   ui_stack.parser, ui_stack.fsm)
    yield w
    w.close()


def test_dialog_has_three_panes(qapp, config_manager):
    dlg = WorkflowDialog(config_manager)
    assert isinstance(dlg._palette, ModulePalette)
    assert dlg._stack.count() == 2, "视图栈应为 列表 + 画布 两页"
    assert isinstance(dlg._stack.widget(0), WorkflowTab)
    assert isinstance(dlg._stack.widget(1), WorkflowCanvasTab)
    assert dlg._right_drawer is not None


def test_dialog_exposes_drawer_api(qapp, config_manager):
    """WorkflowTab.showEvent 通过 hasattr 守卫调用这两个 API，必须存在。"""
    dlg = WorkflowDialog(config_manager)
    assert hasattr(dlg, "set_right_drawer_widget")
    assert hasattr(dlg, "set_right_drawer_visible")


def test_dialog_injects_editor_panel_into_drawer(qapp, config_manager):
    """模拟 showEvent：编辑器面板应被注入抽屉容器并标记为展开。

    注意：offscreen 下父窗口未 show，isVisible() 恒 False，
    故断言内部「期望展开」标记 _drawer_shown（这正是实现用于规避该陷阱的机制）。
    """
    dlg = WorkflowDialog(config_manager)
    tab = dlg._wf_tab
    dlg.set_right_drawer_widget(tab._editor_panel)
    dlg.set_right_drawer_visible(True)
    layout = dlg._right_drawer.layout()
    assert layout.count() == 1
    assert layout.itemAt(0).widget() is tab._editor_panel
    assert dlg._drawer_shown is True


def test_drawer_toggle_hides(qapp, config_manager):
    dlg = WorkflowDialog(config_manager)
    dlg.set_right_drawer_widget(dlg._wf_tab._editor_panel)
    dlg.set_right_drawer_visible(True)
    dlg.set_right_drawer_visible(False)
    assert dlg._drawer_shown is False


def test_drawer_injection_is_idempotent(qapp, config_manager):
    """重复注入同一控件应直接返回（避免 takeAt/setParent 引起闪烁）。"""
    dlg = WorkflowDialog(config_manager)
    panel = dlg._wf_tab._editor_panel
    dlg.set_right_drawer_widget(panel)
    dlg.set_right_drawer_widget(panel)
    assert dlg._right_drawer.layout().count() == 1


def test_views_share_single_source_of_truth(qapp, config_manager):
    """画布视图与列表视图必须指向同一份 _steps_dicts（单一事实源）。"""
    dlg = WorkflowDialog(config_manager)
    assert dlg._wf_canvas._workflow_tab is dlg._wf_tab
    assert dlg._wf_tab._canvas_tab is dlg._wf_canvas


def test_canvas_reflects_list_changes(qapp, config_manager):
    """列表插入一步后，画布节点数应随之增加（同步重建）。"""
    dlg = WorkflowDialog(config_manager)
    dlg._wf_tab._on_new()
    dlg._wf_canvas.refresh_from_workflow()
    before = dlg._wf_canvas._canvas.node_count()
    dlg._wf_tab._on_palette_activated({"type": "primitive",
                                       "payload": "move_to_anchor"})
    after = dlg._wf_canvas._canvas.node_count()
    assert after == before + 1, f"画布未同步：{before} -> {after}"


def test_view_switch_toggles_stack(qapp, config_manager):
    dlg = WorkflowDialog(config_manager)
    dlg._switch_view(1)
    assert dlg._stack.currentIndex() == 1
    assert dlg._btn_canvas.isChecked() is True
    dlg._switch_view(0)
    assert dlg._stack.currentIndex() == 0
    assert dlg._btn_list.isChecked() is True


def test_dialog_palette_click_inserts(qapp, config_manager):
    """弹窗左侧模块库点击 → 经 WorkflowTab 插入并自动切回列表视图。"""
    dlg = WorkflowDialog(config_manager)
    dlg._wf_tab._on_new()
    before = len(dlg._wf_tab._steps_dicts)
    dlg._switch_view(1)
    dlg._on_palette_activated({"type": "primitive", "payload": "log"})
    assert len(dlg._wf_tab._steps_dicts) == before + 1
    assert dlg._stack.currentIndex() == 0, "插入后应切回列表视图"
    assert dlg._wf_tab._canvas_model.validate() == []


def test_mainwindow_no_longer_registers_workflow_tabs(window):
    """主窗口左侧导航不再有「工作流 / 工作流画布」页签（已剥离为弹窗）。

    并断言 MainWindow 暴露 open_workflow_dialog 入口方法。
    """
    from modules.text_resources import TextResources
    labels = list(window._tab_order)
    assert TextResources.TAB_WORKFLOW not in labels, \
        "「工作流」页签应已从主窗口导航剥离"
    assert TextResources.TAB_WORKFLOW_CANVAS not in labels, \
        "「工作流画布」页签应已从主窗口导航剥离"
    assert hasattr(window, "open_workflow_dialog")


def test_system_tab_has_workflow_entry_button(qapp, config_manager):
    """系统设置页「修改游戏配置」之后应有「工作流编排」入口按钮。"""
    from PyQt5.QtWidgets import QPushButton
    from modules.text_resources import TextResources
    from ui.tab_system import SystemTab

    tab = SystemTab(config_manager, None)
    buttons = tab.findChildren(QPushButton)
    labels = [b.text() for b in buttons]
    assert TextResources.SYS_BTN_WORKFLOW in labels, \
        f"系统设置页缺少工作流编排入口按钮，现有按钮：{labels}"
    # 顺序：修改游戏配置 在 工作流编排 之前
    assert labels.index(TextResources.SYS_BTN_GAME_CONFIG) < \
        labels.index(TextResources.SYS_BTN_WORKFLOW), \
        "工作流编排按钮应排在「修改游戏配置」之后"
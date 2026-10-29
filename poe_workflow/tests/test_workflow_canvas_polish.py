# -*- coding: utf-8 -*-
"""工作流画布 阶段4（打磨）单元测试。

覆盖：
- 主题合规：新增控件用 objectName + theme QSS，**不再有内联硬编码颜色**
- 状态行 level 属性（ok / error / info）走主题，不写死颜色
- Q3 子工作流展开只读预览（展开/收起/重建保持/读不到时回退）
- 方向键微调（含 Shift 加速）
- 弹窗默认开启可编辑
依赖 tests/conftest.py 的 qapp（pytest-qt, offscreen）。
"""
import io
import os
import re

import pytest

from poe_workflow.ui.theme import CANVAS_COLORS, get_canvas_colors
from poe_workflow.ui.workflow_canvas import GRID, SubWorkflowNode, WorkflowCanvasView
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _leaf(sid, prim="move_to_anchor", **params):
    return {"id": sid, "kind": "action", "primitive": prim,
            "params": params or {"anchor": "a"},
            "on_error": "retry", "retry_count": 1,
            "retry_delay_ms": 500, "delay_ms": 0}


def _sub_step(target="preset_mapmaker_full"):
    return {"id": "1", "kind": "action", "primitive": "log",
            "params": {"message": "call"}, "on_error": "jump",
            "jump_target": target, "retry_count": 0,
            "retry_delay_ms": 0, "delay_ms": 0}


# ── 主题合规 ────────────────────────────────────────────────────────────────
def test_theme_has_rules_for_new_objectnames():
    """主题必须覆盖新增控件的 objectName（MEMORY ⑥ 约定：不硬编码颜色）。"""
    from poe_workflow.ui.theme import LIGHT_QSS, DARK_QSS
    keys = ["StatusHint", "CanvasStatus", "WorkflowDialog",
            "WorkflowDialogSplitter", "PaletteTitle", "PaletteGroup",
            "PaletteHint", "PaletteScroll", "PaletteItem"]
    missing_light = [k for k in keys if f"#{k}" not in LIGHT_QSS]
    missing_dark = [k for k in keys if f"#{k}" not in DARK_QSS]
    assert not missing_light, f"浅色主题缺少规则：{missing_light}"
    assert not missing_dark, f"深色主题缺少规则：{missing_dark}"


def test_canvas_status_has_level_colors():
    """状态行按 level 着色（ok/error/info），深浅两套都要有。"""
    from poe_workflow.ui.theme import LIGHT_QSS, DARK_QSS
    for qss in (LIGHT_QSS, DARK_QSS):
        for level in ("ok", "error", "info"):
            assert f'QLabel#CanvasStatus[level="{level}"]' in qss


@pytest.mark.parametrize("relpath", [
    "ui/workflow_canvas.py",
    "ui/workflow_palette.py",
    "ui/tab_workflow_canvas.py",
    "ui/dialog_workflow.py",
    "ui/tab_workflow.py",
])
def test_no_hardcoded_color_in_new_ui_files(relpath):
    """新增 UI 文件不得出现内联 setStyleSheet 颜色（须走 objectName + 主题）。"""
    src = io.open(os.path.join(REPO, relpath), encoding="utf-8").read()
    assert "setStyleSheet" not in src, f"{relpath} 仍有内联样式，应改用 objectName"


# ── 状态行 level ────────────────────────────────────────────────────────────
def test_status_level_property_set(qapp, config_manager):
    """_set_status 应设置 level 属性并重跑 QSS（unpolish/polish）。"""
    from poe_workflow.ui.tab_workflow_canvas import WorkflowCanvasTab
    cv = WorkflowCanvasTab(config_manager)
    cv._set_status("成功", "ok")
    assert cv._status.property("level") == "ok"
    cv._set_status("失败", "error")
    assert cv._status.property("level") == "error"


def test_status_objectname_set(qapp, config_manager):
    from poe_workflow.ui.tab_workflow_canvas import WorkflowCanvasTab
    cv = WorkflowCanvasTab(config_manager)
    assert cv._status.objectName() == "CanvasStatus"


# ── Q3 子工作流只读预览 ──────────────────────────────────────────────────────
def test_subworkflow_toggle_expands(qapp):
    v = WorkflowCanvasView()
    v.set_steps([_sub_step()])
    v.set_subworkflow_loader(lambda name: [_leaf("s1"), _leaf("s2")])
    node = v._node_by_id["1"]
    assert isinstance(node, SubWorkflowNode)
    assert node.expanded is False
    assert v.toggle_subworkflow(node) is True


def test_subworkflow_toggle_collapses(qapp):
    """再次点击同一子工作流 → 收起（重建后须取新图元，旧图元已销毁）。"""
    v = WorkflowCanvasView()
    steps = [_sub_step()]
    v.set_steps(steps)
    v.set_subworkflow_loader(lambda name: [_leaf("s1")])
    assert v.toggle_subworkflow(v._node_by_id["1"]) is True
    assert v._node_by_id["1"].expanded is True
    # 重建后重新取图元（真实点击路径就是这样）
    assert v.toggle_subworkflow(v._node_by_id["1"]) is False
    assert v._node_by_id["1"].expanded is False


def test_subworkflow_kind_renders_and_previews(qapp):
    """P4-A：kind=subworkflow 步骤（正常路径调用）应渲染为 SubWorkflowNode 并可预览。"""
    v = WorkflowCanvasView()
    step = {"id": "1", "kind": "subworkflow", "jump_target": "preset_mapmaker_full",
            "on_error": "retry", "retry_count": 0, "retry_delay_ms": 0, "delay_ms": 0}
    v.set_steps([step])
    v.set_subworkflow_loader(lambda name: [_leaf("s1"), _leaf("s2")])
    node = v._node_by_id["1"]
    assert isinstance(node, SubWorkflowNode)
    assert v.toggle_subworkflow(node) is True


def test_subworkflow_missing_target_falls_back(qapp):
    """子工作流文件读不到 → 不应保持展开态（静默失败回退）。"""
    v = WorkflowCanvasView()
    v.set_steps([_sub_step("no_such_module_xyz")])
    v.set_subworkflow_loader(lambda name: [])
    node = v._node_by_id["1"]
    assert v.toggle_subworkflow(node) is False
    assert node.expanded is False


def test_subworkflow_without_loader_is_noop(qapp):
    v = WorkflowCanvasView()
    v.set_steps([_sub_step()])
    node = v._node_by_id["1"]
    # 未注入 loader：仅切换图元展开标记，不崩溃
    v.toggle_subworkflow(node)


def test_subworkflow_expansion_survives_rebuild(qapp):
    """重建（set_steps）后展开态保持——按 step dict 身份比对，不依赖图元对象。"""
    v = WorkflowCanvasView()
    steps = [_sub_step()]
    v.set_steps(steps)
    v.set_subworkflow_loader(lambda name: [_leaf("s1")])
    v.toggle_subworkflow(v._node_by_id["1"])
    v.set_steps(steps)          # 重建
    assert v._node_by_id["1"].expanded is True, "重建后展开态丢失"


def test_real_subworkflow_loader_reads_file(qapp, config_manager):
    """真实读取器应能读出仓库里的预置子工作流。"""
    from poe_workflow.ui.tab_workflow_canvas import _load_subworkflow_steps
    steps = _load_subworkflow_steps("preset_mapmaker_full")
    assert isinstance(steps, list) and steps, "应能读到 preset_mapmaker_full.json"


def test_real_subworkflow_loader_missing_returns_empty(qapp):
    from poe_workflow.ui.tab_workflow_canvas import _load_subworkflow_steps
    assert _load_subworkflow_steps("definitely_missing_module") == []
    assert _load_subworkflow_steps("") == []


# ── 方向键微调 ──────────────────────────────────────────────────────────────
def _key_event(qapp, key, shift=False):
    """构造一个按键事件（offscreen 下直接调用 keyPressEvent 即可）。"""
    from PyQt5.QtGui import QKeyEvent
    from PyQt5.QtCore import QEvent, Qt
    mods = Qt.ShiftModifier if shift else Qt.NoModifier
    return QKeyEvent(QEvent.KeyPress, key, mods)


def test_arrow_key_nudges_selected_node(qapp):
    from PyQt5.QtCore import Qt
    v = WorkflowCanvasView()
    v.set_steps([_leaf("1"), _leaf("2")])
    v.set_editable(True)
    node = v._node_by_id["1"]
    node.set_selected(True)
    x0, y0 = node.pos().x(), node.pos().y()
    v.keyPressEvent(_key_event(qapp, Qt.Key_Right))
    assert node.pos().x() == x0 + GRID
    v.keyPressEvent(_key_event(qapp, Qt.Key_Down))
    assert node.pos().y() == y0 + GRID


def test_arrow_key_shift_accelerates(qapp):
    from PyQt5.QtCore import Qt
    v = WorkflowCanvasView()
    v.set_steps([_leaf("1")])
    v.set_editable(True)
    node = v._node_by_id["1"]
    node.set_selected(True)
    x0 = node.pos().x()
    v.keyPressEvent(_key_event(qapp, Qt.Key_Right, shift=True))
    assert node.pos().x() == x0 + GRID * 4


def test_arrow_key_disabled_when_read_only(qapp):
    from PyQt5.QtCore import Qt
    v = WorkflowCanvasView()
    v.set_steps([_leaf("1")])
    node = v._node_by_id["1"]
    node.set_selected(True)
    x0 = node.pos().x()
    v.keyPressEvent(_key_event(qapp, Qt.Key_Right))   # 只读态不应移动
    assert node.pos().x() == x0


# ── 弹窗默认开启可编辑 ──────────────────────────────────────────────────────
def test_dialog_enables_canvas_editable(qapp, config_manager):
    from poe_workflow.ui.dialog_workflow import WorkflowDialog
    dlg = WorkflowDialog(config_manager)
    assert dlg._wf_canvas._canvas.is_editable() is True


def test_dialog_set_canvas_editable_toggle(qapp, config_manager):
    from poe_workflow.ui.dialog_workflow import WorkflowDialog
    dlg = WorkflowDialog(config_manager)
    dlg.set_canvas_editable(False)
    assert dlg._wf_canvas._canvas.is_editable() is False
    dlg.set_canvas_editable(True)
    assert dlg._wf_canvas._canvas.is_editable() is True


# ── 主题配色完整性 ──────────────────────────────────────────────────────────
def test_canvas_colors_have_all_keys():
    """两套主题的画布配色键必须一致（避免某套缺键导致 KeyError）。"""
    light = set(get_canvas_colors("light").keys())
    dark = set(get_canvas_colors("dark").keys())
    assert light == dark, f"画布配色键不一致：仅浅色有 {light - dark}；仅深色有 {dark - light}"


def test_canvas_colors_invalid_key_falls_back():
    from poe_workflow.ui.theme import DEFAULT_THEME
    assert get_canvas_colors("nonexistent") == CANVAS_COLORS[DEFAULT_THEME]


# ── 拖拽「重复插入」回归（真机中断根因，见 fix note）─────────────────────────
def _press(btn, x=5, y=5):
    from PyQt5.QtCore import QEvent, QPointF
    from PyQt5.QtGui import QMouseEvent
    ev = QMouseEvent(QEvent.MouseButtonPress, QPointF(x, y),
                     Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    QApplication.sendEvent(btn, ev)


def _move_held(btn, x, y):
    from PyQt5.QtCore import QEvent, QPointF
    from PyQt5.QtGui import QMouseEvent
    ev = QMouseEvent(QEvent.MouseMove, QPointF(x, y),
                     Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    QApplication.sendEvent(btn, ev)


def _release(btn, x=5, y=5):
    from PyQt5.QtCore import QEvent, QPointF
    from PyQt5.QtGui import QMouseEvent
    ev = QMouseEvent(QEvent.MouseButtonRelease, QPointF(x, y),
                     Qt.LeftButton, Qt.NoButton, Qt.NoModifier)
    QApplication.sendEvent(btn, ev)


def _button(qapp):
    from poe_workflow.ui.workflow_palette import PaletteItemButton
    btn = PaletteItemButton("wait_ms", "primitive", "wait_ms")
    btn.setObjectName("PaletteItem")
    btn.resize(120, 30)
    return btn


def test_pure_click_still_activates(qapp):
    """纯点击必须照常插入（不能被拖拽抑制逻辑误伤）。"""
    btn = _button(qapp)
    fired = []
    btn.clicked.connect(lambda: fired.append(1))
    _press(btn)
    _release(btn)
    assert len(fired) == 1, "纯点击应触发一次 clicked"


def test_drag_does_not_double_fire_click(qapp):
    """拖拽越过阈值后不得再触发 clicked（否则「拖放插一次 + click 再插一次」重复插入）。"""
    btn = _button(qapp)
    fired = []
    btn.clicked.connect(lambda: fired.append(1))
    btn._start_drag = lambda: None      # 拦截 QDrag.exec_ 避免阻塞
    _press(btn)
    _move_held(btn, 90, 90)             # 越过 DRAG_THRESHOLD
    assert btn._suppress_click is True
    _release(btn, 90, 90)
    assert fired == [], f"拖拽后又触发了 {len(fired)} 次 click，会重复插入"


def test_small_move_below_threshold_still_clicks(qapp):
    """未越过阈值的轻微抖动仍算点击。"""
    btn = _button(qapp)
    fired = []
    btn.clicked.connect(lambda: fired.append(1))
    _press(btn)
    _move_held(btn, 7, 7)               # 曼哈顿距离 4 < 8
    _release(btn, 7, 7)
    assert len(fired) == 1


def test_suppress_click_resets_on_next_press(qapp):
    """下一次按下应重置抑制标记（否则上一次拖拽会永久禁用点击）。"""
    btn = _button(qapp)
    btn._start_drag = lambda: None
    _press(btn)
    _move_held(btn, 90, 90)
    _release(btn, 90, 90)
    assert btn._suppress_click is True
    fired = []
    btn.clicked.connect(lambda: fired.append(1))
    _press(btn)
    assert btn._suppress_click is False, "新一次按下必须重置抑制标记"
    _release(btn)
    assert len(fired) == 1, "拖拽之后的正常点击仍应生效"
# -*- coding: utf-8 -*-
"""工作流画布（GUI 升级 阶段2）单元测试。

覆盖 CanvasModel → 画布的映射与布局：
- 叶子/容器/子工作流节点渲染与 id 注册
- loop/branch 嵌套组框正确生成
- Q4 布局方向：步骤横向（x 递增）、容器纵向
- 选中高亮、主题切换、只读（不可拖动）
依赖 tests/conftest.py 的 qapp（pytest-qt, offscreen）。
"""
import pytest

from poe_workflow.ui.theme import get_canvas_colors
from poe_workflow.ui.workflow_canvas import (
    CanvasNode, ContainerNode, StepNode, SubWorkflowNode, WorkflowCanvasView,
)


def _leaf(sid, prim="move_to_anchor", **params):
    return {"id": sid, "kind": "action", "primitive": prim,
            "params": params or {"anchor": "a"},
            "on_error": "retry", "retry_count": 1,
            "retry_delay_ms": 500, "delay_ms": 0}


def _loop(sid, body):
    return {"id": sid, "kind": "loop", "count": 3, "body": body,
            "condition": None, "on_error": "retry", "retry_count": 0,
            "retry_delay_ms": 0, "delay_ms": 0}


def _branch(sid, then_steps, else_steps):
    return {"id": sid, "kind": "branch",
            "condition": {"source": "clipboard", "op": "equals", "value": "x"},
            "then_steps": then_steps, "else_steps": else_steps,
            "on_error": "retry", "retry_count": 0,
            "retry_delay_ms": 0, "delay_ms": 0}


def test_leaf_nodes_render_and_register(qapp):
    v = WorkflowCanvasView()
    v.set_steps([_leaf("1"), _leaf("2", "wait_ms", ms=100)])
    assert v.node_count() == 2
    assert "1" in v._node_by_id and "2" in v._node_by_id
    assert isinstance(v._node_by_id["1"], StepNode)


def test_steps_laid_out_horizontally(qapp):
    """Q4：同层步骤从左到右（x 递增，y 相同）。"""
    v = WorkflowCanvasView()
    v.set_steps([_leaf("1"), _leaf("2"), _leaf("3")])
    xs = [v._node_by_id[i].pos().x() for i in ("1", "2", "3")]
    ys = [v._node_by_id[i].pos().y() for i in ("1", "2", "3")]
    assert xs == sorted(xs) and xs[0] < xs[1] < xs[2]
    assert len(set(ys)) == 1, "同层步骤应在同一行"


def test_loop_container_wraps_body(qapp):
    v = WorkflowCanvasView()
    v.set_steps([_loop("1", [_leaf("1.1"), _leaf("1.2")])])
    assert isinstance(v._node_by_id["1"], ContainerNode)
    # body 内两个子节点都在容器注册表中
    assert "1.1" in v._node_by_id and "1.2" in v._node_by_id


def test_branch_container_stacks_then_else_vertically(qapp):
    """Q4：分支 then / else 两区从上而下堆叠。"""
    v = WorkflowCanvasView()
    v.set_steps([_branch("1", [_leaf("1.1")], [_leaf("1.2")])])
    then_y = v._node_by_id["1.1"].pos().y()
    else_y = v._node_by_id["1.2"].pos().y()
    assert else_y > then_y, "else 区应在 then 区下方"


def test_nested_loop_in_branch(qapp):
    v = WorkflowCanvasView()
    v.set_steps([_branch("1", [_loop("1.1", [_leaf("1.1.1")])], [])])
    assert isinstance(v._node_by_id["1"], ContainerNode)
    assert isinstance(v._node_by_id["1.1"], ContainerNode)
    assert "1.1.1" in v._node_by_id


def test_subworkflow_node_styled(qapp):
    step = {"id": "1", "kind": "action", "primitive": "log",
            "params": {"message": "x"}, "on_error": "jump",
            "jump_target": "my_module", "retry_count": 0,
            "retry_delay_ms": 0, "delay_ms": 0}
    v = WorkflowCanvasView()
    v.set_steps([step])
    assert isinstance(v._node_by_id["1"], SubWorkflowNode)


def test_select_step_highlights_only_target(qapp):
    v = WorkflowCanvasView()
    v.set_steps([_leaf("1"), _leaf("2")])
    v.select_step("2")
    assert v._node_by_id["2"]._selected is True
    assert v._node_by_id["1"]._selected is False


def test_theme_switch_updates_background(qapp):
    v = WorkflowCanvasView()
    v.set_steps([_leaf("1")])
    v.set_theme("dark")
    assert v._theme_key == "dark"
    assert v._colors is get_canvas_colors("dark")
    v.set_theme("light")
    assert v._theme_key == "light"


def test_canvas_is_read_only(qapp):
    """只读：禁止拖动模式。"""
    from PyQt5.QtWidgets import QGraphicsView
    v = WorkflowCanvasView()
    assert v.dragMode() == QGraphicsView.NoDrag


def test_auto_layout_is_stable(qapp):
    v = WorkflowCanvasView()
    steps = [_leaf("1"), _loop("2", [_leaf("2.1")])]
    v.set_steps(steps)
    before = {i: (v._node_by_id[i].pos().x(), v._node_by_id[i].pos().y())
              for i in v._node_by_id}
    v.auto_layout()
    after = {i: (v._node_by_id[i].pos().x(), v._node_by_id[i].pos().y())
             for i in v._node_by_id}
    assert before == after


def test_empty_steps_no_crash(qapp):
    v = WorkflowCanvasView()
    v.set_steps([])
    assert v.node_count() == 0